"""
Инициализация всех сервисов приложения
"""
import asyncio
from typing import Dict, Any
from contextlib import asynccontextmanager

from app.core.logging import get_logger
from app.core.config import settings

# Импортируем все сервисы
from app.services.user_service import user_service
from app.services.playlist_service import playlist_service
from app.services.search_service import search_service
from app.services.payment_service import payment_service
from app.services.analytics_service import analytics_service
from app.services.cache_service import (
    cache_service, 
    track_cache, 
    user_cache, 
    system_cache
)

# Музыкальные сервисы
from app.services.music.vk_audio import VKAudioService
from app.services.music.youtube import YouTubeMusicService
from app.services.music.spotify import SpotifyService
from app.services.music.aggregator import MusicAggregator

logger = get_logger(__name__)


class ServiceManager:
    """Менеджер для управления всеми сервисами"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.initialized = False
        self.services = {}
        
    async def initialize_all(self):
        """Инициализация всех сервисов"""
        if self.initialized:
            return
        
        self.logger.info("Initializing all services...")
        
        try:
            # 1. Инициализируем кеш (Redis)
            await self._init_cache_services()
            
            # 2. Инициализируем музыкальные сервисы
            await self._init_music_services()
            
            # 3. Инициализируем основные сервисы приложения
            await self._init_app_services()
            
            self.initialized = True
            self.logger.info("All services initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize services: {e}")
            raise
    
    async def shutdown_all(self):
        """Закрытие всех сервисов"""
        if not self.initialized:
            return
        
        self.logger.info("Shutting down all services...")
        
        try:
            # Закрываем музыкальные сервисы
            for service_name, service in self.services.items():
                if hasattr(service, 'close_session'):
                    try:
                        await service.close_session()
                        self.logger.info(f"Closed {service_name}")
                    except Exception as e:
                        self.logger.error(f"Error closing {service_name}: {e}")
            
            # Закрываем кеш
            await cache_service.close_redis()
            await track_cache.close_redis()
            await user_cache.close_redis()
            await system_cache.close_redis()
            
            self.initialized = False
            self.logger.info("All services shut down")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
    
    async def _init_cache_services(self):
        """Инициализация сервисов кеширования"""
        self.logger.info("Initializing cache services...")
        
        try:
            # Инициализируем Redis подключения
            await cache_service.init_redis()
            await track_cache.init_redis()
            await user_cache.init_redis()
            await system_cache.init_redis()
            
            self.services['cache'] = cache_service
            self.services['track_cache'] = track_cache
            self.services['user_cache'] = user_cache
            self.services['system_cache'] = system_cache
            
            self.logger.info("Cache services initialized")
            
        except Exception as e:
            self.logger.warning(f"Cache initialization failed: {e}")
            # Кеш не критичен, продолжаем без него
    
    async def _init_music_services(self):
        """Инициализация музыкальных сервисов"""
        self.logger.info("Initializing music services...")
        
        try:
            # VK Audio
            vk_service = VKAudioService()
            await vk_service.__aenter__()
            self.services['vk_audio'] = vk_service
            
            # YouTube Music
            youtube_service = YouTubeMusicService()
            await youtube_service.__aenter__()
            self.services['youtube'] = youtube_service
            
            # Spotify
            spotify_service = SpotifyService()
            await spotify_service.__aenter__()
            self.services['spotify'] = spotify_service
            
            # Агрегатор
            aggregator = MusicAggregator()
            await aggregator.__aenter__()
            self.services['aggregator'] = aggregator
            
            self.logger.info("Music services initialized")
            
        except Exception as e:
            self.logger.error(f"Music services initialization failed: {e}")
            # Музыкальные сервисы критичны
            raise
    
    async def _init_app_services(self):
        """Инициализация основных сервисов приложения"""
        self.logger.info("Initializing application services...")
        
        try:
            # Сервисы уже созданы как глобальные экземпляры
            self.services['user_service'] = user_service
            self.services['playlist_service'] = playlist_service
            self.services['search_service'] = search_service
            self.services['payment_service'] = payment_service
            self.services['analytics_service'] = analytics_service
            
            # Инициализируем поисковый сервис
            if hasattr(search_service, 'init'):
                await search_service.init()
            
            self.logger.info("Application services initialized")
            
        except Exception as e:
            self.logger.error(f"App services initialization failed: {e}")
            raise
    
    async def health_check_all(self) -> Dict[str, Any]:
        """Проверка здоровья всех сервисов"""
        health_status = {
            "overall_status": "healthy",
            "services": {},
            "timestamp": "datetime.now().isoformat()"
        }
        
        unhealthy_count = 0
        
        # Проверяем каждый сервис
        for service_name, service in self.services.items():
            try:
                if hasattr(service, 'health_check'):
                    service_health = await service.health_check()
                else:
                    service_health = {"status": "unknown", "message": "No health check available"}
                
                health_status["services"][service_name] = service_health
                
                if service_health.get("status") != "healthy":
                    unhealthy_count += 1
                    
            except Exception as e:
                health_status["services"][service_name] = {
                    "status": "error",
                    "error": str(e)
                }
                unhealthy_count += 1
        
        # Определяем общий статус
        total_services = len(self.services)
        if unhealthy_count == 0:
            health_status["overall_status"] = "healthy"
        elif unhealthy_count < total_services / 2:
            health_status["overall_status"] = "degraded"
        else:
            health_status["overall_status"] = "unhealthy"
        
        health_status["services_total"] = total_services
        health_status["services_healthy"] = total_services - unhealthy_count
        health_status["services_unhealthy"] = unhealthy_count
        
        return health_status
    
    def get_service(self, service_name: str):
        """Получить сервис по имени"""
        return self.services.get(service_name)
    
    def is_initialized(self) -> bool:
        """Проверить, инициализированы ли сервисы"""
        return self.initialized


# Глобальный менеджер сервисов
service_manager = ServiceManager()


@asynccontextmanager
async def service_lifespan():
    """Контекстный менеджер для жизненного цикла сервисов"""
    try:
        await service_manager.initialize_all()
        yield service_manager
    finally:
        await service_manager.shutdown_all()


# Функции для быстрого доступа к сервисам
def get_user_service():
    """Получить сервис пользователей"""
    return service_manager.get_service('user_service') or user_service


def get_playlist_service():
    """Получить сервис плейлистов"""
    return service_manager.get_service('playlist_service') or playlist_service


def get_search_service():
    """Получить сервис поиска"""
    return service_manager.get_service('search_service') or search_service


def get_cache_service():
    """Получить сервис кеширования"""
    return service_manager.get_service('cache') or cache_service


def get_payment_service():
    """Получить сервис платежей"""
    return service_manager.get_service('payment_service') or payment_service


def get_analytics_service():
    """Получить сервис аналитики"""
    return service_manager.get_service('analytics_service') or analytics_service


def get_music_aggregator():
    """Получить агрегатор музыкальных сервисов"""
    return service_manager.get_service('aggregator')


async def wait_for_services(timeout: int = 30):
    """Ожидание инициализации сервисов"""
    import time
    start_time = time.time()
    
    while not service_manager.is_initialized():
        if time.time() - start_time > timeout:
            raise TimeoutError("Services initialization timeout")
        
        await asyncio.sleep(0.1)


# Инициализация при импорте модуля
async def init_services():
    """Функция для инициализации сервисов из других модулей"""
    if not service_manager.is_initialized():
        await service_manager.initialize_all()


# Экспорт основных сервисов для удобства
__all__ = [
    'service_manager',
    'service_lifespan',
    'get_user_service',
    'get_playlist_service', 
    'get_search_service',
    'get_payment_service',
    'get_analytics_service',
    'get_cache_service',
    'get_music_aggregator',
    'wait_for_services',
    'init_services',
    'user_service',
    'playlist_service',
    'search_service',
    'payment_service',
    'analytics_service',
    'cache_service'
]_search_service',
    'get_cache_service',
    'get_music_aggregator',
    'wait_for_services',
    'init_services',
    'user_service',
    'playlist_service',
    'search_service',
    'cache_service'
]