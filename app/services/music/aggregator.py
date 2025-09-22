"""
Агрегатор всех музыкальных сервисов
"""
import asyncio
import time
from typing import List, Optional, Dict, Any, Tuple, Set
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum

from app.services.music.base import (
    BaseMusicService, SearchResult, DownloadResult,
    ServiceError, TrackNotFoundError
)
from app.services.music.vk_audio import VKAudioService
from app.services.music.youtube import YouTubeMusicService
from app.services.music.spotify import SpotifyService
from app.models.track import TrackSource, AudioQuality
from app.core.config import settings
from app.core.logging import get_logger


class SearchStrategy(str, Enum):
    """Стратегии поиска"""
    FASTEST = "fastest"          # Первый ответивший сервис
    COMPREHENSIVE = "comprehensive"  # Все сервисы параллельно
    SEQUENTIAL = "sequential"    # По очереди до получения результатов
    QUALITY_FIRST = "quality_first"  # Приоритет качественным источникам


@dataclass
class ServiceConfig:
    """Конфигурация сервиса"""
    enabled: bool = True
    priority: int = 1  # 1 = высший приоритет
    timeout: float = 30.0
    max_results: int = 50
    quality_weight: float = 1.0
    reliability_weight: float = 1.0


class MusicAggregator:
    """Агрегатор музыкальных сервисов"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        
        # Инициализация сервисов
        self.services: Dict[TrackSource, BaseMusicService] = {}
        self.service_configs: Dict[TrackSource, ServiceConfig] = {}
        
        # Статистика сервисов
        self.service_stats: Dict[TrackSource, Dict[str, Any]] = {}
        
        # Настройки по умолчанию
        self.default_strategy = SearchStrategy.COMPREHENSIVE
        self.default_timeout = 30.0
        self.max_concurrent_services = 3
        
        self._initialize_services()
    
    def _initialize_services(self):
        """Инициализация всех доступных сервисов"""
        
        # VK Audio
        try:
            self.services[TrackSource.VK_AUDIO] = VKAudioService()
            self.service_configs[TrackSource.VK_AUDIO] = ServiceConfig(
                enabled=True,
                priority=1,  # Высший приоритет - есть скачивание
                timeout=30.0,
                max_results=50,
                quality_weight=0.8,
                reliability_weight=0.7
            )
            self.logger.info("VK Audio service initialized")
        except Exception as e:
            self.logger.warning(f"Failed to initialize VK Audio service: {e}")
        
        # YouTube Music
        try:
            self.services[TrackSource.YOUTUBE] = YouTubeMusicService()
            self.service_configs[TrackSource.YOUTUBE] = ServiceConfig(
                enabled=True,
                priority=2,
                timeout=60.0,  # YouTube может быть медленнее
                max_results=50,
                quality_weight=0.9,
                reliability_weight=0.9
            )
            self.logger.info("YouTube Music service initialized")
        except Exception as e:
            self.logger.warning(f"Failed to initialize YouTube service: {e}")
        
        # Spotify (только метаданные)
        try:
            self.services[TrackSource.SPOTIFY] = SpotifyService()
            self.service_configs[TrackSource.SPOTIFY] = ServiceConfig(
                enabled=True,
                priority=3,  # Только метаданные
                timeout=20.0,
                max_results=50,
                quality_weight=1.0,  # Лучшие метаданные
                reliability_weight=0.95
            )
            self.logger.info("Spotify service initialized")
        except Exception as e:
            self.logger.warning(f"Failed to initialize Spotify service: {e}")
        
        # Инициализируем статистику
        for source in self.services.keys():
            self.service_stats[source] = {
                'total_searches': 0,
                'successful_searches': 0,
                'total_downloads': 0,
                'successful_downloads': 0,
                'avg_response_time': 0.0,
                'last_error': None,
                'last_success': None,
                'health_score': 1.0
            }
    
    async def __aenter__(self):
        """Async context manager entry"""
        for service in self.services.values():
            await service.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        for service in self.services.values():
            await service.__aexit__(exc_type, exc_val, exc_tb)
    
    async def search(
        self,
        query: str,
        limit: int = 50,
        strategy: SearchStrategy = None,
        sources: Optional[List[TrackSource]] = None,
        timeout: Optional[float] = None,
        merge_results: bool = True
    ) -> List[SearchResult]:
        """Основной метод поиска"""
        
        strategy = strategy or self.default_strategy
        timeout = timeout or self.default_timeout
        
        if not query.strip():
            return []
        
        # Определяем активные сервисы
        active_services = self._get_active_services(sources)
        if not active_services:
            self.logger.warning("No active services available")
            return []
        
        self.logger.info(
            f"Starting search: '{query}' (strategy: {strategy}, "
            f"services: {[s.value for s in active_services]}, limit: {limit})"
        )
        
        start_time = time.time()
        
        try:
            # Выполняем поиск согласно стратегии
            if strategy == SearchStrategy.FASTEST:
                results = await self._search_fastest(query, limit, active_services, timeout)
            elif strategy == SearchStrategy.COMPREHENSIVE:
                results = await self._search_comprehensive(query, limit, active_services, timeout)
            elif strategy == SearchStrategy.SEQUENTIAL:
                results = await self._search_sequential(query, limit, active_services, timeout)
            elif strategy == SearchStrategy.QUALITY_FIRST:
                results = await self._search_quality_first(query, limit, active_services, timeout)
            else:
                results = await self._search_comprehensive(query, limit, active_services, timeout)
            
            # Объединяем и обрабатываем результаты
            if merge_results:
                results = await self._merge_and_deduplicate(results)
            
            # Сортируем по релевантности и качеству
            results = self._sort_results(results, query)
            
            search_time = time.time() - start_time
            
            self.logger.info(
                f"Search completed: {len(results)} results in {search_time:.2f}s"
            )
            
            return results[:limit]
            
        except Exception as e:
            self.logger.error(f"Search failed: {e}")
            return []
    
    def _get_active_services(self, sources: Optional[List[TrackSource]] = None) -> List[TrackSource]:
        """Получение списка активных сервисов"""
        active = []
        
        for source, service in self.services.items():
            config = self.service_configs.get(source)
            
            if not config or not config.enabled:
                continue
            
            if sources and source not in sources:
                continue
            
            # Проверяем health score
            stats = self.service_stats.get(source, {})
            if stats.get('health_score', 0) < 0.3:
                self.logger.warning(f"Service {source.value} has low health score")
                continue
            
            active.append(source)
        
        # Сортируем по приоритету
        active.sort(key=lambda s: self.service_configs[s].priority)
        
        return active
    
    async def _search_fastest(
        self,
        query: str,
        limit: int,
        services: List[TrackSource],
        timeout: float
    ) -> List[SearchResult]:
        """Стратегия: первый ответивший"""
        
        tasks = []
        for source in services:
            service = self.services[source]
            config = self.service_configs[source]
            
            task = asyncio.create_task(
                self._search_service_with_timeout(
                    service, source, query, min(limit, config.max_results), config.timeout
                )
            )
            tasks.append(task)
        
        try:
            # Ждем первый завершившийся
            done, pending = await asyncio.wait(
                tasks, 
                timeout=timeout, 
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Отменяем оставшиеся задачи
            for task in pending:
                task.cancel()
            
            # Возвращаем результаты первого завершившегося
            for task in done:
                results = await task
                if results:
                    return results
            
            return []
            
        except Exception as e:
            self.logger.error(f"Fastest search failed: {e}")
            return []
    
    async def _search_comprehensive(
        self,
        query: str,
        limit: int,
        services: List[TrackSource],
        timeout: float
    ) -> List[SearchResult]:
        """Стратегия: все сервисы параллельно"""
        
        tasks = []
        for source in services[:self.max_concurrent_services]:
            service = self.services[source]
            config = self.service_configs[source]
            
            task = asyncio.create_task(
                self._search_service_with_timeout(
                    service, source, query, min(limit, config.max_results), config.timeout
                )
            )
            tasks.append(task)
        
        try:
            # Ждем все задачи
            results_lists = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout
            )
            
            # Объединяем результаты
            all_results = []
            for results in results_lists:
                if isinstance(results, list):
                    all_results.extend(results)
                elif isinstance(results, Exception):
                    self.logger.warning(f"Service search failed: {results}")
            
            return all_results
            
        except asyncio.TimeoutError:
            self.logger.warning(f"Comprehensive search timeout after {timeout}s")
            # Собираем результаты от завершившихся задач
            all_results = []
            for task in tasks:
                if task.done() and not task.cancelled():
                    try:
                        results = await task
                        if isinstance(results, list):
                            all_results.extend(results)
                    except:
                        pass
            return all_results
        
        except Exception as e:
            self.logger.error(f"Comprehensive search failed: {e}")
            return []
    
    async def _search_sequential(
        self,
        query: str,
        limit: int,
        services: List[TrackSource],
        timeout: float
    ) -> List[SearchResult]:
        """Стратегия: по очереди до получения результатов"""
        
        start_time = time.time()
        
        for source in services:
            if time.time() - start_time > timeout:
                break
            
            service = self.services[source]
            config = self.service_configs[source]
            
            try:
                results = await self._search_service_with_timeout(
                    service, source, query, min(limit, config.max_results), config.timeout
                )
                
                if results:
                    self.logger.info(f"Sequential search got results from {source.value}")
                    return results
                    
            except Exception as e:
                self.logger.warning(f"Sequential search failed for {source.value}: {e}")
                continue
        
        return []
    
    async def _search_quality_first(
        self,
        query: str,
        limit: int