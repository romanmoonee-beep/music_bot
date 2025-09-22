"""
Pydantic схемы для плейлистов
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl, validator

from app.models.playlist import PlaylistType, PlaylistPrivacy
from app.schemas.track import TrackResponse


class PlaylistBase(BaseModel):
    """Базовая схема плейлиста"""
    name: str = Field(..., min_length=1, max_length=255, description="Название плейлиста")
    description: Optional[str] = Field(None, max_length=2000, description="Описание плейлиста")


class PlaylistCreate(PlaylistBase):
    """Схема для создания плейлиста"""
    playlist_type: PlaylistType = Field(PlaylistType.USER_CREATED, description="Тип плейлиста")
    privacy: PlaylistPrivacy = Field(PlaylistPrivacy.PRIVATE, description="Настройки приватности")
    cover_url: Optional[HttpUrl] = Field(None, description="URL обложки")
    initial_tracks: Optional[List[str]] = Field(None, description="Начальные треки (ID)")


class PlaylistUpdate(BaseModel):
    """Схема для обновления плейлиста"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    privacy: Optional[PlaylistPrivacy] = None
    cover_url: Optional[HttpUrl] = None
    is_shuffle: Optional[bool] = None
    is_repeat: Optional[bool] = None


class PlaylistResponse(PlaylistBase):
    """Схема ответа с данными плейлиста"""
    id: str
    user_id: int
    playlist_type: PlaylistType
    privacy: PlaylistPrivacy
    tracks_count: int
    total_duration: int
    duration_formatted: str
    is_shuffle: bool
    is_repeat: bool
    cover_url: Optional[str]
    views_count: int
    downloads_count: int
    likes_count: int
    is_empty: bool
    is_system: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class PlaylistWithTracks(PlaylistResponse):
    """Плейлист с треками"""
    tracks: List["PlaylistTrackResponse"]


class PlaylistTrackResponse(BaseModel):
    """Трек в плейлисте"""
    track: TrackResponse
    position: int
    added_at: datetime
    
    class Config:
        from_attributes = True


class PlaylistTrackAdd(BaseModel):
    """Добавление трека в плейлист"""
    track_id: str = Field(..., description="ID трека")
    position: Optional[int] = Field(None, description="Позиция (по умолчанию в конец)")


class PlaylistTrackMove(BaseModel):
    """Перемещение трека в плейлисте"""
    track_id: str = Field(..., description="ID трека")
    new_position: int = Field(..., ge=1, description="Новая позиция")


class PlaylistBatchUpdate(BaseModel):
    """Пакетное обновление плейлиста"""
    playlist_id: str
    operations: List[Dict[str, Any]] = Field(..., description="Список операций")
    
    @validator('operations')
    def validate_operations(cls, v):
        allowed_ops = ['add_track', 'remove_track', 'move_track', 'reorder']
        for op in v:
            if 'operation' not in op or op['operation'] not in allowed_ops:
                raise ValueError(f'Invalid operation. Allowed: {allowed_ops}')
        return v


class PlaylistShare(BaseModel):
    """Шаринг плейлиста"""
    playlist_id: str
    share_type: str = Field(..., description="public, private, limited_time")
    expires_hours: Optional[int] = Field(None, ge=1, le=8760, description="Время жизни в часах")
    password: Optional[str] = Field(None, min_length=4, description="Пароль для доступа")


class PlaylistShareResponse(BaseModel):
    """Ответ с информацией о шаринге"""
    share_token: str
    share_url: str
    expires_at: Optional[datetime]
    views_count: int
    created_at: datetime


class PlaylistDuplicate(BaseModel):
    """Дублирование плейлиста"""
    new_name: Optional[str] = Field(None, description="Новое название (по умолчанию добавляется 'копия')")
    copy_privacy: bool = Field(True, description="Копировать настройки приватности")
    include_description: bool = Field(True, description="Включить описание")


class PlaylistMerge(BaseModel):
    """Объединение плейлистов"""
    target_playlist_id: str = Field(..., description="Целевой плейлист")
    source_playlist_ids: List[str] = Field(..., min_items=1, description="Исходные плейлисты")
    remove_duplicates: bool = Field(True, description="Удалять дубликаты")
    new_name: Optional[str] = Field(None, description="Новое название объединенного плейлиста")


class PlaylistSearch(BaseModel):
    """Поиск плейлистов"""
    query: Optional[str] = Field(None, description="Поисковый запрос")
    privacy: Optional[PlaylistPrivacy] = Field(None, description="Фильтр по приватности")
    playlist_type: Optional[PlaylistType] = Field(None, description="Фильтр по типу")
    user_id: Optional[int] = Field(None, description="Плейлисты конкретного пользователя")
    min_tracks: Optional[int] = Field(None, ge=0, description="Минимальное количество треков")
    max_tracks: Optional[int] = Field(None, ge=1, description="Максимальное количество треков")
    genre: Optional[str] = Field(None, description="Фильтр по жанру треков")
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)


