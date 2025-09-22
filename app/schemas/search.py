"""
Pydantic схемы для поиска
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator

from app.models.search import SearchType, SearchStatus
from app.models.track import TrackSource
from app.schemas.track import TrackResponse


class SearchBase(BaseModel):
    """Базовая схема поиска"""
    query: str = Field(..., min_length=1, max_length=500, description="Поисковый запрос")
    search_type: SearchType = Field(SearchType.TEXT, description="Тип поиска")


class SearchRequest(SearchBase):
    """Запрос на поиск"""
    sources: Optional[List[TrackSource]] = Field(None, description="Источники для поиска")
    limit: int = Field(50, ge=1, le=100, description="Количество результатов")
    offset: int = Field(0, ge=0, description="Смещение")
    filters: Optional[Dict[str, Any]] = Field(None, description="Дополнительные фильтры")
    include_similar: bool = Field(False, description="Включать похожие треки")
    quality_preference: Optional[str] = Field(None, description="Предпочитаемое качество")
    
    @validator('query')
    def validate_query(cls, v):
        # Очищаем запрос от лишних символов
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Query cannot be empty")
        return cleaned


class SearchResponse(BaseModel):
    """Ответ поиска"""
    query: str
    results: List[TrackResponse]
    total_found: int
    search_time_ms: int
    sources_used: List[str]
    suggestions: List[str] = Field(default_factory=list)
    corrections: List[str] = Field(default_factory=list)
    filters_applied: Dict[str, Any] = Field(default_factory=dict)
    has_more: bool
    next_offset: Optional[int] = None


class SearchHistoryResponse(BaseModel):
    """История поиска"""
    id: str
    user_id: int
    query: str
    normalized_query: str
    search_type: SearchType
    status: SearchStatus
    results_count: int
    response_time_ms: int
    sources_used: List[str]
    primary_source: Optional[TrackSource]
    selected_track_id: Optional[str]
    selected_position: Optional[int]
    user_language: Optional[str]
    user_country: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class SearchSuggestionResponse(BaseModel):
    """Поисковая подсказка"""
    id: str
    suggestion: str
    usage_count: int
    success_rate: float
    category: Optional[str]
    
    class Config:
        from_attributes = True


class SearchSuggestionsRequest(BaseModel):
    """Запрос подсказок"""
    query: str = Field(..., min_length=1, max_length=100)
    limit: int = Field(10, ge=1, le=50)
    category: Optional[str] = None


class SearchAnalytics(BaseModel):
    """Аналитика поиска"""
    period: str
    total_searches: int
    successful_searches: int
    success_rate: float
    avg_response_time_ms: float
    popular_queries: List[Dict[str, Any]]
    source_distribution: Dict[str, int]
    error_rate: float
    user_satisfaction: float


class SearchTrends(BaseModel):
    """Тренды поиска"""
    trending_queries: List[Dict[str, Any]]
    rising_queries: List[Dict[str, Any]]
    top_artists: List[str]
    top_genres: List[str]
    seasonal_trends: Dict[str, Any]
    geographic_trends: Dict[str, List[str]]


class SearchOptimization(BaseModel):
    """Оптимизация поиска"""
    query: str
    optimized_query: str
    optimization_type: str = Field(..., description="spelling, synonyms, expansion, filtering")
    confidence: float = Field(..., ge=0, le=1)
    suggestions: List[str] = Field(default_factory=list)


class SearchFilter(BaseModel):
    """Фильтр поиска"""
    field: str = Field(..., description="Поле для фильтрации")
    operator: str = Field(..., description="Оператор: equals, contains, greater_than, less_than, in")
    value: Any = Field(..., description="Значение фильтра")
    weight: float = Field(1.0, ge=0, le=1, description="Вес фильтра")


class AdvancedSearchRequest(BaseModel):
    """Расширенный поиск"""
    query: Optional[str] = None
    filters: List[SearchFilter] = Field(default_factory=list)
    sort_by: str = Field("relevance", description="Сортировка: relevance, popularity, date, duration")
    sort_order: str = Field("desc", description="Порядок: asc, desc")
    sources: Optional[List[TrackSource]] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    duration_from: Optional[int] = None
    duration_to: Optional[int] = None
    explicit_content: bool = True
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)


class SearchFacets(BaseModel):
    """Фасеты поиска"""
    genres: Dict[str, int] = Field(default_factory=dict)
    artists: Dict[str, int] = Field(default_factory=dict)
    years: Dict[str, int] = Field(default_factory=dict)
    sources: Dict[str, int] = Field(default_factory=dict)
    durations: Dict[str, int] = Field(default_factory=dict)
    qualities: Dict[str, int] = Field(default_factory=dict)


class SearchWithFacets(SearchResponse):
    """Поиск с фасетами"""
    facets: SearchFacets


class SearchAutoComplete(BaseModel):
    """Автодополнение поиска"""
    query: str = Field(..., min_length=1, max_length=50)
    limit: int = Field(10, ge=1, le=20)
    include_artists: bool = True
    include_tracks: bool = True
    include_albums: bool = True


class SearchAutoCompleteResponse(BaseModel):
    """Ответ автодополнения"""
    query: str
    suggestions: List[Dict[str, Any]]
    categories: Dict[str, List[str]] = Field(default_factory=dict)


class SearchSpellCheck(BaseModel):
    """Проверка орфографии"""
    query: str
    corrected_query: Optional[str] = None
    confidence: float = Field(0.0, ge=0, le=1)
    suggestions: List[str] = Field(default_factory=list)


class SearchPersonalization(BaseModel):
    """Персонализация поиска"""
    user_id: int
    boost_preferences: Dict[str, float] = Field(default_factory=dict)
    filter_explicit: bool = False
    preferred_sources: List[TrackSource] = Field(default_factory=list)
    blocked_artists: List[str] = Field(default_factory=list)
    language_preference: str = "auto"


class SearchCaching(BaseModel):
    """Кеширование поиска"""
    cache_key: str
    ttl_seconds: int = Field(3600, ge=60, le=86400)
    cache_strategy: str = Field("standard", description="standard, aggressive, minimal")


class SearchMetrics(BaseModel):
    """Метрики поиска"""
    search_id: str
    query: str
    user_id: Optional[int]
    response_time_ms: int
    results_count: int
    sources_queried: List[str]
    cache_hit: bool
    user_clicked: bool
    click_position: Optional[int]
    session_id: Optional[str]


class SearchQuality(BaseModel):
    """Качество поиска"""
    query: str
    precision: float = Field(..., ge=0, le=1)
    recall: float = Field(..., ge=0, le=1)
    f1_score: float = Field(..., ge=0, le=1)
    user_satisfaction: float = Field(..., ge=0, le=5)
    relevance_scores: List[float] = Field(default_factory=list)


class SearchExperiment(BaseModel):
    """A/B тест поиска"""
    experiment_name: str
    variant: str = Field(..., description="control, test_a, test_b")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[int] = None
    session_id: Optional[str] = None


class SearchFeedback(BaseModel):
    """Обратная связь по поиску"""
    search_id: str
    user_id: int
    feedback_type: str = Field(..., description="relevant, irrelevant, spam, missing")
    track_id: Optional[str] = None
    position: Optional[int] = None
    comment: Optional[str] = Field(None, max_length=500)


class SearchReindex(BaseModel):
    """Переиндексация поиска"""
    source: Optional[TrackSource] = None
    full_reindex: bool = False
    batch_size: int = Field(1000, ge=100, le=10000)
    priority: int = Field(1, ge=1, le=10)


class SearchStatus(BaseModel):
    """Статус поисковой системы"""
    is_healthy: bool
    active_sources: List[str]
    index_size: int
    last_update: datetime
    performance_metrics: Dict[str, float]
    error_rate: float


class PopularQuery(BaseModel):
    """Популярный запрос"""
    query: str
    search_count: int
    avg_results: float
    avg_response_time: float
    success_rate: float
    trending_score: float


class SearchInsight(BaseModel):
    """Инсайт поиска"""
    insight_type: str = Field(..., description="trend, pattern, anomaly, opportunity")
    title: str
    description: str
    data: Dict[str, Any]
    confidence: float = Field(..., ge=0, le=1)
    actionable: bool = True
    impact_score: float = Field(..., ge=0, le=10)


class SearchReport(BaseModel):
    """Отчет по поиску"""
    period: str
    total_searches: int
    unique_users: int
    popular_queries: List[PopularQuery]
    performance_metrics: Dict[str, float]
    quality_metrics: Dict[str, float]
    insights: List[SearchInsight]
    recommendations: List[str]
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class VoiceSearchRequest(BaseModel):
    """Голосовой поиск"""
    audio_data: bytes = Field(..., description="Аудио данные")
    audio_format: str = Field("wav", description="Формат аудио")
    language: str = Field("ru", description="Язык распознавания")
    enhance_audio: bool = Field(True, description="Улучшить качество аудио")


class VoiceSearchResponse(SearchResponse):
    """Ответ голосового поиска"""
    transcription: str = Field(..., description="Распознанный текст")
    confidence: float = Field(..., ge=0, le=1, description="Уверенность распознавания")
    processing_time_ms: int = Field(..., description="Время обработки аудио")


class ImageSearchRequest(BaseModel):
    """Поиск по изображению"""
    image_data: bytes = Field(..., description="Данные изображения")
    image_format: str = Field("jpg", description="Формат изображения")
    extract_text: bool = Field(True, description="Извлекать текст с изображения")


class SearchExport(BaseModel):
    """Экспорт результатов поиска"""
    search_id: str
    format: str = Field("json", description="Формат экспорта: json, csv, xlsx")
    include_metadata: bool = True
    include_analytics: bool = False
    max_results: int = Field(1000, ge=1, le=10000)


class SearchBookmark(BaseModel):
    """Закладка поиска"""
    user_id: int
    query: str
    filters: Optional[Dict[str, Any]] = None
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    is_public: bool = False
    tags: List[str] = Field(default_factory=list)


class SearchAlert(BaseModel):
    """Уведомление о поиске"""
    user_id: int
    query: str
    filters: Optional[Dict[str, Any]] = None
    alert_frequency: str = Field("daily", description="Частота: instant, daily, weekly")
    is_active: bool = True
    last_triggered: Optional[datetime] = None
    results_threshold: int = Field(1, ge=1, description="Минимум результатов для срабатывания")