"""
Middleware для проверки подписки и Premium функций
"""
from typing import Any, Awaitable, Callable, Dict, Set
from datetime import datetime, timezone

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from aiogram.filters import Command

from app.core.logging import get_logger
from app.services.user_service import user_service


class SubscriptionMiddleware(BaseMiddleware):
    """Middleware для проверки Premium подписки"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        
        # Команды и действия, требующие Premium подписку
        self.premium_commands: Set[str] = {
            "/premium_search",
            "/high_quality", 
            "/unlimited_downloads",
            "/export_playlist",
            "/advanced_stats"
        }
        
        # Callback данные, требующие Premium
        self.premium_callbacks: Set[str] = {
            "download_320kbps",
            "export_playlist",
            "advanced_search",
            "batch_download",
            "smart_recommendations"
        }
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Проверка доступа к Premium функциям"""
        
        # Проверяем, нужна ли Premium подписка для этого действия
        requires_premium = self._requires_premium(event)
        
        if not requires_premium:
            return await handler(event, data)
        
        # Получаем пользователя
        user = data.get("user")
        is_premium = data.get("is_premium", False)
        
        if not user:
            return await handler(event, data)
        
        # Проверяем Premium статус
        if not is_premium:
            await self._handle_premium_required(event, user.telegram_id)
            return
        
        # Проверяем срок подписки
        subscription = data.get("subscription")
        if subscription and subscription.expires_at <= datetime.now(timezone.utc):
            await self._handle_subscription_expired(event, user.telegram_id)
            return
        
        return await handler(event, data)
    
    def _requires_premium(self, event: TelegramObject) -> bool:
        """Проверка, требует ли действие Premium подписку"""
        
        if isinstance(event, Message):
            if event.text:
                # Проверяем команды
                command = event.text.split()[0] if event.text.startswith('/') else None
                if command in self.premium_commands:
                    return True
        
        elif isinstance(event, CallbackQuery):
            if event.data:
                # Проверяем callback данные
                callback_action = event.data.split(':')[0] if ':' in event.data else event.data
                if callback_action in self.premium_callbacks:
                    return True
        
        return False
    
    async def _handle_premium_required(self, event: TelegramObject, user_id: int) -> None:
        """Обработка запроса Premium функции без подписки"""
        
        premium_message = (
            "💎 **Premium функция**\n\n"
            "Эта функция доступна только для Premium подписчиков.\n\n"
            "**Premium преимущества:**\n"
            "• Безлимитные скачивания\n"
            "• Высокое качество (320kbps)\n"
            "• Приоритетный поиск\n"
            "• Расширенная статистика\n"
            "• Без рекламы\n"
            "• Экспорт плейлистов\n\n"
            "💳 **Цены:**\n"
            "• 1 месяц - ⭐ 150 Stars\n"
            "• 3 месяца - ⭐ 400 Stars (-12%)\n"
            "• 1 год - ⭐ 1400 Stars (-23%)"
        )
        
        from app.bot.keyboards.inline import get_premium_keyboard
        
        try:
            if isinstance(event, Message):
                await event.answer(
                    premium_message,
                    reply_markup=get_premium_keyboard(),
                    parse_mode="Markdown"
                )
            elif isinstance(event, CallbackQuery):
                await event.message.edit_text(
                    premium_message,
                    reply_markup=get_premium_keyboard(),
                    parse_mode="Markdown"
                )
        except Exception as e:
            self.logger.error(f"Failed to send premium required message: {e}")
    
    async def _handle_subscription_expired(self, event: TelegramObject, user_id: int) -> None:
        """Обработка истекшей подписки"""
        
        expired_message = (
            "⏰ **Подписка истекла**\n\n"
            "Ваша Premium подписка закончилась.\n"
            "Продлите подписку, чтобы продолжить пользоваться Premium функциями.\n\n"
            "💳 **Продлить подписку:**"
        )
        
        from app.bot.keyboards.inline import get_renew_subscription_keyboard
        
        try:
            if isinstance(event, Message):
                await event.answer(
                    expired_message,
                    reply_markup=get_renew_subscription_keyboard(),
                    parse_mode="Markdown"
                )
            elif isinstance(event, CallbackQuery):
                await event.message.edit_text(
                    expired_message,
                    reply_markup=get_renew_subscription_keyboard(),
                    parse_mode="Markdown"
                )
        except Exception as e:
            self.logger.error(f"Failed to send subscription expired message: {e}")


class DownloadLimitsMiddleware(BaseMiddleware):
    """Middleware для проверки лимитов скачивания"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        
        # Действия, которые считаются скачиванием
        self.download_actions: Set[str] = {
            "download",
            "get_track",
            "download_track"
        }
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Проверка лимитов скачивания"""
        
        # Проверяем, является ли это действие скачиванием
        is_download = self._is_download_action(event)
        
        if not is_download:
            return await handler(event, data)
        
        user = data.get("user")
        user_limits = data.get("user_limits")
        
        if not user or not user_limits:
            return await handler(event, data)
        
        # Проверяем лимиты
        if not user_limits.get("can_download", False):
            await self._handle_download_limit_exceeded(event, user_limits)
            return
        
        return await handler(event, data)
    
    def _is_download_action(self, event: TelegramObject) -> bool:
        """Проверка, является ли действие скачиванием"""
        
        if isinstance(event, CallbackQuery) and event.data:
            action = event.data.split(':')[0] if ':' in event.data else event.data
            return action in self.download_actions
        
        return False
    
    async def _handle_download_limit_exceeded(self, event: TelegramObject, user_limits: Dict[str, Any]) -> None:
        """Обработка превышения лимита скачиваний"""
        
        tracks_used = user_limits.get("tracks_used", 0)
        tracks_limit = user_limits.get("tracks_limit", 0)
        is_premium = user_limits.get("is_premium", False)
        
        if is_premium:
            limit_message = (
                "⚠️ **Дневной лимит исчерпан**\n\n"
                f"Вы скачали {tracks_used} из {tracks_limit} треков сегодня.\n"
                "Лимит обновится завтра в 00:00 UTC.\n\n"
                "Если вам нужно больше треков, обратитесь в поддержку."
            )
        else:
            limit_message = (
                f"📊 **Дневной лимит: {tracks_used}/{tracks_limit}**\n\n"
                "Ваш дневной лимит скачиваний исчерпан.\n"
                "Лимит обновится завтра в 00:00 UTC.\n\n"
                "💎 **Premium пользователи получают:**\n"
                "• Безлимитные скачивания\n"
                "• Высокое качество 320kbps\n"
                "• Приоритетный поиск\n\n"
                "Хотите Premium?"
            )
        
        try:
            if isinstance(event, CallbackQuery):
                keyboard = None
                if not is_premium:
                    from app.bot.keyboards.inline import get_premium_offer_keyboard
                    keyboard = get_premium_offer_keyboard()
                
                await event.answer(limit_message, show_alert=True)
                
                if keyboard:
                    try:
                        await event.message.reply(
                            "💎 Получить Premium подписку:",
                            reply_markup=keyboard
                        )
                    except:
                        pass
                        
        except Exception as e:
            self.logger.error(f"Failed to send download limit message: {e}")