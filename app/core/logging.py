"""
Настройка структурированного логирования с помощью structlog
"""
import logging
import logging.config
import sys
from pathlib import Path
from typing import Any, Dict

import structlog
from structlog.types import FilteringBoundLogger

from app.core.config import settings


def setup_logging() -> None:
    """Настройка системы логирования"""
    
    # Создание директории для логов
    settings.LOGS_DIR.mkdir(exist_ok=True)
    
    # Конфигурация structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.set_exc_info,
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            _add_request_id,
            _add_user_id,
            structlog.processors.JSONRenderer() if settings.LOG_FORMAT == "json" 
            else structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL.upper())
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Настройка стандартного логирования Python
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
            },
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": settings.LOG_LEVEL,
                "formatter": "json" if settings.LOG_FORMAT == "json" else "standard",
                "stream": sys.stdout,
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": settings.LOG_LEVEL,
                "formatter": "json" if settings.LOG_FORMAT == "json" else "standard",
                "filename": settings.LOGS_DIR / "app.log",
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5,
                "encoding": "utf8",
            },
            "error_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "ERROR",
                "formatter": "json" if settings.LOG_FORMAT == "json" else "standard",
                "filename": settings.LOGS_DIR / "error.log",
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5,
                "encoding": "utf8",
            },
        },
        "loggers": {
            "": {  # root logger
                "handlers": ["console", "file", "error_file"],
                "level": settings.LOG_LEVEL,
                "propagate": False,
            },
            "aiogram": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            "sqlalchemy": {
                "handlers": ["console", "file"],
                "level": "WARNING",
                "propagate": False,
            },
            "aiohttp": {
                "handlers": ["console", "file"],
                "level": "WARNING",
                "propagate": False,
            },
        },
    }
    
    logging.config.dictConfig(logging_config)


def _add_request_id(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Добавление request_id в лог"""
    from contextvars import ContextVar
    
    request_id_var: ContextVar[str] = ContextVar('request_id', default='')
    request_id = request_id_var.get()
    
    if request_id:
        event_dict["request_id"] = request_id
    
    return event_dict


def _add_user_id(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Добавление user_id в лог"""
    from contextvars import ContextVar
    
    user_id_var: ContextVar[int] = ContextVar('user_id', default=0)
    user_id = user_id_var.get()
    
    if user_id:
        event_dict["user_id"] = user_id
    
    return event_dict


def get_logger(name: str) -> FilteringBoundLogger:
    """Получение логгера с именем"""
    return structlog.get_logger(name)


class LoggerMixin:
    """Mixin класс для добавления логгера в любой класс"""
    
    @property
    def logger(self) -> FilteringBoundLogger:
        """Логгер для текущего класса"""
        return get_logger(self.__class__.__name__)


class RequestLogger:
    """Логгер для HTTP запросов"""
    
    def __init__(self):
        self.logger = get_logger("request")
    
    async def log_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration: float,
        user_id: int = None,
        request_id: str = None,
        **kwargs
    ):
        """Логирование HTTP запроса"""
        self.logger.info(
            "HTTP request completed",
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=round(duration * 1000, 2),
            user_id=user_id,
            request_id=request_id,
            **kwargs
        )


class BotLogger:
    """Логгер для Telegram бота"""
    
    def __init__(self):
        self.logger = get_logger("bot")
    
    async def log_update(
        self,
        update_type: str,
        user_id: int,
        chat_id: int = None,
        command: str = None,
        **kwargs
    ):
        """Логирование обновления от Telegram"""
        self.logger.info(
            "Bot update received",
            update_type=update_type,
            user_id=user_id,
            chat_id=chat_id,
            command=command,
            **kwargs
        )
    
    async def log_search(
        self,
        user_id: int,
        query: str,
        results_count: int,
        duration: float,
        source: str = None,
        **kwargs
    ):
        """Логирование поиска музыки"""
        self.logger.info(
            "Music search performed",
            user_id=user_id,
            query=query,
            results_count=results_count,
            duration_ms=round(duration * 1000, 2),
            source=source,
            **kwargs
        )
    
    async def log_download(
        self,
        user_id: int,
        track_id: str,
        track_title: str,
        source: str,
        duration: float,
        file_size: int = None,
        **kwargs
    ):
        """Логирование скачивания трека"""
        self.logger.info(
            "Track downloaded",
            user_id=user_id,
            track_id=track_id,
            track_title=track_title,
            source=source,
            duration_ms=round(duration * 1000, 2),
            file_size_mb=round(file_size / 1024 / 1024, 2) if file_size else None,
            **kwargs
        )


