"""
Модель музыкального трека
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from enum import Enum
import hashlib

from sqlalchemy import String, Boolean, Integer, BigInteger, DateTime, Text, Float, Enum as SQLEnum, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func, and_, or_

from app.models.base import BaseModel, CacheableMixin, StatsMixin, MetadataMixin, SearchableMixin


class TrackSource(str, Enum):
    """Источник трека"""
    VK_AUDIO = "vk_audio"
    YOUTUBE = "youtube"
    SPOTIFY = "spotify"
    SOUNDCLOUD = "soundcloud"
    DEEZER = "deezer"
    APPLE_MUSIC = "apple_music"
    LOCAL = "local"


class TrackStatus(str, Enum):
    """Статус трека"""
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    PROCESSING = "processing"
    ERROR = "error"


class AudioQuality(str, Enum):
    """Качество аудио"""
    LOW = "128kbps"
    MEDIUM = "192kbps"
    HIGH = "256kbps"
    ULTRA = "320kbps"


class Track(BaseModel, CacheableMixin, StatsMixin, MetadataMixin, SearchableMixin):
    """Модель музыкального трека"""
    
    __tablename__ = "tracks"
    
    # Основная информация
    title: Mapped[str] = mapped_column(
        String(500),
        index=True,
        comment="Название трека"
    )
    
    artist: Mapped[str] = mapped_column(
        String(500),
        index=True,
        comment="Исполнитель"
    )
    
    album: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Альбом"
    )
    
    genre: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Жанр"
    )
    
    year: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Год выпуска"
    )
    
    # Техническая информация
    duration: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Длительность в секундах"
    )
    
    bitrate: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Битрейт в kbps"
    )
    
    file_size: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        comment="Размер файла в байтах"
    )
    
    audio_quality: Mapped[AudioQuality] = mapped_column(
        SQLEnum(AudioQuality),
        default=AudioQuality.MEDIUM,
        comment="Качество аудио"
    )
    
    # Источники и идентификаторы
    source: Mapped[TrackSource] = mapped_column(
        SQLEnum(TrackSource),
        default=TrackSource.VK_AUDIO,
        comment="Источник трека"
    )
    
    external_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="ID трека во внешнем сервисе"
    )
    
    external_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="URL трека во внешнем сервисе"
    )
    
    download_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Прямая ссылка на скачивание"
    )
    
    # Хеш для дедупликации
    content_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="MD5 хеш контента для дедупликации"
    )
    
    fingerprint: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Аудио-отпечаток трека"
    )
    
    # Статус и доступность
    status: Mapped[TrackStatus] = mapped_column(
        SQLEnum(TrackStatus),
        default=TrackStatus.ACTIVE,
        comment="Статус трека"
    )
    
    is_explicit: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Содержит ли трек нецензурную лексику"
    )
    
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Верифицирован ли трек модератором"
    )
    
    # Метрики популярности
    popularity_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        comment="Оценка популярности трека (0-100)"
    )
    
    trending_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        comment="Оценка трендовости трека"
    )
    
    # Временные метки для кеширования
    last_played_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Последнее воспроизведение"
    )
    
    last_downloaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Последнее скачивание"
    )
    
    url_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Время истечения ссылки на скачивание"
    )
    
    # Дополнительные поля для поиска
    search_tags: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="Теги для поиска"
    )
    
    # Связи
    playlist_tracks = relationship("PlaylistTrack", back_populates="track", lazy="selectin")
    search_results = relationship("SearchResult", back_populates="track", lazy="selectin")
    
    # Индексы для оптимизации поиска
    __table_args__ = (
        Index("idx_track_search", "artist", "title"),
        Index("idx_track_popularity", "popularity_score", "status"),
        Index("idx_track_source_external", "source", "external_id"),
        Index("idx_track_hash", "content_hash"),
        UniqueConstraint("source", "external_id", name="uq_track_source_external"),
    )
    
    def __repr__(self) -> str:
        return f"<Track(artist='{self.artist}', title='{self.title}')>"
    
    @property
    def full_title(self) -> str:
        """Полное название трека"""
        return f"{self.artist} - {self.title}"
    
    @property
    def duration_formatted(self) -> str:
        """Форматированная длительность (MM:SS)"""
        if not self.duration:
            return "0:00"
        
        minutes = self.duration // 60
        seconds = self.duration % 60
        return f"{minutes}:{seconds:02d}"
    
    @property
    def file_size_formatted(self) -> str:
        """Форматированный размер файла"""
        if not self.file_size:
            return "0 MB"
        
        mb = self.file_size / (1024 * 1024)
        return f"{mb:.1f} MB"
    
    @property
    def is_url_expired(self) -> bool:
        """Проверка истечения ссылки на скачивание"""
        if not self.url_expires_at:
            return False
        return self.url_expires_at <= datetime.now(timezone.utc)
    
    @property
    def is_available(self) -> bool:
        """Доступен ли трек для скачивания"""
        return (
            self.status == TrackStatus.ACTIVE and
            self.download_url is not None and
            not self.is_url_expired
        )
    
    def generate_content_hash(self, content: bytes) -> str:
        """Генерация хеша контента"""
        return hashlib.md5(content).hexdigest()
    
    def generate_search_vector(self) -> None:
        """Обновление поискового вектора"""
        search_fields = [
            self.title,
            self.artist,
            self.album or "",
            self.genre or "",
            " ".join(self.search_tags or [])
        ]
        self.update_search_vector(*search_fields)
    
    async def update_popularity(self, session: AsyncSession) -> None:
        """Обновление оценки популярности на основе метрик"""
        # Формула популярности: взвешенная сумма метрик
        views_weight = 0.3
        downloads_weight = 0.5
        likes_weight = 0.2
        
        # Нормализация метрик (логарифмическая шкала)
        import math
        
        views_score = math.log10(max(1, self.views_count)) * 10
        downloads_score = math.log10(max(1, self.downloads_count)) * 15
        likes_score = math.log10(max(1, self.likes_count)) * 5
        
        self.popularity_score = min(100.0, 
            views_score * views_weight +
            downloads_score * downloads_weight +
            likes_score * likes_weight
        )
        
        await session.flush()
    
    async def update_trending_score(self, session: AsyncSession, days: int = 7) -> None:
        """Обновление трендовости на основе активности за последние дни"""
        # Здесь можно добавить логику подсчета активности за последние дни
        # Пока используем упрощенную формула
        recent_activity = await self._get_recent_activity(session, days)
        
        # Трендовость = активность за последние дни / общая активность
        total_activity = self.views_count + self.downloads_count
        if total_activity > 0:
            self.trending_score = (recent_activity / total_activity) * 100
        else:
            self.trending_score = 0.0
        
        await session.flush()
    
    async def _get_recent_activity(self, session: AsyncSession, days: int) -> int:
        """Получение активности за последние дни (упрощенная версия)"""
        # В реальной реализации здесь должен быть запрос к таблице активности
        # Пока возвращаем приблизительное значение
        return max(0, int(self.views_count * 0.1))
    
    async def mark_as_played(self, session: AsyncSession, user_id: int) -> None:
        """Отметка о воспроизведении трека"""
        self.last_played_at = datetime.now(timezone.utc)
        await self.increment_views(session)
        
        # Можно добавить запись в таблицу истории воспроизведения
        # self._log_play_event(session, user_id)
    
    async def mark_as_downloaded(self, session: AsyncSession, user_id: int) -> None:
        """Отметка о скачивании трека"""
        self.last_downloaded_at = datetime.now(timezone.utc)
        await self.increment_downloads(session)
        
        # Можно добавить запись в таблицу истории скачиваний
        # self._log_download_event(session, user_id)
    
    async def refresh_download_url(self, session: AsyncSession) -> bool:
        """Обновление ссылки на скачивание"""
        # Здесь должна быть логика обновления ссылки через соответствующий сервис
        # Пока просто обновляем время истечения
        if self.download_url:
            self.url_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
            await session.flush()
            return True
        return False
    
    @classmethod
    async def search(
        cls,
        session: AsyncSession,
        query: str,
        limit: int = 50,
        offset: int = 0,
        source: Optional[TrackSource] = None,
        quality: Optional[AudioQuality] = None
    ) -> List["Track"]:
        """Поиск треков по запросу"""
        # Базовый запрос
        search_query = select(cls).where(cls.status == TrackStatus.ACTIVE)
        
        # Фильтр по источнику
        if source:
            search_query = search_query.where(cls.source == source)
        
        # Фильтр по качеству
        if quality:
            search_query = search_query.where(cls.audio_quality == quality)
        
        # Текстовый поиск
        if query.strip():
            search_terms = query.lower().split()
            conditions = []
            
            for term in search_terms:
                term_condition = or_(
                    cls.title.ilike(f"%{term}%"),
                    cls.artist.ilike(f"%{term}%"),
                    cls.album.ilike(f"%{term}%"),
                    cls.search_vector.ilike(f"%{term}%")
                )
                conditions.append(term_condition)
            
            if conditions:
                search_query = search_query.where(and_(*conditions))
        
        # Сортировка по популярности
        search_query = search_query.order_by(
            cls.popularity_score.desc(),
            cls.downloads_count.desc(),
            cls.created_at.desc()
        )
        
        # Пагинация
        search_query = search_query.offset(offset).limit(limit)
        
        result = await session.execute(search_query)
        return list(result.scalars().all())
    
    @classmethod
    async def get_by_external_id(
        cls,
        session: AsyncSession,
        source: TrackSource,
        external_id: str
    ) -> Optional["Track"]:
        """Получение трека по внешнему ID"""
        result = await session.execute(
            select(cls).where(
                cls.source == source,
                cls.external_id == external_id
            )
        )
        return result.scalar_one_or_none()
    
    @classmethod
    async def get_by_hash(
        cls,
        session: AsyncSession,
        content_hash: str
    ) -> Optional["Track"]:
        """Получение трека по хешу контента"""
        result = await session.execute(
            select(cls).where(cls.content_hash == content_hash)
        )
        return result.scalar_one_or_none()
    
    @classmethod
    async def get_popular(
        cls,
        session: AsyncSession,
        limit: int = 50,
        genre: Optional[str] = None,
        days: Optional[int] = None
    ) -> List["Track"]:
        """Получение популярных треков"""
        query = select(cls).where(cls.status == TrackStatus.ACTIVE)
        
        if genre:
            query = query.where(cls.genre == genre)
        
        if days:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.where(cls.last_played_at >= since)
        
        query = query.order_by(
            cls.popularity_score.desc(),
            cls.downloads_count.desc()
        ).limit(limit)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @classmethod
    async def get_trending(
        cls,
        session: AsyncSession,
        limit: int = 50,
        genre: Optional[str] = None
    ) -> List["Track"]:
        """Получение трендовых треков"""
        query = select(cls).where(
            cls.status == TrackStatus.ACTIVE,
            cls.trending_score > 0
        )
        
        if genre:
            query = query.where(cls.genre == genre)
        
        query = query.order_by(
            cls.trending_score.desc(),
            cls.created_at.desc()
        ).limit(limit)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @classmethod
    async def get_similar(
        cls,
        session: AsyncSession,
        track_id: str,
        limit: int = 20
    ) -> List["Track"]:
        """Получение похожих треков"""
        # Получаем базовый трек
        base_track = await cls.get_by_id(session, track_id)
        if not base_track:
            return []
        
        # Поиск похожих по артисту, жанру и тегам
        query = select(cls).where(
            cls.status == TrackStatus.ACTIVE,
            cls.id != base_track.id,
            or_(
                cls.artist == base_track.artist,
                cls.genre == base_track.genre,
                cls.album == base_track.album
            )
        ).order_by(
            cls.popularity_score.desc()
        ).limit(limit)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @classmethod
    async def get_by_artist(
        cls,
        session: AsyncSession,
        artist: str,
        limit: int = 50
    ) -> List["Track"]:
        """Получение треков по исполнителю"""
        result = await session.execute(
            select(cls).where(
                cls.status == TrackStatus.ACTIVE,
                cls.artist.ilike(f"%{artist}%")
            ).order_by(
                cls.popularity_score.desc()
            ).limit(limit)
        )
        return list(result.scalars().all())
    
    @classmethod
    async def get_expired_urls(
        cls,
        session: AsyncSession,
        limit: int = 100
    ) -> List["Track"]:
        """Получение треков с истекшими ссылками"""
        result = await session.execute(
            select(cls).where(
                cls.status == TrackStatus.ACTIVE,
                cls.url_expires_at <= datetime.now(timezone.utc)
            ).limit(limit)
        )
        return list(result.scalars().all())
    
    @classmethod
    async def cleanup_unavailable(
        cls,
        session: AsyncSession,
        days: int = 30
    ) -> int:
        """Очистка недоступных треков старше N дней"""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        result = await session.execute(
            select(func.count(cls.id)).where(
                cls.status == TrackStatus.UNAVAILABLE,
                cls.updated_at <= cutoff_date
            )
        )
        count = result.scalar()
        
        # Мягкое удаление
        await session.execute(
            cls.__table__.update().where(
                cls.status == TrackStatus.UNAVAILABLE,
                cls.updated_at <= cutoff_date
            ).values(
                status=TrackStatus.BLOCKED,
                updated_at=datetime.now(timezone.utc)
            )
        )
        
        await session.commit()
        return count
    
    @classmethod
    async def get_stats(cls, session: AsyncSession) -> dict:
        """Получение статистики треков"""
        # Общее количество
        total_result = await session.execute(
            select(func.count(cls.id))
        )
        total_tracks = total_result.scalar()
        
        # Активные треки
        active_result = await session.execute(
            select(func.count(cls.id)).where(
                cls.status == TrackStatus.ACTIVE
            )
        )
        active_tracks = active_result.scalar()
        
        # Статистика по источникам
        source_stats = {}
        for source in TrackSource:
            source_result = await session.execute(
                select(func.count(cls.id)).where(
                    cls.source == source,
                    cls.status == TrackStatus.ACTIVE
                )
            )
            source_stats[source.value] = source_result.scalar()
        
        # Статистика по качеству
        quality_stats = {}
        for quality in AudioQuality:
            quality_result = await session.execute(
                select(func.count(cls.id)).where(
                    cls.audio_quality == quality,
                    cls.status == TrackStatus.ACTIVE
                )
            )
            quality_stats[quality.value] = quality_result.scalar()
        
        # Общий размер файлов
        size_result = await session.execute(
            select(func.sum(cls.file_size)).where(
                cls.status == TrackStatus.ACTIVE,
                cls.file_size.isnot(None)
            )
        )
        total_size = size_result.scalar() or 0
        
        return {
            "total_tracks": total_tracks,
            "active_tracks": active_tracks,
            "blocked_tracks": total_tracks - active_tracks,
            "source_distribution": source_stats,
            "quality_distribution": quality_stats,
            "total_size_gb": round(total_size / (1024**3), 2),
        }


class TrackPlayHistory(BaseModel):
    """История воспроизведения треков"""
    
    __tablename__ = "track_play_history"
    
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
        comment="ID пользователя"
    )
    
    track_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        comment="ID трека"
    )
    
    played_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="Время воспроизведения"
    )
    
    source: Mapped[TrackSource] = mapped_column(
        SQLEnum(TrackSource),
        comment="Источник воспроизведения"
    )
    
    # Связи
    track = relationship("Track", lazy="selectin")
    
    __table_args__ = (
        Index("idx_play_history_user_date", "user_id", "played_at"),
        Index("idx_play_history_track_date", "track_id", "played_at"),
    )


class TrackDownloadHistory(BaseModel):
    """История скачиваний треков"""
    
    __tablename__ = "track_download_history"
    
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
        comment="ID пользователя"
    )
    
    track_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        comment="ID трека"
    )
    
    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="Время скачивания"
    )
    
    file_size: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        comment="Размер скачанного файла"
    )
    
    quality: Mapped[AudioQuality] = mapped_column(
        SQLEnum(AudioQuality),
        comment="Качество скачанного файла"
    )
    
    # Связи
    track = relationship("Track", lazy="selectin")
    
    __table_args__ = (
        Index("idx_download_history_user_date", "user_id", "downloaded_at"),
        Index("idx_download_history_track_date", "track_id", "downloaded_at"),
    )