class PlaylistSearchResult(BaseModel):
    """Результат поиска плейлистов"""
    playlists: List[PlaylistResponse]
    total_count: int
    search_time_ms: int
    filters_applied: Dict[str, Any]


class PlaylistAnalytics(BaseModel):
    """Аналитика плейлиста"""
    playlist_id: str
    name: str
    owner_id: int
    total_plays: int
    unique_listeners: int
    avg_completion_rate: float
    most_played_tracks: List[Dict[str, Any]]
    skip_rates_by_position: Dict[int, float]
    listening_patterns: Dict[str, Any]
    geographic_distribution: Dict[str, int]
    device_distribution: Dict[str, int]
    discovery_sources: Dict[str, int]


class PlaylistStats(BaseModel):
    """Статистика плейлиста"""
    views_count: int
    likes_count: int
    shares_count: int
    downloads_count: int
    followers_count: int
    avg_track_rating: float
    total_listening_time: int
    unique_artists_count: int
    genres_distribution: Dict[str, int]


class PlaylistRecommendation(BaseModel):
    """Рекомендация плейлиста"""
    playlist: PlaylistResponse
    confidence: float = Field(..., ge=0, le=1)
    reason: str
    similarity_score: float = Field(..., ge=0, le=1)
    common_tracks_count: int


class PlaylistCuration(BaseModel):
    """Кураторский плейлист"""
    playlist: PlaylistResponse
    curator_id: int
    curator_name: str
    featured_until: Optional[datetime]
    curation_notes: Optional[str]
    featured_position: int = Field(1, ge=1)
    tags: List[str] = Field(default_factory=list)


class PlaylistGeneration(BaseModel):
    """Автоматическая генерация плейлиста"""
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    seed_tracks: Optional[List[str]] = Field(None, description="Базовые треки для генерации")
    seed_artists: Optional[List[str]] = Field(None, description="Базовые исполнители")
    seed_genres: Optional[List[str]] = Field(None, description="Базовые жанры")
    target_duration_minutes: Optional[int] = Field(None, ge=10, le=600)
    target_track_count: Optional[int] = Field(None, ge=5, le=500)
    mood: Optional[str] = Field(None, description="Настроение: energetic, chill, sad, happy")
    tempo: Optional[str] = Field(None, description="Темп: slow, medium, fast")
    popularity: Optional[str] = Field(None, description="Популярность: mainstream, underground, mixed")
    include_explicit: bool = Field(True, description="Включать контент 18+")
    diversity_factor: float = Field(0.5, ge=0, le=1, description="Фактор разнообразия")


class SmartPlaylistRule(BaseModel):
    """Правило для умного плейлиста"""
    field: str = Field(..., description="Поле для фильтрации: genre, artist, year, rating")
    operator: str = Field(..., description="Оператор: equals, contains, greater_than, less_than")
    value: str = Field(..., description="Значение для сравнения")
    weight: float = Field(1.0, ge=0, le=1, description="Вес правила")


class SmartPlaylistCreate(PlaylistBase):
    """Создание умного плейлиста"""
    rules: List[SmartPlaylistRule] = Field(..., min_items=1, description="Правила фильтрации")
    max_tracks: int = Field(100, ge=1, le=1000, description="Максимальное количество треков")
    auto_update: bool = Field(True, description="Автоматическое обновление")
    update_frequency: str = Field("daily", description="Частота обновления: hourly, daily, weekly")


class PlaylistCollaborator(BaseModel):
    """Участник совместного плейлиста"""
    user_id: int
    role: str = Field(..., description="Роль: editor, viewer, moderator")
    added_at: datetime
    permissions: List[str] = Field(default_factory=list, description="Разрешения")


class PlaylistCollaboration(BaseModel):
    """Настройка совместного плейлиста"""
    playlist_id: str
    enable_collaboration: bool = True
    default_role: str = Field("viewer", description="Роль по умолчанию")
    require_approval: bool = Field(True, description="Требовать одобрение изменений")
    max_collaborators: int = Field(10, ge=1, le=100)


class PlaylistExport(BaseModel):
    """Экспорт плейлиста"""
    playlist_id: str
    format: str = Field("json", description="Формат: json, m3u, csv, spotify")
    include_metadata: bool = Field(True, description="Включать метаданные треков")
    include_analytics: bool = Field(False, description="Включать аналитику")
    quality_preference: Optional[str] = Field(None, description="Предпочитаемое качество")


class PlaylistImport(BaseModel):
    """Импорт плейлиста"""
    name: str = Field(..., max_length=255)
    source: str = Field(..., description="Источник: spotify, apple_music, youtube, file")
    source_url: Optional[HttpUrl] = Field(None, description="URL для импорта")
    file_content: Optional[str] = Field(None, description="Содержимое файла")
    auto_search_missing: bool = Field(True, description="Автопоиск недостающих треков")
    preserve_order: bool = Field(True, description="Сохранить порядок треков")


