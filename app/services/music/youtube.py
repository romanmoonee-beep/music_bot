"""
YouTube Music сервис для поиска и скачивания музыки
"""
import asyncio
import re
import json
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, parse_qs, urlparse
import yt_dlp
from concurrent.futures import ThreadPoolExecutor

from app.services.music.base import (
    BaseMusicService, SearchResult, DownloadResult,
    ServiceError, TrackNotFoundError, DownloadError
)
from app.models.track import TrackSource, AudioQuality
from app.core.config import settings


class YouTubeMusicService(BaseMusicService):
    """Сервис для работы с YouTube Music через yt-dlp"""
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            source=TrackSource.YOUTUBE,
            rate_limit_requests=100,  # YouTube более лоялен
            rate_limit_window=60,
            timeout=60,  # Увеличиваем таймаут для видео
            max_retries=3
        )
        
        self.api_key = api_key or settings.YOUTUBE_API_KEY
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.youtube_url = "https://www.youtube.com"
        self.music_url = "https://music.youtube.com"
        
        # Настройки yt-dlp
        self.ytdl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extractaudio': True,
            'audioformat': 'mp3',
            'audioquality': '192',
            'format': 'bestaudio/best',
            'noplaylist': True,
            'extract_flat': False,
            'writethumbnail': False,
            'writeinfojson': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'ignoreerrors': True,
            'no_color': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        # Thread pool для yt-dlp (блокирующие операции)
        self.executor = ThreadPoolExecutor(max_workers=5)
    
    async def search_youtube_api(self, query: str, limit: int = 50) -> List[SearchResult]:
        """Поиск через YouTube Data API"""
        if not self.api_key:
            self.logger.warning("YouTube API key not provided")
            return []
        
        try:
            # Параметры поиска
            params = {
                'part': 'snippet',
                'q': f"{query} audio",
                'type': 'video',
                'videoEmbeddable': 'true',
                'videoSyndicated': 'true',
                'videoCategoryId': '10',  # Music category
                'order': 'relevance',
                'maxResults': min(limit, 50),
                'key': self.api_key
            }
            
            response = await self.make_request(
                'GET', 
                f"{self.base_url}/search",
                params=params
            )
            
            if response.status != 200:
                raise ServiceError(f"YouTube API error: {response.status}")
            
            data = await response.json()
            
            if 'items' not in data:
                return []
            
            results = []
            for item in data['items']:
                result = self.parse_youtube_search_item(item)
                if result and self.validate_search_result(result):
                    results.append(result)
            
            return results
            
        except Exception as e:
            self.logger.error(f"YouTube API search failed: {e}")
            return []
    
    def parse_youtube_search_item(self, item: Dict) -> Optional[SearchResult]:
        """Парсинг элемента поиска YouTube API"""
        try:
            snippet = item.get('snippet', {})
            video_id = item['id']['videoId']
            
            title = snippet.get('title', '')
            channel_title = snippet.get('channelTitle', '')
            description = snippet.get('description', '')
            
            # Пытаемся извлечь артиста и название из заголовка
            artist, track_title = self.parse_youtube_title(title, channel_title)
            
            if not artist or not track_title:
                return None
            
            # Получаем thumbnail
            thumbnails = snippet.get('thumbnails', {})
            cover_url = None
            if 'high' in thumbnails:
                cover_url = thumbnails['high']['url']
            elif 'medium' in thumbnails:
                cover_url = thumbnails['medium']['url']
            elif 'default' in thumbnails:
                cover_url = thumbnails['default']['url']
            
            # Дата публикации
            published_at = snippet.get('publishedAt')
            year = None
            if published_at:
                try:
                    year = datetime.fromisoformat(published_at.replace('Z', '+00:00')).year
                except:
                    pass
            
            return SearchResult(
                title=track_title,
                artist=artist,
                duration=None,  # Получим позже через yt-dlp
                external_id=video_id,
                external_url=f"{self.youtube_url}/watch?v={video_id}",
                cover_url=cover_url,
                source=TrackSource.YOUTUBE,
                audio_quality=AudioQuality.MEDIUM,
                year=year,
                metadata={
                    'youtube_id': video_id,
                    'channel_title': channel_title,
                    'description': description,
                    'published_at': published_at,
                    'source': 'youtube_api'
                }
            )
            
        except Exception as e:
            self.logger.warning(f"Error parsing YouTube item: {e}")
            return None
    
    def parse_youtube_title(self, title: str, channel_title: str) -> Tuple[Optional[str], Optional[str]]:
        """Извлечение артиста и названия трека из заголовка YouTube"""
        try:
            # Очищаем заголовок от лишних символов
            clean_title = re.sub(r'\([^)]*\)|\[[^\]]*\]', '', title).strip()
            clean_title = re.sub(r'\s+', ' ', clean_title)
            
            # Паттерны для извлечения артиста и трека
            patterns = [
                r'^(.+?)\s*[-–—]\s*(.+)$',  # Artist - Track
                r'^(.+?)\s*[|]\s*(.+)$',   # Artist | Track
                r'^(.+?)\s*:\s*(.+)$',     # Artist: Track
                r'^(.+?)\s*by\s+(.+)$',    # Track by Artist
            ]
            
            for pattern in patterns:
                match = re.match(pattern, clean_title, re.IGNORECASE)
                if match:
                    part1, part2 = match.groups()
                    
                    # Определяем, что артист, а что трек
                    if 'by' in pattern:
                        return part2.strip(), part1.strip()
                    else:
                        return part1.strip(), part2.strip()
            
            # Если паттерны не сработали, используем канал как артиста
            if channel_title and not any(word in channel_title.lower() for word in ['official', 'music', 'records', 'entertainment']):
                return channel_title, clean_title
            
            # Последняя попытка - разделяем по первому тире
            if ' - ' in clean_title:
                parts = clean_title.split(' - ', 1)
                return parts[0].strip(), parts[1].strip()
            
            # Не удалось разобрать
            return None, None
            
        except Exception as e:
            self.logger.warning(f"Error parsing YouTube title: {e}")
            return None, None
    
    async def search_ytdl(self, query: str, limit: int = 50) -> List[SearchResult]:
        """Поиск через yt-dlp"""
        try:
            search_query = f"ytsearch{limit}:{query}"
            
            ytdl_opts = self.ytdl_opts.copy()
            ytdl_opts.update({
                'extract_flat': True,  # Быстрое извлечение метаданных
                'quiet': True
            })
            
            # Выполняем поиск в отдельном потоке
            loop = asyncio.get_event_loop()
            search_results = await loop.run_in_executor(
                self.executor,
                self._ytdl_search,
                search_query,
                ytdl_opts
            )
            
            if not search_results:
                return []
            
            results = []
            for entry in search_results.get('entries', []):
                if not entry:
                    continue
                
                result = self.parse_ytdl_entry(entry)
                if result and self.validate_search_result(result):
                    results.append(result)
            
            return results
            
        except Exception as e:
            self.logger.error(f"yt-dlp search failed: {e}")
            return []
    
    def _ytdl_search(self, search_query: str, ytdl_opts: Dict) -> Optional[Dict]:
        """Синхронный поиск через yt-dlp"""
        try:
            with yt_dlp.YoutubeDL(ytdl_opts) as ytdl:
                return ytdl.extract_info(search_query, download=False)
        except Exception as e:
            self.logger.error(f"yt-dlp extraction failed: {e}")
            return None
    
    def parse_ytdl_entry(self, entry: Dict) -> Optional[SearchResult]:
        """Парсинг записи из yt-dlp"""
        try:
            video_id = entry.get('id')
            title = entry.get('title', '')
            uploader = entry.get('uploader', '')
            duration = entry.get('duration')
            
            if not video_id or not title:
                return None
            
            # Извлекаем артиста и название
            artist, track_title = self.parse_youtube_title(title, uploader)
            
            if not artist or not track_title:
                return None
            
            # Thumbnail
            thumbnail = entry.get('thumbnail')
            
            # Дата загрузки
            upload_date = entry.get('upload_date')
            year = None
            if upload_date:
                try:
                    year = datetime.strptime(upload_date, '%Y%m%d').year
                except:
                    pass
            
            return SearchResult(
                title=track_title,
                artist=artist,
                duration=duration,
                external_id=video_id,
                external_url=f"{self.youtube_url}/watch?v={video_id}",
                cover_url=thumbnail,
                source=TrackSource.YOUTUBE,
                audio_quality=AudioQuality.MEDIUM,
                year=year,
                metadata={
                    'youtube_id': video_id,
                    'uploader': uploader,
                    'upload_date': upload_date,
                    'view_count': entry.get('view_count'),
                    'like_count': entry.get('like_count'),
                    'source': 'ytdl'
                }
            )
            
        except Exception as e:
            self.logger.warning(f"Error parsing yt-dlp entry: {e}")
            return None
    
    async def search(self, query: str, limit: int = 50) -> List[SearchResult]:
        """Основной метод поиска"""
        try:
            cleaned_query = self.clean_query(query)
            if not cleaned_query:
                return []
            
            # Добавляем ключевые слова для лучшего поиска музыки
            music_query = f"{cleaned_query} music audio song"
            
            self.logger.info(f"Searching YouTube: '{music_query}' (limit: {limit})")
            
            results = []
            
            # Стратегия 1: YouTube API (если есть ключ)
            if self.api_key:
                try:
                    api_results = await self.search_youtube_api(music_query, limit)
                    results.extend(api_results)
                    self.logger.info(f"YouTube API returned {len(api_results)} results")
                except Exception as e:
                    self.logger.warning(f"YouTube API search failed: {e}")
            
            # Стратегия 2: yt-dlp (fallback или дополнение)
            if len(results) < limit:
                try:
                    ytdl_results = await self.search_ytdl(music_query, limit - len(results))
                    results.extend(ytdl_results)
                    self.logger.info(f"yt-dlp returned {len(ytdl_results)} results")
                except Exception as e:
                    self.logger.warning(f"yt-dlp search failed: {e}")
            
            # Удаляем дубликаты и фильтруем
            unique_results = self.deduplicate_results(results)
            filtered_results = self.filter_music_results(unique_results)
            
            self.logger.info(f"YouTube search completed: {len(filtered_results)} results")
            return filtered_results[:limit]
            
        except Exception as e:
            self.logger.error(f"YouTube search failed: {e}")
            return []
    
    def deduplicate_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """Удаление дубликатов"""
        seen_ids = set()
        seen_titles = set()
        unique_results = []
        
        for result in results:
            # Проверяем по ID
            if result.external_id in seen_ids:
                continue
            
            # Проверяем по названию и артисту
            title_key = f"{result.artist.lower()}||{result.title.lower()}"
            if title_key in seen_titles:
                continue
            
            seen_ids.add(result.external_id)
            seen_titles.add(title_key)
            unique_results.append(result)
        
        return unique_results
    
    def filter_music_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """Фильтрация результатов - оставляем только музыку"""
        filtered = []
        
        # Слова, которые указывают на НЕ музыку
        exclude_keywords = [
            'interview', 'live stream', 'podcast', 'tutorial', 'reaction',
            'review', 'behind the scenes', 'making of', 'documentary',
            'news', 'vlog', 'gameplay', 'walkthrough', 'trailer'
        ]
        
        for result in results:
            title_lower = result.title.lower()
            
            # Исключаем видео с подозрительными словами
            if any(keyword in title_lower for keyword in exclude_keywords):
                continue
            
            # Исключаем очень короткие (< 30 сек) и очень длинные (> 15 мин) треки
            if result.duration:
                if result.duration < 30 or result.duration > 900:
                    continue
            
            filtered.append(result)
        
        return filtered
    
    async def get_download_url(self, external_id: str) -> Optional[DownloadResult]:
        """Получение ссылки на скачивание"""
        try:
            self.logger.info(f"Getting download URL for YouTube video: {external_id}")
            
            video_url = f"{self.youtube_url}/watch?v={external_id}"
            
            # Настройки для извлечения URL
            ytdl_opts = self.ytdl_opts.copy()
            ytdl_opts.update({
                'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio',
                'extract_flat': False,
                'quiet': True
            })
            
            # Извлекаем информацию в отдельном потоке
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(
                self.executor,
                self._ytdl_extract_info,
                video_url,
                ytdl_opts
            )
            
            if not info:
                raise DownloadError(f"Could not extract info for: {external_id}")
            
            # Ищем лучший аудио формат
            formats = info.get('formats', [])
            best_audio = None
            best_quality_score = 0
            
            for fmt in formats:
                if fmt.get('acodec') == 'none':  # Видео без аудио
                    continue
                
                if fmt.get('vcodec') != 'none':  # Видео с аудио, но нам нужно только аудио
                    continue
                
                # Вычисляем оценку качества
                quality_score = 0
                
                if fmt.get('abr'):  # Audio bitrate
                    quality_score += fmt['abr']
                
                if fmt.get('asr'):  # Audio sample rate
                    quality_score += fmt['asr'] / 1000
                
                if quality_score > best_quality_score:
                    best_quality_score = quality_score
                    best_audio = fmt
            
            if not best_audio:
                # Fallback - берем любой аудио формат
                for fmt in formats:
                    if fmt.get('acodec') and fmt.get('acodec') != 'none':
                        best_audio = fmt
                        break
            
            if not best_audio or not best_audio.get('url'):
                raise DownloadError(f"No audio stream found for: {external_id}")
            
            # Определяем качество
            bitrate = best_audio.get('abr', 128)
            audio_quality = self.detect_audio_quality(int(bitrate), None, None)
            
            # Определяем формат
            ext = best_audio.get('ext', 'mp3')
            if ext in ['webm', 'm4a']:
                format_name = ext
            else:
                format_name = 'mp3'
            
            # URL истекает довольно быстро (обычно 6 часов)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=6)
            
            return DownloadResult(
                url=best_audio['url'],
                expires_at=expires_at,
                file_size=best_audio.get('filesize'),
                audio_quality=audio_quality,
                format=format_name,
                bitrate=bitrate,
                headers={
                    'User-Agent': self.ytdl_opts['user_agent']
                },
                metadata={
                    'youtube_id': external_id,
                    'format_id': best_audio.get('format_id'),
                    'quality': best_audio.get('quality'),
                    'source': 'ytdl'
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to get YouTube download URL: {e}")
            return None
    
    def _ytdl_extract_info(self, url: str, ytdl_opts: Dict) -> Optional[Dict]:
        """Синхронное извлечение информации через yt-dlp"""
        try:
            with yt_dlp.YoutubeDL(ytdl_opts) as ytdl:
                return ytdl.extract_info(url, download=False)
        except Exception as e:
            self.logger.error(f"yt-dlp info extraction failed: {e}")
            return None
    
    async def get_track_info(self, external_id: str) -> Optional[SearchResult]:
        """Получение детальной информации о треке"""
        try:
            video_url = f"{self.youtube_url}/watch?v={external_id}"
            
            ytdl_opts = self.ytdl_opts.copy()
            ytdl_opts.update({
                'extract_flat': False,
                'quiet': True
            })
            
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(
                self.executor,
                self._ytdl_extract_info,
                video_url,
                ytdl_opts
            )
            
            if not info:
                return None
            
            title = info.get('title', '')
            uploader = info.get('uploader', '')
            
            artist, track_title = self.parse_youtube_title(title, uploader)
            
            if not artist or not track_title:
                return None
            
            return SearchResult(
                title=track_title,
                artist=artist,
                duration=info.get('duration'),
                external_id=external_id,
                external_url=video_url,
                cover_url=info.get('thumbnail'),
                source=TrackSource.YOUTUBE,
                audio_quality=AudioQuality.MEDIUM,
                metadata={
                    'youtube_id': external_id,
                    'uploader': uploader,
                    'view_count': info.get('view_count'),
                    'like_count': info.get('like_count'),
                    'upload_date': info.get('upload_date'),
                    'description': info.get('description', '')[:500]  # Обрезаем описание
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to get YouTube track info: {e}")
            return None
    
    async def is_available(self, external_id: str) -> bool:
        """Проверка доступности видео"""
        try:
            info = await self.get_track_info(external_id)
            return info is not None
        except:
            return False
    
    async def close_session(self):
        """Закрытие сессии и thread pool"""
        await super().close_session()
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка работоспособности сервиса"""
        try:
            start_time = datetime.now()
            
            # Простой тестовый поиск
            results = await self.search("test music", limit=1)
            
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return {
                'service': self.source.value,
                'status': 'healthy',
                'api_key_configured': bool(self.api_key),
                'response_time_ms': round(response_time, 2),
                'results_count': len(results),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                'service': self.source.value,
                'status': 'unhealthy',
                'error': str(e),
                'api_key_configured': bool(self.api_key),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }