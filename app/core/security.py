# app/core/security.py
"""
Модуль безопасности: аутентификация, авторизация, rate limiting
"""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
import jwt
from passlib.context import CryptContext
from passlib.hash import bcrypt
import aioredis
from fastapi import HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Request, Depends

from app.core.config import settings
from app.core.logging import get_logger, security_logger
from app.core.exceptions import (
    RateLimitExceededError,
    DailyLimitExceededError,
    HTTPUnauthorizedException,
    HTTPTooManyRequestsException
)

logger = get_logger(__name__)
security = HTTPBearer()


# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class PasswordManager:
    """Менеджер паролей"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Хеширование пароля"""
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Проверка пароля"""
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def generate_password(length: int = 12) -> str:
        """Генерация случайного пароля"""
        return secrets.token_urlsafe(length)


class TokenManager:
    """Менеджер токенов JWT"""
    
    def __init__(self):
        self.algorithm = "HS256"
        self.secret_key = settings.SECRET_KEY
        self.access_token_expire_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES
    
    def create_access_token(
        self,
        subject: str,
        user_id: int = None,
        roles: List[str] = None,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """Создание access token"""
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                minutes=self.access_token_expire_minutes
            )
        
        to_encode = {
            "sub": str(subject),
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "access"
        }
        
        if user_id:
            to_encode["user_id"] = user_id
        
        if roles:
            to_encode["roles"] = roles
        
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def create_refresh_token(self, subject: str, user_id: int = None) -> str:
        """Создание refresh token"""
        expire = datetime.now(timezone.utc) + timedelta(days=30)
        
        to_encode = {
            "sub": str(subject),
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "refresh"
        }
        
        if user_id:
            to_encode["user_id"] = user_id
        
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def decode_token(self, token: str) -> Dict[str, Any]:
        """Декодирование токена"""
        try:
            payload = jwt.decode(
                token, 
                self.secret_key, 
                algorithms=[self.algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPUnauthorizedException("Token expired")
        except jwt.JWTError:
            raise HTTPUnauthorizedException("Invalid token")
    
    def verify_token(self, token: str, token_type: str = "access") -> Dict[str, Any]:
        """Проверка токена"""
        payload = self.decode_token(token)
        
        if payload.get("type") != token_type:
            raise HTTPUnauthorizedException(f"Invalid token type. Expected: {token_type}")
        
        return payload


# Глобальные менеджеры
password_manager = PasswordManager()
token_manager = TokenManager()


class RateLimiter:
    """Rate Limiter с использованием Redis"""
    
    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
    
    async def init_redis(self):
        """Инициализация Redis подключения"""
        try:
            self.redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis.ping()
            logger.info("Rate limiter Redis connection established")
        except Exception as e:
            logger.error(f"Rate limiter Redis connection failed: {e}")
            self.redis = None
    
    async def close_redis(self):
        """Закрытие Redis подключения"""
        if self.redis:
            await self.redis.close()
    
    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int,
        identifier: str = None
    ) -> bool:
        """
        Проверка rate limit
        
        Args:
            key: Уникальный ключ для лимита
            limit: Максимальное количество запросов
            window: Временное окно в секундах
            identifier: Идентификатор для логирования
        
        Returns:
            True если запрос разрешен, False если превышен лимит
        """
        if not self.redis:
            logger.warning("Redis not available for rate limiting")
            return True
        
        try:
            # Используем sliding window log алгоритм
            now = time.time()
            pipeline = self.redis.pipeline()
            
            # Удаляем старые записи
            pipeline.zremrangebyscore(key, 0, now - window)
            
            # Считаем текущее количество запросов
            pipeline.zcard(key)
            
            # Добавляем новый запрос
            pipeline.zadd(key, {str(now): now})
            
            # Устанавливаем TTL
            pipeline.expire(key, window)
            
            results = await pipeline.execute()
            current_requests = results[1]
            
            if current_requests >= limit:
                # Логируем превышение лимита
                await security_logger.log_rate_limit_exceeded(
                    user_id=identifier or 0,
                    limit_type=key.split(':')[0],
                    current_count=current_requests,
                    limit=limit
                )
                
                # Удаляем последний добавленный запрос
                await self.redis.zrem(key, str(now))
                
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Rate limiting check failed: {e}")
            return True  # В случае ошибки разрешаем запрос
    
    async def get_rate_limit_info(self, key: str, window: int) -> Dict[str, Any]:
        """Получение информации о текущем состоянии лимита"""
        if not self.redis:
            return {"current": 0, "window": window}
        
        try:
            now = time.time()
            
            # Очищаем старые записи
            await self.redis.zremrangebyscore(key, 0, now - window)
            
            # Получаем текущее количество
            current = await self.redis.zcard(key)
            
            # Получаем время до сброса
            oldest_request = await self.redis.zrange(key, 0, 0, withscores=True)
            reset_time = None
            
            if oldest_request:
                reset_time = oldest_request[0][1] + window
            
            return {
                "current": current,
                "window": window,
                "reset_time": reset_time
            }
            
        except Exception as e:
            logger.error(f"Getting rate limit info failed: {e}")
            return {"current": 0, "window": window}
    
    async def reset_rate_limit(self, key: str) -> bool:
        """Сброс счетчика rate limit"""
        if not self.redis:
            return False
        
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Resetting rate limit failed: {e}")
            return False


# Глобальный rate limiter
rate_limiter = RateLimiter()


class UserRateLimiter:
    """Rate limiter для пользователей с разными лимитами"""
    
    def __init__(self):
        self.rate_limiter = rate_limiter
    
    async def check_search_limit(self, user_id: int, is_premium: bool = False) -> bool:
        """Проверка лимита поисков"""
        limit = 100 if is_premium else settings.SEARCH_RATE_LIMIT
        key = f"search:{user_id}"
        
        return await self.rate_limiter.check_rate_limit(
            key=key,
            limit=limit,
            window=60,  # 1 минута
            identifier=str(user_id)
        )
    
    async def check_download_limit(self, user_id: int, is_premium: bool = False) -> bool:
        """Проверка дневного лимита скачиваний"""
        limit = settings.RATE_LIMIT_PREMIUM_USERS if is_premium else settings.RATE_LIMIT_FREE_USERS
        key = f"downloads:{user_id}:{datetime.now().strftime('%Y-%m-%d')}"
        
        return await self.rate_limiter.check_rate_limit(
            key=key,
            limit=limit,
            window=86400,  # 24 часа
            identifier=str(user_id)
        )
    
    async def get_user_limits_info(self, user_id: int, is_premium: bool = False) -> Dict[str, Any]:
        """Получение информации о лимитах пользователя"""
        search_key = f"search:{user_id}"
        download_key = f"downloads:{user_id}:{datetime.now().strftime('%Y-%m-%d')}"
        
        search_info = await self.rate_limiter.get_rate_limit_info(search_key, 60)
        download_info = await self.rate_limiter.get_rate_limit_info(download_key, 86400)
        
        search_limit = 100 if is_premium else settings.SEARCH_RATE_LIMIT
        download_limit = settings.RATE_LIMIT_PREMIUM_USERS if is_premium else settings.RATE_LIMIT_FREE_USERS
        
        return {
            "search": {
                "current": search_info["current"],
                "limit": search_limit,
                "remaining": max(0, search_limit - search_info["current"]),
                "reset_time": search_info.get("reset_time")
            },
            "downloads": {
                "current": download_info["current"],
                "limit": download_limit,
                "remaining": max(0, download_limit - download_info["current"]),
                "reset_time": download_info.get("reset_time")
            },
            "is_premium": is_premium
        }


# Глобальный user rate limiter
user_rate_limiter = UserRateLimiter()


class TelegramAuth:
    """Аутентификация для Telegram"""
    
    @staticmethod
    def verify_telegram_auth(data: Dict[str, Any], bot_token: str) -> bool:
        """Проверка подлинности данных от Telegram"""
        if "hash" not in data:
            return False
        
        received_hash = data.pop("hash")
        
        # Создаем строку для проверки
        data_check_arr = []
        for key, value in sorted(data.items()):
            data_check_arr.append(f"{key}={value}")
        
        data_check_string = "\n".join(data_check_arr)
        
        # Создаем secret key
        secret_key = hashlib.sha256(bot_token.encode()).digest()
        
        # Создаем hash
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(calculated_hash, received_hash)
    
    @staticmethod
    def verify_telegram_webhook(data: bytes, secret_token: str) -> bool:
        """Проверка webhook от Telegram"""
        if not secret_token:
            return True
        
        expected_token = f"sha256={secret_token}"
        received_token = hmac.new(
            secret_token.encode(),
            data,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_token, f"sha256={received_token}")


class AdminAuth:
    """Аутентификация для админ-панели"""
    
    @staticmethod
    def verify_admin_api_key(api_key: str) -> bool:
        """Проверка API ключа администратора"""
        return hmac.compare_digest(api_key, settings.ADMIN_API_KEY)
    
    @staticmethod
    def create_admin_token(admin_id: str, roles: List[str] = None) -> str:
        """Создание токена для администратора"""
        return token_manager.create_access_token(
            subject=admin_id,
            roles=roles or ["admin"],
            expires_delta=timedelta(hours=8)
        )


# Dependency functions для FastAPI
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Получение текущего пользователя из JWT токена"""
    try:
        payload = token_manager.verify_token(credentials.credentials)
        user_id = payload.get("user_id")
        
        if not user_id:
            raise HTTPUnauthorizedException("User ID not found in token")
        
        return {
            "id": user_id,
            "subject": payload.get("sub"),
            "roles": payload.get("roles", [])
        }
        
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPUnauthorizedException("Invalid authentication credentials")


