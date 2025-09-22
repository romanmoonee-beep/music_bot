# app/core/exceptions.py
"""
Кастомные исключения для приложения
"""
from typing import Any, Dict, Optional
from fastapi import HTTPException, status


class BaseAppException(Exception):
    """Базовое исключение для приложения"""
    
    def __init__(
        self,
        message: str,
        code: str = None,
        details: Dict[str, Any] = None
    ):
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}
        super().__init__(self.message)
    
    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для API ответов"""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details
        }


# Database Exceptions
class DatabaseError(BaseAppException):
    """Ошибка базы данных"""
    pass


class RecordNotFoundError(DatabaseError):
    """Запись не найдена"""
    
    def __init__(self, entity: str, identifier: Any):
        super().__init__(
            message=f"{entity} not found",
            code="RECORD_NOT_FOUND",
            details={"entity": entity, "identifier": str(identifier)}
        )


class RecordAlreadyExistsError(DatabaseError):
    """Запись уже существует"""
    
    def __init__(self, entity: str, field: str, value: Any):
        super().__init__(
            message=f"{entity} with {field}={value} already exists",
            code="RECORD_ALREADY_EXISTS",
            details={"entity": entity, "field": field, "value": str(value)}
        )


class DatabaseConnectionError(DatabaseError):
    """Ошибка подключения к БД"""
    
    def __init__(self, details: str = None):
        super().__init__(
            message="Database connection failed",
            code="DATABASE_CONNECTION_ERROR",
            details={"details": details} if details else {}
        )


# User Exceptions
class UserError(BaseAppException):
    """Ошибки пользователя"""
    pass


class UserNotFoundError(UserError):
    """Пользователь не найден"""
    
    def __init__(self, telegram_id: int):
        super().__init__(
            message=f"User with telegram_id={telegram_id} not found",
            code="USER_NOT_FOUND",
            details={"telegram_id": telegram_id}
        )


class UserBannedError(UserError):
    """Пользователь заблокирован"""
    
    def __init__(self, telegram_id: int, reason: str = None):
        super().__init__(
            message=f"User {telegram_id} is banned",
            code="USER_BANNED",
            details={"telegram_id": telegram_id, "reason": reason}
        )


class UserInactiveError(UserError):
    """Пользователь неактивен"""
    
    def __init__(self, telegram_id: int):
        super().__init__(
            message=f"User {telegram_id} is inactive",
            code="USER_INACTIVE",
            details={"telegram_id": telegram_id}
        )


# Rate Limiting Exceptions
class RateLimitError(BaseAppException):
    """Превышение лимитов"""
    pass


class DailyLimitExceededError(RateLimitError):
    """Превышен дневной лимит"""
    
    def __init__(self, user_id: int, limit_type: str, current: int, maximum: int):
        super().__init__(
            message=f"Daily {limit_type} limit exceeded: {current}/{maximum}",
            code="DAILY_LIMIT_EXCEEDED",
            details={
                "user_id": user_id,
                "limit_type": limit_type,
                "current": current,
                "maximum": maximum
            }
        )


class RateLimitExceededError(RateLimitError):
    """Превышен лимит запросов"""
    
    def __init__(self, user_id: int, limit_type: str, retry_after: int):
        super().__init__(
            message=f"Rate limit exceeded for {limit_type}. Retry after {retry_after} seconds",
            code="RATE_LIMIT_EXCEEDED",
            details={
                "user_id": user_id,
                "limit_type": limit_type,
                "retry_after": retry_after
            }
        )


# Music Service Exceptions
class MusicServiceError(BaseAppException):
    """Ошибки музыкальных сервисов"""
    pass


class TrackNotFoundError(MusicServiceError):
    """Трек не найден"""
    
    def __init__(self, query: str, source: str = None):
        super().__init__(
            message=f"Track not found: {query}",
            code="TRACK_NOT_FOUND",
            details={"query": query, "source": source}
        )


class DownloadError(MusicServiceError):
    """Ошибка скачивания"""
    
    def __init__(self, track_id: str, source: str, reason: str = None):
        super().__init__(
            message=f"Download failed for track {track_id}",
            code="DOWNLOAD_ERROR",
            details={
                "track_id": track_id,
                "source": source,
                "reason": reason
            }
        )


class ServiceUnavailableError(MusicServiceError):
    """Сервис недоступен"""
    
    def __init__(self, service_name: str, reason: str = None):
        super().__init__(
            message=f"Service {service_name} is unavailable",
            code="SERVICE_UNAVAILABLE",
            details={"service": service_name, "reason": reason}
        )


class SearchError(MusicServiceError):
    """Ошибка поиска"""
    
    def __init__(self, query: str, reason: str = None):
        super().__init__(
            message=f"Search failed for query: {query}",
            code="SEARCH_ERROR",
            details={"query": query, "reason": reason}
        )


# Payment Exceptions
class PaymentError(BaseAppException):
    """Ошибки платежей"""
    pass


class PaymentNotFoundError(PaymentError):
    """Платеж не найден"""
    
    def __init__(self, payment_id: str):
        super().__init__(
            message=f"Payment {payment_id} not found",
            code="PAYMENT_NOT_FOUND",
            details={"payment_id": payment_id}
        )


class PaymentFailedError(PaymentError):
    """Платеж не удался"""
    
    def __init__(self, payment_id: str, reason: str = None):
        super().__init__(
            message=f"Payment {payment_id} failed",
            code="PAYMENT_FAILED",
            details={"payment_id": payment_id, "reason": reason}
        )


class SubscriptionError(PaymentError):
    """Ошибка подписки"""
    
    def __init__(self, user_id: int, message: str):
        super().__init__(
            message=f"Subscription error for user {user_id}: {message}",
            code="SUBSCRIPTION_ERROR",
            details={"user_id": user_id}
        )


class SubscriptionNotFoundError(SubscriptionError):
    """Подписка не найдена"""
    
    def __init__(self, user_id: int):
        super().__init__(
            user_id=user_id,
            message="Active subscription not found"
        )


# Playlist Exceptions
class PlaylistError(BaseAppException):
    """Ошибки плейлистов"""
    pass


class PlaylistNotFoundError(PlaylistError):
    """Плейлист не найден"""
    
    def __init__(self, playlist_id: int):
        super().__init__(
            message=f"Playlist {playlist_id} not found",
            code="PLAYLIST_NOT_FOUND",
            details={"playlist_id": playlist_id}
        )


class PlaylistAccessDeniedError(PlaylistError):
    """Нет доступа к плейлисту"""
    
    def __init__(self, playlist_id: int, user_id: int):
        super().__init__(
            message=f"Access denied to playlist {playlist_id}",
            code="PLAYLIST_ACCESS_DENIED",
            details={"playlist_id": playlist_id, "user_id": user_id}
        )


# Cache Exceptions
class CacheError(BaseAppException):
    """Ошибки кеширования"""
    pass


class CacheConnectionError(CacheError):
    """Ошибка подключения к кешу"""
    
    def __init__(self, details: str = None):
        super().__init__(
            message="Cache connection failed",
            code="CACHE_CONNECTION_ERROR",
            details={"details": details} if details else {}
        )


# File Storage Exceptions
class FileStorageError(BaseAppException):
    """Ошибки файлового хранилища"""
    pass


class FileNotFoundError(FileStorageError):
    """Файл не найден"""
    
    def __init__(self, file_path: str):
        super().__init__(
            message=f"File not found: {file_path}",
            code="FILE_NOT_FOUND",
            details={"file_path": file_path}
        )


class FileUploadError(FileStorageError):
    """Ошибка загрузки файла"""
    
    def __init__(self, file_name: str, reason: str = None):
        super().__init__(
            message=f"File upload failed: {file_name}",
            code="FILE_UPLOAD_ERROR",
            details={"file_name": file_name, "reason": reason}
        )


# Validation Exceptions
class ValidationError(BaseAppException):
    """Ошибка валидации"""
    
    def __init__(self, field: str, value: Any, reason: str):
        super().__init__(
            message=f"Validation failed for {field}: {reason}",
            code="VALIDATION_ERROR",
            details={"field": field, "value": str(value), "reason": reason}
        )


class InvalidInputError(ValidationError):
    """Некорректный ввод"""
    
    def __init__(self, field: str, value: Any):
        super().__init__(
            field=field,
            value=value,
            reason="Invalid input format"
        )


# Configuration Exceptions
class ConfigurationError(BaseAppException):
    """Ошибка конфигурации"""
    
    def __init__(self, setting: str, reason: str = None):
        super().__init__(
            message=f"Configuration error: {setting}",
            code="CONFIGURATION_ERROR",
            details={"setting": setting, "reason": reason}
        )


# External Service Exceptions
class ExternalServiceError(BaseAppException):
    """Ошибка внешнего сервиса"""
    
    def __init__(self, service: str, status_code: int = None, reason: str = None):
        super().__init__(
            message=f"External service error: {service}",
            code="EXTERNAL_SERVICE_ERROR",
            details={
                "service": service,
                "status_code": status_code,
                "reason": reason
            }
        )


# HTTP Exceptions для FastAPI
class HTTPNotFoundException(HTTPException):
    """HTTP 404 исключение"""
    
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail
        )


class HTTPBadRequestException(HTTPException):
    """HTTP 400 исключение"""
    
    def __init__(self, detail: str = "Bad request"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )


class HTTPUnauthorizedException(HTTPException):
    """HTTP 401 исключение"""
    
    def __init__(self, detail: str = "Unauthorized"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail
        )


class HTTPForbiddenException(HTTPException):
    """HTTP 403 исключение"""
    
    def __init__(self, detail: str = "Forbidden"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail
        )


class HTTPTooManyRequestsException(HTTPException):
    """HTTP 429 исключение"""
    
    def __init__(self, detail: str = "Too many requests", retry_after: int = 60):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry_after)}
        )


class HTTPInternalServerErrorException(HTTPException):
    """HTTP 500 исключение"""
    
    def __init__(self, detail: str = "Internal server error"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail
        )


# Utility functions
def handle_database_error(error: Exception) -> BaseAppException:
    """Обработка ошибок базы данных"""
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError
    from asyncpg.exceptions import UniqueViolationError, PostgresError
    
    if isinstance(error, IntegrityError):
        return RecordAlreadyExistsError("Record", "constraint", "unknown")
    elif isinstance(error, UniqueViolationError):
        return RecordAlreadyExistsError("Record", "unique_field", "unknown")
    elif isinstance(error, (SQLAlchemyError, PostgresError)):
        return DatabaseConnectionError(str(error))
    else:
        return DatabaseError(str(error))


def exception_to_http(exception: BaseAppException) -> HTTPException:
    """Конвертация кастомного исключения в HTTP исключение"""
    
    error_mapping = {
        "RECORD_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "Resource not found"),
        "USER_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "User not found"),
        "USER_BANNED": (status.HTTP_403_FORBIDDEN, "User is banned"),
        "USER_INACTIVE": (status.HTTP_403_FORBIDDEN, "User is inactive"),
        "DAILY_LIMIT_EXCEEDED": (status.HTTP_429_TOO_MANY_REQUESTS, "Daily limit exceeded"),
        "RATE_LIMIT_EXCEEDED": (status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded"),
        "TRACK_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "Track not found"),
        "DOWNLOAD_ERROR": (status.HTTP_500_INTERNAL_SERVER_ERROR, "Download failed"),
        "SERVICE_UNAVAILABLE": (status.HTTP_503_SERVICE_UNAVAILABLE, "Service unavailable"),
        "PAYMENT_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "Payment not found"),
        "PAYMENT_FAILED": (status.HTTP_400_BAD_REQUEST, "Payment failed"),
        "PLAYLIST_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "Playlist not found"),
        "PLAYLIST_ACCESS_DENIED": (status.HTTP_403_FORBIDDEN, "Access denied to playlist"),
        "VALIDATION_ERROR": (status.HTTP_422_UNPROCESSABLE_ENTITY, "Validation error"),
        "CONFIGURATION_ERROR": (status.HTTP_500_INTERNAL_SERVER_ERROR, "Configuration error"),
    }
    
    status_code, default_detail = error_mapping.get(
        exception.code,
        (status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error")
    )
    
    detail = exception.to_dict() if hasattr(exception, 'to_dict') else str(exception)
    
    headers = {}
    if exception.code == "RATE_LIMIT_EXCEEDED" and "retry_after" in exception.details:
        headers["Retry-After"] = str(exception.details["retry_after"])
    
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers=headers if headers else None
    )