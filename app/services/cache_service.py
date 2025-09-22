"""
Сервис многоуровневого кеширования
"""
import json
import pickle
import hashlib
from typing import Any, Optional, Dict, List, Union
from datetime import datetime, timezone, timedelta
import aioredis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import get_logger


class CacheService:
    """Сервис для многоуровневого кеширования"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.redis: Optional[aioredis.Redis] = None
        self.local_cache: Dict[str, Dict[str, Any]] = {}
        self.max_local_cache_size = 1000
        
        # Настройки TTL для разных типов данных
        self.ttl_settings = {
            'track_search': settings.CACHE_TTL_SEARCH,
            'track_info': settings.CACHE_TTL_TRACKS,
            'user_data': settings.CACHE_TTL_USER_DATA,
            'playlist': 1800,  # 30 минут
            'download_url': 3600,  # 1 час
            'user_limits': 300,  # 5 минут
            'trending': 1800,  # 30 минут
            'recommendations': 3600,  # 1 час
            'health_check': 60,  # 1 минута
        }
    
    async def init_redis(self):
        """Инициализация Redis подключения"""
        try:
            self.redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                retry_on_timeout=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            
            # Проверяем подключение
            await self.redis.ping()
            self.logger.info("Redis connection established")
            
        except Exception as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            self.redis = None
    
    async def close_redis(self):
        """Закрытие Redis подключения"""
        if self.redis:
            await self.redis.close()
            self.redis = None
            self.logger.info("Redis connection closed")
    
    def _make_cache_key(self, prefix: str, key: str) -> str:
        """Создать ключ для кеша"""
        # Хешируем длинные ключи
        if len(key) > 100:
            key_hash = hashlib.md5(key.encode()).hexdigest()
            return f"{settings.PROJECT_NAME}:{prefix}:{key_hash}"
        return f"{settings.PROJECT_NAME}:{prefix}:{key}"
    
    def _serialize_value(self, value: Any) -> str:
        """Сериализация значения для кеша"""
        try:
            if isinstance(value, (str, int, float, bool)):
                return json.dumps(value)
            else:
                # Для сложных объектов используем pickle через base64
                import base64
                pickled = pickle.dumps(value)
                encoded = base64.b64encode(pickled).decode('utf-8')
                return json.dumps({"__pickle__": encoded})
        except Exception as e:
            self.logger.error(f"Failed to serialize value: {e}")
            return json.dumps(None)
    
    def _deserialize_value(self, value: str) -> Any:
        """Десериализация значения из кеша"""
        try:
            data = json.loads(value)
            
            # Проверяем, не pickle ли это
            if isinstance(data, dict) and "__pickle__" in data:
                import base64
                decoded = base64.b64decode(data["__pickle__"])
                return pickle.loads(decoded)
            
            return data
        except Exception as e:
            self.logger.error(f"Failed to deserialize value: {e}")
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        cache_type: str = "default"
    ) -> bool:
        """Установить значение в кеш"""
        try:
            cache_key = self._make_cache_key(cache_type, key)
            serialized_value = self._serialize_value(value)
            
            if ttl is None:
                ttl = self.ttl_settings.get(cache_type, 3600)
            
            # L1: Локальный кеш
            self._set_local_cache(cache_key, value, ttl)
            
            # L2: Redis
            if self.redis:
                try:
                    await self.redis.setex(cache_key, ttl, serialized_value)
                    return True
                except RedisError as e:
                    self.logger.warning(f"Redis set failed: {e}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Cache set failed: {e}")
            return False
    
    async def get(self, key: str, cache_type: str = "default") -> Any:
        """Получить значение из кеша"""
        try:
            cache_key = self._make_cache_key(cache_type, key)
            
            # L1: Локальный кеш
            local_value = self._get_local_cache(cache_key)
            if local_value is not None:
                return local_value
            
            # L2: Redis
            if self.redis:
                try:
                    redis_value = await self.redis.get(cache_key)
                    if redis_value:
                        deserialized = self._deserialize_value(redis_value)
                        # Сохраняем в локальный кеш
                        if deserialized is not None:
                            self._set_local_cache(cache_key, deserialized, 300)  # 5 мин в локальном
                        return deserialized
                except RedisError as e:
                    self.logger.warning(f"Redis get failed: {e}")
            
            return None
            
        except Exception as e:
            self.logger.error(f"Cache get failed: {e}")
            return None
    
    async def delete(self, key: str, cache_type: str = "default") -> bool:
        """Удалить значение из кеша"""
        try:
            cache_key = self._make_cache_key(cache_type, key)
            
            # L1: Локальный кеш
            self.local_cache.pop(cache_key, None)
            
            # L2: Redis
            if self.redis:
                try:
                    await self.redis.delete(cache_key)
                except RedisError as e:
                    self.logger.warning(f"Redis delete failed: {e}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Cache delete failed: {e}")
            return False
    
    async def exists(self, key: str, cache_type: str = "default") -> bool:
        """Проверить существование ключа в кеше"""
        try:
            cache_key = self._make_cache_key(cache_type, key)
            
            # L1: Локальный кеш
            if cache_key in self.local_cache:
                cache_item = self.local_cache[cache_key]
                if cache_item["expires_at"] > datetime.now(timezone.utc):
                    return True
                else:
                    del self.local_cache[cache_key]
            
            # L2: Redis
            if self.redis:
                try:
                    return await self.redis.exists(cache_key) > 0
                except RedisError as e:
                    self.logger.warning(f"Redis exists failed: {e}")
            
            return False
            
        except Exception as e:
            self.logger.error(f"Cache exists failed: {e}")
            return False
    
    async def set_many(
        self,
        items: Dict[str, Any],
        ttl: Optional[int] = None,
        cache_type: str = "default"
    ) -> bool:
        """Установить множество значений"""
        try:
            if not items:
                return True
            
            if ttl is None:
                ttl = self.ttl_settings.get(cache_type, 3600)
            
            # Подготавливаем данные для Redis
            redis_data = {}
            for key, value in items.items():
                cache_key = self._make_cache_key(cache_type, key)
                serialized_value = self._serialize_value(value)
                redis_data[cache_key] = serialized_value
                
                # Добавляем в локальный кеш
                self._set_local_cache(cache_key, value, ttl)
            
            # Устанавливаем в Redis
            if self.redis and redis_data:
                try:
                    pipe = self.redis.pipeline()
                    for cache_key, serialized_value in redis_data.items():
                        pipe.setex(cache_key, ttl, serialized_value)
                    await pipe.execute()
                except RedisError as e:
                    self.logger.warning(f"Redis mset failed: {e}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Cache set_many failed: {e}")
            return False
    
    async def get_many(
        self,
        keys: List[str],
        cache_type: str = "default"
    ) -> Dict[str, Any]:
        """Получить множество значений"""
        try:
            result = {}
            redis_keys_needed = []
            cache_keys_map = {}
            
            # Проверяем локальный кеш
            for key in keys:
                cache_key = self._make_cache_key(cache_type, key)
                cache_keys_map[cache_key] = key
                
                local_value = self._get_local_cache(cache_key)
                if local_value is not None:
                    result[key] = local_value
                else:
                    redis_keys_needed.append(cache_key)
            
            # Получаем недостающие из Redis
            if self.redis and redis_keys_needed:
                try:
                    redis_values = await self.redis.mget(redis_keys_needed)
                    for cache_key, redis_value in zip(redis_keys_needed, redis_values):
                        if redis_value:
                            original_key = cache_keys_map[cache_key]
                            deserialized = self._deserialize_value(redis_value)
                            if deserialized is not None:
                                result[original_key] = deserialized
                                # Сохраняем в локальный кеш
                                self._set_local_cache(cache_key, deserialized, 300)
                except RedisError as e:
                    self.logger.warning(f"Redis mget failed: {e}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Cache get_many failed: {e}")
            return {}
    
    async def increment(
        self,
        key: str,
        amount: int = 1,
        cache_type: str = "counter"
    ) -> int:
        """Увеличить счетчик"""
        try:
            cache_key = self._make_cache_key(cache_type, key)
            
            if self.redis:
                try:
                    return await self.redis.incrby(cache_key, amount)
                except RedisError as e:
                    self.logger.warning(f"Redis incr failed: {e}")
            
            # Fallback к локальному кешу
            current = self._get_local_cache(cache_key) or 0
            new_value = current + amount
            self._set_local_cache(cache_key, new_value, 3600)
            return new_value
            
        except Exception as e:
            self.logger.error(f"Cache increment failed: {e}")
            return 0
    
    async def expire(self, key: str, ttl: int, cache_type: str = "default") -> bool:
        """Установить время жизни для ключа"""
        try:
            cache_key = self._make_cache_key(cache_type, key)
            
            if self.redis:
                try:
                    return await self.redis.expire(cache_key, ttl)
                except RedisError as e:
                    self.logger.warning(f"Redis expire failed: {e}")
            
            return False
            
        except Exception as e:
            self.logger.error(f"Cache expire failed: {e}")
            return False
    
    async def clear_pattern(self, pattern: str, cache_type: str = "default") -> int:
        """Очистить ключи по паттерну"""
        try:
            cache_pattern = self._make_cache_key(cache_type, pattern)
            deleted_count = 0
            
            # Очищаем локальный кеш
            keys_to_delete = []
            for cache_key in self.local_cache.keys():
                if cache_pattern.replace("*", "") in cache_key:
                    keys_to_delete.append(cache_key)
            
            for cache_key in keys_to_delete:
                del self.local_cache[cache_key]
                deleted_count += 1
            
            # Очищаем Redis
            if self.redis:
                try:
                    keys = await self.redis.keys(cache_pattern)
                    if keys:
                        deleted_redis = await self.redis.delete(*keys)
                        deleted_count += deleted_redis
                except RedisError as e:
                    self.logger.warning(f"Redis pattern delete failed: {e}")
            
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Cache clear pattern failed: {e}")
            return 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Получить статистику кеша"""
        try:
            stats = {
                "local_cache_size": len(self.local_cache),
                "local_cache_max_size": self.max_local_cache_size,
                "redis_connected": self.redis is not None
            }
            
            if self.redis:
                try:
                    redis_info = await self.redis.info()
                    stats.update({
                        "redis_used_memory": redis_info.get("used_memory_human", "N/A"),
                        "redis_connected_clients": redis_info.get("connected_clients", 0),
                        "redis_total_commands": redis_info.get("total_commands_processed", 0),
                        "redis_keyspace_hits": redis_info.get("keyspace_hits", 0),
                        "redis_keyspace_misses": redis_info.get("keyspace_misses", 0)
                    })
                    
                    # Вычисляем hit rate
                    hits = redis_info.get("keyspace_hits", 0)
                    misses = redis_info.get("keyspace_misses", 0)
                    if hits + misses > 0:
                        stats["redis_hit_rate"] = round(hits / (hits + misses) * 100, 2)
                    else:
                        stats["redis_hit_rate"] = 0
                        
                except RedisError as e:
                    self.logger.warning(f"Failed to get Redis stats: {e}")
                    stats["redis_error"] = str(e)
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Failed to get cache stats: {e}")
            return {"error": str(e)}
    
    def _set_local_cache(self, key: str, value: Any, ttl: int):
        """Установить значение в локальный кеш"""
        # Очищаем если превышен размер
        if len(self.local_cache) >= self.max_local_cache_size:
            self._cleanup_local_cache()
        
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        self.local_cache[key] = {
            "value": value,
            "expires_at": expires_at
        }
    
    def _get_local_cache(self, key: str) -> Any:
        """Получить значение из локального кеша"""
        if key not in self.local_cache:
            return None
        
        cache_item = self.local_cache[key]
        if cache_item["expires_at"] <= datetime.now(timezone.utc):
            del self.local_cache[key]
            return None
        
        return cache_item["value"]
    
    def _cleanup_local_cache(self):
        """Очистка устаревших записей в локальном кеше"""
        now = datetime.now(timezone.utc)
        expired_keys = []
        
        for key, cache_item in self.local_cache.items():
            if cache_item["expires_at"] <= now:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.local_cache[key]
        
        # Если все еще превышен лимит, удаляем самые старые
        if len(self.local_cache) >= self.max_local_cache_size:
            sorted_items = sorted(
                self.local_cache.items(),
                key=lambda x: x[1]["expires_at"]
            )
            
            # Удаляем 20% самых старых записей
            to_remove = len(sorted_items) // 5
            for i in range(to_remove):
                del self.local_cache[sorted_items[i][0]]


