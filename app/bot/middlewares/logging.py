"""
Middleware для логирования активности бота
"""
import time
from typing import Any, Awaitable, Callable, Dict
from datetime import datetime, timezone

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, InlineQuery, Update

from app.core.logging import get_logger, bot_logger
from app.services.analytics_service import analytics_service


class LoggingMiddleware(BaseMiddleware):
    """Middleware для детального логирования"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Логирование входящих событий и ответов"""
        
        start_time = time.time()
        user = data.get("user")
        tg_user = data.get("tg_user")
        
        # Информация о событии
        event_info = self._extract_event_info(event)
        
        # Логируем входящее событие
        if user and tg_user:
            self.logger.info(
                "Bot event received",
                user_id=user.telegram_id,
                username=tg_user.username,
                event_type=event_info["type"],
                content=event_info["content"],
                chat_type=event_info.get("chat_type"),
                is_premium=data.get("is_premium", False)
            )
        
        try:
            # Выполняем handler
            result = await handler(event, data)
            
            # Время обработки
            processing_time = time.time() - start_time
            
            # Логируем успешную обработку
            self.logger.info(
                "Bot event processed",
                user_id=user.telegram_id if user else None,
                event_type=event_info["type"],
                processing_time_ms=round(processing_time * 1000, 2),
                status="success"
            )
            
            # Отправляем аналитику
            if user:
                await self._send_analytics(user.id, event_info, processing_time)
            
            return result
            
        except Exception as e:
            processing_time = time.time() - start_time
            
            # Логируем ошибку
            self.logger.error(
                "Bot event processing failed",
                user_id=user.telegram_id if user else None,
                event_type=event_info["type"],
                processing_time_ms=round(processing_time * 1000, 2),
                error=str(e),
                error_type=type(e).__name__,
                status="error"
            )
            
            raise
    
    def _extract_event_info(self, event: TelegramObject) -> Dict[str, Any]:
        """Извлечение информации о событии"""
        
        if isinstance(event, Message):
            return {
                "type": "message",
                "content": event.text[:100] if event.text else f"[{event.content_type}]",
                "chat_type": event.chat.type if event.chat else None,
                "chat_id": event.chat.id if event.chat else None,
                "message_id": event.message_id,
                "has_media": bool(event.photo or event.document or event.audio or event.video)
            }
        
        elif isinstance(event, CallbackQuery):
            return {
                "type": "callback_query",
                "content": event.data[:100] if event.data else None,
                "chat_type": event.message.chat.type if event.message and event.message.chat else None,
                "chat_id": event.message.chat.id if event.message and event.message.chat else None,
                "message_id": event.message.message_id if event.message else None
            }
        
        elif isinstance(event, InlineQuery):
            return {
                "type": "inline_query", 
                "content": event.query[:100] if event.query else "",
                "offset": event.offset,
                "chat_type": "inline"
            }
        
        elif isinstance(event, Update):
            if event.message:
                return self._extract_event_info(event.message)
            elif event.callback_query:
                return self._extract_event_info(event.callback_query)
            elif event.inline_query:
                return self._extract_event_info(event.inline_query)
        
        return {
            "type": "unknown",
            "content": str(event)[:100],
            "chat_type": "unknown"
        }
    
    async def _send_analytics(self, user_id: int, event_info: Dict[str, Any], processing_time: float) -> None:
        """Отправка данных в аналитику"""
        try:
            from app.models.analytics import EventType
            
            # Определяем тип события для аналитики
            event_type_mapping = {
                "message": EventType.MESSAGE_SENT,
                "callback_query": EventType.BUTTON_CLICKED,
                "inline_query": EventType.INLINE_QUERY
            }
            
            event_type = event_type_mapping.get(event_info["type"], EventType.OTHER)
            
            # Отправляем в аналитику
            await analytics_service.track_user_event(
                user_id=user_id,
                event_type=event_type,
                event_data={
                    "content": event_info.get("content"),
                    "chat_type": event_info.get("chat_type"),
                    "processing_time_ms": round(processing_time * 1000, 2),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to send analytics: {e}")


class PerformanceMiddleware(BaseMiddleware):
    """Middleware для мониторинга производительности"""
    
    def __init__(self, slow_threshold: float = 1.0):
        self.slow_threshold = slow_threshold  # секунды
        self.logger = get_logger(self.__class__.__name__)
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Мониторинг производительности handlers"""
        
        start_time = time.time()
        handler_name = handler.__name__ if hasattr(handler, '__name__') else str(handler)
        
        try:
            result = await handler(event, data)
            processing_time = time.time() - start_time
            
            # Логируем медленные запросы
            if processing_time > self.slow_threshold:
                user = data.get("user")
                self.logger.warning(
                    "Slow handler execution",
                    handler=handler_name,
                    processing_time_ms=round(processing_time * 1000, 2),
                    user_id=user.telegram_id if user else None,
                    threshold_ms=round(self.slow_threshold * 1000, 2)
                )
            
            return result
            
        except Exception as e:
            processing_time = time.time() - start_time
            
            self.logger.error(
                "Handler execution failed",
                handler=handler_name,
                processing_time_ms=round(processing_time * 1000, 2),
                error=str(e),
                error_type=type(e).__name__
            )
            
            raise


class ErrorHandlingMiddleware(BaseMiddleware):
    """Middleware для обработки ошибок"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Глобальная обработка ошибок"""
        
        try:
            return await handler(event, data)
            
        except Exception as e:
            user = data.get("user")
            
            # Логируем ошибку
            self.logger.error(
                "Unhandled error in bot handler",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user.telegram_id if user else None,
                handler=handler.__name__ if hasattr(handler, '__name__') else str(handler)
            )
            
            # Отправляем пользователю сообщение об ошибке
            await self._send_error_message(event)
            
            # Не re-raise ошибку, чтобы бот продолжал работать
    
    async def _send_error_message(self, event: TelegramObject) -> None:
        """Отправка сообщения об ошибке пользователю"""
        error_message = (
            "❌ Произошла ошибка при обработке вашего запроса.\n\n"
            "Попробуйте позже или обратитесь в поддержку: @support"
        )
        
        try:
            if isinstance(event, Message):
                await event.answer(error_message)
            elif isinstance(event, CallbackQuery):
                await event.answer(error_message, show_alert=True)
        except:
            # Если не удалось отправить сообщение об ошибке, просто игнорируем
            pass