class PlaylistBackup(BaseModel):
    """Резервная копия плейлиста"""
    playlist_id: str
    backup_name: Optional[str] = None
    include_metadata: bool = True
    compress: bool = True


class PlaylistRestore(BaseModel):
    """Восстановление плейлиста"""
    backup_id: str
    restore_name: Optional[str] = None
    overwrite_existing: bool = False


class PlaylistActivity(BaseModel):
    """Активность в плейлисте"""
    activity_type: str = Field(..., description="Тип: track_added, track_removed, played, shared")
    user_id: int
    track_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime


class PlaylistFeed(BaseModel):
    """Лента активности плейлиста"""
    playlist_id: str
    activities: List[PlaylistActivity]
    last_updated: datetime
    has_more: bool


class PlaylistComment(BaseModel):
    """Комментарий к плейлисту"""
    playlist_id: str
    user_id: int
    comment: str = Field(..., min_length=1, max_length=500)
    parent_comment_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PlaylistRating(BaseModel):
    """Оценка плейлиста"""
    playlist_id: str
    user_id: int
    rating: int = Field(..., ge=1, le=5)
    review: Optional[str] = Field(None, max_length=1000)


class PlaylistSubscription(BaseModel):
    """Подписка на плейлист"""
    playlist_id: str
    user_id: int
    notification_settings: Dict[str, bool] = Field(default_factory=lambda: {
        "new_tracks": True,
        "updates": True,
        "comments": False
    })


class PlaylistTemplate(BaseModel):
    """Шаблон плейлиста"""
    name: str = Field(..., max_length=255)
    description: str = Field(..., max_length=2000)
    category: str = Field(..., description="Категория шаблона")
    rules: List[SmartPlaylistRule]
    default_cover: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    is_public: bool = True


class PlaylistMood(BaseModel):
    """Настроение плейлиста"""
    playlist_id: str
    mood_tags: List[str] = Field(..., description="Теги настроения")
    energy_level: int = Field(..., ge=1, le=10, description="Уровень энергии")
    valence: float = Field(..., ge=0, le=1, description="Позитивность")
    danceability: float = Field(..., ge=0, le=1, description="Танцевальность")
    tempo_category: str = Field(..., description="Категория темпа")


class PlaylistChallenge(BaseModel):
    """Вызов плейлиста"""
    name: str = Field(..., max_length=255)
    description: str = Field(..., max_length=1000)
    rules: Dict[str, Any] = Field(..., description="Правила вызова")
    duration_days: int = Field(..., ge=1, le=365)
    participants_count: int = 0
    is_active: bool = True
    prizes: Optional[List[str]] = None


class PlaylistTrend(BaseModel):
    """Трендовый плейлист"""
    playlist: PlaylistResponse
    trend_score: float = Field(..., ge=0, le=100)
    growth_rate: float
    viral_factor: float
    trend_duration_days: int
    peak_position: int
    current_position: int


class PlaylistMetrics(BaseModel):
    """Метрики плейлистов"""
    total_playlists: int
    public_playlists: int
    private_playlists: int
    avg_tracks_per_playlist: float
    avg_duration_minutes: float
    most_popular_genres: List[Dict[str, Any]]
    collaboration_rate: float
    export_requests: int
    import_success_rate: float


class PlaylistPersonalization(BaseModel):
    """Персонализация плейлиста"""
    user_id: int
    playlist_preferences: Dict[str, Any] = Field(default_factory=dict)
    listening_history_weight: float = Field(0.7, ge=0, le=1)
    social_signals_weight: float = Field(0.2, ge=0, le=1)
    discovery_factor: float = Field(0.1, ge=0, le=1)
    exclude_genres: List[str] = Field(default_factory=list)
    preferred_artists: List[str] = Field(default_factory=list)


class PlaylistOptimization(BaseModel):
    """Оптимизация плейлиста"""
    playlist_id: str
    optimization_type: str = Field(..., description="flow, diversity, engagement, discovery")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    preserve_favorites: bool = True
    max_changes_percent: float = Field(0.3, ge=0, le=1)


class PlaylistInsight(BaseModel):
    """Инсайты плейлиста"""
    playlist_id: str
    insights: List[Dict[str, Any]] = Field(..., description="Список инсайтов")
    recommendations: List[str] = Field(default_factory=list)
    performance_score: float = Field(..., ge=0, le=100)
    engagement_trends: Dict[str, Any] = Field(default_factory=dict)
    audience_analysis: Dict[str, Any] = Field(default_factory=dict)


class PlaylistReport(BaseModel):
    """Отчет по плейлисту"""
    playlist_id: str
    report_period: str = Field(..., description="Период отчета")
    metrics: PlaylistStats
    insights: PlaylistInsight
    recommendations: List[PlaylistRecommendation]
    trends: List[Dict[str, Any]]
    generated_at: datetime = Field(default_factory=datetime.utcnow)