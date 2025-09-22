"""
Модели для аналитики и метрик
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from enum import Enum

from sqlalchemy import String, Boolean, Integer, BigInteger, DateTime, Float, Enum as SQLEnum, Index, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func, and_

from app.models.base import BaseModel


class EventType(str, Enum):
    """Типы событий для аналитики"""
    # Пользовательские события
    USER_REGISTRATION = "user_registration"
    USER_LOGIN = "user_login"
    USER_PREMIUM_PURCHASE = "user_premium_purchase"
    USER_PREMIUM_EXPIRED = "user_premium_expired"
    
    # Музыкальные события
    TRACK_SEARCH = "track_search"
    TRACK_PLAY = "track_play"
    TRACK_DOWNLOAD = "track_download"
    TRACK_LIKE = "track_like"
    TRACK_SHARE = "track_share"
    
    # Плейлисты
    PLAYLIST_CREATE = "playlist_create"
    PLAYLIST_ADD_TRACK = "playlist_add_track"
    PLAYLIST_SHARE = "playlist_share"
    
    # Платежи
    PAYMENT_INITIATED = "payment_initiated"
    PAYMENT_COMPLETED = "payment_completed"
    PAYMENT_FAILED = "payment_failed"
    
    # Системные события
    BOT_COMMAND = "bot_command"
    API_REQUEST = "api_request"
    ERROR_OCCURRED = "error_occurred"


class UserAgent(str, Enum):
    """Типы клиентов"""
    TELEGRAM_BOT = "telegram_bot"
    TELEGRAM_WEB = "telegram_web"
    TELEGRAM_MOBILE = "telegram_mobile"
    TELEGRAM_DESKTOP = "telegram_desktop"
    API_CLIENT = "api_client"
    ADMIN_PANEL = "admin_panel"


class AnalyticsEvent(BaseModel):
    """Модель событий для аналитики"""
    
    __tablename__ = "analytics_events"
    
    # Основная информация о событии
    event_type: Mapped[EventType] = mapped_column(
        SQLEnum(EventType),
        index=True,
        comment="Тип события"
    )
    
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
        comment="ID пользователя (если применимо)"
    )
    
    session_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="ID сессии пользователя"
    )
    
    # Контекст события
    entity_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Тип сущности (track, playlist, user, etc.)"
    )
    
    entity_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="ID сущности"
    )
    
    # Свойства события
    properties: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Дополнительные свойства события"
    )
    
    # Технические данные
    user_agent: Mapped[Optional[UserAgent]] = mapped_column(
        SQLEnum(UserAgent),
        nullable=True,
        comment="Клиент пользователя"
    )
    
    ip_address: Mapped[Optional[str]] = mapped_column(
        INET,
        nullable=True,
        comment="IP адрес пользователя"
    )
    
    country_code: Mapped[Optional[str]] = mapped_column(
        String(3),
        nullable=True,
        comment="Код страны"
    )
    
    # Временные метки
    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="Точное время события"
    )
    
    # Индексы для быстрого поиска
    __table_args__ = (
        Index("idx_analytics_user_time", "user_id", "event_timestamp"),
        Index("idx_analytics_type_time", "event_type", "event_timestamp"),
        Index("idx_analytics_entity", "entity_type", "entity_id"),
        Index("idx_analytics_country_time", "country_code", "event_timestamp"),
    )
    
    def __repr__(self) -> str:
        return f"<AnalyticsEvent(type={self.event_type}, user_id={self.user_id})>"
    
    @classmethod
    async def track_event(
        cls,
        session: AsyncSession,
        event_type: EventType,
        user_id: Optional[int] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        user_agent: Optional[UserAgent] = None,
        ip_address: Optional[str] = None,
        country_code: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> "AnalyticsEvent":
        """Создание события аналитики"""
        event = cls(
            event_type=event_type,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            properties=properties or {},
            user_agent=user_agent,
            ip_address=ip_address,
            country_code=country_code,
            session_id=session_id
        )
        
        session.add(event)
        # Не делаем flush для батчинга событий
        
        return event
    
    @classmethod
    async def get_events_count(
        cls,
        session: AsyncSession,
        event_type: Optional[EventType] = None,
        user_id: Optional[int] = None,
        hours: int = 24
    ) -> int:
        """Получение количества событий за период"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        query = select(func.count(cls.id)).where(
            cls.event_timestamp >= since
        )
        
        if event_type:
            query = query.where(cls.event_type == event_type)
        
        if user_id:
            query = query.where(cls.user_id == user_id)
        
        result = await session.execute(query)
        return result.scalar()
    
    @classmethod
    async def get_popular_tracks(
        cls,
        session: AsyncSession,
        hours: int = 24,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Получение популярных треков за период"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        result = await session.execute(
            select(
                cls.entity_id,
                func.count(cls.id).label('play_count')
            ).where(
                cls.event_type == EventType.TRACK_PLAY,
                cls.entity_type == 'track',
                cls.event_timestamp >= since,
                cls.entity_id.isnot(None)
            ).group_by(
                cls.entity_id
            ).order_by(
                func.count(cls.id).desc()
            ).limit(limit)
        )
        
        return [
            {
                'track_id': row.entity_id,
                'play_count': row.play_count
            }
            for row in result
        ]
    
    @classmethod
    async def get_user_activity_stats(
        cls,
        session: AsyncSession,
        hours: int = 24
    ) -> Dict[str, Any]:
        """Получение статистики активности пользователей"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Общая активность
        total_events_result = await session.execute(
            select(func.count(cls.id)).where(
                cls.event_timestamp >= since
            )
        )
        total_events = total_events_result.scalar()
        
        # Уникальные пользователи
        unique_users_result = await session.execute(
            select(func.count(func.distinct(cls.user_id))).where(
                cls.event_timestamp >= since,
                cls.user_id.isnot(None)
            )
        )
        unique_users = unique_users_result.scalar()
        
        # События по типам
        event_types_result = await session.execute(
            select(
                cls.event_type,
                func.count(cls.id).label('count')
            ).where(
                cls.event_timestamp >= since
            ).group_by(
                cls.event_type
            ).order_by(
                func.count(cls.id).desc()
            )
        )
        
        event_types_stats = {
            row.event_type.value: row.count
            for row in event_types_result
        }
        
        # География
        countries_result = await session.execute(
            select(
                cls.country_code,
                func.count(cls.id).label('count')
            ).where(
                cls.event_timestamp >= since,
                cls.country_code.isnot(None)
            ).group_by(
                cls.country_code
            ).order_by(
                func.count(cls.id).desc()
            ).limit(10)
        )
        
        countries_stats = {
            row.country_code: row.count
            for row in countries_result
        }
        
        return {
            'total_events': total_events,
            'unique_users': unique_users,
            'avg_events_per_user': total_events / unique_users if unique_users > 0 else 0,
            'event_types': event_types_stats,
            'top_countries': countries_stats
        }


class DailyStats(BaseModel):
    """Ежедневная статистика (агрегированная таблица)"""
    
    __tablename__ = "daily_stats"
    
    # Дата статистики
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        comment="Дата статистики (00:00 UTC)"
    )
    
    # Пользователи
    total_users: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Общее количество пользователей"
    )
    
    new_users: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Новые пользователи за день"
    )
    
    active_users: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Активные пользователи за день"
    )
    
    premium_users: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Премиум пользователи на конец дня"
    )
    
    # Музыкальная активность
    total_searches: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Общее количество поисков за день"
    )
    
    total_plays: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Общее количество воспроизведений за день"
    )
    
    total_downloads: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Общее количество скачиваний за день"
    )
    
    unique_tracks_played: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Уникальные треки, которые воспроизводились"
    )
    
    # Плейлисты
    playlists_created: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Создано плейлистов за день"
    )
    
    tracks_added_to_playlists: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Треков добавлено в плейлисты"
    )
    
    # Платежи и доходы
    payments_completed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Завершенные платежи за день"
    )
    
    revenue_usd: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        comment="Доход в USD за день"
    )
    
    new_subscriptions: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Новые подписки за день"
    )
    
    # Технические метрики
    api_requests: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="API запросы за день"
    )
    
    errors_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Количество ошибок за день"
    )
    
    avg_response_time_ms: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        comment="Среднее время ответа в миллисекундах"
    )
    
    # Индексы
    __table_args__ = (
        Index("idx_daily_stats_date", "date"),
    )
    
    def __repr__(self) -> str:
        return f"<DailyStats(date={self.date.date()}, active_users={self.active_users})>"
    
    @classmethod
    async def calculate_stats_for_date(
        cls,
        session: AsyncSession,
        date: datetime
    ) -> "DailyStats":
        """Расчет статистики за конкретную дату"""
        # Приводим дату к началу дня UTC
        start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=1)
        
        # Получаем или создаем запись
        existing_result = await session.execute(
            select(cls).where(cls.date == start_date)
        )
        stats = existing_result.scalar_one_or_none()
        
        if not stats:
            stats = cls(date=start_date)
            session.add(stats)
        
        # Пользователи
        from app.models.user import User
        
        # Общее количество пользователей на конец дня
        total_users_result = await session.execute(
            select(func.count(User.id)).where(
                User.created_at <= end_date
            )
        )
        stats.total_users = total_users_result.scalar()
        
        # Новые пользователи за день
        new_users_result = await session.execute(
            select(func.count(User.id)).where(
                User.created_at >= start_date,
                User.created_at < end_date
            )
        )
        stats.new_users = new_users_result.scalar()
        
        # Активные пользователи (с событиями за день)
        active_users_result = await session.execute(
            select(func.count(func.distinct(AnalyticsEvent.user_id))).where(
                AnalyticsEvent.event_timestamp >= start_date,
                AnalyticsEvent.event_timestamp < end_date,
                AnalyticsEvent.user_id.isnot(None)
            )
        )
        stats.active_users = active_users_result.scalar()
        
        # Премиум пользователи на конец дня
        premium_users_result = await session.execute(
            select(func.count(User.id)).where(
                User.subscription_expires_at > end_date,
                User.subscription_type != 'free'
            )
        )
        stats.premium_users = premium_users_result.scalar()
        
        # Музыкальная активность
        # Поиски
        searches_result = await session.execute(
            select(func.count(AnalyticsEvent.id)).where(
                AnalyticsEvent.event_type == EventType.TRACK_SEARCH,
                AnalyticsEvent.event_timestamp >= start_date,
                AnalyticsEvent.event_timestamp < end_date
            )
        )
        stats.total_searches = searches_result.scalar()
        
        # Воспроизведения
        plays_result = await session.execute(
            select(func.count(AnalyticsEvent.id)).where(
                AnalyticsEvent.event_type == EventType.TRACK_PLAY,
                AnalyticsEvent.event_timestamp >= start_date,
                AnalyticsEvent.event_timestamp < end_date
            )
        )
        stats.total_plays = plays_result.scalar()
        
        # Скачивания
        downloads_result = await session.execute(
            select(func.count(AnalyticsEvent.id)).where(
                AnalyticsEvent.event_type == EventType.TRACK_DOWNLOAD,
                AnalyticsEvent.event_timestamp >= start_date,
                AnalyticsEvent.event_timestamp < end_date
            )
        )
        stats.total_downloads = downloads_result.scalar()
        
        # Уникальные треки
        unique_tracks_result = await session.execute(
            select(func.count(func.distinct(AnalyticsEvent.entity_id))).where(
                AnalyticsEvent.event_type == EventType.TRACK_PLAY,
                AnalyticsEvent.entity_type == 'track',
                AnalyticsEvent.event_timestamp >= start_date,
                AnalyticsEvent.event_timestamp < end_date,
                AnalyticsEvent.entity_id.isnot(None)
            )
        )
        stats.unique_tracks_played = unique_tracks_result.scalar()
        
        # Плейлисты
        playlists_created_result = await session.execute(
            select(func.count(AnalyticsEvent.id)).where(
                AnalyticsEvent.event_type == EventType.PLAYLIST_CREATE,
                AnalyticsEvent.event_timestamp >= start_date,
                AnalyticsEvent.event_timestamp < end_date
            )
        )
        stats.playlists_created = playlists_created_result.scalar()
        
        tracks_added_result = await session.execute(
            select(func.count(AnalyticsEvent.id)).where(
                AnalyticsEvent.event_type == EventType.PLAYLIST_ADD_TRACK,
                AnalyticsEvent.event_timestamp >= start_date,
                AnalyticsEvent.event_timestamp < end_date
            )
        )
        stats.tracks_added_to_playlists = tracks_added_result.scalar()
        
        # Платежи
        from app.models.subscription import Payment, PaymentStatus
        
        payments_result = await session.execute(
            select(
                func.count(Payment.id),
                func.sum(Payment.amount_usd)
            ).where(
                Payment.status == PaymentStatus.COMPLETED,
                Payment.paid_at >= start_date,
                Payment.paid_at < end_date
            )
        )
        payment_data = payments_result.first()
        stats.payments_completed = payment_data[0] or 0
        stats.revenue_usd = float(payment_data[1] or 0)
        
        # Новые подписки
        from app.models.subscription import Subscription
        
        subscriptions_result = await session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.created_at >= start_date,
                Subscription.created_at < end_date
            )
        )
        stats.new_subscriptions = subscriptions_result.scalar()
        
        # Технические метрики
        api_requests_result = await session.execute(
            select(func.count(AnalyticsEvent.id)).where(
                AnalyticsEvent.event_type == EventType.API_REQUEST,
                AnalyticsEvent.event_timestamp >= start_date,
                AnalyticsEvent.event_timestamp < end_date
            )
        )
        stats.api_requests = api_requests_result.scalar()
        
        errors_result = await session.execute(
            select(func.count(AnalyticsEvent.id)).where(
                AnalyticsEvent.event_type == EventType.ERROR_OCCURRED,
                AnalyticsEvent.event_timestamp >= start_date,
                AnalyticsEvent.event_timestamp < end_date
            )
        )
        stats.errors_count = errors_result.scalar()
        
        # Среднее время ответа (из properties событий API_REQUEST)
        response_times_result = await session.execute(
            select(
                func.avg(
                    func.cast(
                        AnalyticsEvent.properties['response_time'].astext,
                        Float
                    )
                )
            ).where(
                AnalyticsEvent.event_type == EventType.API_REQUEST,
                AnalyticsEvent.event_timestamp >= start_date,
                AnalyticsEvent.event_timestamp < end_date,
                AnalyticsEvent.properties['response_time'].isnot(None)
            )
        )
        avg_response = response_times_result.scalar()
        stats.avg_response_time_ms = float(avg_response or 0)
        
        await session.flush()
        return stats
    
    @classmethod
    async def get_stats_range(
        cls,
        session: AsyncSession,
        start_date: datetime,
        end_date: datetime
    ) -> List["DailyStats"]:
        """Получение статистики за период"""
        result = await session.execute(
            select(cls).where(
                cls.date >= start_date,
                cls.date <= end_date
            ).order_by(cls.date)
        )
        
        return list(result.scalars().all())


class UserSession(BaseModel):
    """Сессии пользователей для аналитики"""
    
    __tablename__ = "user_sessions"
    
    # Идентификаторы
    session_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        comment="Уникальный ID сессии"
    )
    
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
        comment="ID пользователя"
    )
    
    # Время сессии
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        comment="Время начала сессии"
    )
    
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Время окончания сессии"
    )
    
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        comment="Последняя активность"
    )
    
    # Метрики сессии
    events_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Количество событий в сессии"
    )
    
    duration_seconds: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Длительность сессии в секундах"
    )
    
    # Технические данные
    user_agent: Mapped[Optional[UserAgent]] = mapped_column(
        SQLEnum(UserAgent),
        nullable=True,
        comment="Клиент пользователя"
    )
    
    ip_address: Mapped[Optional[str]] = mapped_column(
        INET,
        nullable=True,
        comment="IP адрес"
    )
    
    country_code: Mapped[Optional[str]] = mapped_column(
        String(3),
        nullable=True,
        comment="Код страны"
    )
    
    # Действия в сессии
    tracks_played: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Треков воспроизведено"
    )
    
    tracks_downloaded: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Треков скачано"
    )
    
    searches_performed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Поисков выполнено"
    )
    
    # Индексы
    __table_args__ = (
        Index("idx_session_user_time", "user_id", "started_at"),
        Index("idx_session_duration", "duration_seconds"),
        Index("idx_session_activity", "last_activity_at"),
    )
    
    def __repr__(self) -> str:
        return f"<UserSession(session_id='{self.session_id}', user_id={self.user_id})>"
    
    @property
    def is_active(self) -> bool:
        """Проверка активности сессии (последняя активность менее 30 минут назад)"""
        if self.ended_at:
            return False
        
        threshold = datetime.now(timezone.utc) - timedelta(minutes=30)
        return self.last_activity_at > threshold
    
    async def update_activity(self, session: AsyncSession) -> None:
        """Обновление времени последней активности"""
        self.last_activity_at = datetime.now(timezone.utc)
        await session.flush()
    
    async def increment_event_counter(
        self,
        session: AsyncSession,
        event_type: EventType
    ) -> None:
        """Увеличение счетчиков событий"""
        self.events_count += 1
        
        if event_type == EventType.TRACK_PLAY:
            self.tracks_played += 1
        elif event_type == EventType.TRACK_DOWNLOAD:
            self.tracks_downloaded += 1
        elif event_type == EventType.TRACK_SEARCH:
            self.searches_performed += 1
        
        await self.update_activity(session)
    
    async def end_session(self, session: AsyncSession) -> None:
        """Завершение сессии"""
        now = datetime.now(timezone.utc)
        self.ended_at = now
        
        # Рассчитываем длительность
        delta = now - self.started_at
        self.duration_seconds = int(delta.total_seconds())
        
        await session.flush()
    
    @classmethod
    async def create_session(
        cls,
        session: AsyncSession,
        session_id: str,
        user_id: Optional[int] = None,
        user_agent: Optional[UserAgent] = None,
        ip_address: Optional[str] = None,
        country_code: Optional[str] = None
    ) -> "UserSession":
        """Создание новой сессии"""
        user_session = cls(
            session_id=session_id,
            user_id=user_id,
            user_agent=user_agent,
            ip_address=ip_address,
            country_code=country_code
        )
        
        session.add(user_session)
        await session.flush()
        
        return user_session
    
    @classmethod
    async def get_active_sessions_count(
        cls,
        session: AsyncSession
    ) -> int:
        """Получение количества активных сессий"""
        threshold = datetime.now(timezone.utc) - timedelta(minutes=30)
        
        result = await session.execute(
            select(func.count(cls.id)).where(
                cls.ended_at.is_(None),
                cls.last_activity_at > threshold
            )
        )
        
        return result.scalar()
    
    @classmethod
    async def cleanup_old_sessions(
        cls,
        session: AsyncSession,
        hours: int = 24
    ) -> int:
        """Очистка старых неактивных сессий"""
        threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Завершаем старые активные сессии
        old_sessions_result = await session.execute(
            select(cls).where(
                cls.ended_at.is_(None),
                cls.last_activity_at <= threshold
            )
        )
        
        count = 0
        for old_session in old_sessions_result.scalars().all():
            await old_session.end_session(session)
            count += 1
        
        await session.commit()
        return count


class PerformanceMetric(BaseModel):
    """Метрики производительности системы"""
    
    __tablename__ = "performance_metrics"
    
    # Тип метрики
    metric_name: Mapped[str] = mapped_column(
        String(100),
        index=True,
        comment="Название метрики"
    )
    
    # Значение
    value: Mapped[float] = mapped_column(
        Float,
        comment="Значение метрики"
    )
    
    # Единица измерения
    unit: Mapped[str] = mapped_column(
        String(20),
        comment="Единица измерения (ms, bytes, count, etc.)"
    )
    
    # Контекст
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Дополнительный контекст метрики"
    )
    
    # Время измерения
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="Время измерения"
    )
    
    # Индексы
    __table_args__ = (
        Index("idx_performance_name_time", "metric_name", "measured_at"),
    )
    
    @classmethod
    async def record_metric(
        cls,
        session: AsyncSession,
        name: str,
        value: float,
        unit: str = "count",
        context: Optional[Dict[str, Any]] = None
    ) -> "PerformanceMetric":
        """Запись метрики производительности"""
        metric = cls(
            metric_name=name,
            value=value,
            unit=unit,
            context=context or {}
        )
        
        session.add(metric)
        # Батчим записи для производительности
        
        return metric
    
    @classmethod
    async def get_avg_metric(
        cls,
        session: AsyncSession,
        name: str,
        hours: int = 1
    ) -> Optional[float]:
        """Получение среднего значения метрики за период"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        result = await session.execute(
            select(func.avg(cls.value)).where(
                cls.metric_name == name,
                cls.measured_at >= since
            )
        )
        
        return result.scalar()