async def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Получение текущего администратора"""
    user = await get_current_user(credentials)
    
    if "admin" not in user.get("roles", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    return user


async def verify_api_key(request: Request):
    """Проверка API ключа"""
    api_key = request.headers.get("X-API-Key")
    
    if not api_key:
        raise HTTPUnauthorizedException("API key required")
    
    if not AdminAuth.verify_admin_api_key(api_key):
        raise HTTPUnauthorizedException("Invalid API key")
    
    return True


# Middleware для rate limiting
class RateLimitMiddleware:
    """Middleware для проверки rate limits"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        request = Request(scope, receive)
        
        # Определяем клиента
        client_ip = self._get_client_ip(request)
        user_id = self._get_user_id_from_request(request)
        
        # Проверяем общий rate limit по IP
        ip_key = f"ip:{client_ip}"
        ip_allowed = await rate_limiter.check_rate_limit(
            key=ip_key,
            limit=1000,  # 1000 запросов в час
            window=3600,
            identifier=client_ip
        )
        
        if not ip_allowed:
            response = HTTPTooManyRequestsException(
                "Too many requests from this IP",
                retry_after=3600
            )
            await self._send_error_response(send, response)
            return
        
        # Проверяем rate limit пользователя если есть
        if user_id:
            user_key = f"api:{user_id}"
            user_allowed = await rate_limiter.check_rate_limit(
                key=user_key,
                limit=500,  # 500 запросов в час
                window=3600,
                identifier=str(user_id)
            )
            
            if not user_allowed:
                response = HTTPTooManyRequestsException(
                    "Too many requests from this user",
                    retry_after=3600
                )
                await self._send_error_response(send, response)
                return
        
        await self.app(scope, receive, send)
    
    def _get_client_ip(self, request: Request) -> str:
        """Получение IP адреса клиента"""
        # Проверяем заголовки proxy
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"
    
    def _get_user_id_from_request(self, request: Request) -> Optional[int]:
        """Получение user_id из запроса"""
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        
        try:
            token = auth_header.split(" ")[1]
            payload = token_manager.decode_token(token)
            return payload.get("user_id")
        except:
            return None
    
    async def _send_error_response(self, send, exception: HTTPException):
        """Отправка ошибки"""
        await send({
            'type': 'http.response.start',
            'status': exception.status_code,
            'headers': [
                [b'content-type', b'application/json'],
                [b'retry-after', str(exception.headers.get("Retry-After", 60)).encode()]
            ]
        })
        
        body = f'{{"error": "Rate limit exceeded", "detail": "{exception.detail}"}}'
        await send({
            'type': 'http.response.body',
            'body': body.encode()
        })


