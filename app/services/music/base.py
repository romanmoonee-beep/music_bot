"""
Базовый класс для музыкальных сервисов
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone
import time
import asyncio
import aiohttp
from urllib.parse import quote

from app.core.logging import get_logger
from app.models.track import TrackSource, AudioQuality


@dataclass
class SearchResult:
    """Результат поиска трека"""
    title: str
    artist: str
    album: Optional[str] = None
    duration: Optional[int] = None  # в секундах
    external_id: str = ""
    external_url: str = ""
    download_url: Optional[str] = None
    cover_url: Optional[str] = None
    bitrate: Optional[int] = None
    file_size: Optional[int] = None
    source: TrackSource = TrackSource.VK_AUDIO
    audio_quality: AudioQuality = AudioQuality.MEDIUM
    year: Optional[int] = None
    genre: Optional[str] = None
    is_explicit: bool = False
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class DownloadResult:
    """Результат скачивания трека"""
    url: str
    expires_at: Optional[datetime] = None
    file_size: Optional[int] = None
    audio_quality: AudioQuality = AudioQuality.MEDIUM
    format: str = "mp3"
    bitrate: Optional[int] = None
    headers: Optional[Dict[str, str]] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.headers is None:
            self.headers = {}


class RateLimiter:
    """Простой rate limiter для API запросов"""
    
    def __init__(self, max_requests: int, time_window: int):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
    
    async def wait_if_needed(self):
        """Ожидание если достигнут лимит запросов"""
        now = time.time()
        
        # Удаляем старые запросы
        self.requests = [req_time for req_time in self.requests 
                        if now - req_time < self.time_window]
        
        # Проверяем лимит
        if len(self.requests) >= self.max_requests:
            sleep_time = self.time_window - (now - self.requests[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                # Очищаем после ожидания
                self.requests = []
        
        # Добавляем текущий запрос
        self.requests.append(now)


class BaseMusicService(ABC):
    """Базовый класс для музыкальных сервисов"""
    
    def __init__(self, 
                 source: TrackSource,
                 rate_limit_requests: int = 60,
                 rate_limit_window: int = 60,
                 timeout: int = 30,
                 max_retries: int = 3):
        self.source = source
        self.logger = get_logger(f"{self.__class__.__name__}")
        self.rate_limiter = RateLimiter(rate_limit_requests, rate_limit_window)
        self.timeout = timeout
        self.max_retries = max_retries
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.init_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close_session()
    
    async def init_session(self):
        """Инициализация HTTP сессии"""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=100,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=30,
                enable_cleanup_closed=True
            )
            
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=self.get_default_headers()
            )
    
    async def close_session(self):
        """Закрытие HTTP сессии"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    def get_default_headers(self) -> Dict[str, str]:
        """Получение заголовков по умолчанию"""
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    
    async def make_request(self, 
                          method: str, 
                          url: str, 
                          params: Optional[Dict] = None,
                          data: Optional[Dict] = None,
                          headers: Optional[Dict] = None,
                          retries: Optional[int] = None) -> aiohttp.ClientResponse:
        """Выполнение HTTP запроса с повторами и rate limiting"""
        await self.init_session()
        await self.rate_limiter.wait_if_needed()
        
        if retries is None:
            retries = self.max_retries
        
        request_headers = self.get_default_headers()
        if headers:
            request_headers.update(headers)
        
        for attempt in range(retries + 1):
            try:
                start_time = time.time()
                
                async with self._session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    headers=request_headers
                ) as response:
                    response_time = (time.time() - start_time) * 1000
                    
                    self.logger.debug(
                        f"Request completed",
                        method=method,
                        url=url,
                        status=response.status,
                        response_time_ms=round(response_time, 2),
                        attempt=attempt + 1
                    )
                    
                    if response.status == 429:  # Too Many Requests
                        retry_after = int(response.headers.get('Retry-After', 60))
                        self.logger.warning(f"Rate limited, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue
                    
                    if response.status >= 500 and attempt < retries:
                        self.logger.warning(f"Server error {response.status}, retrying...")
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    
                    return response
                    
            except asyncio.TimeoutError:
                self.logger.warning(f"Request timeout, attempt {attempt + 1}")
                if attempt < retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
                
            except aiohttp.ClientError as e:
                self.logger.warning(f"Request error: {e}, attempt {attempt + 1}")
                if attempt < retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
        
        raise Exception(f"Max retries ({retries}) exceeded for {method} {url}")
    
    def clean_query(self, query: str) -> str:
        """Очистка поискового запроса"""
        # Удаляем лишние символы и нормализуем
        cleaned = query.strip()
        
        # Заменяем множественные пробелы на одинарные
        import re
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        # Удаляем специальные символы (кроме основных)
        cleaned = re.sub(r'[^\w\s\-()[\].,!?\'"]', '', cleaned)
        
        return cleaned
    
    def parse_duration(self, duration_str: str) -> Optional[int]:
        """Парсинг длительности из строки в секунды"""
        if not duration_str:
            return None
        
        try:
            # Формат MM:SS или HH:MM:SS
            parts = duration_str.split(':')
            if len(parts) == 2:  # MM:SS
                minutes, seconds = map(int, parts)
                return minutes * 60 + seconds
            elif len(parts) == 3:  # HH:MM:SS
                hours, minutes, seconds = map(int, parts)
                return hours * 3600 + minutes * 60 + seconds
            else:
                # Пробуем как число секунд
                return int(float(duration_str))
        except (ValueError, TypeError):
            return None
    
    def format_file_size(self, size_bytes: int) -> str:
        """Форматирование размера файла"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
    
    def detect_audio_quality(self, bitrate: Optional[int], file_size: Optional[int], duration: Optional[int]) -> AudioQuality:
        """Определение качества аудио"""
        if bitrate:
            if bitrate >= 300:
                return AudioQuality.ULTRA
            elif bitrate >= 240:
                return AudioQuality.HIGH
            elif bitrate >= 180:
                return AudioQuality.MEDIUM
            else:
                return AudioQuality.LOW
        
        # Если нет битрейта, пробуем по размеру файла
        if file_size and duration:
            # Примерный расчет битрейта
            estimated_bitrate = (file_size * 8) / (duration * 1000)  # kbps
            return self.detect_audio_quality(int(estimated_bitrate), None, None)
        
        return AudioQuality.MEDIUM
    
    def validate_search_result(self, result: SearchResult) -> bool:
        """Валидация результата поиска"""
        if not result.title or not result.artist:
            return False
        
        if len(result.title) < 1 or len(result.artist) < 1:
            return False
        
        if result.duration and (result.duration < 10 or result.duration > 7200):  # 10 сек - 2 часа
            return False
        
        return True
    
    @abstractmethod
    async def search(self, query: str, limit: int = 50) -> List[SearchResult]:
        """Поиск треков"""
        pass
    
    @abstractmethod
    async def get_download_url(self, external_id: str) -> Optional[DownloadResult]:
        """Получение ссылки на скачивание"""
        pass
    
    async def search_track(self, artist: str, title: str, limit: int = 10) -> List[SearchResult]:
        """Поиск конкретного трека по артисту и названию"""
        query = f"{artist} - {title}"
        return await self.search(query, limit)
    
    async def get_track_info(self, external_id: str) -> Optional[SearchResult]:
        """Получение информации о треке по ID"""
        # Базовая реализация - должна быть переопределена в наследниках
        return None
    
    async def is_available(self, external_id: str) -> bool:
        """Проверка доступности трека"""
        try:
            result = await self.get_download_url(external_id)
            return result is not None
        except:
            return False
    
    async def get_similar_tracks(self, external_id: str, limit: int = 20) -> List[SearchResult]:
        """Получение похожих треков"""
        # Базовая реализация - возвращает пустой список
        # Должна быть переопределена в наследниках при наличии такой функции
        return []
    
    async def get_artist_tracks(self, artist: str, limit: int = 50) -> List[SearchResult]:
        """Получение треков исполнителя"""
        return await self.search(artist, limit)
    
    async def get_popular_tracks(self, genre: Optional[str] = None, limit: int = 50) -> List[SearchResult]:
        """Получение популярных треков"""
        # Базовая реализация - возвращает пустой список
        # Должна быть переопределена в наследниках
        return []
    
    def get_service_stats(self) -> Dict[str, Any]:
        """Получение статистики сервиса"""
        return {
            'source': self.source.value,
            'rate_limit_requests': self.rate_limiter.max_requests,
            'rate_limit_window': self.rate_limiter.time_window,
            'current_requests': len(self.rate_limiter.requests),
            'session_active': self._session is not None and not self._session.closed,
            'max_retries': self.max_retries,
            'timeout': self.timeout
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка работоспособности сервиса"""
        try:
            # Простой тестовый поиск
            start_time = time.time()
            results = await self.search("test", limit=1)
            response_time = (time.time() - start_time) * 1000
            
            return {
                'service': self.source.value,
                'status': 'healthy',
                'response_time_ms': round(response_time, 2),
                'results_count': len(results),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                'service': self.source.value,
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }


class ServiceError(Exception):
    """Базовая ошибка музыкального сервиса"""
    pass


class RateLimitError(ServiceError):
    """Ошибка превышения лимита запросов"""
    pass


class TrackNotFoundError(ServiceError):
    """Ошибка - трек не найден"""
    pass


class DownloadError(ServiceError):
    """Ошибка скачивания"""
    pass


class AuthenticationError(ServiceError):
    """Ошибка аутентификации"""
    pass