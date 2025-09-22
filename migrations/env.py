import asyncio
from logging.config import fileConfig
from pathlib import Path
import sys
import os

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Импортируем наши настройки и модели
from app.core.config import settings
from app.models import Base, get_all_models

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url():
    """Получение URL базы данных"""
    # Используем URL из настроек, заменяем asyncpg на psycopg2 для Alembic
    url = str(settings.DATABASE_URL)
    if '+asyncpg' in url:
        url = url.replace('+asyncpg', '+psycopg2')
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=False,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Выполнение миграций с подключением"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=False,
        # Включаем расширенные опции для лучшего сравнения
        include_schemas=True,
        include_object=include_object,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def include_object(object, name, type_, reflected, compare_to):
    """Фильтрация объектов для миграций"""
    
    # Исключаем системные таблицы PostgreSQL
    if type_ == "table" and name in [
        'spatial_ref_sys',  # PostGIS
        'geography_columns',  # PostGIS
        'geometry_columns',  # PostGIS
        'raster_columns',  # PostGIS
        'raster_overviews',  # PostGIS
    ]:
        return False
    
    # Исключаем временные таблицы
    if type_ == "table" and (name.startswith('temp_') or name.startswith('tmp_')):
        return False
    
    # Исключаем Alembic версионную таблицу из автогенерации
    if type_ == "table" and name == 'alembic_version':
        return False
    
    return True


def process_revision_directives(context, revision, directives):
    """Обработка директив ревизии для улучшения миграций"""
    
    # Если нет изменений, не создаем пустую миграцию
    if getattr(config.cmd_opts, 'autogenerate', False):
        script = directives[0]
        if script.upgrade_ops.is_empty():
            directives[:] = []
            print("No changes detected, skipping migration generation")


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    
    # Конфигурация для асинхронного движка
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    
    # Создаем асинхронный движок
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()