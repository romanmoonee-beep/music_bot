# app/bot/main.py
"""
Основной модуль Telegram бота
"""
import asyncio
import logging
from typing import Dict, Any
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app.core.config import settings
from app.core.logging import get_logger, bot_logger
from app.core.redis import redis_manager
from app.core.exceptions import ConfigurationError

from app.bot.middlewares.auth import AuthMiddleware
from app.bot.middlewares.throttling import ThrottlingMiddleware
from app.bot.middlewares.logging import LoggingMiddleware
from app.bot.middlewares.subscription import SubscriptionMiddleware

from app.bot.handlers.start import router as start_router
from app.bot.handlers.search import router as search_router
from app.bot.handlers.playlist import router as playlist_router
from app.bot.handlers.profile import router as profile_router
from app.bot.handlers.premium import router as premium_router
from app.bot.handlers.inline import router as inline_router
from app.bot.handlers.admin import router as admin_router

from app.services import service_manager

logger = get_logger(__name__)


class MusicBot:
    """Класс музыкального бота"""
    
    def __init__(self):
        self.bot: Bot = None
        self.dispatcher: Dispatcher = None
        self.storage: RedisStorage = None
        self._webhook_app: web.Application = None
    
    async def create_bot(self) -> Bot:
        """Создание экземпляра бота"""
        if not settings.BOT_TOKEN:
            raise ConfigurationError("BOT_TOKEN", "Bot token not configured")
        
        # Настройка сессии
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(
                'https://api.telegram.org',
                is_local=False
            )
        )
        
        # Создание бота
        bot = Bot(
            token=settings.BOT_TOKEN,
            parse_mode=ParseMode.HTML,
            session=session
        )
        
        # Проверка токена
        try:
            bot_info = await bot.get_me()
            logger.info(f"Bot created: @{bot_info.username} ({bot_info.first_name})")
        except Exception as e:
            logger.error(f"Failed to get bot info: {e}")
            raise ConfigurationError("BOT_TOKEN", "Invalid bot token")
        
        self.bot = bot
        return bot
    
    async def create_dispatcher(self) -> Dispatcher:
        """Создание диспетчера"""
        # Создание Redis storage для FSM
        self.storage = RedisStorage(
            redis=redis_manager.get_connection("session")
        )
        
        # Создание диспетчера
        dp = Dispatcher(storage=self.storage)
        
        # Регистрация middleware
        self._register_middlewares(dp)
        
        # Регистрация роутеров
        self._register_routers(dp)
        
        # Регистрация обработчиков ошибок
        self._register_error_handlers(dp)
        
        self.dispatcher = dp
        return dp
    
    def _register_middlewares(self, dp: Dispatcher):
        """Регистрация middleware"""
        # Порядок важен - middleware выполняются в порядке регистрации
        
        # Логирование (первый - для отслеживания всех обновлений)
        dp.message.middleware(LoggingMiddleware())
        dp.callback_query.middleware(LoggingMiddleware())
        dp.inline_query.middleware(LoggingMiddleware())
        
        # Аутентификация и создание пользователей
        dp.message.middleware(AuthMiddleware())
        dp.callback_query.middleware(AuthMiddleware())
        dp.inline_query.middleware(AuthMiddleware())
        
        # Throttling (защита от спама)
        dp.message.middleware(ThrottlingMiddleware())
        dp.callback_query.middleware(ThrottlingMiddleware())
        dp.inline_query.middleware(ThrottlingMiddleware())
        
        # Проверка подписки (последний - после всех проверок)
        dp.message.middleware(SubscriptionMiddleware())
        dp.callback_query.middleware(SubscriptionMiddleware())
        
        logger.info("Middlewares registered")
    
    def _register_routers(self, dp: Dispatcher):
        """Регистрация роутеров"""
        routers = [
            ("start", start_router),
            ("search", search_router),
            ("playlist", playlist_router),
            ("profile", profile_router),
            ("premium", premium_router),
            ("inline", inline_router),
            ("admin", admin_router),
        ]
        
        for name, router in routers:
            try:
                dp.include_router(router)
                logger.info(f"Router '{name}' registered")
            except Exception as e:
                logger.error(f"Failed to register router '{name}': {e}")
        
        logger.info("All routers registered")
    
    def _register_error_handlers(self, dp: Dispatcher):
        """Регистрация обработчиков ошибок"""
        
        @dp.error()
        async def global_error_handler(event, exception):
            """Глобальный обработчик ошибок"""
            logger.error(
                f"Unhandled bot error: {exception}",
                update_type=event.update.event_type if event.update else "unknown",
                user_id=event.update.event.from_user.id if hasattr(event.update.event, 'from_user') else None,
                error_type=type(exception).__name__
            )
            
            # Уведомляем пользователя о технической ошибке
            if hasattr(event.update.event, 'message'):
                try:
                    await event.update.event.message.answer(
                        "🔧 Произошла техническая ошибка. Наши разработчики уже работают над её устранением.\n\n"
                        "Попробуйте повторить действие через несколько минут.",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as send_error:
                    logger.error(f"Failed to send error message: {send_error}")
            
            return True  # Помечаем ошибку как обработанную
        
        logger.info("Error handlers registered")
    
    async def setup_webhook(self, app: web.Application) -> web.Application:
        """Настройка webhook"""
        if not settings.WEBHOOK_URL:
            raise ConfigurationError("WEBHOOK_URL", "Webhook URL not configured")
        
        webhook_url = f"{settings.WEBHOOK_URL}{settings.WEBHOOK_PATH}"
        
        # Устанавливаем webhook
        await self.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query", "inline_query", "chosen_inline_result"],
            drop_pending_updates=True
        )
        
        logger.info(f"Webhook set to: {webhook_url}")
        
        # Настраиваем обработчик webhook
        SimpleRequestHandler(
            dispatcher=self.dispatcher,
            bot=self.bot
        ).register(app, path=settings.WEBHOOK_PATH)
        
        self._webhook_app = app
        return app
    
    async def start_polling(self):
        """Запуск в режиме polling"""
        logger.info("Starting bot in polling mode...")
        
        # Удаляем webhook если установлен
        await self.bot.delete_webhook(drop_pending_updates=True)
        
        try:
            await self.dispatcher.start_polling(
                self.bot,
                polling_timeout=30,
                handle_as_tasks=True,
                allowed_updates=["message", "callback_query", "inline_query", "chosen_inline_result"]
            )
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Polling error: {e}")
            raise
    
    async def stop(self):
        """Остановка бота"""
        try:
            if self.bot:
                # Удаляем webhook
                await self.bot.delete_webhook(drop_pending_updates=True)
                
                # Закрываем сессию
                await self.bot.session.close()
                
            if self.storage:
                await self.storage.close()
            
            logger.info("Bot stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")


