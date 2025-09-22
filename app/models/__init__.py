"""
Инициализация всех моделей базы данных
"""

# Импортируем базовый класс первым
from app.models.base import BaseModel

# Основные модели
from app.models.user import (
    User,
    UserStatus,
    SubscriptionType
)

from app.models.track import (
    Track,
    TrackSource,
    TrackStatus,
    AudioQuality,
    TrackPlayHistory,
    TrackDownloadHistory
)

from app.models.playlist import (
    Playlist,
    PlaylistTrack,
    PlaylistShare,
    PlaylistType,
    PlaylistPrivacy
)

from app.models.search import (
    SearchHistory,
    SearchResult,
    SearchSuggestion,
    PopularQuery,
    SearchType,
    SearchStatus
)

from app.models.subscription import (
    Subscription,
    Payment,
    PromoCode,
    PromoCodeUsage,
    Revenue,
    PaymentMethod,
    PaymentStatus,
    SubscriptionStatus
)

from app.models.analytics import (
    AnalyticsEvent,
    DailyStats,
    UserSession,
    PerformanceMetric,
    EventType,
    UserAgent
)

# Список всех моделей для удобства
__all__ = [
    # Базовые классы
    "BaseModel",
    
    # Пользователи
    "User",
    "UserStatus", 
    "SubscriptionType",
    
    # Треки
    "Track",
    "TrackPlayHistory",
    "TrackDownloadHistory",
    "TrackSource",
    "TrackStatus", 
    "AudioQuality",
    
    # Плейлисты
    "Playlist",
    "PlaylistTrack",
    "PlaylistShare",
    "PlaylistType",
    "PlaylistPrivacy",
    
    # Поиск
    "SearchHistory",
    "SearchResult", 
    "SearchSuggestion",
    "PopularQuery",
    "SearchType",
    "SearchStatus",
    
    # Подписки и платежи
    "Subscription",
    "Payment",
    "PromoCode",
    "PromoCodeUsage", 
    "Revenue",
    "PaymentMethod",
    "PaymentStatus",
    "SubscriptionStatus",
    
    # Аналитика
    "AnalyticsEvent",
    "DailyStats",
    "UserSession",
    "PerformanceMetric",
    "EventType",
    "UserAgent",
]

# Функция для получения всех таблиц
def get_all_tables():
    """Возвращает все таблицы для создания/удаления"""
    return BaseModel.metadata.tables

# Функция для получения всех моделей
def get_all_models():
    """Возвращает все классы моделей"""
    return [
        User,
        Track,
        TrackPlayHistory,
        TrackDownloadHistory,
        Playlist,
        PlaylistTrack,
        PlaylistShare,
        SearchHistory,
        SearchResult,
        SearchSuggestion,
        PopularQuery,
        Subscription,
        Payment,
        PromoCode,
        PromoCodeUsage,
        Revenue,
        AnalyticsEvent,
        DailyStats,
        UserSession,
        PerformanceMetric,
    ]