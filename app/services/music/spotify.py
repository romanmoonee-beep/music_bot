"""
Spotify сервис для получения метаданных треков
"""
import base64
import asyncio
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta

from app.services.music.base import (
    BaseMusicService, SearchResult, DownloadResult,
    ServiceError, TrackNotFoundError
)
from app.models.track import TrackSource, AudioQuality
from app.core.config import settings


class SpotifyService(BaseMusicService):
    """Сервис для работы с Spotify API (только метаданные)"""
    
    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        super().__init__(
            source=TrackSource.SPOTIFY,
            rate_limit_requests=100,
            rate_limit_window=60,
            timeout=30,
            max_retries=3
        )
        
        self.client_id = client_id or settings.SPOTIFY_CLIENT_ID
        self.client_secret = client_secret or settings.SPOTIFY_CLIENT_SECRET
        self.base_url = "https://api.spotify.com/v1"
        self.auth_url = "https://accounts.spotify.com/api/token"
        
        self.access_token = None
        self.token_expires_at = None
    
    async def authenticate(self) -> bool:
        """Получение access token через Client Credentials Flow"""
        if not self.client_id or not self.client_secret:
            self.logger.warning("Spotify credentials not provided")
            return False
        
        try:
            # Проверяем действительность текущего токена
            if (self.access_token and self.token_expires_at and 
                datetime.now(timezone.utc) < self.token_expires_at):
                return True
            
            self.logger.info("Authenticating with Spotify...")
            
            # Подготавливаем данные для авторизации
            auth_string = f"{self.client_id}:{self.client_secret}"
            auth_bytes = auth_string.encode('ascii')
            auth_base64 = base64.b64encode(auth_bytes).decode('ascii')
            
            headers = {
                'Authorization': f'Basic {auth_base64}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = 'grant_type=client_credentials'
            
            response = await self.make_request(
                'POST',
                self.auth_url,
                data=data,
                headers=headers
            )
            
            if response.status != 200:
                raise ServiceError(f"Spotify auth failed with status {response.status}")
            
            auth_data = await response.json()
            
            self.access_token = auth_data['access_token']
            expires_in = auth_data.get('expires_in', 3600)
            self.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
            
            self.logger.info("Spotify authentication successful")
            return True
            
        except Exception as e:
            self.logger.error(f"Spotify authentication failed: {e}")
            return False
    
    def get_auth_headers(self) -> Dict[str, str]:
        """Получение заголовков с авторизацией"""
        if not self.access_token:
            raise ServiceError("Not authenticated with Spotify")
        
        headers = self.get_default_headers()
        headers['Authorization'] = f'Bearer {self.access_token}'
        return headers
    
    async def spotify_api_call(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Вызов Spotify API"""
        # Проверяем авторизацию
        if not await self.authenticate():
            raise ServiceError("Failed to authenticate with Spotify")
        
        url = f"{self.base_url}/{endpoint}"
        headers = self.get_auth_headers()
        
        response = await self.make_request('GET', url, params=params, headers=headers)
        
        if response.status == 401:
            # Токен истек, пробуем обновить
            self.access_token = None
            if await self.authenticate():
                headers = self.get_auth_headers()
                response = await self.make_request('GET', url, params=params, headers=headers)
        
        if response.status != 200:
            raise ServiceError(f"Spotify API error: {response.status}")
        
        return await response.json()
    
    async def search(self, query: str, limit: int = 50) -> List[SearchResult]:
        """Поиск треков в Spotify"""
        try:
            cleaned_query = self.clean_query(query)
            if not cleaned_query:
                return []
            
            self.logger.info(f"Searching Spotify: '{cleaned_query}' (limit: {limit})")
            
            params = {
                'q': cleaned_query,
                'type': 'track',
                'limit': min(limit, 50),  # Spotify максимум 50
                'market': 'US'  # Используем US для большего покрытия
            }
            
            data = await self.spotify_api_call('search', params)
            
            if 'tracks' not in data or 'items' not in data['tracks']:
                return []
            
            results = []
            for track_data in data['tracks']['items']:
                result = self.parse_spotify_track(track_data)
                if result and self.validate_search_result(result):
                    results.append(result)
            
            self.logger.info(f"Spotify search completed: {len(results)} results")
            return results
            
        except Exception as e:
            self.logger.error(f"Spotify search failed: {e}")
            return []
    
    def parse_spotify_track(self, track_data: Dict) -> Optional[SearchResult]:
        """Парсинг трека из Spotify API"""
        try:
            track_id = track_data.get('id')
            name = track_data.get('name', '').strip()
            
            # Артисты
            artists = track_data.get('artists', [])
            if not artists:
                return None
            
            artist = ', '.join(artist['name'] for artist in artists)
            
            # Альбом
            album_data = track_data.get('album', {})
            album = album_data.get('name', '').strip() if album_data else None
            
            # Длительность (в миллисекундах)
            duration_ms = track_data.get('duration_ms')
            duration = int