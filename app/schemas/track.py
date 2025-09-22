"""
Pydantic схемы для треков
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator, HttpUrl
from decimal import Decimal

from app.models.track import TrackSource, TrackStatus, AudioQuality


class TrackBase(BaseModel):
    """Базовая схема трека"""
    title: str = Field(..., min_length=1, max_length=500, description="Название трека")
    artist: str = Field(..., min_length=1, max_length=500, description="Исполнитель")
    album: Optional[str] = Field(None, max_length=500, description="Альбом")
    genre: Optional[str] = Field(None, max_length=100, description="Жанр")
    year: Optional[int] = Field(None, ge=1900, le=2030, description="Год выпуска")


class TrackCreate(TrackBase):
    """Схема для создания трека"""
    duration: Optional[int] = Field(None, ge=1, description="Длительность в секундах")
    bitrate: Optional[int] = Field(None, ge=32, le=320, description="Битрейт в kbps")
    file_size: Optional[int] = Field(None, ge=1, description="Размер файла в байтах")
    audio_quality: AudioQuality = Field(AudioQuality.MEDIUM, description="Качество аудио")
    source: TrackSource = Field(TrackSource.VK_AUDIO, description="Источник трека")
    external_id: Optional[str] = Field(None, max_length=255, description="Внешний ID")
    external_url: Optional[HttpUrl] = Field(None, description="Внешняя ссылка")
    download_url: Optional[HttpUrl] = Field(None, description="Ссылка на скачивание")
    is_explicit: bool = Field(False, description="Содержит нецензурную лексику")
    search_tags: Optional[List[str]] = Field(None, description="Теги для поиска")


class TrackUpdate(BaseModel):
    """Схема для обновления трека"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    artist: Optional[str] = Field(None, min_length=1, max_length=500)
    album: Optional[str] = Field(None, max_length=500)
    genre: Optional[str] = Field(None, max_length=100)
    year: Optional[int] = Field(None, ge=1900, le=2030)
    audio_quality: Optional[AudioQuality] = None
    status: Optional[TrackStatus] = None
    is_explicit: Optional[bool] = None
    search_tags: Optional[List[str]] = None


class TrackResponse(TrackBase):
    """Схема ответа с данными трека"""
    id: str
    duration: Optional[int]
    duration_formatted: str
    bitrate: Optional[int]
    file_size: Optional[int]
    file_size_formatted: str
    audio_quality: AudioQuality
    source: TrackSource
    status: TrackStatus
    is_explicit: bool
    is_verified: bool
    popularity_score: float
    trending_score: float
    views_count: int
    downloads_count: int
    likes_count: int
    created_at: datetime
    updated_at: Optional[datetime]
    is_available: bool
    
    class Config:
        from_attributes = True


class TrackSearch(BaseModel):
    """Параметры поиска треков"""
    query: str = Field(..., min_length=1, max_length=200, description="Поисковый запрос")
    source: Optional[TrackSource] = Field(None, description="Источник поиска")
    quality: Optional[AudioQuality] = Field(None, description="Минимальное качество")
    genre: Optional[str] = Field(None, description="Фильтр по жанру")
    year_from: Optional[int] = Field(None, ge=1900, description="Год с")
    year_to: Optional[int] = Field(None, le=2030, description="Год по")
    duration_from: Optional[int] = Field(None, ge=1, description="Минимальная длительность")
    duration_to: Optional[int] = Field(None, le=7200, description="Максимальная длительность")
    explicit_content: bool = Field(True, description="Включать контент 18+")
    limit: int = Field(50, ge=1, le=100, description="Количество результатов")
    offset: int = Field(0, ge=0, description="Смещение")


class TrackSearchResult(BaseModel):
    """Результат поиска треков"""
    tracks: List[TrackResponse]
    total_count: int
    search_time_ms: int
    sources_used: List[str]
    suggestions: List[str] = Field(default_factory=list)
    filters_applied: Dict[str, Any] = Field(default_factory=dict)


class TrackMetadata(BaseModel):
    """Метаданные трека"""
    title: str
    artist: str
    album: Optional[str] = None
    album_artist: Optional[str] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    duration: Optional[int] = None
    bitrate: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    lyrics: Optional[str] = None
    cover_art_url: Optional[HttpUrl] = None
    composer: Optional[str] = None
    publisher: Optional[str] = None
    isrc: Optional[str] = None  # International Standard Recording Code


class TrackAnalytics(BaseModel):
    """Аналитика трека"""
    track_id: str
    title: str
    artist: str
    total_plays: int
    total_downloads: int
    unique_listeners: int
    avg_rating: float
    popularity_trend: List[Dict[str, Any]]
    geographic_distribution: Dict[str, int]
    age_distribution: Dict[str, int]
    platform_distribution: Dict[str, int]
    peak_listening_hours: List[int]
    related_tracks: List[str]


class TrackStats(BaseModel):
    """Статистика трека"""
    views_count: int
    downloads_count: int
    likes_count: int
    shares_count: int
    playlist_additions: int
    last_played_at: Optional[datetime]
    popularity_rank: Optional[int]
    trending_rank: Optional[int]


class TrackDownload(BaseModel):
    """Информация о скачивании трека"""
    track_id: str
    download_url: HttpUrl
    expires_at: datetime
    file_size: int
    audio_quality: AudioQuality
    format: str = "mp3"
    metadata: TrackMetadata