class DatabaseLogger:
    """Логгер для операций с базой данных"""
    
    def __init__(self):
        self.logger = get_logger("database")
    
    async def log_query(
        self,
        query_type: str,
        table: str,
        duration: float,
        rows_affected: int = None,
        **kwargs
    ):
        """Логирование запроса к БД"""
        self.logger.debug(
            "Database query executed",
            query_type=query_type,
            table=table,
            duration_ms=round(duration * 1000, 2),
            rows_affected=rows_affected,
            **kwargs
        )


class SecurityLogger:
    """Логгер для событий безопасности"""
    
    def __init__(self):
        self.logger = get_logger("security")
    
    async def log_rate_limit_exceeded(
        self,
        user_id: int,
        limit_type: str,
        current_count: int,
        limit: int,
        **kwargs
    ):
        """Логирование превышения лимитов"""
        self.logger.warning(
            "Rate limit exceeded",
            user_id=user_id,
            limit_type=limit_type,
            current_count=current_count,
            limit=limit,
            **kwargs
        )
    
    async def log_suspicious_activity(
        self,
        user_id: int,
        activity_type: str,
        details: str,
        **kwargs
    ):
        """Логирование подозрительной активности"""
        self.logger.warning(
            "Suspicious activity detected",
            user_id=user_id,
            activity_type=activity_type,
            details=details,
            **kwargs
        )
    
    async def log_payment_event(
        self,
        user_id: int,
        event_type: str,
        amount: float,
        currency: str,
        transaction_id: str = None,
        **kwargs
    ):
        """Логирование платежных событий"""
        self.logger.info(
            "Payment event",
            user_id=user_id,
            event_type=event_type,
            amount=amount,
            currency=currency,
            transaction_id=transaction_id,
            **kwargs
        )


# Глобальные логгеры
request_logger = RequestLogger()
bot_logger = BotLogger()
db_logger = DatabaseLogger()
security_logger = SecurityLogger()


# Декораторы для автоматического логирования
def log_function_call(logger_instance=None):
    """Декоратор для логирования вызовов функций"""
    import functools
    import time
    
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            logger = logger_instance or get_logger(func.__module__)
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                
                logger.debug(
                    f"Function {func.__name__} completed",
                    function=func.__name__,
                    duration_ms=round(duration * 1000, 2),
                    args_count=len(args),
                    kwargs_count=len(kwargs)
                )
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                
                logger.error(
                    f"Function {func.__name__} failed",
                    function=func.__name__,
                    duration_ms=round(duration * 1000, 2),
                    error=str(e),
                    error_type=type(e).__name__
                )
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            logger = logger_instance or get_logger(func.__module__)
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                logger.debug(
                    f"Function {func.__name__} completed",
                    function=func.__name__,
                    duration_ms=round(duration * 1000, 2),
                    args_count=len(args),
                    kwargs_count=len(kwargs)
                )
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                
                logger.error(
                    f"Function {func.__name__} failed",
                    function=func.__name__,
                    duration_ms=round(duration * 1000, 2),
                    error=str(e),
                    error_type=type(e).__name__
                )
                raise
        
        # Определяем, асинхронная ли функция
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# Инициализация логирования при импорте модуля
setup_logging()