"""
Модель плейлиста пользователя
"""
from typing import Optional, List
from datetime import datetime, timezone
from enum import Enum
import uuid

from sqlalchemy import String, Boolean, Integer, BigInteger, DateTime, Text, Enum as SQLEnum, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func, and_

from app.models.base import BaseModel, CacheableMixin, StatsMixin, MetadataMixin


class PlaylistType(str, Enum):
    """Тип плейлиста"""
    USER_CREATED = "user_created"
    FAVORITES = "favorites"
    RECENTLY_PLAYED = "recently_played"
    SMART = "smart"
    RECOMMENDED = "recommended"


class PlaylistPrivacy(str, Enum):
    """Приватность плейлиста"""
    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"


class Playlist(BaseModel, CacheableMixin, StatsMixin, MetadataMixin):
    """Модель плейлиста"""
    
    __tablename__ = "playlists"
    
    # Основная информация
    name: Mapped[str] = mapped_column(
        String(255),
        comment="Название плейлиста"
    )
    
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Описание плейлиста"
    )
    
    # Владелец плейлиста
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        index=True,
        comment="ID владельца плейлиста"
    )
    
    # Тип и настройки
    playlist_type: Mapped[PlaylistType] = mapped_column(
        SQLEnum(PlaylistType),
        default=PlaylistType.USER_CREATED,
        comment="Тип плейлиста"
    )
    
    privacy: Mapped[PlaylistPrivacy] = mapped_column(
        SQLEnum(PlaylistPrivacy),
        default=PlaylistPrivacy.PRIVATE,
        comment="Настройки приватности"
    )
    
    # Статистика
    tracks_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="Количество треков в плейлисте"
    )
    
    total_duration: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="Общая длительность в секундах"
    )
    
    # Настройки воспроизведения
    is_shuffle: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Включено ли перемешивание"
    )
    
    is_repeat: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Включен ли повтор"
    )
    
    # Изображение плейлиста
    cover_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="URL обложки плейлиста"
    )
    
    # Связи
    user = relationship("User", back_populates="playlists", lazy="selectin")
    playlist_tracks = relationship(
        "PlaylistTrack", 
        back_populates="playlist", 
        lazy="selectin",
        order_by="PlaylistTrack.position"
    )
    
    # Индексы
    __table_args__ = (
        Index("idx_playlist_user_type", "user_id", "playlist_type"),
        Index("idx_playlist_privacy", "privacy"),
    )
    
    def __repr__(self) -> str:
        return f"<Playlist(name='{self.name}', user_id={self.user_id})>"
    
    @property
    def duration_formatted(self) -> str:
        """Форматированная длительность плейлиста"""
        if not self.total_duration:
            return "0:00"
        
        hours = self.total_duration // 3600
        minutes = (self.total_duration % 3600) // 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:00"
        else:
            return f"{minutes}:{self.total_duration % 60:02d}"
    
    @property
    def is_empty(self) -> bool:
        """Проверка пустоты плейлиста"""
        return self.tracks_count == 0
    
    @property
    def is_system(self) -> bool:
        """Является ли плейлист системным"""
        return self.playlist_type in [
            PlaylistType.FAVORITES,
            PlaylistType.RECENTLY_PLAYED,
            PlaylistType.RECOMMENDED
        ]
    
    async def add_track(
        self, 
        session: AsyncSession, 
        track_id: str,
        position: Optional[int] = None
    ) -> "PlaylistTrack":
        """Добавление трека в плейлист"""
        # Проверяем, есть ли уже такой трек
        existing = await session.execute(
            select(PlaylistTrack).where(
                PlaylistTrack.playlist_id == self.id,
                PlaylistTrack.track_id == track_id
            )
        )
        
        if existing.scalar_one_or_none():
            raise ValueError("Трек уже есть в плейлисте")
        
        # Определяем позицию
        if position is None:
            max_position_result = await session.execute(
                select(func.max(PlaylistTrack.position)).where(
                    PlaylistTrack.playlist_id == self.id
                )
            )
            max_position = max_position_result.scalar() or 0
            position = max_position + 1
        
        # Создаем связь
        playlist_track = PlaylistTrack(
            playlist_id=self.id,
            track_id=track_id,
            position=position
        )
        
        session.add(playlist_track)
        
        # Обновляем статистику плейлиста
        await self._update_stats(session)
        
        await session.flush()
        return playlist_track
    
    async def remove_track(
        self, 
        session: AsyncSession, 
        track_id: str
    ) -> bool:
        """Удаление трека из плейлиста"""
        result = await session.execute(
            select(PlaylistTrack).where(
                PlaylistTrack.playlist_id == self.id,
                PlaylistTrack.track_id == track_id
            )
        )
        
        playlist_track = result.scalar_one_or_none()
        if not playlist_track:
            return False
        
        await session.delete(playlist_track)
        
        # Пересчитываем позиции
        await self._reorder_tracks(session, playlist_track.position)
        
        # Обновляем статистику
        await self._update_stats(session)
        
        await session.flush()
        return True
    
    async def move_track(
        self,
        session: AsyncSession,
        track_id: str,
        new_position: int
    ) -> bool:
        """Перемещение трека в плейлисте"""
        result = await session.execute(
            select(PlaylistTrack).where(
                PlaylistTrack.playlist_id == self.id,
                PlaylistTrack.track_id == track_id
            )
        )
        
        playlist_track = result.scalar_one_or_none()
        if not playlist_track:
            return False
        
        old_position = playlist_track.position
        
        # Обновляем позиции других треков
        if new_position > old_position:
            # Сдвигаем вниз
            await session.execute(
                PlaylistTrack.__table__.update().where(
                    and_(
                        PlaylistTrack.playlist_id == self.id,
                        PlaylistTrack.position > old_position,
                        PlaylistTrack.position <= new_position
                    )
                ).values(position=PlaylistTrack.position - 1)
            )
        else:
            # Сдвигаем вверх
            await session.execute(
                PlaylistTrack.__table__.update().where(
                    and_(
                        PlaylistTrack.playlist_id == self.id,
                        PlaylistTrack.position >= new_position,
                        PlaylistTrack.position < old_position
                    )
                ).values(position=PlaylistTrack.position + 1)
            )
        
        # Устанавливаем новую позицию
        playlist_track.position = new_position
        
        await session.flush()
        return True
    
    async def clear(self, session: AsyncSession) -> int:
        """Очистка плейлиста"""
        # Считаем количество треков
        count_result = await session.execute(
            select(func.count(PlaylistTrack.id)).where(
                PlaylistTrack.playlist_id == self.id
            )
        )
        count = count_result.scalar()
        
        # Удаляем все треки
        await session.execute(
            PlaylistTrack.__table__.delete().where(
                PlaylistTrack.playlist_id == self.id
            )
        )
        
        # Обновляем статистику
        self.tracks_count = 0
        self.total_duration = 0
        
        await session.flush()
        return count
    
    async def duplicate(
        self,
        session: AsyncSession,
        new_name: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> "Playlist":
        """Дублирование плейлиста"""
        # Получаем все треки текущего плейлиста
        tracks_result = await session.execute(
            select(PlaylistTrack).where(
                PlaylistTrack.playlist_id == self.id
            ).order_by(PlaylistTrack.position)
        )
        tracks = tracks_result.scalars().all()
        
        # Создаем новый плейлист
        new_playlist = Playlist(
            name=new_name or f"{self.name} (копия)",
            description=self.description,
            user_id=user_id or self.user_id,
            playlist_type=PlaylistType.USER_CREATED,
            privacy=self.privacy,
            cover_url=self.cover_url
        )
        
        session.add(new_playlist)
        await session.flush()
        
        # Копируем треки
        for track in tracks:
            new_track = PlaylistTrack(
                playlist_id=new_playlist.id,
                track_id=track.track_id,
                position=track.position,
                added_at=datetime.now(timezone.utc)
            )
            session.add(new_track)
        
        # Обновляем статистику
        await new_playlist._update_stats(session)
        
        await session.flush()
        return new_playlist
    
    async def _update_stats(self, session: AsyncSession) -> None:
        """Обновление статистики плейлиста"""
        # Количество треков
        count_result = await session.execute(
            select(func.count(PlaylistTrack.id)).where(
                PlaylistTrack.playlist_id == self.id
            )
        )
        self.tracks_count = count_result.scalar()
        
        # Общая длительность (через join с треками)
        from app.models.track import Track
        
        duration_result = await session.execute(
            select(func.sum(Track.duration)).select_from(
                PlaylistTrack.__table__.join(
                    Track.__table__,
                    PlaylistTrack.track_id == Track.id
                )
            ).where(
                PlaylistTrack.playlist_id == self.id,
                Track.duration.isnot(None)
            )
        )
        self.total_duration = duration_result.scalar() or 0
        
        await session.flush()
    
    async def _reorder_tracks(self, session: AsyncSession, deleted_position: int) -> None:
        """Пересчет позиций треков после удаления"""
        await session.execute(
            PlaylistTrack.__table__.update().where(
                and_(
                    PlaylistTrack.playlist_id == self.id,
                    PlaylistTrack.position > deleted_position
                )
            ).values(position=PlaylistTrack.position - 1)
        )
    
    @classmethod
    async def get_user_playlists(
        cls,
        session: AsyncSession,
        user_id: int,
        playlist_type: Optional[PlaylistType] = None
    ) -> List["Playlist"]:
        """Получение плейлистов пользователя"""
        query = select(cls).where(cls.user_id == user_id)
        
        if playlist_type:
            query = query.where(cls.playlist_type == playlist_type)
        
        query = query.order_by(cls.created_at.desc())
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @classmethod
    async def get_favorites_playlist(
        cls,
        session: AsyncSession,
        user_id: int
    ) -> "Playlist":
        """Получение или создание плейлиста избранного"""
        result = await session.execute(
            select(cls).where(
                cls.user_id == user_id,
                cls.playlist_type == PlaylistType.FAVORITES
            )
        )
        
        playlist = result.scalar_one_or_none()
        
        if not playlist:
            # Создаем плейлист избранного
            playlist = cls(
                name="❤️ Избранное",
                description="Ваши любимые треки",
                user_id=user_id,
                playlist_type=PlaylistType.FAVORITES,
                privacy=PlaylistPrivacy.PRIVATE
            )
            session.add(playlist)
            await session.flush()
        
        return playlist
    
    @classmethod
    async def get_public_playlists(
        cls,
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0
    ) -> List["Playlist"]:
        """Получение публичных плейлистов"""
        result = await session.execute(
            select(cls).where(
                cls.privacy == PlaylistPrivacy.PUBLIC,
                cls.tracks_count > 0
            ).order_by(
                cls.views_count.desc(),
                cls.created_at.desc()
            ).offset(offset).limit(limit)
        )
        return list(result.scalars().all())


class PlaylistTrack(BaseModel):
    """Связь между плейлистом и треком"""
    
    __tablename__ = "playlist_tracks"
    
    # Связи
    playlist_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("playlists.id", ondelete="CASCADE"),
        index=True,
        comment="ID плейлиста"
    )
    
    track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tracks.id", ondelete="CASCADE"),
        index=True,
        comment="ID трека"
    )
    
    # Позиция в плейлисте
    position: Mapped[int] = mapped_column(
        Integer,
        comment="Позиция трека в плейлисте"
    )
    
    # Время добавления
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        comment="Время добавления трека"
    )
    
    # Связи
    playlist = relationship("Playlist", back_populates="playlist_tracks", lazy="selectin")
    track = relationship("Track", back_populates="playlist_tracks", lazy="selectin")
    
    # Индексы и ограничения
    __table_args__ = (
        UniqueConstraint("playlist_id", "track_id", name="uq_playlist_track"),
        UniqueConstraint("playlist_id", "position", name="uq_playlist_position"),
        Index("idx_playlist_track_position", "playlist_id", "position"),
    )
    
    def __repr__(self) -> str:
        return f"<PlaylistTrack(playlist_id={self.playlist_id}, track_id={self.track_id}, position={self.position})>"