# Глобальный экземпляр бота
music_bot = MusicBot()


@asynccontextmanager
async def bot_lifespan():
    """Контекст менеджер для жизненного цикла бота"""
    try:
        # Инициализация сервисов
        await service_manager.initialize_all()
        
        # Создание бота и диспетчера
        await music_bot.create_bot()
        await music_bot.create_dispatcher()
        
        yield music_bot
        
    finally:
        # Остановка бота
        await music_bot.stop()
        
        # Закрытие сервисов
        await service_manager.shutdown_all()


async def create_webhook_app() -> web.Application:
    """Создание web приложения для webhook"""
    app = web.Application()
    
    # Middleware для логирования HTTP запросов
    async def logging_middleware(request, handler):
        start_time = asyncio.get_event_loop().time()
        
        try:
            response = await handler(request)
            duration = asyncio.get_event_loop().time() - start_time
            
            logger.info(
                "HTTP request",
                method=request.method,
                path=request.path,
                status=response.status,
                duration_ms=round(duration * 1000, 2),
                remote_addr=request.remote
            )
            
            return response
            
        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            
            logger.error(
                "HTTP request failed",
                method=request.method,
                path=request.path,
                error=str(e),
                duration_ms=round(duration * 1000, 2),
                remote_addr=request.remote
            )
            raise
    
    app.middlewares.append(logging_middleware)
    
    # Health check endpoint
    async def health_check(request):
        """Health check endpoint"""
        try:
            # Проверяем состояние сервисов
            health_status = await service_manager.health_check_all()
            
            status_code = 200
            if health_status["overall_status"] == "unhealthy":
                status_code = 503
            elif health_status["overall_status"] == "degraded":
                status_code = 206
            
            return web.json_response(health_status, status=status_code)
            
        except Exception as e:
            return web.json_response(
                {"status": "error", "error": str(e)},
                status=500
            )
    
    # Metrics endpoint (для Prometheus)
    async def metrics(request):
        """Metrics endpoint"""
        try:
            # Здесь можно интегрировать с prometheus_client
            metrics_data = {
                "bot_updates_total": 0,  # Счетчик обновлений
                "bot_errors_total": 0,   # Счетчик ошибок
                "active_users": 0,       # Активные пользователи
                # Другие метрики...
            }
            
            return web.Response(
                text="\n".join([f"{k} {v}" for k, v in metrics_data.items()]),
                content_type="text/plain"
            )
            
        except Exception as e:
            return web.Response(
                text=f"# Error collecting metrics: {e}",
                content_type="text/plain",
                status=500
            )
    
    # Регистрация endpoints
    app.router.add_get('/health', health_check)
    app.router.add_get('/metrics', metrics)
    
    return app


async def run_webhook_app():
    """Запуск приложения в режиме webhook"""
    async with bot_lifespan() as bot:
        app = await create_webhook_app()
        await bot.setup_webhook(app)
        
        # Настройка и запуск aiohttp сервера
        runner = web.AppRunner(app)
        await runner.setup()
        
        site = web.TCPSite(
            runner,
            host=settings.WEBHOOK_HOST,
            port=settings.WEBHOOK_PORT
        )
        
        logger.info(f"Starting webhook server on {settings.WEBHOOK_HOST}:{settings.WEBHOOK_PORT}")
        await site.start()
        
        try:
            # Ждем бесконечно
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            logger.info("Webhook server stopped by user")
        finally:
            await runner.cleanup()


async def run_polling():
    """Запуск в режиме polling"""
    async with bot_lifespan() as bot:
        await bot.start_polling()


def main():
    """Главная функция"""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "webhook":
        # Режим webhook
        asyncio.run(run_webhook_app())
    else:
        # Режим polling (по умолчанию)
        asyncio.run(run_polling())


if __name__ == "__main__":
    main()