class TrackUpload(BaseModel):
    """Схема для загрузки трека"""
    title: str = Field(..., min_length=1, max_length=500)
    artist: str = Field(..., min_length=1, max_length=500)
    file_data: bytes = Field(..., description="Данные аудио файла")
    file_name: str = Field(..., description="Имя файла")
    metadata: Optional[TrackMetadata] = None
    
    @validator('file_name')
    def validate_file_extension(cls, v):
        allowed_extensions = ['.mp3', '.wav', '.flac', '.m4a', '.ogg']
        if not any(v.lower().endswith(ext) for ext in allowed_extensions):
            raise ValueError(f'File must have one of these extensions: {allowed_extensions}')
        return v


class TrackBatch(BaseModel):
    """Пакетная операция с треками"""
    track_ids: List[str] = Field(..., min_items=1, max_items=1000)
    operation: str = Field(..., description="add_to_playlist, remove, update_status")
    parameters: Dict[str, Any] = Field(default_factory=dict)


class TrackRecommendation(BaseModel):
    """Рекомендация трека"""
    track: TrackResponse
    confidence: float = Field(..., ge=0, le=1, description="Уверенность рекомендации")
    reason: str = Field(..., description="Причина рекомендации")
    context: Dict[str, Any] = Field(default_factory=dict)


class TrackSimilarity(BaseModel):
    """Похожие треки"""
    base_track_id: str
    similar_tracks: List[TrackRecommendation]
    similarity_algorithm: str
    calculated_at: datetime


class TrackChart(BaseModel):
    """Трек в чарте"""
    position: int
    track: TrackResponse
    position_change: int = Field(0, description="Изменение позиции (+/-)")
    weeks_in_chart: int = Field(1, description="Недель в чарте")
    peak_position: int = Field(..., description="Лучшая позиция")


class TrackChartResponse(BaseModel):
    """Ответ с чартом треков"""
    chart_name: str
    chart_type: str = Field(..., description="popular, trending, new_releases")
    period: str = Field(..., description="daily, weekly, monthly")
    chart_date: datetime
    tracks: List[TrackChart]
    total_tracks: int


class TrackGenreStats(BaseModel):
    """Статистика по жанрам"""
    genre: str
    tracks_count: int
    total_plays: int
    total_downloads: int
    avg_rating: float
    top_artists: List[str]
    trending_score: float


class TrackSourceStats(BaseModel):
    """Статистика по источникам"""
    source: TrackSource
    tracks_count: int
    success_rate: float
    avg_response_time_ms: int
    quality_distribution: Dict[str, int]
    last_updated: datetime


class TrackModerationRequest(BaseModel):
    """Запрос на модерацию трека"""
    track_id: str
    action: str = Field(..., description="approve, reject, flag")
    reason: Optional[str] = None
    moderator_notes: Optional[str] = None


class TrackReport(BaseModel):
    """Жалоба на трек"""
    track_id: str
    user_id: int
    report_type: str = Field(..., description="copyright, inappropriate, spam, other")
    description: str = Field(..., min_length=10, max_length=1000)
    evidence_urls: Optional[List[HttpUrl]] = None


class TrackLyrics(BaseModel):
    """Текст песни"""
    track_id: str
    lyrics: str = Field(..., max_length=10000)
    language: str = Field("ru", description="Язык текста")
    source: Optional[str] = None
    is_synchronized: bool = Field(False, description="Синхронизированный текст")
    timestamps: Optional[List[Dict[str, Any]]] = None


class TrackPlaylist(BaseModel):
    """Трек в контексте плейлиста"""
    track: TrackResponse
    position: int
    added_at: datetime
    added_by: Optional[int] = None


class TrackExport(BaseModel):
    """Экспорт треков"""
    format: str = Field("json", description="json, csv, m3u")
    track_ids: Optional[List[str]] = None
    filters: Optional[Dict[str, Any]] = None
    include_metadata: bool = True
    include_analytics: bool = False


class TrackImport(BaseModel):
    """Импорт треков"""
    source: str = Field(..., description="spotify, apple_music, youtube_playlist")
    source_url: HttpUrl
    import_metadata: bool = True
    auto_search: bool = True
    quality_preference: AudioQuality = AudioQuality.MEDIUM


class TrackCuration(BaseModel):
    """Кураторский трек"""
    track: TrackResponse
    curator_notes: Optional[str] = None
    featured_until: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    priority: int = Field(1, ge=1, le=10)


class TrackFeedback(BaseModel):
    """Обратная связь по треку"""
    track_id: str
    user_id: int
    rating: int = Field(..., ge=1, le=5)
    review: Optional[str] = Field(None, max_length=500)
    tags: Optional[List[str]] = None


class TrackHistory(BaseModel):
    """История прослушивания трека"""
    track: TrackResponse
    played_at: datetime
    play_duration: Optional[int] = None
    device_type: Optional[str] = None
    context: Optional[str] = None  # playlist, search, recommendation


class TrackRadio(BaseModel):
    """Радио на основе трека"""
    seed_track_id: str
    radio_name: str
    tracks: List[TrackResponse]
    algorithm: str
    diversity_factor: float = Field(0.5, ge=0, le=1)
    generated_at: datetime