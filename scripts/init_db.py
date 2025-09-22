#!/usr/bin/env python3
"""
Скрипт инициализации базы данных
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.database import init_database, close_database, db_manager
from app.core.logging import get_logger
from app.models import get_all_models
import app.models  # Импортируем все модели

logger = get_logger(__name__)


async def create_tables():
    """Создание всех таблиц"""
    try:
        logger.info("Создание таблиц базы данных...")
        await db_manager.create_all_tables()
        logger.info("✅ Все таблицы успешно созданы")
    except Exception as e:
        logger.error(f"❌ Ошибка создания таблиц: {e}")
        raise


async def check_connection():
    """Проверка подключения к базе данных"""
    try:
        logger.info("Проверка подключения к базе данных...")
        is_connected = await db_manager.check_connection()
        if is_connected:
            logger.info("✅ Подключение к базе данных успешно")
        else:
            logger.error("❌ Не удалось подключиться к базе данных")
            return False
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к базе данных: {e}")
        return False


async def get_database_info():
    """Получение информации о базе данных"""
    try:
        from app.core.database import get_database_stats
        stats = await get_database_stats()
        
        logger.info("📊 Информация о базе данных:")
        logger.info(f"  📁 Название: {stats['database_name']}")
        logger.info(f"  📏 Размер: {stats['database_size']}")
        logger.info(f"  📋 Таблиц: {stats['tables_count']}")
        logger.info(f"  🔗 Активных подключений: {stats['active_connections']}")
        
    except Exception as e:
        logger.warning(f"⚠️ Не удалось получить статистику БД: {e}")


async def create_initial_data():
    """Создание начальных данных"""
    try:
        logger.info("Создание начальных данных...")
        
        from app.core.database import get_session
        from app.models.user import User, UserStatus, SubscriptionType
        from app.models.subscription import PromoCode
        from datetime import datetime, timezone
        
        async with get_session() as session:
            # Проверяем, есть ли уже пользователи
            existing_users = await User.count(session)
            if existing_users > 0:
                logger.info(f"📊 В базе уже есть {existing_users} пользователей")
                return
            
            # Создаем тестового админа (если нужно)
            if settings.DEBUG:
                admin_user = User(
                    telegram_id=123456789,
                    username="admin",
                    first_name="Admin",
                    last_name="User",
                    status=UserStatus.PREMIUM,
                    subscription_type=SubscriptionType.PREMIUM_1Y,
                    subscription_expires_at=datetime(2030, 12, 31, tzinfo=timezone.utc),
                    language_code="ru"
                )
                session.add(admin_user)
                logger.info("👑 Создан тестовый админ пользователь")
            
            # Создаем базовые промокоды
            promo_codes = [
                {
                    "code": "WELCOME50",
                    "description": "Скидка 50% на первую подписку",
                    "discount_type": "percentage",
                    "discount_value": 50,
                    "usage_limit": 1000,
                    "user_limit": 1,
                    "is_active": True
                },
                {
                    "code": "TESTFREE",
                    "description": "Бесплатная подписка на месяц (для тестирования)",
                    "discount_type": "free",
                    "discount_value": 100,
                    "usage_limit": 100,
                    "user_limit": 1,
                    "is_active": settings.DEBUG
                }
            ]
            
            for promo_data in promo_codes:
                promo = PromoCode(**promo_data)
                session.add(promo)
            
            logger.info(f"🎫 Создано {len(promo_codes)} промокодов")
            
            await session.commit()
            logger.info("✅ Начальные данные созданы")
            
    except Exception as e:
        logger.error(f"❌ Ошибка создания начальных данных: {e}")
        raise


async def setup_extensions():
    """Настройка расширений PostgreSQL"""
    try:
        logger.info("Настройка расширений PostgreSQL...")
        
        from app.core.database import get_session
        from sqlalchemy import text
        
        async with get_session() as session:
            # UUID расширение
            await session.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            
            # Полнотекстовый поиск для русского языка
            await session.execute(text('CREATE EXTENSION IF NOT EXISTS "unaccent"'))
            
            # Расширение для работы с массивами
            await session.execute(text('CREATE EXTENSION IF NOT EXISTS "intarray"'))
            
            await session.commit()
            
        logger.info("✅ Расширения PostgreSQL настроены")
        
    except Exception as e:
        logger.warning(f"⚠️ Не удалось настроить расширения PostgreSQL: {e}")


async def create_indexes():
    """Создание дополнительных индексов"""
    try:
        logger.info("Создание дополнительных индексов...")
        
        from app.core.database import get_session
        from sqlalchemy import text
        
        async with get_session() as session:
            # Индексы для полнотекстового поиска
            indexes = [
                """
                CREATE INDEX IF NOT EXISTS idx_tracks_fulltext 
                ON tracks USING gin(to_tsvector('russian', title || ' ' || artist || ' ' || coalesce(album, '')))
                """,
                
                """
                CREATE INDEX IF NOT EXISTS idx_playlists_fulltext 
                ON playlists USING gin(to_tsvector('russian', name || ' ' || coalesce(description, '')))
                """,
                
                # Индексы для аналитики
                """
                CREATE INDEX IF NOT EXISTS idx_analytics_events_time_user 
                ON analytics_events (event_timestamp DESC, user_id) 
                WHERE user_id IS NOT NULL
                """,
                
                # Индексы для производительности
                """
                CREATE INDEX IF NOT EXISTS idx_users_active_premium 
                ON users (last_activity_at DESC) 
                WHERE status = 'premium' AND subscription_expires_at > NOW()
                """,
            ]
            
            for index_sql in indexes:
                try:
                    await session.execute(text(index_sql))
                except Exception as idx_error:
                    logger.warning(f"Не удалось создать индекс: {idx_error}")
            
            await session.commit()
            
        logger.info("✅ Дополнительные индексы созданы")
        
    except Exception as e:
        logger.warning(f"⚠️ Ошибка создания индексов: {e}")


async def main():
    """Основная функция инициализации"""
    logger.info("🚀 Начало инициализации базы данных")
    logger.info(f"📍 Окружение: {settings.ENVIRONMENT}")
    logger.info(f"🗄️ База данных: {settings.POSTGRES_DB}")
    logger.info(f"🏠 Сервер: {settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}")
    
    try:
        # Инициализация подключения
        await init_database()
        
        # Проверка подключения
        if not await check_connection():
            logger.error("❌ Не удалось подключиться к базе данных")
            return False
        
        # Настройка расширений
        await setup_extensions()
        
        # Создание таблиц
        await create_tables()
        
        # Создание дополнительных индексов
        await create_indexes()
        
        # Получение информации о БД
        await get_database_info()
        
        # Создание начальных данных
        await create_initial_data()
        
        logger.info("🎉 Инициализация базы данных завершена успешно!")
        return True
        
    except Exception as e:
        logger.error(f"💥 Критическая ошибка при инициализации: {e}")
        return False
        
    finally:
        # Закрытие подключения
        await close_database()


async def drop_all():
    """Удаление всех таблиц (ОСТОРОЖНО!)"""
    logger.warning("⚠️ ВНИМАНИЕ: Удаление всех таблиц!")
    
    try:
        await init_database()
        
        # Подтверждение
        if settings.ENVIRONMENT == "production":
            logger.error("❌ Удаление таблиц в продакшне запрещено!")
            return False
        
        await db_manager.drop_all_tables()
        logger.info("✅ Все таблицы удалены")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка удаления таблиц: {e}")
        return False
        
    finally:
        await close_database()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Инициализация базы данных")
    parser.add_argument(
        "--drop", 
        action="store_true", 
        help="Удалить все таблицы перед созданием"
    )
    parser.add_argument(
        "--drop-only", 
        action="store_true", 
        help="Только удалить таблицы"
    )
    
    args = parser.parse_args()
    
    if args.drop_only:
        success = asyncio.run(drop_all())
        sys.exit(0 if success else 1)
    
    if args.drop:
        logger.info("🗑️ Удаление существующих таблиц...")
        asyncio.run(drop_all())
    
    # Основная инициализация
    success = asyncio.run(main())
    sys.exit(0 if success else 1)