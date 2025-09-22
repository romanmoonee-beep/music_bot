"""
Middleware для ограничения частоты запросов (rate limiting)
"""
import time
import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional
from datetime import datetime, timezone, timedelta

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, InlineQuery
from aiogram.exceptions import TelegramTooManyRequests

from app.core.logging import get_logger, security_logger
from app.services.cache_service import user_cache
from app.core.config import settings


class ThrottlingMiddleware(BaseMiddleware):
    """Middleware для контроля частоты запросов"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        
        # Лимиты для разных типов действий
        self.rate_limits = {
            "message": {"limit": 30, "window": 60},      # 30 сообщений в минуту
            "callback": {"limit": 50, "window": 60},     # 50 коллбеков в минуту
            "inline": {"limit": 100, "window": 60},      # 100 inline запросов в минуту
            "search": {"limit": 20, "window": 60},       # 20 поисков в минуту
            "download": {"limit": 10, "window": 60},     # 10 скачиваний в минуту
        }
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Основной метод middleware"""
        
        user = data.get("user")
        if not user:
            return await handler(event, data)
        
        # Определяем тип действия
        action_type = self._get_action_type(event, data)
        if not action_type:
            return await handler(event, data)
        
        # Проверяем rate limit
        is_allowed, remaining, reset_time = await self._check_rate_limit(
            user.telegram_id, 
            action_type,
            data.get("is_premium", False)
        )
        
        if not is_allowed:
            await self._handle_rate_limit_exceeded(
                event, 
                user.telegram_id, 
                action_type,
                remaining, 
                reset_time
            )
            return
        
        # Добавляем информацию о лимитах в данные
        data["rate_limit_remaining"] = remaining
        data["rate_limit_reset"] = reset_time
        
        try:
            result = await handler(event, data)
            
            # Записываем успешное действие
            await self._record_action(user.telegram_id, action_type)
            
            return result
            
        except TelegramTooManyRequests as e:
            # Telegram API rate limit
            self.logger.warning(f"Telegram API rate limit for user {user.telegram_id}: {e}")
            await asyncio.sleep(e.retry_after or 1)
            raise
        except Exception:
            # Записываем действие даже при ошибке (для предотвращения спама)
            await self._record_action(user.telegram_id, action_type)
            raise
    
    def _get_action_type(self, event: TelegramObject, data: Dict[str, Any]) -> Optional[str]:
        """Определение типа действия для rate limiting"""
        
        # Проверяем специальные действия по callback data или тексту
        if isinstance(event, CallbackQuery):
            if event.data:
                if event.data.startswith("search:") or event.data.startswith("find:"):
                    return "search"
                elif event.data.startswith("download:") or event.data.startswith("get:"):
                    return "download"
                return "callback"
        
        elif isinstance(event, Message):
            if event.text:
                # Поисковые запросы (не команды)
                if not event.text.startswith("/") and len(event.text) > 2:
                    return "search"
            return "message"
        
        elif isinstance(event, InlineQuery):
            return "inline"
        
        return None
    
    async def _check_rate_limit(
        self, 
        user_id: int, 
        action_type: str, 
        is_premium: bool
    ) -> tuple[bool, int, datetime]:
        """Проверка rate limit для пользователя"""
        
        # Получаем лимиты для типа действия
        base_limits = self.rate_limits.get(action_type, {"limit": 10, "window": 60})
        
        # Увеличиваем лимиты для premium пользователей
        if is_premium:
            limit = int(base_limits["limit"] * 2)
        else:
            limit = base_limits["limit"]
        
        window = base_limits["window"]
        
        # Ключ для кеша
        cache_key = f"rate_limit:{user_id}:{action_type}"
        
        # Получаем текущие данные из кеша
        current_data = await user_cache.get(cache_key, "rate_limit")
        
        now = time.time()
        reset_time = datetime.now(timezone.utc) + timedelta(seconds=window)
        
        if not current_data:
            # Первый запрос
            await user_cache.set(
                cache_key, 
                {"count": 0, "window_start": now},
                ttl=window,
                cache_type="rate_limit"
            )
            return True, limit - 1, reset_time
        
        window_start = current_data.get("window_start", now)
        count = current_data.get("count", 0)
        
        # Проверяем, не истекло ли окно
        if now - window_start > window:
            # Новое окно
            await user_cache.set(
                cache_key,
                {"count": 0, "window_start": now},
                ttl=window,
                cache_type="rate_limit"
            )
            return True, limit - 1, reset_time
        
        # Проверяем лимит
        if count >= limit:
            remaining_time = window - (now - window_start)
            reset_time = datetime.now(timezone.utc) + timedelta(seconds=remaining_time)
            return False, 0, reset_time
        
        return True, limit - count - 1, reset_time
    
    async def _record_action(self, user_id: int, action_type: str) -> None:
        """Запись выполненного действия"""
        cache_key = f"rate_limit:{user_id}:{action_type}"
        
        current_data = await user_cache.get(cache_key, "rate_limit")
        if current_data:
            current_data["count"] = current_data.get("count", 0) + 1
            await user_cache.set(
                cache_key,
                current_data,
                ttl=self.rate_limits.get(action_type, {}).get("window", 60),
                cache_type="rate_limit"
            )
    
    async def _handle_rate_limit_exceeded(
        self,
        event: TelegramObject,
        user_id: int,
        action_type: str,
        remaining: int,
        reset_time: datetime
    ) -> None:
        """Обработка превышения rate limit"""
        
        # Логируем превышение лимита
        await security_logger.log_rate_limit_exceeded(
            user_id=user_id,
            limit_type=action_type,
            current_count=0,  # Мы не знаем точное количество здесь
            limit=self.rate_limits.get(action_type, {}).get("limit", 0)
        )
        
        # Формируем сообщение пользователю
        action_names = {
            "message": "сообщений",
            "callback": "нажатий кнопок", 
            "inline": "inline запросов",
            "search": "поисковых запросов",
            "download": "скачиваний"
        }
        
        action_name = action_names.get(action_type, "действий")
        
        # Время до сброса лимита
        time_left = reset_time - datetime.now(timezone.utc)
        minutes_left = int(time_left.total_seconds() // 60)
        seconds_left = int(time_left.total_seconds() % 60)
        
        if minutes_left > 0:
            time_str = f"{minutes_left} мин {seconds_left} сек"
        else:
            time_str = f"{seconds_left} сек"
        
        limit_message = (
            f"⏰ Слишком много {action_name}!\n\n"
            f"Попробуйте снова через {time_str}\n\n"
            f"💎 Premium пользователи имеют увеличенные лимиты"
        )
        
        # Отправляем сообщение
        if isinstance(event, Message):
            try:
                await event.answer(limit_message)
            except:
                pass
        elif isinstance(event, CallbackQuery):
            try:
                await event.answer(limit_message, show_alert=True)
            except:
                pass


class AntiFloodMiddleware(BaseMiddleware):
    """Простая защита от флуда сообщениями"""
    
    def __init__(self, flood_limit: int = 5, flood_window: int = 10):
        self.flood_limit = flood_limit
        self.flood_window = flood_window
        self.logger = get_logger(self.__class__.__name__)
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Проверка на флуд"""
        
        if not isinstance(event, Message):
            return await handler(event, data)
        
        user = data.get("user")
        if not user:
            return await handler(event, data)
        
        # Проверяем флуд
        cache_key = f"flood:{user.telegram_id}"
        flood_data = await user_cache.get(cache_key, "antiflood")
        
        now = time.time()
        
        if not flood_data:
            flood_data = {"messages": [], "last_flood_time": 0}
        
        # Очищаем старые сообщения
        flood_data["messages"] = [
            msg_time for msg_time in flood_data["messages"]
            if now - msg_time < self.flood_window
        ]
        
        # Добавляем текущее сообщение
        flood_data["messages"].append(now)
        
        # Проверяем превышение лимита
        if len(flood_data["messages"]) > self.flood_limit:
            # Проверяем, когда последний раз отправляли предупреждение
            if now - flood_data.get("last_flood_time", 0) > 30:  # Не чаще раза в 30 сек
                flood_data["last_flood_time"] = now
                await user_cache.set(cache_key, flood_data, ttl=300, cache_type="antiflood")
                
                try:
                    await event.answer(
                        "🛑 Обнаружен флуд!\n\n"
                        "Пожалуйста, не отправляйте сообщения слишком часто."
                    )
                except:
                    pass
                
                # Логируем
                await security_logger.log_suspicious_activity(
                    user_id=user.telegram_id,
                    activity_type="flood",
                    details=f"{len(flood_data['messages'])} messages in {self.flood_window}s"
                )
            
            return  # Блокируем обработку сообщения
        
        # Сохраняем данные
        await user_cache.set(cache_key, flood_data, ttl=300, cache_type="antiflood")
        
        return await handler(event, data)