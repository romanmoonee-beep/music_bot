"""
Настройка подключения к базе данных PostgreSQL с SQLAlchemy 2.0
"""
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager

import asyncpg
from sqlalchemy import MetaData, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import text
from sqlalchemy.types import DateTime, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
import uuid

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей"""
    
    # Настройки метаданных
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s"
        }
    )
    
    # Общие поля для всех таблиц
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Уникальный идентификатор"
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        comment="Дата создания"
    )
    
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Дата последнего обновления"
    )
    
    def __repr__(self) -> str:
        """Базовое строковое представление"""
        return f"<{self.__class__.__name__}(id={self.id})>"


# Создание движка базы данных
engine: Optional[AsyncEngine] = None
async_session_maker: Optional[async_sessionmaker[AsyncSession]] = None


def create_engine() -> AsyncEngine:
    """Создание асинхронного движка базы данных"""
    return create_async_engine(
        str(settings.DATABASE_URL),
        echo=settings.DEBUG,
        pool_size=20,
        max_overflow=30,
        pool_pre_ping=True,
        pool_recycle=3600,
        json_serializer=lambda obj: obj,
        connect_args={
            "server_settings": {
                "application_name": f"{settings.PROJECT_NAME}",
                "jit": "off",
            },
            "command_timeout": 60,
        },
    )


async def init_database() -> None:
    """Инициализация подключения к базе данных"""
    global engine, async_session_maker
    
    try:
        engine = create_engine()
        async_session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
        
        # Проверка подключения
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
            
        logger.info("Подключение к базе данных установлено")
        
    except Exception as e:
        logger.error(f"Ошибка подключения к базе данных: {e}")
        raise


async def close_database() -> None:
    """Закрытие подключения к базе данных"""
    global engine
    
    if engine:
        await engine.dispose()
        logger.info("Подключение к базе данных закрыто")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Получение сессии базы данных"""
    if not async_session_maker:
        raise RuntimeError("База данных не инициализирована")
    
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class DatabaseManager:
    """Менеджер базы данных для удобной работы"""
    
    def __init__(self):
        self.engine = engine
        self.session_maker = async_session_maker
    
    async def get_session(self) -> AsyncSession:
        """Получить новую сессию"""
        if not self.session_maker:
            raise RuntimeError("База данных не инициализирована")
        return self.session_maker()
    
    @asynccontextmanager
    async def session_scope(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager для автоматического управления сессией"""
        session = await self.get_session()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    
    async def create_all_tables(self) -> None:
        """Создание всех таблиц"""
        if not self.engine:
            raise RuntimeError("База данных не инициализирована")
        
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("Все таблицы созданы")
    
    async def drop_all_tables(self) -> None:
        """Удаление всех таблиц (осторожно!)"""
        if not self.engine:
            raise RuntimeError("База данных не инициализирована")
        
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        
        logger.warning("Все таблицы удалены")
    
    async def check_connection(self) -> bool:
        """Проверка подключения к базе данных"""
        try:
            if not self.engine:
                return False
            
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к БД: {e}")
            return False


# Глобальный менеджер базы данных
db_manager = DatabaseManager()


# Dependency для FastAPI
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency для получения сессии БД в FastAPI"""
    async with get_session() as session:
        yield session


# Event listeners для автоматического обновления updated_at
@event.listens_for(Base, 'before_update', propagate=True)
def receive_before_update(mapper, connection, target):
    """Автоматическое обновление поля updated_at"""
    target.updated_at = datetime.now(timezone.utc)


# Функции для работы с транзакциями
async def execute_in_transaction(func, *args, **kwargs):
    """Выполнение функции в транзакции"""
    async with get_session() as session:
        return await func(session, *args, **kwargs)


# Utility функции для миграций и администрирования
async def get_table_info(table_name: str) -> dict:
    """Получение информации о таблице"""
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = :table_name
                ORDER BY ordinal_position
            """),
            {"table_name": table_name}
        )
        
        columns = []
        for row in result:
            columns.append({
                "name": row.column_name,
                "type": row.data_type,
                "nullable": row.is_nullable == "YES",
                "default": row.column_default
            })
        
        return {
            "table_name": table_name,
            "columns": columns
        }


async def get_database_stats() -> dict:
    """Получение статистики базы данных"""
    async with get_session() as session:
        # Размер базы данных
        size_result = await session.execute(
            text("SELECT pg_size_pretty(pg_database_size(current_database()))")
        )
        db_size = size_result.scalar()
        
        # Количество таблиц
        tables_result = await session.execute(
            text("""
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
        )
        tables_count = tables_result.scalar()
        
        # Количество подключений
        connections_result = await session.execute(
            text("SELECT COUNT(*) FROM pg_stat_activity")
        )
        connections_count = connections_result.scalar()
        
        return {
            "database_size": db_size,
            "tables_count": tables_count,
            "active_connections": connections_count,
            "database_name": settings.POSTGRES_DB
        }