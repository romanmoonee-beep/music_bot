"""
Инициализация всех middleware для бота
"""
from app.bot.middlewares.auth import AuthMiddleware, UserDataMiddleware
from app.bot.middlewares.throttling import ThrottlingMiddleware, AntiFloodMiddleware
from app.bot.middlewares.logging import LoggingMiddleware, PerformanceMiddleware, ErrorHandlingMiddleware
from app.bot.middlewares.subscription import SubscriptionMiddleware, DownloadLimitsMiddleware

__all__ = [
    "AuthMiddleware",
    "UserDataMiddleware", 
    "ThrottlingMiddleware",
    "AntiFloodMiddleware",
    "LoggingMiddleware",
    "PerformanceMiddleware", 
    "ErrorHandlingMiddleware",
    "SubscriptionMiddleware",
    "DownloadLimitsMiddleware"
]