# Специализированные методы для конкретных типов данных

class TrackCacheService(CacheService):
    """Специализированный сервис кеширования для треков"""
    
    async def cache_search_results(
        self,
        query: str,
        results: List[Any],
        source: str = "all"
    ) -> bool:
        """Кешировать результаты поиска треков"""
        cache_key = f"search:{source}:{hashlib.md5(query.encode()).hexdigest()}"
        return await self.set(cache_key, results, cache_type="track_search")
    
    async def get_cached_search_results(
        self,
        query: str,
        source: str = "all"
    ) -> Optional[List[Any]]:
        """Получить кешированные результаты поиска"""
        cache_key = f"search:{source}:{hashlib.md5(query.encode()).hexdigest()}"
        return await self.get(cache_key, cache_type="track_search")
    
    async def cache_track_info(self, track_id: str, track_info: Any) -> bool:
        """Кешировать информацию о треке"""
        cache_key = f"track:{track_id}"
        return await self.set(cache_key, track_info, cache_type="track_info")
    
    async def get_cached_track_info(self, track_id: str) -> Optional[Any]:
        """Получить кешированную информацию о треке"""
        cache_key = f"track:{track_id}"
        return await self.get(cache_key, cache_type="track_info")
    
    async def cache_download_url(
        self,
        track_id: str,
        download_result: Any
    ) -> bool:
        """Кешировать URL для скачивания"""
        cache_key = f"download:{track_id}"
        return await self.set(cache_key, download_result, cache_type="download_url")
    
    async def get_cached_download_url(self, track_id: str) -> Optional[Any]:
        """Получить кешированный URL для скачивания"""
        cache_key = f"download:{track_id}"
        return await self.get(cache_key, cache_type="download_url")
    
    async def invalidate_track_cache(self, track_id: str) -> bool:
        """Инвалидировать кеш трека"""
        await self.delete(f"track:{track_id}", "track_info")
        await self.delete(f"download:{track_id}", "download_url")
        return True


