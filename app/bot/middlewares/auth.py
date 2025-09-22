"""
Middleware для аутентификации и работы с пользователями
"""
from typing import Any, Awaitable, Callable, Dict, Optional
from datetime import datetime, timezone

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser, Update, Message, CallbackQuery

from app.core.logging import get_logger, bot_logger
from app.services.user_service import user_service
from app.models.user import User


class AuthMiddleware(BaseMiddleware):
    """Middleware для аутентификации пользователей"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Основной метод middleware"""
        
        # Получаем пользователя из события
        tg_user = self._extract_user(event)
        if not tg_user:
            return await handler(event, data)
        
        # Проверяем, не бот ли это
        if tg_user.is_bot:
            self.logger.warning(f"Bot user attempted to use service: {tg_user.id}")
            return
        
        try:
            # Получаем или создаем пользователя в БД
            user = await user_service.get_or_create_user(
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                last_name=tg_user.last_name,
                language_code=tg_user.language_code
            )
            
            # Проверяем, не заблокирован ли пользователь
            if not user.is_active:
                await self._handle_banned_user(event, user)
                return
            
            # Обновляем время последней активности
            await user_service.update_last_seen(tg_user.id)
            
            # Проверяем лимиты пользователя
            limits = await user_service.check_daily_limits(tg_user.id)
            
            # Добавляем данные в контекст
            data["user"] = user
            data["tg_user"] = tg_user
            data["user_limits"] = limits
            data["is_premium"] = await user_service.is_premium_user(tg_user.id)
            
            # Логируем активность
            await bot_logger.log_update(
                update_type=self._get_update_type(event),
                user_id=tg_user.id,
                chat_id=getattr(event, 'chat', {}).get('id') if hasattr(event, 'chat') else None,
                command=self._extract_command(event)
            )
            
        except Exception as e:
            self.logger.error(f"Auth middleware error for user {tg_user.id}: {e}")
            # Продолжаем выполнение даже при ошибке аутентификации
        
        return await handler(event, data)
    
    def _extract_user(self, event: TelegramObject) -> Optional[TgUser]:
        """Извлечение пользователя из события"""
        if hasattr(event, 'from_user'):
            return event.from_user
        elif hasattr(event, 'message') and hasattr(event.message, 'from_user'):
            return event.message.from_user
        elif isinstance(event, Update):
            if event.message and event.message.from_user:
                return event.message.from_user
            elif event.callback_query and event.callback_query.from_user:
                return event.callback_query.from_user
            elif event.inline_query and event.inline_query.from_user:
                return event.inline_query.from_user
        return None
    
    def _get_update_type(self, event: TelegramObject) -> str:
        """Определение типа обновления"""
        if isinstance(event, Message):
            return "message"
        elif isinstance(event, CallbackQuery):
            return "callback_query"
        elif hasattr(event, 'inline_query'):
            return "inline_query"
        elif isinstance(event, Update):
            if event.message:
                return "message"
            elif event.callback_query:
                return "callback_query"
            elif event.inline_query:
                return "inline_query"
            elif event.chosen_inline_result:
                return "chosen_inline_result"
        return "unknown"
    
    def _extract_command(self, event: TelegramObject) -> Optional[str]:
        """Извлечение команды из события"""
        if isinstance(event, Message) and event.text:
            if event.text.startswith('/'):
                return event.text.split()[0]
        elif isinstance(event, CallbackQuery) and event.data:
            return event.data.split(':')[0] if ':' in event.data else event.data
        return None
    
    async def _handle_banned_user(self, event: TelegramObject, user: User) -> None:
        """Обработка заблокированного пользователя"""
        ban_message = (
            f"🚫 Ваш аккаунт заблокирован\n\n"
            f"Причина: {user.ban_reason or 'Не указана'}\n"
            f"Дата блокировки: {user.banned_at.strftime('%d.%m.%Y %H:%M') if user.banned_at else 'Не указана'}\n\n"
            f"Для разблокировки обратитесь в поддержку: @support"
        )
        
        if isinstance(event, Message):
            try:
                await event.answer(ban_message)
            except:
                pass
        elif isinstance(event, CallbackQuery):
            try:
                await event.answer(ban_message, show_alert=True)
            except:
                pass


class UserDataMiddleware(BaseMiddleware):
    """Middleware для дополнительных данных пользователя"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Добавление дополнительных данных пользователя"""
        
        user = data.get("user")
        if not user:
            return await handler(event, data)
        
        try:
            # Получаем подписку пользователя
            subscription = await user_service.get_user_subscription(user.telegram_id)
            data["subscription"] = subscription
            
            # Получаем статистику пользователя (кешированно)
            # stats = await user_service.get_user_stats(user.telegram_id)
            # data["user_stats"] = stats
            
        except Exception as e:
            logger = get_logger(self.__class__.__name__)
            logger.error(f"UserData middleware error: {e}")
        
        return await handler(event, data)