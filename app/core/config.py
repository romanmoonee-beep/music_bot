"""
Конфигурация приложения с использованием Pydantic Settings
"""
from functools import lru_cache
from pathlib import Path
from typing import Optional, List

from pydantic import BaseSettings, PostgresDsn, RedisDsn, validator


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Основные настройки
    PROJECT_NAME: str = "Music Bot"
    VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development, staging, production
    
    # Telegram Bot
    BOT_TOKEN: str
    BOT_USERNAME: str = "musicbot"
    WEBHOOK_URL: Optional[str] = None
    WEBHOOK_PATH: str = "/webhook"
    
    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str = "music_bot"
    DATABASE_URL: Optional[PostgresDsn] = None
    
    @validator("DATABASE_URL", pre=True)
    def assemble_db_connection(cls, v: Optional[str], values: dict) -> str:
        if isinstance(v, str):
            return v
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            user=values.get("POSTGRES_USER"),
            password=values.get("POSTGRES_PASSWORD"),
            host=values.get("POSTGRES_SERVER"),
            port=str(values.get("POSTGRES_PORT")),
            path=f"/{values.get('POSTGRES_DB') or ''}",
        )
    
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_URL: Optional[RedisDsn] = None
    
    @validator("REDIS_URL", pre=True)
    def assemble_redis_connection(cls, v: Optional[str], values: dict) -> str:
        if isinstance(v, str):
            return v
        password = values.get("REDIS_PASSWORD")
        if password:
            return f"redis://:{password}@{values.get('REDIS_HOST')}:{values.get('REDIS_PORT')}/{values.get('REDIS_DB')}"
        return f"redis://{values.get('REDIS_HOST')}:{values.get('REDIS_PORT')}/{values.get('REDIS_DB')}"
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    
    # ClickHouse (для аналитики)
    CLICKHOUSE_HOST: str = "localhost"
    CLICKHOUSE_PORT: int = 9000
    CLICKHOUSE_USER: str = "default"
    CLICKHOUSE_PASSWORD: str = ""
    CLICKHOUSE_DB: str = "music_analytics"
    
    # MeiliSearch
    MEILISEARCH_URL: str = "http://localhost:7700"
    MEILISEARCH_API_KEY: Optional[str] = None
    
    # Security
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 дней
    ADMIN_API_KEY: str
    
    # Music Services
    VK_API_TOKEN: Optional[str] = None
    SPOTIFY_CLIENT_ID: Optional[str] = None
    SPOTIFY_CLIENT_SECRET: Optional[str] = None
    YOUTUBE_API_KEY: Optional[str] = None
    
    # Payments
    CRYPTOBOT_API_TOKEN: Optional[str] = None
    TELEGRAM_STARS_ENABLED: bool = True
    
    # File Storage (MinIO/S3)
    S3_ENDPOINT: str = "localhost:9000"
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET_NAME: str = "music-files"
    S3_USE_SSL: bool = False
    
    # Rate Limiting
    RATE_LIMIT_FREE_USERS: int = 30  # треков в день
    RATE_LIMIT_PREMIUM_USERS: int = 10000  # треков в день
    SEARCH_RATE_LIMIT: int = 20  # поисков в минуту
    
    # Premium Settings
    PREMIUM_PRICE_1M: int = 150  # Stars за 1 месяц
    PREMIUM_PRICE_3M: int = 400  # Stars за 3 месяца
    PREMIUM_PRICE_1Y: int = 1400  # Stars за 1 год
    
    # Audio Quality
    DEFAULT_AUDIO_QUALITY: str = "192kbps"
    PREMIUM_AUDIO_QUALITY: str = "320kbps"
    
    # Cache Settings
    CACHE_TTL_TRACKS: int = 3600  # 1 час
    CACHE_TTL_SEARCH: int = 1800  # 30 минут
    CACHE_TTL_USER_DATA: int = 300  # 5 минут
    
    # Monitoring
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 8000
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json или text
    
    # Admin Panel
    ADMIN_PANEL_URL: str = "http://localhost:3000"
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]
    
    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    TEMP_DIR: Path = BASE_DIR / "temp"
    LOGS_DIR: Path = BASE_DIR / "logs"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Получить настройки приложения (с кешированием)"""
    return Settings()


# Экспортируем настройки
settings = get_settings()