"""
Сервис для работы с пользователями
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.database import get_session
from app.core.logging import get_logger
from app.core.config import settings
from app.models.user import User, UserSubscription, SubscriptionType
from app.models.track import Track, TrackPlay
from app.schemas.user import UserCreate, UserUpdate, UserResponse, UserStats
from app.schemas.payment import SubscriptionCreate


class UserService:
    """Сервис для управления пользователями"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
    
    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = None
    ) -> User:
        """Получить или создать пользователя"""
        async with get_session() as session:
            # Ищем существующего пользователя
            query = select(User).where(User.telegram_id == telegram_id)
            result = await session.execute(query)
            user = result.scalar_one_or_none()
            
            if user:
                # Обновляем данные если изменились
                updated = False
                if username and user.username != username:
                    user.username = username
                    updated = True
                if first_name and user.first_name != first_name:
                    user.first_name = first_name
                    updated = True
                if last_name and user.last_name != last_name:
                    user.last_name = last_name
                    updated = True
                if language_code and user.language_code != language_code:
                    user.language_code = language_code
                    updated = True
                
                if updated:
                    user.last_seen_at = datetime.now(timezone.utc)
                    await session.commit()
                    await session.refresh(user)
                    self.logger.info(f"Updated user data for {telegram_id}")
                
                return user
            
            # Создаем нового пользователя
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code or 'ru',
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc),
                is_active=True,
                settings={'notifications': True, 'quality': 'medium'}
            )
            
            session.add(user)
            await session.commit()
            await session.refresh(user)
            
            self.logger.info(f"Created new user: {telegram_id}")
            return user
    
    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Получить пользователя по Telegram ID"""
        async with get_session() as session:
            query = select(User).where(User.telegram_id == telegram_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()
    
    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Получить пользователя по ID"""
        async with get_session() as session:
            query = select(User).where(User.id == user_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()
    
    async def update_user(self, user_id: int, user_data: UserUpdate) -> Optional[User]:
        """Обновить данные пользователя"""
        async with get_session() as session:
            query = select(User).where(User.id == user_id)
            result = await session.execute(query)
            user = result.scalar_one_or_none()
            
            if not user:
                return None
            
            # Обновляем поля
            update_data = user_data.dict(exclude_unset=True)
            for field, value in update_data.items():
                setattr(user, field, value)
            
            user.updated_at = datetime.now(timezone.utc)
            
            await session.commit()
            await session.refresh(user)
            
            self.logger.info(f"Updated user {user_id}")
            return user
    
    async def update_last_seen(self, telegram_id: int) -> None:
        """Обновить время последней активности"""
        async with get_session() as session:
            query = select(User).where(User.telegram_id == telegram_id)
            result = await session.execute(query)
            user = result.scalar_one_or_none()
            
            if user:
                user.last_seen_at = datetime.now(timezone.utc)
                await session.commit()
    
    async def is_premium_user(self, telegram_id: int) -> bool:
        """Проверить является ли пользователь Premium"""
        async with get_session() as session:
            query = select(User).options(
                selectinload(User.subscriptions)
            ).where(User.telegram_id == telegram_id)
            
            result = await session.execute(query)
            user = result.scalar_one_or_none()
            
            if not user:
                return False
            
            # Проверяем активные подписки
            now = datetime.now(timezone.utc)
            for subscription in user.subscriptions:
                if (subscription.is_active and 
                    subscription.subscription_type == SubscriptionType.PREMIUM and
                    subscription.expires_at > now):
                    return True
            
            return False
    
    async def get_user_subscription(self, telegram_id: int) -> Optional[UserSubscription]:
        """Получить активную подписку пользователя"""
        async with get_session() as session:
            query = select(UserSubscription).join(User).where(
                User.telegram_id == telegram_id,
                UserSubscription.is_active == True,
                UserSubscription.expires_at > datetime.now(timezone.utc)
            ).order_by(UserSubscription.expires_at.desc())
            
            result = await session.execute(query)
            return result.scalar_one_or_none()
    
    async def create_subscription(
        self,
        telegram_id: int,
        subscription_data: SubscriptionCreate
    ) -> Optional[UserSubscription]:
        """Создать подписку для пользователя"""
        async with get_session() as session:
            user = await self.get_user_by_telegram_id(telegram_id)
            if not user:
                return None
            
            # Деактивируем старые подписки
            old_subs_query = select(UserSubscription).where(
                UserSubscription.user_id == user.id,
                UserSubscription.is_active == True
            )
            old_subs_result = await session.execute(old_subs_query)
            old_subscriptions = old_subs_result.scalars().all()
            
            for old_sub in old_subscriptions:
                old_sub.is_active = False
            
            # Создаем новую подписку
            subscription = UserSubscription(
                user_id=user.id,
                subscription_type=subscription_data.subscription_type,
                payment_method=subscription_data.payment_method,
                amount=subscription_data.amount,
                currency=subscription_data.currency,
                starts_at=datetime.now(timezone.utc),
                expires_at=subscription_data.expires_at,
                is_active=True,
                auto_renew=subscription_data.auto_renew,
                created_at=datetime.now(timezone.utc)
            )
            
            session.add(subscription)
            await session.commit()
            await session.refresh(subscription)
            
            self.logger.info(f"Created subscription for user {telegram_id}")
            return subscription
    
    async def get_user_stats(self, telegram_id: int) -> UserStats:
        """Получить статистику пользователя"""
        async with get_session() as session:
            user = await self.get_user_by_telegram_id(telegram_id)
            if not user:
                return UserStats(
                    tracks_downloaded=0,
                    tracks_played=0,
                    playlists_created=0,
                    total_listening_time=0,
                    favorite_genres=[],
                    join_date=datetime.now(timezone.utc)
                )
            
            # Количество скачанных треков
            downloads_query = select(Track).where(
                Track.created_by_id == user.id
            )
            downloads_result = await session.execute(downloads_query)
            tracks_downloaded = len(downloads_result.scalars().all())
            
            # Количество прослушиваний
            plays_query = select(TrackPlay).where(
                TrackPlay.user_id == user.id
            )
            plays_result = await session.execute(plays_query)
            track_plays = plays_result.scalars().all()
            tracks_played = len(track_plays)
            
            # Общее время прослушивания
            total_listening_time = sum(
                play.duration_played or 0 for play in track_plays
            )
            
            # Любимые жанры
            genre_counts = {}
            for play in track_plays:
                if hasattr(play, 'track') and play.track and play.track.genre:
                    genre = play.track.genre
                    genre_counts[genre] = genre_counts.get(genre, 0) + 1
            
            favorite_genres = sorted(
                genre_counts.items(), key=lambda x: x[1], reverse=True
            )[:5]
            
            return UserStats(
                tracks_downloaded=tracks_downloaded,
                tracks_played=tracks_played,
                playlists_created=len(user.playlists) if user.playlists else 0,
                total_listening_time=total_listening_time,
                favorite_genres=[genre for genre, _ in favorite_genres],
                join_date=user.created_at
            )
    
    async def check_daily_limits(self, telegram_id: int) -> Dict[str, Any]:
        """Проверить дневные лимиты пользователя"""
        is_premium = await self.is_premium_user(telegram_id)
        
        # Лимиты для разных типов пользователей
        if is_premium:
            daily_track_limit = settings.RATE_LIMIT_PREMIUM_USERS
            search_rate_limit = 100  # запросов в минуту
        else:
            daily_track_limit = settings.RATE_LIMIT_FREE_USERS
            search_rate_limit = settings.SEARCH_RATE_LIMIT
        
        # Подсчитываем использование за сегодня
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        async with get_session() as session:
            user = await self.get_user_by_telegram_id(telegram_id)
            if not user:
                return {
                    'tracks_used': 0,
                    'tracks_limit': daily_track_limit,
                    'tracks_remaining': daily_track_limit,
                    'is_premium': False,
                    'can_download': True
                }
            
            # Считаем скачанные сегодня треки
            tracks_query = select(Track).where(
                Track.created_by_id == user.id,
                Track.created_at >= today_start
            )
            tracks_result = await session.execute(tracks_query)
            tracks_used = len(tracks_result.scalars().all())
            
            tracks_remaining = max(0, daily_track_limit - tracks_used)
            can_download = tracks_remaining > 0
            
            return {
                'tracks_used': tracks_used,
                'tracks_limit': daily_track_limit,
                'tracks_remaining': tracks_remaining,
                'is_premium': is_premium,
                'can_download': can_download,
                'search_rate_limit': search_rate_limit
            }
    
    async def ban_user(self, telegram_id: int, reason: Optional[str] = None) -> bool:
        """Заблокировать пользователя"""
        async with get_session() as session:
            user = await self.get_user_by_telegram_id(telegram_id)
            if not user:
                return False
            
            user.is_active = False
            user.ban_reason = reason
            user.banned_at = datetime.now(timezone.utc)
            user.updated_at = datetime.now(timezone.utc)
            
            await session.commit()
            
            self.logger.warning(f"Banned user {telegram_id}, reason: {reason}")
            return True
    
    async def unban_user(self, telegram_id: int) -> bool:
        """Разблокировать пользователя"""
        async with get_session() as session:
            user = await self.get_user_by_telegram_id(telegram_id)
            if not user:
                return False
            
            user.is_active = True
            user.ban_reason = None
            user.banned_at = None
            user.updated_at = datetime.now(timezone.utc)
            
            await session.commit()
            
            self.logger.info(f"Unbanned user {telegram_id}")
            return True
    
    async def delete_user_data(self, telegram_id: int) -> bool:
        """Удалить все данные пользователя (GDPR)"""
        async with get_session() as session:
            user = await self.get_user_by_telegram_id(telegram_id)
            if not user:
                return False
            
            # Помечаем пользователя как удаленного
            user.is_deleted = True
            user.username = None
            user.first_name = "Deleted"
            user.last_name = "User"
            user.settings = {}
            user.updated_at = datetime.now(timezone.utc)
            
            await session.commit()
            
            self.logger.info(f"Deleted user data for {telegram_id}")
            return True
    
    async def get_users_for_broadcast(
        self,
        is_active: bool = True,
        is_premium: Optional[bool] = None,
        language_codes: Optional[List[str]] = None,
        last_seen_days: Optional[int] = None
    ) -> List[User]:
        """Получить пользователей для рассылки"""
        async with get_session() as session:
            query = select(User).where(
                User.is_active == is_active,
                User.is_deleted == False
            )
            
            # Фильтр по Premium статусу
            if is_premium is not None:
                if is_premium:
                    # Только Premium пользователи
                    query = query.join(UserSubscription).where(
                        UserSubscription.is_active == True,
                        UserSubscription.subscription_type == SubscriptionType.PREMIUM,
                        UserSubscription.expires_at > datetime.now(timezone.utc)
                    )
                else:
                    # Только Free пользователи (без активных Premium подписок)
                    subquery = select(UserSubscription.user_id).where(
                        UserSubscription.is_active == True,
                        UserSubscription.subscription_type == SubscriptionType.PREMIUM,
                        UserSubscription.expires_at > datetime.now(timezone.utc)
                    )
                    query = query.where(~User.id.in_(subquery))
            
            # Фильтр по языкам
            if language_codes:
                query = query.where(User.language_code.in_(language_codes))
            
            # Фильтр по активности
            if last_seen_days:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=last_seen_days)
                query = query.where(User.last_seen_at >= cutoff_date)
            
            result = await session.execute(query)
            return result.scalars().all()
    
    async def get_user_count_stats(self) -> Dict[str, int]:
        """Получить статистику по количеству пользователей"""
        async with get_session() as session:
            # Общее количество
            total_query = select(User).where(User.is_deleted == False)
            total_result = await session.execute(total_query)
            total_users = len(total_result.scalars().all())
            
            # Активные пользователи
            active_query = select(User).where(
                User.is_active == True,
                User.is_deleted == False
            )
            active_result = await session.execute(active_query)
            active_users = len(active_result.scalars().all())
            
            # Premium пользователи
            now = datetime.now(timezone.utc)
            premium_query = select(User).join(UserSubscription).where(
                User.is_deleted == False,
                UserSubscription.is_active == True,
                UserSubscription.subscription_type == SubscriptionType.PREMIUM,
                UserSubscription.expires_at > now
            )
            premium_result = await session.execute(premium_query)
            premium_users = len(premium_result.scalars().all())
            
            # Новые пользователи за неделю
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            new_query = select(User).where(
                User.created_at >= week_ago,
                User.is_deleted == False
            )
            new_result = await session.execute(new_query)
            new_users = len(new_result.scalars().all())
            
            return {
                'total': total_users,
                'active': active_users,
                'premium': premium_users,
                'new_this_week': new_users,
                'free': total_users - premium_users
            }


# Создаем глобальный экземпляр сервиса
user_service = UserService()