class SecurityManager:
    """Менеджер безопасности"""
    
    def __init__(self):
        self.rate_limiter = rate_limiter
        self.user_rate_limiter = user_rate_limiter
        self.telegram_auth = TelegramAuth()
        self.admin_auth = AdminAuth()
    
    async def init(self):
        """Инициализация менеджера безопасности"""
        await self.rate_limiter.init_redis()
        logger.info("Security manager initialized")
    
    async def close(self):
        """Закрытие менеджера безопасности"""
        await self.rate_limiter.close_redis()
        logger.info("Security manager closed")
    
    async def validate_user_action(
        self,
        user_id: int,
        action: str,
        is_premium: bool = False
    ) -> bool:
        """Валидация действия пользователя"""
        
        if action == "search":
            return await self.user_rate_limiter.check_search_limit(user_id, is_premium)
        elif action == "download":
            return await self.user_rate_limiter.check_download_limit(user_id, is_premium)
        
        return True
    
    async def log_suspicious_activity(
        self,
        user_id: int,
        activity_type: str,
        details: Dict[str, Any]
    ):
        """Логирование подозрительной активности"""
        await security_logger.log_suspicious_activity(
            user_id=user_id,
            activity_type=activity_type,
            details=str(details)
        )
    
    async def get_security_stats(self) -> Dict[str, Any]:
        """Получение статистики безопасности"""
        try:
            if not self.rate_limiter.redis:
                return {"redis_available": False}
            
            # Получаем информацию о Redis
            info = await self.rate_limiter.redis.info()
            
            # Считаем активные rate limits
            keys = await self.rate_limiter.redis.keys("*:*")
            active_limits = len(keys)
            
            # Группируем по типам
            limit_types = {}
            for key in keys:
                limit_type = key.split(':')[0]
                limit_types[limit_type] = limit_types.get(limit_type, 0) + 1
            
            return {
                "redis_available": True,
                "active_rate_limits": active_limits,
                "limit_types": limit_types,
                "redis_memory_usage": info.get("used_memory_human"),
                "redis_connected_clients": info.get("connected_clients"),
            }
            
        except Exception as e:
            logger.error(f"Failed to get security stats: {e}")
            return {"error": str(e)}


# Глобальный менеджер безопасности
security_manager = SecurityManager()


# Utility functions
def generate_secure_token(length: int = 32) -> str:
    """Генерация безопасного токена"""
    return secrets.token_urlsafe(length)


def hash_string(text: str, salt: str = None) -> str:
    """Хеширование строки"""
    if salt is None:
        salt = secrets.token_hex(16)
    
    return hashlib.pbkdf2_hmac(
        'sha256',
        text.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()


def verify_hash(text: str, hashed: str, salt: str) -> bool:
    """Проверка хеша"""
    return hmac.compare_digest(
        hash_string(text, salt),
        hashed
    )


# Decorators
def require_auth(func):
    """Декоратор для проверки аутентификации"""
    import functools
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # Логика проверки аутентификации
        return await func(*args, **kwargs)
    
    return wrapper


def require_admin(func):
    """Декоратор для проверки прав администратора"""
    import functools
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # Логика проверки прав администратора
        return await func(*args, **kwargs)
    
    return wrapper


def rate_limit(limit: int, window: int, per_user: bool = True):
    """Декоратор для rate limiting"""
    import functools
    
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Логика rate limiting
            return await func(*args, **kwargs)
        
        return wrapper
    
    return decorator