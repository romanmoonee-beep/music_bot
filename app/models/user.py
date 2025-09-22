"""
Модель пользователя Telegram бота
"""
from typing import Optional, List
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import String, Boolean, Integer, BigInteger, DateTime, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func

from app.models.base import BaseModel, CacheableMixin, SoftDeleteMixin, StatsMixin, MetadataMixin


class UserStatus(str, Enum):
    """Статус пользователя"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"
    PREMIUM = "premium"


class SubscriptionType(str, Enum):
    """Тип подписки"""
    FREE = "free"
    PREMIUM_1M = "premium_1m"
    PREMIUM_3M = "premium_3m"
    PREMIUM_1Y = "premium_1y"


class User(BaseModel, CacheableMixin, SoftDeleteMixin, StatsMixin, MetadataMixin):
    """Модель пользователя"""
    
    __tablename__ = "users"
    
    # Основная информация
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
        comment="ID пользователя в Telegram"
    )
    
    username: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Username пользователя в Telegram"
    )
    
    first_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Имя пользователя"
    )
    
    last_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Фамилия пользователя"
    )
    
    language_code: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        default="ru",
        comment="Код языка пользователя"
    )
    
    # Статус и активность
    status: Mapped[UserStatus] = mapped_column(
        SQLEnum(UserStatus),
        default=UserStatus.ACTIVE,
        comment="Статус пользователя"
    )
    
    is_bot: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Является ли пользователь ботом"
    )
    
    is_premium_telegram: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Имеет ли пользователь Telegram Premium"
    )
    
    # Подписка
    subscription_type: Mapped[SubscriptionType] = mapped_column(
        SQLEnum(SubscriptionType),
        default=SubscriptionType.FREE,
        comment="Тип подписки"
    )
    
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата окончания подписки"
    )
    
    # Активность
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Последняя активность"
    )
    
    last_command: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Последняя выполненная команда"
    )
    
    # Статистика использования
    total_searches: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
        comment="Общее количество поисков"
    )
    
    daily_searches: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="Количество поисков за день"
    )
    
    daily_downloads: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="Количество скачиваний за день"
    )
    
    last_search_reset: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата последнего сброса дневных лимитов"
    )
    
    # Настройки пользователя
    preferred_quality: Mapped[str] = mapped_column(
        String(20),
        default="192kbps",
        comment="Предпочитаемое качество аудио"
    )
    
    auto_add_to_playlist: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Автоматически добавлять в плейлист"
    )
    
    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        comment="Включены ли уведомления"
    )
    
    # Геолокация
    country_code: Mapped[Optional[str]] = mapped_column(
        String(3),
        nullable=True,
        comment="Код страны пользователя"
    )
    
    city: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Город пользователя"
    )
    
    timezone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Часовой пояс пользователя"
    )
    
    # Реферальная система
    referrer_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        comment="ID пригласившего пользователя"
    )
    
    referral_code: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        unique=True,
        comment="Реферальный код пользователя"
    )
    
    invited_users_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="Количество приглашенных пользователей"
    )
    
    # Связи
    playlists = relationship("Playlist", back_populates="user", lazy="selectin")
    searches = relationship("SearchHistory", back_populates="user", lazy="selectin")
    subscriptions = relationship("Subscription", back_populates="user", lazy="selectin")
    
    def __repr__(self) -> str:
        return f"<User(telegram_id={self.telegram_id}, username={self.username})>"
    
    @property
    def full_name(self) -> str:
        """Полное имя пользователя"""
        parts = []
        if self.first_name:
            parts.append(self.first_name)
        if self.last_name:
            parts.append(self.last_name)
        return " ".join(parts) or self.username or f"User {self.telegram_id}"
    
    @property
    def display_name(self) -> str:
        """Отображаемое имя пользователя"""
        if self.username:
            return f"@{self.username}"
        return self.full_name
    
    @property
    def is_premium(self) -> bool:
        """Проверка наличия активной премиум подписки"""
        if self.subscription_type == SubscriptionType.FREE:
            return False
        
        if not self.subscription_expires_at:
            return False
        
        return self.subscription_expires_at > datetime.now(timezone.utc)
    
    @property
    def days_until_expiry(self) -> Optional[int]:
        """Количество дней до окончания подписки"""
        if not self.subscription_expires_at:
            return None
        
        delta = self.subscription_expires_at - datetime.now(timezone.utc)
        return max(0, delta.days)
    
    @property
    def can_search(self) -> bool:
        """Может ли пользователь выполнять поиск"""
        if self.status == UserStatus.BANNED:
            return False
        
        # Сброс дневных лимитов
        self._reset_daily_limits_if_needed()
        
        if self.is_premium:
            return True
        
        # Лимиты для бесплатных пользователей
        from app.core.config import settings
        return self.daily_searches < settings.RATE_LIMIT_FREE_USERS
    
    @property
    def can_download(self) -> bool:
        """Может ли пользователь скачивать треки"""
        if self.status == UserStatus.BANNED:
            return False
        
        # Сброс дневных лимитов
        self._reset_daily_limits_if_needed()
        
        if self.is_premium:
            return True
        
        # Лимиты для бесплатных пользователей
        from app.core.config import settings
        return self.daily_downloads < settings.RATE_LIMIT_FREE_USERS
    
    def _reset_daily_limits_if_needed(self) -> None:
        """Сброс дневных лимитов при необходимости"""
        now = datetime.now(timezone.utc)
        
        if (not self.last_search_reset or 
            self.last_search_reset.date() < now.date()):
            self.daily_searches = 0
            self.daily_downloads = 0
            self.last_search_reset = now
    
    async def update_activity(self, session: AsyncSession, command: str = None) -> None:
        """Обновление активности пользователя"""
        self.last_activity_at = datetime.now(timezone.utc)
        if command:
            self.last_command = command
        await session.flush()
    
    async def increment_search_count(self, session: AsyncSession) -> None:
        """Увеличение счетчика поисков"""
        self._reset_daily_limits_if_needed()
        self.total_searches += 1
        self.daily_searches += 1
        await session.flush()
    
    async def increment_download_count(self, session: AsyncSession) -> None:
        """Увеличение счетчика скачиваний"""
        self._reset_daily_limits_if_needed()
        self.daily_downloads += 1
        await session.flush()
    
    async def set_premium(
        self, 
        session: AsyncSession,
        subscription_type: SubscriptionType,
        expires_at: datetime
    ) -> None:
        """Установка премиум подписки"""
        self.subscription_type = subscription_type
        self.subscription_expires_at = expires_at
        self.status = UserStatus.PREMIUM
        await session.flush()
    
    async def remove_premium(self, session: AsyncSession) -> None:
        """Удаление премиум подписки"""
        self.subscription_type = SubscriptionType.FREE
        self.subscription_expires_at = None
        self.status = UserStatus.ACTIVE
        await session.flush()
    
    async def ban(self, session: AsyncSession, reason: str = None) -> None:
        """Блокировка пользователя"""
        self.status = UserStatus.BANNED
        if reason:
            self.set_metadata("ban_reason", reason)
            self.set_metadata("banned_at", datetime.now(timezone.utc).isoformat())
        await session.flush()
    
    async def unban(self, session: AsyncSession) -> None:
        """Разблокировка пользователя"""
        self.status = UserStatus.ACTIVE
        self.remove_metadata("ban_reason")
        self.remove_metadata("banned_at")
        await session.flush()
    
    @classmethod
    async def get_by_telegram_id(
        cls,
        session: AsyncSession,
        telegram_id: int
    ) -> Optional["User"]:
        """Получение пользователя по Telegram ID"""
        result = await session.execute(
            select(cls).where(cls.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()
    
    @classmethod
    async def get_or_create(
        cls,
        session: AsyncSession,
        telegram_id: int,
        **kwargs
    ) -> tuple["User", bool]:
        """Получение или создание пользователя"""
        user = await cls.get_by_telegram_id(session, telegram_id)
        
        if user:
            return user, False
        
        # Создание нового пользователя
        user_data = {"telegram_id": telegram_id}
        user_data.update(kwargs)
        
        user = cls(**user_data)
        session.add(user)
        await session.flush()
        await session.refresh(user)
        
        return user, True
    
    @classmethod
    async def get_premium_users(
        cls,
        session: AsyncSession,
        limit: Optional[int] = None
    ) -> List["User"]:
        """Получение пользователей с активной премиум подпиской"""
        query = select(cls).where(
            cls.subscription_type != SubscriptionType.FREE,
            cls.subscription_expires_at > datetime.now(timezone.utc)
        )
        
        if limit:
            query = query.limit(limit)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @classmethod
    async def get_active_users(
        cls,
        session: AsyncSession,
        days: int = 7,
        limit: Optional[int] = None
    ) -> List["User"]:
        """Получение активных пользователей за последние N дней"""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = select(cls).where(
            cls.last_activity_at >= since,
            cls.status != UserStatus.BANNED
        )
        
        if limit:
            query = query.limit(limit)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @classmethod
    async def get_users_by_country(
        cls,
        session: AsyncSession,
        country_code: str,
        limit: Optional[int] = None
    ) -> List["User"]:
        """Получение пользователей по стране"""
        query = select(cls).where(cls.country_code == country_code)
        
        if limit:
            query = query.limit(limit)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @classmethod
    async def get_users_for_broadcast(
        cls,
        session: AsyncSession,
        subscription_type: Optional[SubscriptionType] = None,
        country_code: Optional[str] = None,
        active_days: Optional[int] = None
    ) -> List["User"]:
        """Получение пользователей для рассылки с фильтрами"""
        query = select(cls).where(
            cls.status != UserStatus.BANNED,
            cls.notifications_enabled == True
        )
        
        if subscription_type:
            query = query.where(cls.subscription_type == subscription_type)
        
        if country_code:
            query = query.where(cls.country_code == country_code)
        
        if active_days:
            since = datetime.now(timezone.utc) - timedelta(days=active_days)
            query = query.where(cls.last_activity_at >= since)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @classmethod
    async def get_stats(cls, session: AsyncSession) -> dict:
        """Получение общей статистики пользователей"""
        # Общее количество
        total_result = await session.execute(
            select(func.count(cls.id))
        )
        total_users = total_result.scalar()
        
        # Активные пользователи (за последнюю неделю)
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        active_result = await session.execute(
            select(func.count(cls.id)).where(
                cls.last_activity_at >= week_ago
            )
        )
        active_users = active_result.scalar()
        
        # Премиум пользователи
        premium_result = await session.execute(
            select(func.count(cls.id)).where(
                cls.subscription_type != SubscriptionType.FREE,
                cls.subscription_expires_at > datetime.now(timezone.utc)
            )
        )
        premium_users = premium_result.scalar()
        
        # Заблокированные пользователи
        banned_result = await session.execute(
            select(func.count(cls.id)).where(
                cls.status == UserStatus.BANNED
            )
        )
        banned_users = banned_result.scalar()
        
        return {
            "total_users": total_users,
            "active_users": active_users,
            "premium_users": premium_users,
            "banned_users": banned_users,
            "conversion_rate": (premium_users / total_users * 100) if total_users > 0 else 0
        }