class UserCacheService(CacheService):
    """Специализированный сервис кеширования для пользователей"""
    
    async def cache_user_limits(
        self,
        telegram_id: int,
        limits_data: Dict[str, Any]
    ) -> bool:
        """Кешировать лимиты пользователя"""
        cache_key = f"limits:{telegram_id}"
        return await self.set(cache_key, limits_data, cache_type="user_limits")
    
    async def get_cached_user_limits(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Получить кешированные лимиты пользователя"""
        cache_key = f"limits:{telegram_id}"
        return await self.get(cache_key, cache_type="user_limits")
    
    async def cache_user_subscription(
        self,
        telegram_id: int,
        subscription_data: Any
    ) -> bool:
        """Кешировать информацию о подписке пользователя"""
        cache_key = f"subscription:{telegram_id}"
        return await self.set(cache_key, subscription_data, cache_type="user_data")
    
    async def get_cached_user_subscription(self, telegram_id: int) -> Optional[Any]:
        """Получить кешированную информацию о подписке"""
        cache_key = f"subscription:{telegram_id}"
        return await self.get(cache_key, cache_type="user_data")
    
    async def increment_user_downloads(self, telegram_id: int) -> int:
        """Увеличить счетчик скачиваний пользователя"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cache_key = f"downloads:{telegram_id}:{today}"
        count = await self.increment(cache_key, 1, "counter")
        
        # Устанавливаем TTL на конец дня
        tomorrow = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        ttl = int((tomorrow - datetime.now(timezone.utc)).total_seconds())
        await self.expire(cache_key, ttl, "counter")
        
        return count
    
    async def get_user_daily_downloads(self, telegram_id: int) -> int:
        """Получить количество скачиваний пользователя за день"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cache_key = f"downloads:{telegram_id}:{today}"
        result = await self.get(cache_key, "counter")
        return result or 0
    
    async def invalidate_user_cache(self, telegram_id: int) -> bool:
        """Инвалидировать весь кеш пользователя"""
        await self.clear_pattern(f"*{telegram_id}*", "user_data")
        await self.clear_pattern(f"*{telegram_id}*", "user_limits")
        await self.clear_pattern(f"*{telegram_id}*", "counter")
        return True


class SystemCacheService(CacheService):
    """Системный кеш для общих данных"""
    
    async def cache_trending_tracks(self, tracks: List[Any]) -> bool:
        """Кешировать популярные треки"""
        return await self.set("trending_tracks", tracks, cache_type="trending")
    
    async def get_cached_trending_tracks(self) -> Optional[List[Any]]:
        """Получить кешированные популярные треки"""
        return await self.get("trending_tracks", cache_type="trending")
    
    async def cache_service_health(
        self,
        service_name: str,
        health_data: Dict[str, Any]
    ) -> bool:
        """Кешировать состояние сервиса"""
        cache_key = f"health:{service_name}"
        return await self.set(cache_key, health_data, cache_type="health_check")
    
    async def get_cached_service_health(self, service_name: str) -> Optional[Dict[str, Any]]:
        """Получить кешированное состояние сервиса"""
        cache_key = f"health:{service_name}"
        return await self.get(cache_key, cache_type="health_check")
    
    async def cache_recommendations(
        self,
        user_id: int,
        recommendations: List[Any]
    ) -> bool:
        """Кешировать рекомендации для пользователя"""
        cache_key = f"recommendations:{user_id}"
        return await self.set(cache_key, recommendations, cache_type="recommendations")
    
    async def get_cached_recommendations(self, user_id: int) -> Optional[List[Any]]:
        """Получить кешированные рекомендации"""
        cache_key = f"recommendations:{user_id}"
        return await self.get(cache_key, cache_type="recommendations")


# Создаем глобальные экземпляры сервисов
cache_service = CacheService()
track_cache = TrackCacheService()
user_cache = UserCacheService()
system_cache = SystemCacheService()