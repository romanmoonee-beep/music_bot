"""
Pydantic схемы для пользователей
"""
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator
from decimal import Decimal

from app.models.user import UserStatus, SubscriptionType


class UserBase(BaseModel):
    """Базовая схема пользователя"""
    telegram_id: int = Field(..., description="ID пользователя в Telegram")
    username: Optional[str] = Field(None, description="Username пользователя")
    first_name: Optional[str] = Field(None, description="Имя пользователя")
    last_name: Optional[str] = Field(None, description="Фамилия пользователя")
    language_code: Optional[str] = Field("ru", description="Код языка")


class UserCreate(UserBase):
    """Схема для создания пользователя"""
    is_bot: bool = Field(False, description="Является ли ботом")
    is_premium_telegram: bool = Field(False, description="Telegram Premium")
    country_code: Optional[str] = Field(None, description="Код страны")
    city: Optional[str] = Field(None, description="Город")
    timezone: Optional[str] = Field(None, description="Часовой пояс")
    referrer_id: Optional[int] = Field(None, description="ID пригласившего")


class UserUpdate(BaseModel):
    """Схема для обновления пользователя"""
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    language_code: Optional[str] = None
    preferred_quality: Optional[str] = None
    auto_add_to_playlist: Optional[bool] = None
    notifications_enabled: Optional[bool] = None
    country_code: Optional[str] = None
    city: Optional[str] = None
    timezone: Optional[str] = None


class UserResponse(UserBase):
    """Схема ответа с данными пользователя"""
    id: str
    status: UserStatus
    subscription_type: SubscriptionType
    subscription_expires_at: Optional[datetime]
    is_premium: bool
    total_searches: int
    daily_searches: int
    daily_downloads: int
    views_count: int
    downloads_count: int
    likes_count: int
    tracks_count: int
    last_activity_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class UserStats(BaseModel):
    """Статистика пользователя"""
    total_searches: int
    total_downloads: int
    total_plays: int
    favorite_tracks_count: int
    playlists_count: int
    days_since_registration: int
    premium_days_left: Optional[int]
    most_played_genre: Optional[str]
    listening_time_hours: float


class UserProfile(BaseModel):
    """Профиль пользователя для отображения"""
    telegram_id: int
    display_name: str
    status: UserStatus
    is_premium: bool
    subscription_expires_at: Optional[datetime]
    registration_date: datetime
    last_activity: Optional[datetime]
    stats: UserStats
    preferences: Dict[str, Any]


class UserSettings(BaseModel):
    """Настройки пользователя"""
    preferred_quality: str = Field("192kbps", description="Качество аудио")
    auto_add_to_playlist: bool = Field(False, description="Автодобавление в плейлист")
    notifications_enabled: bool = Field(True, description="Уведомления")
    language_code: str = Field("ru", description="Язык интерфейса")
    
    @validator('preferred_quality')
    def validate_quality(cls, v):
        allowed_qualities = ['128kbps', '192kbps', '256kbps', '320kbps']
        if v not in allowed_qualities:
            raise ValueError(f'Quality must be one of {allowed_qualities}')
        return v


class UserActivityLog(BaseModel):
    """Лог активности пользователя"""
    user_id: int
    action: str
    details: Optional[Dict[str, Any]]
    timestamp: datetime
    ip_address: Optional[str]
    user_agent: Optional[str]


class UserSearchStats(BaseModel):
    """Статистика поисков пользователя"""
    total_searches: int
    successful_searches: int
    success_rate: float
    avg_results_per_search: float
    most_searched_queries: list[str]
    popular_sources: Dict[str, int]
    search_frequency_by_hour: Dict[int, int]


class UserSubscriptionInfo(BaseModel):
    """Информация о подписке пользователя"""
    subscription_type: SubscriptionType
    is_active: bool
    expires_at: Optional[datetime]
    days_left: Optional[int]
    auto_renew: bool
    can_upgrade: bool
    benefits: list[str]


class UserLimits(BaseModel):
    """Лимиты пользователя"""
    daily_searches_limit: int
    daily_downloads_limit: int
    current_searches: int
    current_downloads: int
    can_search: bool
    can_download: bool
    reset_time: datetime


class AdminUserView(BaseModel):
    """Представление пользователя для админки"""
    id: str
    telegram_id: int
    username: Optional[str]
    full_name: str
    status: UserStatus
    subscription_type: SubscriptionType
    subscription_expires_at: Optional[datetime]
    registration_date: datetime
    last_activity: Optional[datetime]
    total_searches: int
    total_downloads: int
    country_code: Optional[str]
    city: Optional[str]
    referrer_id: Optional[int]
    invited_users_count: int
    
    class Config:
        from_attributes = True


class UserBanRequest(BaseModel):
    """Запрос на блокировку пользователя"""
    user_id: int
    reason: str = Field(..., min_length=3, max_length=500)
    ban_duration_days: Optional[int] = Field(None, description="Длительность бана в днях (None = навсегда)")


class UserUnbanRequest(BaseModel):
    """Запрос на разблокировку пользователя"""
    user_id: int
    reason: Optional[str] = Field(None, description="Причина разблокировки")


