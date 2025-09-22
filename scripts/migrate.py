#!/usr/bin/env python3
"""
Скрипт управления миграциями базы данных
"""
import asyncio
import sys
from pathlib import Path
import subprocess
import os

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MigrationManager:
    """Менеджер миграций"""
    
    def __init__(self):
        self.project_root = Path(__file__).resolve().parent.parent
        self.alembic_cfg_path = self.project_root / "alembic.ini"
        self.migrations_dir = self.project_root / "migrations"
        
        # Создаем конфигурацию Alembic
        self.alembic_cfg = Config(str(self.alembic_cfg_path))
        self.alembic_cfg.set_main_option("script_location", str(self.migrations_dir))
        self.alembic_cfg.set_main_option("sqlalchemy.url", str(settings.DATABASE_URL))
    
    def init_alembic(self):
        """Инициализация Alembic"""
        try:
            logger.info("Initializing Alembic...")
            
            # Создаем директорию для миграций
            self.migrations_dir.mkdir(exist_ok=True)
            
            # Инициализируем Alembic
            command.init(self.alembic_cfg, str(self.migrations_dir))
            
            logger.info("✅ Alembic initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Alembic: {e}")
            raise
    
    def create_migration(self, message: str, autogenerate: bool = True):
        """Создание новой миграции"""
        try:
            logger.info(f"Creating migration: '{message}'")
            
            if autogenerate:
                # Автогенерация на основе изменений в моделях
                command.revision(
                    self.alembic_cfg,
                    message=message,
                    autogenerate=True
                )
            else:
                # Пустая миграция для ручного заполнения
                command.revision(
                    self.alembic_cfg,
                    message=message
                )
            
            logger.info("✅ Migration created successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to create migration: {e}")
            raise
    
    def upgrade(self, revision: str = "head"):
        """Применение миграций"""
        try:
            logger.info(f"Upgrading database to: {revision}")
            
            command.upgrade(self.alembic_cfg, revision)
            
            logger.info("✅ Database upgraded successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to upgrade database: {e}")
            raise
    
    def downgrade(self, revision: str):
        """Откат миграций"""
        try:
            logger.info(f"Downgrading database to: {revision}")
            
            command.downgrade(self.alembic_cfg, revision)
            
            logger.info("✅ Database downgraded successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to downgrade database: {e}")
            raise
    
    def show_current_revision(self):
        """Показать текущую ревизию"""
        try:
            # Создаем синхронный engine для Alembic
            engine = create_engine(str(settings.DATABASE_URL).replace('+asyncpg', '+psycopg2'))
            
            with engine.connect() as connection:
                context = MigrationContext.configure(connection)
                current_rev = context.get_current_revision()
                
                if current_rev:
                    logger.info(f"📍 Current revision: {current_rev}")
                else:
                    logger.info("📍 No migrations applied yet")
                
                return current_rev
                
        except Exception as e:
            logger.error(f"❌ Failed to get current revision: {e}")
            return None
    
    def show_history(self, verbose: bool = False):
        """Показать историю миграций"""
        try:
            logger.info("📋 Migration history:")
            
            script_dir = ScriptDirectory.from_config(self.alembic_cfg)
            
            for revision in script_dir.walk_revisions():
                if verbose:
                    logger.info(f"  {revision.revision}: {revision.doc}")
                    if revision.down_revision:
                        logger.info(f"    ⬇️  Down revision: {revision.down_revision}")
                else:
                    logger.info(f"  {revision.revision}: {revision.doc}")
            
        except Exception as e:
            logger.error(f"❌ Failed to show history: {e}")
    
    def show_pending(self):
        """Показать ожидающие миграции"""
        try:
            engine = create_engine(str(settings.DATABASE_URL).replace('+asyncpg', '+psycopg2'))
            
            with engine.connect() as connection:
                context = MigrationContext.configure(connection)
                current_rev = context.get_current_revision()
                
                script_dir = ScriptDirectory.from_config(self.alembic_cfg)
                head_rev = script_dir.get_current_head()
                
                if current_rev == head_rev:
                    logger.info("✅ Database is up to date")
                    return []
                
                # Получаем список ожидающих миграций
                pending = []
                for revision in script_dir.iterate_revisions(head_rev, current_rev):
                    if revision.revision != current_rev:
                        pending.append(revision)
                
                if pending:
                    logger.info(f"⏳ Pending migrations ({len(pending)}):")
                    for revision in reversed(pending):
                        logger.info(f"  {revision.revision}: {revision.doc}")
                
                return pending
                
        except Exception as e:
            logger.error(f"❌ Failed to check pending migrations: {e}")
            return []
    
    def validate_schema(self):
        """Валидация схемы базы данных"""
        try:
            logger.info("🔍 Validating database schema...")
            
            # Проверяем текущую ревизию
            current_rev = self.show_current_revision()
            
            # Проверяем ожидающие миграции
            pending = self.show_pending()
            
            if pending:
                logger.warning(f"⚠️  Found {len(pending)} pending migrations")
                return False
            
            # Проверяем целостность данных
            engine = create_engine(str(settings.DATABASE_URL).replace('+asyncpg', '+psycopg2'))
            
            with engine.connect() as connection:
                # Проверяем основные таблицы
                required_tables = [
                    'users', 'tracks', 'playlists', 'playlist_tracks',
                    'search_history', 'subscriptions', 'payments',
                    'analytics_events'
                ]
                
                missing_tables = []
                for table in required_tables:
                    result = connection.execute(text(
                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :table_name)"
                    ), {"table_name": table})
                    
                    if not result.scalar():
                        missing_tables.append(table)
                
                if missing_tables:
                    logger.error(f"❌ Missing tables: {missing_tables}")
                    return False
                
                logger.info("✅ Schema validation passed")
                return True
                
        except Exception as e:
            logger.error(f"❌ Schema validation failed: {e}")
            return False
    
    def backup_before_migration(self):
        """Создание бэкапа перед миграцией"""
        try:
            from datetime import datetime
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = f"backup_before_migration_{timestamp}.sql"
            backup_path = self.project_root / "backups" / backup_file
            
            # Создаем директорию для бэкапов
            backup_path.parent.mkdir(exist_ok=True)
            
            logger.info(f"📦 Creating backup: {backup_file}")
            
            # Команда pg_dump
            dump_cmd = [
                "pg_dump",
                f"--host={settings.POSTGRES_SERVER}",
                f"--port={settings.POSTGRES_PORT}",
                f"--username={settings.POSTGRES_USER}",
                f"--dbname={settings.POSTGRES_DB}",
                "--verbose",
                "--clean",
                "--no-owner",
                "--no-privileges",
                f"--file={backup_path}"
            ]
            
            # Устанавливаем пароль через переменную окружения
            env = os.environ.copy()
            env['PGPASSWORD'] = settings.POSTGRES_PASSWORD
            
            result = subprocess.run(dump_cmd, env=env, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"✅ Backup created: {backup_path}")
                return str(backup_path)
            else:
                logger.error(f"❌ Backup failed: {result.stderr}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Failed to create backup: {e}")
            return None
    
    def safe_upgrade(self, revision: str = "head", create_backup: bool = True):
        """Безопасное обновление с бэкапом"""
        try:
            # Проверяем текущее состояние
            if not self.validate_schema():
                logger.error("❌ Schema validation failed, aborting migration")
                return False
            
            # Создаем бэкап
            backup_path = None
            if create_backup:
                backup_path = self.backup_before_migration()
                if not backup_path:
                    logger.error("❌ Backup failed, aborting migration")
                    return False
            
            # Показываем ожидающие миграции
            pending = self.show_pending()
            if not pending:
                logger.info("✅ No migrations to apply")
                return True
            
            logger.info(f"🚀 Applying {len(pending)} migration(s)...")
            
            # Применяем миграции
            self.upgrade(revision)
            
            # Проверяем результат
            if self.validate_schema():
                logger.info("✅ Migration completed successfully")
                return True
            else:
                logger.error("❌ Post-migration validation failed")
                if backup_path:
                    logger.info(f"💡 Backup available at: {backup_path}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Safe upgrade failed: {e}")
            return False


