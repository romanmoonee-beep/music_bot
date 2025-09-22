"""
Сервис для работы с плейлистами
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import and_, or_, func

from app.core.database import get_session
from app.core.logging import get_logger
from app.models.user import User
from app.models.playlist import Playlist, PlaylistTrack, PlaylistCollaborator, CollaboratorRole
from app.models.track import Track
from app.schemas.playlist import (
    PlaylistCreate, PlaylistUpdate, PlaylistResponse,
    PlaylistTrackAdd, PlaylistCollaboratorAdd
)


class PlaylistService:
    """Сервис для управления плейлистами"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
    
    async def create_playlist(
        self,
        user_id: int,
        playlist_data: PlaylistCreate
    ) -> Optional[Playlist]:
        """Создать новый плейлист"""
        async with get_session() as session:
            # Проверяем существование пользователя
            user_query = select(User).where(User.id == user_id)
            user_result = await session.execute(user_query)
            user = user_result.scalar_one_or_none()
            
            if not user:
                self.logger.error(f"User {user_id} not found")
                return None
            
            # Создаем плейлист
            playlist = Playlist(
                title=playlist_data.title,
                description=playlist_data.description,
                cover_url=playlist_data.cover_url,
                is_public=playlist_data.is_public,
                created_by_id=user_id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            
            session.add(playlist)
            await session.commit()
            await session.refresh(playlist)
            
            self.logger.info(f"Created playlist '{playlist.title}' for user {user_id}")
            return playlist
    
    async def get_playlist_by_id(
        self,
        playlist_id: int,
        user_id: Optional[int] = None
    ) -> Optional[Playlist]:
        """Получить плейлист по ID"""
        async with get_session() as session:
            query = select(Playlist).options(
                selectinload(Playlist.tracks).selectinload(PlaylistTrack.track),
                selectinload(Playlist.collaborators).selectinload(PlaylistCollaborator.user),
                selectinload(Playlist.created_by)
            ).where(Playlist.id == playlist_id)
            
            result = await session.execute(query)
            playlist = result.scalar_one_or_none()
            
            if not playlist:
                return None
            
            # Проверяем права доступа
            if not playlist.is_public and user_id:
                if not await self._has_playlist_access(playlist_id, user_id):
                    return None
            
            return playlist
    
    async def get_user_playlists(
        self,
        user_id: int,
        include_collaborations: bool = True,
        limit: int = 50,
        offset: int = 0
    ) -> List[Playlist]:
        """Получить плейлисты пользователя"""
        async with get_session() as session:
            # Плейлисты, созданные пользователем
            query = select(Playlist).options(
                selectinload(Playlist.tracks),
                selectinload(Playlist.collaborators)
            ).where(
                Playlist.created_by_id == user_id,
                Playlist.is_deleted == False
            )
            
            if include_collaborations:
                # Добавляем плейлисты, где пользователь является коллаборатором
                collaborator_query = select(Playlist).options(
                    selectinload(Playlist.tracks),
                    selectinload(Playlist.collaborators)
                ).join(PlaylistCollaborator).where(
                    PlaylistCollaborator.user_id == user_id,
                    Playlist.is_deleted == False
                )
                
                # Объединяем запросы
                query = query.union(collaborator_query)
            
            query = query.order_by(Playlist.updated_at.desc()).limit(limit).offset(offset)
            
            result = await session.execute(query)
            return result.scalars().all()
    
    async def update_playlist(
        self,
        playlist_id: int,
        user_id: int,
        playlist_data: PlaylistUpdate
    ) -> Optional[Playlist]:
        """Обновить плейлист"""
        async with get_session() as session:
            # Проверяем права на редактирование
            if not await self._can_edit_playlist(playlist_id, user_id):
                self.logger.warning(f"User {user_id} has no edit access to playlist {playlist_id}")
                return None
            
            query = select(Playlist).where(Playlist.id == playlist_id)
            result = await session.execute(query)
            playlist = result.scalar_one_or_none()
            
            if not playlist:
                return None
            
            # Обновляем поля
            update_data = playlist_data.dict(exclude_unset=True)
            for field, value in update_data.items():
                setattr(playlist, field, value)
            
            playlist.updated_at = datetime.now(timezone.utc)
            
            await session.commit()
            await session.refresh(playlist)
            
            self.logger.info(f"Updated playlist {playlist_id}")
            return playlist
    
    async def delete_playlist(self, playlist_id: int, user_id: int) -> bool:
        """Удалить плейлист (мягкое удаление)"""
        async with get_session() as session:
            # Проверяем права (только владелец может удалить)
            query = select(Playlist).where(
                Playlist.id == playlist_id,
                Playlist.created_by_id == user_id
            )
            result = await session.execute(query)
            playlist = result.scalar_one_or_none()
            
            if not playlist:
                return False
            
            playlist.is_deleted = True
            playlist.updated_at = datetime.now(timezone.utc)
            
            await session.commit()
            
            self.logger.info(f"Deleted playlist {playlist_id}")
            return True
    
    async def add_track_to_playlist(
        self,
        playlist_id: int,
        user_id: int,
        track_data: PlaylistTrackAdd
    ) -> bool:
        """Добавить трек в плейлист"""
        async with get_session() as session:
            # Проверяем права на редактирование
            if not await self._can_edit_playlist(playlist_id, user_id):
                return False
            
            # Проверяем существование трека
            track_query = select(Track).where(Track.id == track_data.track_id)
            track_result = await session.execute(track_query)
            track = track_result.scalar_one_or_none()
            
            if not track:
                self.logger.error(f"Track {track_data.track_id} not found")
                return False
            
            # Проверяем, не добавлен ли уже трек
            existing_query = select(PlaylistTrack).where(
                PlaylistTrack.playlist_id == playlist_id,
                PlaylistTrack.track_id == track_data.track_id
            )
            existing_result = await session.execute(existing_query)
            existing = existing_result.scalar_one_or_none()
            
            if existing:
                self.logger.warning(f"Track {track_data.track_id} already in playlist {playlist_id}")
                return False
            
            # Определяем позицию
            if track_data.position is not None:
                position = track_data.position
                # Сдвигаем существующие треки
                await self._shift_tracks_positions(session, playlist_id, position)
            else:
                # Добавляем в конец
                max_pos_query = select(func.max(PlaylistTrack.position)).where(
                    PlaylistTrack.playlist_id == playlist_id
                )
                max_pos_result = await session.execute(max_pos_query)
                max_position = max_pos_result.scalar() or 0
                position = max_position + 1
            
            # Создаем связь
            playlist_track = PlaylistTrack(
                playlist_id=playlist_id,
                track_id=track_data.track_id,
                position=position,
                added_by_id=user_id,
                added_at=datetime.now(timezone.utc)
            )
            
            session.add(playlist_track)
            
            # Обновляем время изменения плейлиста
            await self._update_playlist_timestamp(session, playlist_id)
            
            await session.commit()
            
            self.logger.info(f"Added track {track_data.track_id} to playlist {playlist_id}")
            return True
    
    async def remove_track_from_playlist(
        self,
        playlist_id: int,
        track_id: int,
        user_id: int
    ) -> bool:
        """Удалить трек из плейлиста"""
        async with get_session() as session:
            # Проверяем права на редактирование
            if not await self._can_edit_playlist(playlist_id, user_id):
                return False
            
            # Находим связь
            query = select(PlaylistTrack).where(
                PlaylistTrack.playlist_id == playlist_id,
                PlaylistTrack.track_id == track_id
            )
            result = await session.execute(query)
            playlist_track = result.scalar_one_or_none()
            
            if not playlist_track:
                return False
            
            position = playlist_track.position
            
            # Удаляем связь
            await session.delete(playlist_track)
            
            # Сдвигаем позиции остальных треков
            await self._shift_tracks_positions(session, playlist_id, position + 1, -1)
            
            # Обновляем время изменения плейлиста
            await self._update_playlist_timestamp(session, playlist_id)
            
            await session.commit()
            
            self.logger.info(f"Removed track {track_id} from playlist {playlist_id}")
            return True
    
    async def reorder_playlist_tracks(
        self,
        playlist_id: int,
        user_id: int,
        track_orders: List[Dict[str, int]]  # [{"track_id": 1, "position": 1}, ...]
    ) -> bool:
        """Изменить порядок треков в плейлисте"""
        async with get_session() as session:
            # Проверяем права на редактирование
            if not await self._can_edit_playlist(playlist_id, user_id):
                return False
            
            # Обновляем позиции
            for track_order in track_orders:
                track_id = track_order["track_id"]
                new_position = track_order["position"]
                
                query = select(PlaylistTrack).where(
                    PlaylistTrack.playlist_id == playlist_id,
                    PlaylistTrack.track_id == track_id
                )
                result = await session.execute(query)
                playlist_track = result.scalar_one_or_none()
                
                if playlist_track:
                    playlist_track.position = new_position
            
            # Обновляем время изменения плейлиста
            await self._update_playlist_timestamp(session, playlist_id)
            
            await session.commit()
            
            self.logger.info(f"Reordered tracks in playlist {playlist_id}")
            return True
    
    async def add_collaborator(
        self,
        playlist_id: int,
        owner_id: int,
        collaborator_data: PlaylistCollaboratorAdd
    ) -> bool:
        """Добавить коллаборатора в плейлист"""
        async with get_session() as session:
            # Проверяем, что пользователь является владельцем
            playlist_query = select(Playlist).where(
                Playlist.id == playlist_id,
                Playlist.created_by_id == owner_id
            )
            playlist_result = await session.execute(playlist_query)
            playlist = playlist_result.scalar_one_or_none()
            
            if not playlist:
                return False
            
            # Проверяем существование пользователя-коллаборатора
            user_query = select(User).where(User.id == collaborator_data.user_id)
            user_result = await session.execute(user_query)
            user = user_result.scalar_one_or_none()
            
            if not user:
                return False
            
            # Проверяем, не является ли уже коллаборатором
            existing_query = select(PlaylistCollaborator).where(
                PlaylistCollaborator.playlist_id == playlist_id,
                PlaylistCollaborator.user_id == collaborator_data.user_id
            )
            existing_result = await session.execute(existing_query)
            existing = existing_result.scalar_one_or_none()
            
            if existing:
                return False
            
            # Создаем коллаборатора
            collaborator = PlaylistCollaborator(
                playlist_id=playlist_id,
                user_id=collaborator_data.user_id,
                role=collaborator_data.role,
                added_by_id=owner_id,
                added_at=datetime.now(timezone.utc)
            )
            
            session.add(collaborator)
            await session.commit()
            
            self.logger.info(f"Added collaborator {collaborator_data.user_id} to playlist {playlist_id}")
            return True
    
    async def remove_collaborator(
        self,
        playlist_id: int,
        owner_id: int,
        collaborator_user_id: int
    ) -> bool:
        """Удалить коллаборатора из плейлиста"""
        async with get_session() as session:
            # Проверяем права владельца
            playlist_query = select(Playlist).where(
                Playlist.id == playlist_id,
                Playlist.created_by_id == owner_id
            )
            playlist_result = await session.execute(playlist_query)
            playlist = playlist_result.scalar_one_or_none()
            
            if not playlist:
                return False
            
            # Находим коллаборатора
            collab_query = select(PlaylistCollaborator).where(
                PlaylistCollaborator.playlist_id == playlist_id,
                PlaylistCollaborator.user_id == collaborator_user_id
            )
            collab_result = await session.execute(collab_query)
            collaborator = collab_result.scalar_one_or_none()
            
            if not collaborator:
                return False
            
            await session.delete(collaborator)
            await session.commit()
            
            self.logger.info(f"Removed collaborator {collaborator_user_id} from playlist {playlist_id}")
            return True
    
    async def get_public_playlists(
        self,
        limit: int = 50,
        offset: int = 0,
        search_query: Optional[str] = None
    ) -> List[Playlist]:
        """Получить публичные плейлисты"""
        async with get_session() as session:
            query = select(Playlist).options(
                selectinload(Playlist.created_by),
                selectinload(Playlist.tracks)
            ).where(
                Playlist.is_public == True,
                Playlist.is_deleted == False
            )
            
            if search_query:
                search_filter = or_(
                    Playlist.title.ilike(f"%{search_query}%"),
                    Playlist.description.ilike(f"%{search_query}%")
                )
                query = query.where(search_filter)
            
            query = query.order_by(Playlist.updated_at.desc()).limit(limit).offset(offset)
            
            result = await session.execute(query)
            return result.scalars().all()
    
    async def get_trending_playlists(self, limit: int = 20) -> List[Playlist]:
        """Получить популярные плейлисты"""
        async with get_session() as session:
            # Простая логика: плейлисты с наибольшим количеством треков
            # В реальной системе можно добавить метрики просмотров, лайков и т.д.
            
            query = select(Playlist).options(
                selectinload(Playlist.created_by),
                selectinload(Playlist.tracks)
            ).join(PlaylistTrack).where(
                Playlist.is_public == True,
                Playlist.is_deleted == False
            ).group_by(Playlist.id).order_by(
                func.count(PlaylistTrack.id).desc()
            ).limit(limit)
            
            result = await session.execute(query)
            return result.scalars().all()
    
    async def duplicate_playlist(
        self,
        playlist_id: int,
        user_id: int,
        new_title: Optional[str] = None
    ) -> Optional[Playlist]:
        """Дублировать плейлист"""
        async with get_session() as session:
            # Получаем оригинальный плейлист
            original = await self.get_playlist_by_id(playlist_id, user_id)
            if not original:
                return None
            
            # Создаем новый плейлист
            new_playlist = Playlist(
                title=new_title or f"Copy of {original.title}",
                description=original.description,
                cover_url=original.cover_url,
                is_public=False,  # Копии всегда приватные
                created_by_id=user_id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            
            session.add(new_playlist)
            await session.flush()  # Получаем ID нового плейлиста
            
            # Копируем треки
            for playlist_track in original.tracks:
                new_playlist_track = PlaylistTrack(
                    playlist_id=new_playlist.id,
                    track_id=playlist_track.track_id,
                    position=playlist_track.position,
                    added_by_id=user_id,
                    added_at=datetime.now(timezone.utc)
                )
                session.add(new_playlist_track)
            
            await session.commit()
            await session.refresh(new_playlist)
            
            self.logger.info(f"Duplicated playlist {playlist_id} for user {user_id}")
            return new_playlist
    
    async def get_playlist_stats(self, playlist_id: int) -> Dict[str, Any]:
        """Получить статистику плейлиста"""
        async with get_session() as session:
            playlist = await self.get_playlist_by_id(playlist_id)
            if not playlist:
                return {}
            
            # Количество треков
            tracks_count = len(playlist.tracks) if playlist.tracks else 0
            
            # Общая длительность
            total_duration = 0
            if playlist.tracks:
                for playlist_track in playlist.tracks:
                    if playlist_track.track and playlist_track.track.duration:
                        total_duration += playlist_track.track.duration
            
            # Количество коллабораторов
            collaborators_count = len(playlist.collaborators) if playlist.collaborators else 0
            
            # Жанры в плейлисте
            genres = set()
            if playlist.tracks:
                for playlist_track in playlist.tracks:
                    if playlist_track.track and playlist_track.track.genre:
                        genres.add(playlist_track.track.genre)
            
            return {
                'tracks_count': tracks_count,
                'total_duration': total_duration,
                'collaborators_count': collaborators_count,
                'genres': list(genres),
                'created_at': playlist.created_at,
                'updated_at': playlist.updated_at,
                'is_public': playlist.is_public
            }
    
    async def search_user_playlists(
        self,
        user_id: int,
        search_query: str,
        limit: int = 20
    ) -> List[Playlist]:
        """Поиск по плейлистам пользователя"""
        async with get_session() as session:
            query = select(Playlist).options(
                selectinload(Playlist.tracks)
            ).where(
                or_(
                    Playlist.created_by_id == user_id,
                    Playlist.id.in_(
                        select(PlaylistCollaborator.playlist_id).where(
                            PlaylistCollaborator.user_id == user_id
                        )
                    )
                ),
                Playlist.is_deleted == False,
                or_(
                    Playlist.title.ilike(f"%{search_query}%"),
                    Playlist.description.ilike(f"%{search_query}%")
                )
            ).order_by(Playlist.updated_at.desc()).limit(limit)
            
            result = await session.execute(query)
            return result.scalars().all()
    
    # Вспомогательные методы
    
    async def _has_playlist_access(self, playlist_id: int, user_id: int) -> bool:
        """Проверить доступ к плейлисту"""
        async with get_session() as session:
            # Владелец или коллаборатор
            access_query = select(Playlist).where(
                Playlist.id == playlist_id,
                or_(
                    Playlist.created_by_id == user_id,
                    Playlist.id.in_(
                        select(PlaylistCollaborator.playlist_id).where(
                            PlaylistCollaborator.user_id == user_id
                        )
                    )
                )
            )
            result = await session.execute(access_query)
            return result.scalar_one_or_none() is not None
    
    async def _can_edit_playlist(self, playlist_id: int, user_id: int) -> bool:
        """Проверить права на редактирование плейлиста"""
        async with get_session() as session:
            # Владелец или коллаборатор с правами редактирования
            edit_query = select(Playlist).where(
                Playlist.id == playlist_id,
                or_(
                    Playlist.created_by_id == user_id,
                    Playlist.id.in_(
                        select(PlaylistCollaborator.playlist_id).where(
                            PlaylistCollaborator.user_id == user_id,
                            PlaylistCollaborator.role.in_([
                                CollaboratorRole.EDITOR,
                                CollaboratorRole.ADMIN
                            ])
                        )
                    )
                )
            )
            result = await session.execute(edit_query)
            return result.scalar_one_or_none() is not None
    
    async def _shift_tracks_positions(
        self,
        session: AsyncSession,
        playlist_id: int,
        from_position: int,
        shift: int = 1
    ) -> None:
        """Сдвинуть позиции треков"""
        shift_query = select(PlaylistTrack).where(
            PlaylistTrack.playlist_id == playlist_id,
            PlaylistTrack.position >= from_position
        )
        shift_result = await session.execute(shift_query)
        tracks_to_shift = shift_result.scalars().all()
        
        for track in tracks_to_shift:
            track.position += shift
    
    async def _update_playlist_timestamp(
        self,
        session: AsyncSession,
        playlist_id: int
    ) -> None:
        """Обновить время изменения плейлиста"""
        playlist_query = select(Playlist).where(Playlist.id == playlist_id)
        playlist_result = await session.execute(playlist_query)
        playlist = playlist_result.scalar_one_or_none()
        
        if playlist:
            playlist.updated_at = datetime.now(timezone.utc)


# Создаем глобальный экземпляр сервиса
playlist_service = PlaylistService()