class UserPremiumGrant(BaseModel):
    """Выдача премиума администратором"""
    user_id: int
    subscription_type: SubscriptionType
    duration_days: int = Field(..., gt=0, description="Длительность в днях")
    reason: Optional[str] = Field(None, description="Причина выдачи")


class UserAnalytics(BaseModel):
    """Аналитика по пользователю"""
    user_id: int
    registration_date: datetime
    total_sessions: int
    avg_session_duration_minutes: float
    total_listening_time_hours: float
    favorite_genres: list[str]
    most_active_hours: list[int]
    device_usage: Dict[str, int]
    geographic_activity: Dict[str, int]
    conversion_events: list[Dict[str, Any]]


class BulkUserAction(BaseModel):
    """Массовое действие с пользователями"""
    user_ids: list[int] = Field(..., min_items=1, max_items=1000)
    action: str = Field(..., description="Тип действия: ban, unban, grant_premium, send_message")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Параметры действия")


class UserExportRequest(BaseModel):
    """Запрос на экспорт данных пользователей"""
    filters: Dict[str, Any] = Field(default_factory=dict)
    format: str = Field("csv", description="Формат экспорта: csv, json, xlsx")
    fields: list[str] = Field(default_factory=list, description="Поля для экспорта")


class UserImportRequest(BaseModel):
    """Запрос на импорт пользователей"""
    format: str = Field("csv", description="Формат импорта")
    data: str = Field(..., description="Данные для импорта")
    update_existing: bool = Field(False, description="Обновлять существующих пользователей")


class UserMetrics(BaseModel):
    """Метрики пользователя для дашборда"""
    total_users: int
    active_users_24h: int
    active_users_7d: int
    active_users_30d: int
    new_users_today: int
    new_users_7d: int
    premium_users: int
    premium_conversion_rate: float
    avg_session_duration: float
    top_countries: list[Dict[str, Any]]
    user_growth_trend: list[Dict[str, Any]]


class UserActivityMetrics(BaseModel):
    """Метрики активности пользователей"""
    hourly_activity: Dict[int, int]
    daily_activity: Dict[str, int]
    weekly_activity: Dict[str, int]
    retention_rates: Dict[str, float]
    churn_rate: float
    engagement_score: float


class UserSegment(BaseModel):
    """Сегмент пользователей"""
    name: str
    description: str
    filters: Dict[str, Any]
    user_count: int
    created_at: datetime
    updated_at: Optional[datetime]


class UserCohort(BaseModel):
    """Когорта пользователей"""
    cohort_month: str
    users_count: int
    retention_data: Dict[str, float]
    revenue_data: Dict[str, float]


class UserFeedback(BaseModel):
    """Обратная связь от пользователя"""
    user_id: int
    feedback_type: str = Field(..., description="Тип: bug, feature_request, complaint, praise")
    message: str = Field(..., min_length=10, max_length=2000)
    rating: Optional[int] = Field(None, ge=1, le=5, description="Оценка от 1 до 5")
    metadata: Optional[Dict[str, Any]] = None


class UserNotification(BaseModel):
    """Уведомление для пользователя"""
    user_id: Optional[int] = None  # None для массовой рассылки
    title: str = Field(..., max_length=100)
    message: str = Field(..., max_length=1000)
    notification_type: str = Field("info", description="info, warning, success, error")
    action_url: Optional[str] = None
    expires_at: Optional[datetime] = None
    is_urgent: bool = False


class UserPreferences(BaseModel):
    """Расширенные предпочтения пользователя"""
    audio_quality: str = "192kbps"
    download_format: str = "mp3"
    auto_add_to_favorites: bool = False
    show_explicit_content: bool = True
    preferred_language: str = "ru"
    notification_settings: Dict[str, bool] = Field(default_factory=lambda: {
        "new_features": True,
        "recommendations": True,
        "playlist_updates": True,
        "premium_offers": True
    })
    privacy_settings: Dict[str, bool] = Field(default_factory=lambda: {
        "show_listening_activity": False,
        "allow_friend_requests": True,
        "show_playlists": True
    })


class UserDevice(BaseModel):
    """Устройство пользователя"""
    device_id: str
    device_type: str = Field(..., description="mobile, desktop, web")
    os: Optional[str] = None
    browser: Optional[str] = None
    app_version: Optional[str] = None
    last_seen: datetime
    is_active: bool


class UserLocation(BaseModel):
    """Местоположение пользователя"""
    country_code: str
    country_name: str
    city: Optional[str] = None
    timezone: Optional[str] = None
    coordinates: Optional[Dict[str, float]] = None
    detected_at: datetime


class UserReferral(BaseModel):
    """Реферальная информация"""
    referrer_id: Optional[int]
    referral_code: str
    invitations_sent: int
    successful_invitations: int
    rewards_earned: int
    referral_link: str


class UserEngagement(BaseModel):
    """Показатели вовлеченности пользователя"""
    engagement_score: float = Field(..., ge=0, le=100)
    last_activity_days_ago: int
    sessions_last_week: int
    avg_session_duration: float
    actions_per_session: float
    feature_adoption_rate: float
    retention_probability: float