def main():
    """Основная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Database migration management")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Инициализация
    init_parser = subparsers.add_parser('init', help='Initialize Alembic')
    
    # Создание миграции
    create_parser = subparsers.add_parser('create', help='Create new migration')
    create_parser.add_argument('message', help='Migration message')
    create_parser.add_argument('--empty', action='store_true', help='Create empty migration')
    
    # Применение миграций
    upgrade_parser = subparsers.add_parser('upgrade', help='Apply migrations')
    upgrade_parser.add_argument('revision', nargs='?', default='head', help='Target revision')
    upgrade_parser.add_argument('--backup', action='store_true', help='Create backup before upgrade')
    
    # Откат миграций
    downgrade_parser = subparsers.add_parser('downgrade', help='Rollback migrations')
    downgrade_parser.add_argument('revision', help='Target revision')
    
    # Информация
    info_parser = subparsers.add_parser('current', help='Show current revision')
    history_parser = subparsers.add_parser('history', help='Show migration history')
    history_parser.add_argument('--verbose', action='store_true', help='Verbose output')
    
    pending_parser = subparsers.add_parser('pending', help='Show pending migrations')
    validate_parser = subparsers.add_parser('validate', help='Validate database schema')
    
    # Безопасное обновление
    safe_parser = subparsers.add_parser('safe-upgrade', help='Safe upgrade with backup')
    safe_parser.add_argument('revision', nargs='?', default='head', help='Target revision')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    manager = MigrationManager()
    
    try:
        if args.command == 'init':
            manager.init_alembic()
        
        elif args.command == 'create':
            manager.create_migration(args.message, autogenerate=not args.empty)
        
        elif args.command == 'upgrade':
            if args.backup:
                manager.safe_upgrade(args.revision)
            else:
                manager.upgrade(args.revision)
        
        elif args.command == 'downgrade':
            manager.downgrade(args.revision)
        
        elif args.command == 'current':
            manager.show_current_revision()
        
        elif args.command == 'history':
            manager.show_history(args.verbose)
        
        elif args.command == 'pending':
            manager.show_pending()
        
        elif args.command == 'validate':
            if manager.validate_schema():
                print("✅ Schema is valid")
                sys.exit(0)
            else:
                print("❌ Schema validation failed")
                sys.exit(1)
        
        elif args.command == 'safe-upgrade':
            if manager.safe_upgrade(args.revision):
                sys.exit(0)
            else:
                sys.exit(1)
        
    except KeyboardInterrupt:
        logger.info("🛑 Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Command failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()