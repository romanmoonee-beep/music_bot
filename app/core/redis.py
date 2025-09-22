# app/core/redis.py
"""
Redis подключение и утилиты
"""
import asyncio
import json
import pickle
import time
from typing import Any, Optional, Dict, List, Union
from contextlib import asynccontextmanager

import aioredis
from aioredis import Redis
from aioredis.exceptions import RedisError, ConnectionError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RedisManager:
    """Менеджер Redis подключений"""
    
    def __init__(self):
        self.redis: Optional[Redis] = None
        self.pubsub_redis: Optional[Redis] = None
        self.cache_redis: Optional[Redis] = None
        self.session_redis: Optional[Redis] = None
        self._connection_pool = None
        
    async def init_connections(self):
        """Инициализация всех Redis подключений"""
        try:
            # Основное подключение
            self.redis = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=False,  # Для работы с бинарными данными
                retry_on_timeout=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                health_check_interval=30
            )
            
            # Подключение для pub/sub
            self.pubsub_redis = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                retry_on_timeout=True
            )
            
            # Подключение для кеша
            self.cache_redis = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                retry_on_timeout=True,
                db=1  # Отдельная база для кеша
            )
            
            # Подключение для сессий
            self.session_redis = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                retry_on_timeout=True,
                db=2  # Отдельная база для сессий
            )
            
            # Проверяем подключения
            await self.redis.ping()
            await self.pubsub_redis.ping()
            await self.cache_redis.ping()
            await self.session_redis.ping()
            
            logger.info("All Redis connections established successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis connections: {e}")
            raise
    
    async def close_connections(self):
        """Закрытие всех Redis подключений"""
        connections = [
            ("main", self.redis),
            ("pubsub", self.pubsub_redis),
            ("cache", self.cache_redis),
            ("session", self.session_redis)
        ]
        
        for name, connection in connections:
            if connection:
                try:
                    await connection.close()
                    logger.info(f"Closed Redis {name} connection")
                except Exception as e:
                    logger.error(f"Error closing Redis {name} connection: {e}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка состояния всех Redis подключений"""
        health_status = {
            "timestamp": time.time(),
            "overall_status": "healthy",
            "connections": {}
        }
        
        connections = [
            ("main", self.redis),
            ("pubsub", self.pubsub_redis),
            ("cache", self.cache_redis),
            ("session", self.session_redis)
        ]
        
        unhealthy_count = 0
        
        for name, connection in connections:
            try:
                if connection:
                    await connection.ping()
                    info = await connection.info()
                    
                    health_status["connections"][name] = {
                        "status": "healthy",
                        "connected_clients": info.get("connected_clients", 0),
                        "used_memory": info.get("used_memory_human", "unknown"),
                        "uptime": info.get("uptime_in_seconds", 0)
                    }
                else:
                    health_status["connections"][name] = {
                        "status": "not_initialized"
                    }
                    unhealthy_count += 1
                    
            except Exception as e:
                health_status["connections"][name] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
                unhealthy_count += 1
        
        if unhealthy_count > 0:
            health_status["overall_status"] = "degraded" if unhealthy_count < 4 else "unhealthy"
        
        return health_status
    
    def get_connection(self, connection_type: str = "main") -> Optional[Redis]:
        """Получение подключения по типу"""
        connections = {
            "main": self.redis,
            "pubsub": self.pubsub_redis,
            "cache": self.cache_redis,
            "session": self.session_redis
        }
        
        return connections.get(connection_type)


# Глобальный менеджер Redis
redis_manager = RedisManager()


class RedisCache:
    """Кеш на основе Redis"""
    
    def __init__(self, connection_type: str = "cache", prefix: str = "cache"):
        self.connection_type = connection_type
        self.prefix = prefix
    
    @property
    def redis(self) -> Redis:
        """Получение Redis подключения"""
        connection = redis_manager.get_connection(self.connection_type)
        if not connection:
            raise ConnectionError("Redis connection not available")
        return connection
    
    def _make_key(self, key: str) -> str:
        """Создание ключа с префиксом"""
        return f"{self.prefix}:{key}"
    
    async def get(self, key: str, default: Any = None) -> Any:
        """Получение значения из кеша"""
        try:
            redis_key = self._make_key(key)
            value = await self.redis.get(redis_key)
            
            if value is None:
                return default
            
            # Пытаемся десериализовать JSON
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                # Если не JSON, пытаемся pickle
                try:
                    return pickle.loads(value)
                except:
                    # Возвращаем как есть
                    return value
                    
        except RedisError as e:
            logger.error(f"Redis get error for key {key}: {e}")
            return default
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        nx: bool = False,
        xx: bool = False
    ) -> bool:
        """Установка значения в кеш"""
        try:
            redis_key = self._make_key(key)
            
            # Сериализуем значение
            if isinstance(value, (dict, list, tuple)):
                serialized_value = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, (str, int, float, bool)):
                serialized_value = json.dumps(value)
            else:
                # Для сложных объектов используем pickle
                serialized_value = pickle.dumps(value)
            
            # Устанавливаем значение
            result = await self.redis.set(
                redis_key,
                serialized_value,
                ex=ttl,
                nx=nx,
                xx=xx
            )
            
            return bool(result)
            
        except RedisError as e:
            logger.error(f"Redis set error for key {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Удаление ключа из кеша"""
        try:
            redis_key = self._make_key(key)
            result = await self.redis.delete(redis_key)
            return bool(result)
        except RedisError as e:
            logger.error(f"Redis delete error for key {key}: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Проверка существования ключа"""
        try:
            redis_key = self._make_key(key)
            return await self.redis.exists(redis_key)
        except RedisError as e:
            logger.error(f"Redis exists error for key {key}: {e}")
            return False
    
    async def expire(self, key: str, ttl: int) -> bool:
        """Установка TTL для ключа"""
        try:
            redis_key = self._make_key(key)
            return await self.redis.expire(redis_key, ttl)
        except RedisError as e:
            logger.error(f"Redis expire error for key {key}: {e}")
            return False
    
    async def increment(self, key: str, amount: int = 1) -> int:
        """Инкремент счетчика"""
        try:
            redis_key = self._make_key(key)
            return await self.redis.incrby(redis_key, amount)
        except RedisError as e:
            logger.error(f"Redis increment error for key {key}: {e}")
            return 0
    
    async def decrement(self, key: str, amount: int = 1) -> int:
        """Декремент счетчика"""
        try:
            redis_key = self._make_key(key)
            return await self.redis.decrby(redis_key, amount)
        except RedisError as e:
            logger.error(f"Redis decrement error for key {key}: {e}")
            return 0
    
    async def mget(self, keys: List[str]) -> List[Any]:
        """Получение множества значений"""
        try:
            redis_keys = [self._make_key(key) for key in keys]
            values = await self.redis.mget(redis_keys)
            
            result = []
            for value in values:
                if value is None:
                    result.append(None)
                else:
                    try:
                        result.append(json.loads(value))
                    except json.JSONDecodeError:
                        try:
                            result.append(pickle.loads(value))
                        except:
                            result.append(value)
            
            return result
            
        except RedisError as e:
            logger.error(f"Redis mget error for keys {keys}: {e}")
            return [None] * len(keys)
    
    async def mset(self, mapping: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """Установка множества значений"""
        try:
            redis_mapping = {}
            for key, value in mapping.items():
                redis_key = self._make_key(key)
                
                if isinstance(value, (dict, list, tuple)):
                    serialized_value = json.dumps(value, ensure_ascii=False)
                elif isinstance(value, (str, int, float, bool)):
                    serialized_value = json.dumps(value)
                else:
                    serialized_value = pickle.dumps(value)
                
                redis_mapping[redis_key] = serialized_value
            
            result = await self.redis.mset(redis_mapping)
            
            # Устанавливаем TTL для всех ключей если указан
            if ttl and result:
                pipeline = self.redis.pipeline()
                for redis_key in redis_mapping.keys():
                    pipeline.expire(redis_key, ttl)
                await pipeline.execute()
            
            return bool(result)
            
        except RedisError as e:
            logger.error(f"Redis mset error: {e}")
            return False
    
    async def keys(self, pattern: str = "*") -> List[str]:
        """Получение ключей по паттерну"""
        try:
            redis_pattern = self._make_key(pattern)
            redis_keys = await self.redis.keys(redis_pattern)
            
            # Убираем префикс из ключей
            prefix_len = len(self.prefix) + 1
            return [key[prefix_len:] for key in redis_keys]
            
        except RedisError as e:
            logger.error(f"Redis keys error for pattern {pattern}: {e}")
            return []
    
    async def clear_by_pattern(self, pattern: str = "*") -> int:
        """Удаление ключей по паттерну"""
        try:
            redis_pattern = self._make_key(pattern)
            keys = await self.redis.keys(redis_pattern)
            
            if keys:
                return await self.redis.delete(*keys)
            
            return 0
            
        except RedisError as e:
            logger.error(f"Redis clear pattern error for {pattern}: {e}")
            return 0
    
    async def flush_all(self) -> bool:
        """Очистка всего кеша"""
        try:
            await self.redis.flushdb()
            return True
        except RedisError as e:
            logger.error(f"Redis flush error: {e}")
            return False


class RedisPubSub:
    """Pub/Sub на основе Redis"""
    
    def __init__(self):
        self.connection = redis_manager.get_connection("pubsub")
        self.subscriptions = {}
    
    async def publish(self, channel: str, message: Any) -> int:
        """Публикация сообщения"""
        try:
            if isinstance(message, (dict, list)):
                message = json.dumps(message, ensure_ascii=False)
            elif not isinstance(message, str):
                message = str(message)
            
            return await self.connection.publish(channel, message)
            
        except RedisError as e:
            logger.error(f"Redis publish error for channel {channel}: {e}")
            return 0
    
    async def subscribe(self, channel: str, callback):
        """Подписка на канал"""
        try:
            pubsub = self.connection.pubsub()
            await pubsub.subscribe(channel)
            
            self.subscriptions[channel] = {
                "pubsub": pubsub,
                "callback": callback
            }
            
            # Запускаем обработку сообщений в фоне
            asyncio.create_task(self._handle_messages(channel))
            
            logger.info(f"Subscribed to Redis channel: {channel}")
            
        except RedisError as e:
            logger.error(f"Redis subscribe error for channel {channel}: {e}")
    
    async def unsubscribe(self, channel: str):
        """Отписка от канала"""
        try:
            if channel in self.subscriptions:
                pubsub = self.subscriptions[channel]["pubsub"]
                await pubsub.unsubscribe(channel)
                await pubsub.close()
                
                del self.subscriptions[channel]
                logger.info(f"Unsubscribed from Redis channel: {channel}")
                
        except RedisError as e:
            logger.error(f"Redis unsubscribe error for channel {channel}: {e}")
    
    async def _handle_messages(self, channel: str):
        """Обработка сообщений из канала"""
        try:
            subscription = self.subscriptions.get(channel)
            if not subscription:
                return
            
            pubsub = subscription["pubsub"]
            callback = subscription["callback"]
            
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = message["data"]
                        
                        # Пытаемся распарсить JSON
                        try:
                            data = json.loads(data)
                        except json.JSONDecodeError:
                            pass  # Оставляем как есть
                        
                        await callback(channel, data)
                        
                    except Exception as e:
                        logger.error(f"Error in pubsub callback for channel {channel}: {e}")
                        
        except Exception as e:
            logger.error(f"Redis pubsub listener error for channel {channel}: {e}")


class RedisSession:
    """Сессии на основе Redis"""
    
    def __init__(self, prefix: str = "session"):
        self.cache = RedisCache("session", prefix)
    
    async def create_session(
        self,
        session_id: str,
        user_id: int,
        data: Dict[str, Any],
        ttl: int = 3600
    ) -> bool:
        """Создание сессии"""
        session_data = {
            "user_id": user_id,
            "created_at": time.time(),
            "data": data
        }
        
        return await self.cache.set(session_id, session_data, ttl)
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Получение сессии"""
        return await self.cache.get(session_id)
    
    async def update_session(
        self,
        session_id: str,
        data: Dict[str, Any],
        extend_ttl: int = None
    ) -> bool:
        """Обновление сессии"""
        session_data = await self.get_session(session_id)
        if not session_data:
            return False
        
        session_data["data"].update(data)
        session_data["updated_at"] = time.time()
        
        result = await self.cache.set(session_id, session_data)
        
        if extend_ttl:
            await self.cache.expire(session_id, extend_ttl)
        
        return result
    
    async def delete_session(self, session_id: str) -> bool:
        """Удаление сессии"""
        return await self.cache.delete(session_id)
    
    async def get_user_sessions(self, user_id: int) -> List[str]:
        """Получение всех сессий пользователя"""
        all_keys = await self.cache.keys("*")
        user_sessions = []
        
        for key in all_keys:
            session_data = await self.cache.get(key)
            if session_data and session_data.get("user_id") == user_id:
                user_sessions.append(key)
        
        return user_sessions
    
    async def cleanup_expired_sessions(self) -> int:
        """Очистка истекших сессий"""
        # Redis автоматически удаляет истекшие ключи
        # Эта функция нужна для дополнительной очистки если необходимо
        return 0


# Глобальные экземпляры
redis_cache = RedisCache()
redis_pubsub = RedisPubSub()
redis_session = RedisSession()


# Utility functions
async def init_redis():
    """Инициализация Redis подключений"""
    await redis_manager.init_connections()


async def close_redis():
    """Закрытие Redis подключений"""
    await redis_manager.close_connections()


@asynccontextmanager
async def redis_lock(key: str, timeout: int = 10, blocking_timeout: int = 5):
    """Распределенная блокировка на Redis"""
    redis = redis_manager.get_connection("main")
    lock_key = f"lock:{key}"
    lock_value = f"{time.time()}"
    
    try:
        # Пытаемся получить блокировку
        acquired = await redis.set(
            lock_key,
            lock_value,
            nx=True,
            ex=timeout
        )
        
        if not acquired:
            # Ждем освобождения блокировки
            start_time = time.time()
            while time.time() - start_time < blocking_timeout:
                await asyncio.sleep(0.1)
                acquired = await redis.set(
                    lock_key,
                    lock_value,
                    nx=True,
                    ex=timeout
                )
                if acquired:
                    break
        
        if not acquired:
            raise TimeoutError(f"Could not acquire lock for key: {key}")
        
        yield
        
    finally:
        # Освобождаем блокировку только если она наша
        try:
            script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            await redis.eval(script, 1, lock_key, lock_value)
        except Exception as e:
            logger.warning(f"Failed to release lock {key}: {e}")


# Rate limiting utilities
class RedisRateLimiter:
    """Rate limiter на основе Redis с различными алгоритмами"""
    
    def __init__(self, prefix: str = "rate_limit"):
        self.redis = redis_manager.get_connection("main")
        self.prefix = prefix
    
    async def sliding_window_log(
        self,
        key: str,
        limit: int,
        window_seconds: int
    ) -> Dict[str, Any]:
        """Sliding window log алгоритм"""
        redis_key = f"{self.prefix}:swl:{key}"
        now = time.time()
        cutoff = now - window_seconds
        
        pipeline = self.redis.pipeline()
        
        # Удаляем старые записи
        pipeline.zremrangebyscore(redis_key, 0, cutoff)
        
        # Считаем текущее количество
        pipeline.zcard(redis_key)
        
        # Добавляем новую запись
        pipeline.zadd(redis_key, {str(now): now})
        
        # Устанавливаем TTL
        pipeline.expire(redis_key, window_seconds + 1)
        
        results = await pipeline.execute()
        current_count = results[1]
        
        if current_count > limit:
            # Удаляем добавленную запись
            await self.redis.zrem(redis_key, str(now))
            
            # Получаем время до сброса
            oldest = await self.redis.zrange(redis_key, 0, 0, withscores=True)
            reset_time = oldest[0][1] + window_seconds if oldest else now + window_seconds
            
            return {
                "allowed": False,
                "current": current_count,
                "limit": limit,
                "reset_time": reset_time,
                "retry_after": int(reset_time - now)
            }
        
        return {
            "allowed": True,
            "current": current_count + 1,
            "limit": limit,
            "reset_time": now + window_seconds,
            "retry_after": 0
        }
    
    async def fixed_window_counter(
        self,
        key: str,
        limit: int,
        window_seconds: int
    ) -> Dict[str, Any]:
        """Fixed window counter алгоритм"""
        redis_key = f"{self.prefix}:fwc:{key}"
        now = int(time.time())
        window_start = (now // window_seconds) * window_seconds
        window_key = f"{redis_key}:{window_start}"
        
        # Получаем текущий счетчик
        current_count = await self.redis.get(window_key)
        current_count = int(current_count) if current_count else 0
        
        if current_count >= limit:
            reset_time = window_start + window_seconds
            return {
                "allowed": False,
                "current": current_count,
                "limit": limit,
                "reset_time": reset_time,
                "retry_after": int(reset_time - now)
            }
        
        # Инкрементируем счетчик
        pipeline = self.redis.pipeline()
        pipeline.incr(window_key)
        pipeline.expire(window_key, window_seconds + 1)
        await pipeline.execute()
        
        return {
            "allowed": True,
            "current": current_count + 1,
            "limit": limit,
            "reset_time": window_start + window_seconds,
            "retry_after": 0
        }
    
    async def token_bucket(
        self,
        key: str,
        capacity: int,
        refill_rate: float,
        tokens_requested: int = 1
    ) -> Dict[str, Any]:
        """Token bucket алгоритм"""
        redis_key = f"{self.prefix}:tb:{key}"
        now = time.time()
        
        # Lua скрипт для атомарного обновления bucket
        script = """
        local key = KEYS[1]
        local capacity = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local tokens_requested = tonumber(ARGV[3])
        local now = tonumber(ARGV[4])
        
        local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
        local tokens = tonumber(bucket[1]) or capacity
        local last_refill = tonumber(bucket[2]) or now
        
        -- Добавляем токены на основе времени
        local time_passed = now - last_refill
        local new_tokens = math.min(capacity, tokens + (time_passed * refill_rate))
        
        if new_tokens >= tokens_requested then
            new_tokens = new_tokens - tokens_requested
            redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
            redis.call('EXPIRE', key, 3600)
            return {1, new_tokens, capacity}
        else
            redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
            redis.call('EXPIRE', key, 3600)
            return {0, new_tokens, capacity}
        end
        """
        
        result = await self.redis.eval(
            script,
            1,
            redis_key,
            capacity,
            refill_rate,
            tokens_requested,
            now
        )
        
        allowed = bool(result[0])
        current_tokens = result[1]
        
        return {
            "allowed": allowed,
            "tokens_remaining": current_tokens,
            "capacity": capacity,
            "retry_after": int((tokens_requested - current_tokens) / refill_rate) if not allowed else 0
        }


# Analytics utilities
class RedisAnalytics:
    """Аналитика на основе Redis"""
    
    def __init__(self, prefix: str = "analytics"):
        self.redis = redis_manager.get_connection("main")
        self.prefix = prefix
    
    async def increment_counter(
        self,
        metric: str,
        value: int = 1,
        tags: Dict[str, str] = None
    ):
        """Инкремент счетчика метрики"""
        key = f"{self.prefix}:counter:{metric}"
        
        if tags:
            tag_str = ":".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{key}:{tag_str}"
        
        await self.redis.incrby(key, value)
    
    async def record_timing(
        self,
        metric: str,
        duration_ms: float,
        tags: Dict[str, str] = None
    ):
        """Запись времени выполнения"""
        key = f"{self.prefix}:timing:{metric}"
        
        if tags:
            tag_str = ":".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{key}:{tag_str}"
        
        # Используем sorted set для хранения времени
        timestamp = time.time()
        await self.redis.zadd(key, {str(timestamp): duration_ms})
        
        # Удаляем старые записи (оставляем последние 1000)
        await self.redis.zremrangebyrank(key, 0, -1001)
    
    async def record_gauge(
        self,
        metric: str,
        value: float,
        tags: Dict[str, str] = None
    ):
        """Запись gauge метрики"""
        key = f"{self.prefix}:gauge:{metric}"
        
        if tags:
            tag_str = ":".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{key}:{tag_str}"
        
        await self.redis.set(key, value)
    
    async def get_counter_value(
        self,
        metric: str,
        tags: Dict[str, str] = None
    ) -> int:
        """Получение значения счетчика"""
        key = f"{self.prefix}:counter:{metric}"
        
        if tags:
            tag_str = ":".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{key}:{tag_str}"
        
        value = await self.redis.get(key)
        return int(value) if value else 0
    
    async def get_timing_stats(
        self,
        metric: str,
        tags: Dict[str, str] = None
    ) -> Dict[str, float]:
        """Получение статистики по времени"""
        key = f"{self.prefix}:timing:{metric}"
        
        if tags:
            tag_str = ":".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{key}:{tag_str}"
        
        # Получаем все значения времени
        timings = await self.redis.zrange(key, 0, -1, withscores=True)
        
        if not timings:
            return {"count": 0, "min": 0, "max": 0, "avg": 0, "p50": 0, "p95": 0, "p99": 0}
        
        values = [score for _, score in timings]
        values.sort()
        
        count = len(values)
        min_val = min(values)
        max_val = max(values)
        avg_val = sum(values) / count
        
        # Перцентили
        p50 = values[int(count * 0.5)] if count > 0 else 0
        p95 = values[int(count * 0.95)] if count > 0 else 0
        p99 = values[int(count * 0.99)] if count > 0 else 0
        
        return {
            "count": count,
            "min": min_val,
            "max": max_val,
            "avg": round(avg_val, 2),
            "p50": p50,
            "p95": p95,
            "p99": p99
        }
    
    async def get_top_metrics(self, pattern: str = "*", limit: int = 10) -> List[Dict[str, Any]]:
        """Получение топ метрик"""
        counter_pattern = f"{self.prefix}:counter:{pattern}"
        counter_keys = await self.redis.keys(counter_pattern)
        
        metrics = []
        for key in counter_keys:
            value = await self.redis.get(key)
            if value:
                metric_name = key.replace(f"{self.prefix}:counter:", "")
                metrics.append({
                    "metric": metric_name,
                    "value": int(value)
                })
        
        # Сортируем по значению
        metrics.sort(key=lambda x: x["value"], reverse=True)
        return metrics[:limit]


# Message Queue utilities
class RedisQueue:
    """Очередь сообщений на Redis"""
    
    def __init__(self, name: str, prefix: str = "queue"):
        self.redis = redis_manager.get_connection("main")
        self.name = name
        self.key = f"{prefix}:{name}"
    
    async def put(self, item: Any, priority: int = 0) -> bool:
        """Добавление элемента в очередь"""
        try:
            if isinstance(item, (dict, list)):
                serialized_item = json.dumps(item, ensure_ascii=False)
            else:
                serialized_item = str(item)
            
            # Используем sorted set для приоритетной очереди
            await self.redis.zadd(self.key, {serialized_item: priority})
            return True
            
        except Exception as e:
            logger.error(f"Failed to put item in queue {self.name}: {e}")
            return False
    
    async def get(self, timeout: int = 0) -> Optional[Any]:
        """Получение элемента из очереди"""
        try:
            if timeout:
                # Блокирующее получение
                result = await self.redis.bzpopmin(self.key, timeout=timeout)
                if result:
                    _, item, _ = result
                    try:
                        return json.loads(item)
                    except json.JSONDecodeError:
                        return item
            else:
                # Неблокирующее получение
                result = await self.redis.zpopmin(self.key)
                if result:
                    item, _ = result[0]
                    try:
                        return json.loads(item)
                    except json.JSONDecodeError:
                        return item
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get item from queue {self.name}: {e}")
            return None
    
    async def size(self) -> int:
        """Размер очереди"""
        try:
            return await self.redis.zcard(self.key)
        except Exception as e:
            logger.error(f"Failed to get queue {self.name} size: {e}")
            return 0
    
    async def clear(self) -> bool:
        """Очистка очереди"""
        try:
            await self.redis.delete(self.key)
            return True
        except Exception as e:
            logger.error(f"Failed to clear queue {self.name}: {e}")
            return False


# Глобальные экземпляры утилит
redis_rate_limiter = RedisRateLimiter()
redis_analytics = RedisAnalytics()


# Context managers
@asynccontextmanager
async def redis_pipeline(connection_type: str = "main"):
    """Context manager для Redis pipeline"""
    redis = redis_manager.get_connection(connection_type)
    pipeline = redis.pipeline()
    
    try:
        yield pipeline
        await pipeline.execute()
    except Exception as e:
        logger.error(f"Redis pipeline error: {e}")
        raise
    finally:
        await pipeline.reset()


@asynccontextmanager
async def redis_transaction(connection_type: str = "main"):
    """Context manager для Redis транзакции"""
    redis = redis_manager.get_connection(connection_type)
    
    async with redis.pipeline(transaction=True) as pipeline:
        try:
            yield pipeline
            await pipeline.execute()
        except Exception as e:
            logger.error(f"Redis transaction error: {e}")
            raise


# Debugging utilities
async def redis_debug_info() -> Dict[str, Any]:
    """Отладочная информация о Redis"""
    health = await redis_manager.health_check()
    
    debug_info = {
        "health": health,
        "cache_stats": {},
        "queue_stats": {},
        "memory_usage": {}
    }
    
    # Статистика кеша
    try:
        cache_keys = await redis_cache.keys("*")
        debug_info["cache_stats"] = {
            "total_keys": len(cache_keys),
            "sample_keys": cache_keys[:10]
        }
    except Exception as e:
        debug_info["cache_stats"] = {"error": str(e)}
    
    # Использование памяти
    try:
        redis = redis_manager.get_connection("main")
        if redis:
            info = await redis.info("memory")
            debug_info["memory_usage"] = {
                "used_memory": info.get("used_memory_human"),
                "used_memory_peak": info.get("used_memory_peak_human"),
                "used_memory_rss": info.get("used_memory_rss_human")
            }
    except Exception as e:
        debug_info["memory_usage"] = {"error": str(e)}
    
    return debug_info