class PlaylistShare(BaseModel):
    """Модель для шаринга плейлистов"""
    
    __tablename__ = "playlist_shares"
    
    playlist_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("playlists.id", ondelete="CASCADE"),
        index=True,
        comment="ID плейлиста"
    )
    
    shared_by: Mapped[int] = mapped_column(
        BigInteger,
        comment="ID пользователя, поделившегося плейлистом"
    )
    
    shared_with: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        comment="ID пользователя, с которым поделились (если приватный шаринг)"
    )
    
    share_token: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        comment="Токен для доступа к плейлисту"
    )
    
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Время истечения доступа"
    )
    
    views_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="Количество просмотров"
    )
    
    # Связи
    playlist = relationship("Playlist", lazy="selectin")
    
    @property
    def is_expired(self) -> bool:
        """Проверка истечения токена"""
        if not self.expires_at:
            return False
        return self.expires_at <= datetime.now(timezone.utc)
    
    @classmethod
    async def create_share_link(
        cls,
        session: AsyncSession,
        playlist_id: str,
        shared_by: int,
        expires_hours: Optional[int] = None
    ) -> str:
        """Создание ссылки для шаринга"""
        import secrets
        
        # Генерируем уникальный токен
        share_token = secrets.token_urlsafe(32)
        
        # Время истечения
        expires_at = None
        if expires_hours:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
        
        # Создаем запись
        share = cls(
            playlist_id=playlist_id,
            shared_by=shared_by,
            share_token=share_token,
            expires_at=expires_at
        )
        
        session.add(share)
        await session.flush()
        
        return share_token