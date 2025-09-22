#!/usr/bin/env python3
"""
Скрипт резервного копирования базы данных и файлов
"""
import asyncio
import sys
import os
import subprocess
import shutil
import gzip
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import boto3
from botocore.exceptions import NoCredentialsError

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.logging import get_logger
from app.core.database import get_session
from sqlalchemy import text

logger = get_logger(__name__)


class BackupManager:
    """Менеджер резервного копирования"""
    
    def __init__(self):
        self.project_root = Path(__file__).resolve().parent.parent
        self.backup_dir = self.project_root / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        
        # Настройки
        self.max_local_backups = 7  # Хранить локально 7 бэкапов
        self.compression_level = 6  # Уровень сжатия gzip
        
        # S3 настройки (опционально)
        self.s3_bucket = getattr(settings, 'BACKUP_S3_BUCKET', None)
        self.s3_prefix = getattr(settings, 'BACKUP_S3_PREFIX', 'music-bot-backups/')
        self.s3_client = None
        
        if self.s3_bucket:
            try:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID', None),
                    aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
                    region_name=getattr(settings, 'AWS_REGION', 'us-east-1')
                )
            except Exception as e:
                logger.warning(f"Failed to initialize S3 client: {e}")
    
    def get_timestamp(self) -> str:
        """Получение timestamp для имен файлов"""
        return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    async def create_database_backup(self, compress: bool = True) -> Optional[Path]:
        """Создание бэкапа базы данных"""
        try:
            timestamp = self.get_timestamp()
            backup_name = f"db_backup_{timestamp}.sql"
            backup_path = self.backup_dir / backup_name
            
            logger.info(f"📦 Creating database backup: {backup_name}")
            
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
                "--inserts",  # Для лучшей совместимости
                f"--file={backup_path}"
            ]
            
            # Устанавливаем пароль через переменную окружения
            env = os.environ.copy()
            env['PGPASSWORD'] = settings.POSTGRES_PASSWORD
            
            # Выполняем бэкап
            result = subprocess.run(dump_cmd, env=env, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"❌ pg_dump failed: {result.stderr}")
                return None
            
            # Добавляем метаданные
            await self._add_backup_metadata(backup_path)
            
            # Сжимаем если нужно
            if compress:
                compressed_path = await self._compress_file(backup_path)
                if compressed_path:
                    backup_path.unlink()  # Удаляем несжатый файл
                    backup_path = compressed_path
            
            # Получаем размер файла
            file_size = backup_path.stat().st_size
            size_mb = file_size / (1024 * 1024)
            
            logger.info(f"✅ Database backup created: {backup_path.name} ({size_mb:.1f} MB)")
            
            return backup_path
            
        except Exception as e:
            logger.error(f"❌ Failed to create database backup: {e}")
            return None
    
    async def _add_backup_metadata(self, backup_path: Path):
        """Добавление метаданных в бэкап"""
        try:
            # Получаем статистику базы данных
            async with get_session() as session:
                stats = await self._get_database_stats(session)
            
            # Создаем метаданные
            metadata = {
                "backup_created_at": datetime.now(timezone.utc).isoformat(),
                "database_name": settings.POSTGRES_DB,
                "database_host": settings.POSTGRES_SERVER,
                "environment": settings.ENVIRONMENT,
                "version": settings.VERSION,
                "statistics": stats
            }
            
            # Добавляем метаданные в начало файла
            with open(backup_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(f"-- Backup metadata: {json.dumps(metadata, indent=2)}\n")
                f.write(content)
                
        except Exception as e:
            logger.warning(f"Failed to add metadata: {e}")
    
    async def _get_database_stats(self, session) -> Dict[str, Any]:
        """Получение статистики базы данных"""
        try:
            stats = {}
            
            # Основные таблицы
            tables = [
                'users', 'tracks', 'playlists', 'playlist_tracks',
                'search_history', 'subscriptions', 'payments', 'analytics_events'
            ]
            
            for table in tables:
                try:
                    result = await session.execute(
                        text(f"SELECT COUNT(*) FROM {table}")
                    )
                    stats[f"{table}_count"] = result.scalar()
                except Exception as e:
                    logger.warning(f"Failed to get count for {table}: {e}")
                    stats[f"{table}_count"] = 0
            
            # Размер базы данных
            try:
                result = await session.execute(
                    text("SELECT pg_size_pretty(pg_database_size(current_database()))")
                )
                stats['database_size'] = result.scalar()
            except Exception as e:
                logger.warning(f"Failed to get database size: {e}")
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get database stats: {e}")
            return {}
    
    async def _compress_file(self, file_path: Path) -> Optional[Path]:
        """Сжатие файла с помощью gzip"""
        try:
            compressed_path = file_path.with_suffix(file_path.suffix + '.gz')
            
            logger.info(f"🗜️ Compressing backup: {file_path.name}")
            
            with open(file_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb', compresslevel=self.compression_level) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Проверяем размеры
            original_size = file_path.stat().st_size
            compressed_size = compressed_path.stat().st_size
            compression_ratio = (1 - compressed_size / original_size) * 100
            
            logger.info(f"✅ Compression completed: {compression_ratio:.1f}% reduction")
            
            return compressed_path
            
        except Exception as e:
            logger.error(f"❌ Failed to compress file: {e}")
            return None
    
    async def create_files_backup(self, include_logs: bool = False) -> Optional[Path]:
        """Создание бэкапа файлов приложения"""
        try:
            timestamp = self.get_timestamp()
            backup_name = f"files_backup_{timestamp}.tar.gz"
            backup_path = self.backup_dir / backup_name
            
            logger.info(f"📁 Creating files backup: {backup_name}")
            
            # Определяем что бэкапить
            include_paths = [
                "app/",
                "scripts/",
                "migrations/",
                "requirements.txt",
                "pyproject.toml",
                ".env.example",
                "README.md"
            ]
            
            if include_logs:
                include_paths.append("logs/")
            
            # Исключения
            exclude_patterns = [
                "__pycache__",
                "*.pyc",
                "*.pyo",
                ".git",
                ".pytest_cache",
                "temp/",
                "backups/",
                ".env"
            ]
            
            # Команда tar
            tar_cmd = ["tar", "-czf", str(backup_path)]
            
            # Добавляем исключения
            for pattern in exclude_patterns:
                tar_cmd.extend(["--exclude", pattern])
            
            # Добавляем пути
            tar_cmd.extend(include_paths)
            
            # Выполняем в корневой директории проекта
            result = subprocess.run(
                tar_cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.error(f"❌ tar failed: {result.stderr}")
                return None
            
            file_size = backup_path.stat().st_size
            size_mb = file_size / (1024 * 1024)
            
            logger.info(f"✅ Files backup created: {backup_path.name} ({size_mb:.1f} MB)")
            
            return backup_path
            
        except Exception as e:
            logger.error(f"❌ Failed to create files backup: {e}")
            return None
    
    async def create_full_backup(self, compress_db: bool = True, include_logs: bool = False) -> List[Path]:
        """Создание полного бэкапа (БД + файлы)"""
        try:
            logger.info("🚀 Starting full backup...")
            
            backups = []
            
            # Бэкап базы данных
            db_backup = await self.create_database_backup(compress=compress_db)
            if db_backup:
                backups.append(db_backup)
            
            # Бэкап файлов
            files_backup = await self.create_files_backup(include_logs=include_logs)
            if files_backup:
                backups.append(files_backup)
            
            if backups:
                total_size = sum(b.stat().st_size for b in backups)
                total_mb = total_size / (1024 * 1024)
                logger.info(f"✅ Full backup completed: {len(backups)} files, {total_mb:.1f} MB total")
            else:
                logger.error("❌ Full backup failed: no backups created")
            
            return backups
            
        except Exception as e:
            logger.error(f"❌ Full backup failed: {e}")
            return []
    
    async def upload_to_s3(self, backup_path: Path) -> bool:
        """Загрузка бэкапа в S3"""
        if not self.s3_client or not self.s3_bucket:
            logger.warning("S3 not configured, skipping upload")
            return False
        
        try:
            s3_key = f"{self.s3_prefix}{backup_path.name}"
            
            logger.info(f"☁️ Uploading to S3: {s3_key}")
            
            # Загружаем файл
            self.s3_client.upload_file(
                str(backup_path),
                self.s3_bucket,
                s3_key,
                ExtraArgs={
                    'StorageClass': 'STANDARD_IA',  # Дешевле для бэкапов
                    'Metadata': {
                        'created_at': datetime.now(timezone.utc).isoformat(),
                        'environment': settings.ENVIRONMENT,
                        'version': settings.VERSION
                    }
                }
            )
            
            logger.info(f"✅ Uploaded to S3: s3://{self.s3_bucket}/{s3_key}")
            return True
            
        except NoCredentialsError:
            logger.error("❌ AWS credentials not found")
            return False
        except Exception as e:
            logger.error(f"❌ S3 upload failed: {e}")
            return False
    
    def cleanup_old_backups(self, keep_count: int = None) -> int:
        """Очистка старых локальных бэкапов"""
        try:
            keep_count = keep_count or self.max_local_backups
            
            # Получаем все бэкапы, отсортированные по дате
            backups = sorted(
                self.backup_dir.glob("*backup_*.sql*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            files_backups = sorted(
                self.backup_dir.glob("files_backup_*.tar.gz"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            removed_count = 0
            
            # Удаляем старые бэкапы БД
            for backup in backups[keep_count:]:
                try:
                    backup.unlink()
                    removed_count += 1
                    logger.info(f"🗑️ Removed old backup: {backup.name}")
                except Exception as e:
                    logger.warning(f"Failed to remove {backup.name}: {e}")
            
            # Удаляем старые бэкапы файлов
            for backup in files_backups[keep_count:]:
                try:
                    backup.unlink()
                    removed_count += 1
                    logger.info(f"🗑️ Removed old backup: {backup.name}")
                except Exception as e:
                    logger.warning(f"Failed to remove {backup.name}: {e}")
            
            if removed_count > 0:
                logger.info(f"✅ Cleaned up {removed_count} old backup(s)")
            else:
                logger.info("ℹ️ No old backups to clean up")
            
            return removed_count
            
        except Exception as e:
            logger.error(f"❌ Failed to cleanup old backups: {e}")
            return 0
    
    async def restore_database(self, backup_path: Path, drop_existing: bool = False) -> bool:
        """Восстановление базы данных из бэкапа"""
        try:
            if not backup_path.exists():
                logger.error(f"❌ Backup file not found: {backup_path}")
                return False
            
            logger.info(f"🔄 Restoring database from: {backup_path.name}")
            
            # Определяем, сжат ли файл
            if backup_path.suffix == '.gz':
                # Распаковываем временно
                temp_path = backup_path.with_suffix('')
                with gzip.open(backup_path, 'rb') as f_in:
                    with open(temp_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                restore_path = temp_path
            else:
                restore_path = backup_path
            
            # Команда psql для восстановления
            restore_cmd = [
                "psql",
                f"--host={settings.POSTGRES_SERVER}",
                f"--port={settings.POSTGRES_PORT}",
                f"--username={settings.POSTGRES_USER}",
                f"--dbname={settings.POSTGRES_DB}",
                "--verbose",
                f"--file={restore_path}"
            ]
            
            # Если нужно удалить существующие данные
            if drop_existing:
                logger.warning("⚠️ Dropping existing data before restore")
                # Здесь можно добавить DROP команды или использовать --clean в pg_dump
            
            # Устанавливаем пароль через переменную окружения
            env = os.environ.copy()
            env['PGPASSWORD'] = settings.POSTGRES_PASSWORD
            
            # Выполняем восстановление
            result = subprocess.run(restore_cmd, env=env, capture_output=True, text=True)
            
            # Удаляем временный файл если был
            if backup_path.suffix == '.gz' and restore_path != backup_path:
                restore_path.unlink()
            
            if result.returncode != 0:
                logger.error(f"❌ Database restore failed: {result.stderr}")
                return False
            
            logger.info("✅ Database restored successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to restore database: {e}")
            return False
    
    def list_backups(self) -> Dict[str, List[Dict[str, Any]]]:
        """Список всех бэкапов"""
        try:
            db_backups = []
            files_backups = []
            
            # Бэкапы БД
            for backup in sorted(self.backup_dir.glob("db_backup_*.sql*"), key=lambda p: p.stat().st_mtime, reverse=True):
                stat = backup.stat()
                db_backups.append({
                    'name': backup.name,
                    'path': str(backup),
                    'size_mb': stat.st_size / (1024 * 1024),
                    'created_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'compressed': backup.suffix == '.gz'
                })
            
            # Бэкапы файлов
            for backup in sorted(self.backup_dir.glob("files_backup_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True):
                stat = backup.stat()
                files_backups.append({
                    'name': backup.name,
                    'path': str(backup),
                    'size_mb': stat.st_size / (1024 * 1024),
                    'created_at': datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            
            return {
                'database_backups': db_backups,
                'files_backups': files_backups
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to list backups: {e}")
            return {'database_backups': [], 'files_backups': []}
    
    async def verify_backup(self, backup_path: Path) -> Dict[str, Any]:
        """Проверка целостности бэкапа"""
        try:
            logger.info(f"🔍 Verifying backup: {backup_path.name}")
            
            verification = {
                'file_exists': backup_path.exists(),
                'file_size': 0,
                'readable': False,
                'metadata_found': False,
                'sql_syntax_ok': False,
                'estimated_records': 0
            }
            
            if not verification['file_exists']:
                return verification
            
            verification['file_size'] = backup_path.stat().st_size
            
            # Проверяем читаемость файла
            try:
                if backup_path.suffix == '.gz':
                    with gzip.open(backup_path, 'rt', encoding='utf-8') as f:
                        first_lines = [f.readline() for _ in range(10)]
                else:
                    with open(backup_path, 'r', encoding='utf-8') as f:
                        first_lines = [f.readline() for _ in range(10)]
                
                verification['readable'] = True
                
                # Проверяем метаданные
                for line in first_lines:
                    if 'Backup metadata:' in line:
                        verification['metadata_found'] = True
                        break
                
                # Проверяем SQL синтаксис (базовая проверка)
                sql_keywords = ['CREATE', 'INSERT', 'UPDATE', 'DELETE', 'SELECT']
                content = ' '.join(first_lines).upper()
                if any(keyword in content for keyword in sql_keywords):
                    verification['sql_syntax_ok'] = True
                
            except Exception as e:
                logger.warning(f"Failed to read backup file: {e}")
            
            # Примерная оценка количества записей
            if verification['readable']:
                try:
                    if backup_path.suffix == '.gz':
                        with gzip.open(backup_path, 'rt', encoding='utf-8') as f:
                            content = f.read()
                    else:
                        with open(backup_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                    
                    insert_count = content.count('INSERT INTO')
                    verification['estimated_records'] = insert_count
                    
                except Exception as e:
                    logger.warning(f"Failed to estimate records: {e}")
            
            # Итоговая оценка
            verification['is_valid'] = (
                verification['file_exists'] and
                verification['readable'] and
                verification['sql_syntax_ok'] and
                verification['file_size'] > 1024  # Минимум 1KB
            )
            
            if verification['is_valid']:
                logger.info("✅ Backup verification passed")
            else:
                logger.warning("⚠️ Backup verification failed")
            
            return verification
            
        except Exception as e:
            logger.error(f"❌ Backup verification failed: {e}")
            return {'is_valid': False, 'error': str(e)}
    
    async def schedule_backup(self, interval_hours: int = 24, keep_count: int = 7):
        """Планировщик автоматических бэкапов"""
        logger.info(f"⏰ Starting backup scheduler: every {interval_hours}h, keep {keep_count} backups")
        
        while True:
            try:
                # Создаем бэкап
                backups = await self.create_full_backup()
                
                if backups:
                    # Загружаем в S3 если настроен
                    for backup in backups:
                        await self.upload_to_s3(backup)
                    
                    # Очищаем старые бэкапы
                    self.cleanup_old_backups(keep_count)
                    
                    logger.info(f"✅ Scheduled backup completed: {len(backups)} files")
                else:
                    logger.error("❌ Scheduled backup failed")
                
                # Ждем следующий интервал
                await asyncio.sleep(interval_hours * 3600)
                
            except KeyboardInterrupt:
                logger.info("🛑 Backup scheduler stopped")
                break
            except Exception as e:
                logger.error(f"❌ Backup scheduler error: {e}")
                # Ждем меньше при ошибке
                await asyncio.sleep(300)  # 5 минут


async def main():
    """Основная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Database and files backup management")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Создание бэкапов
    db_parser = subparsers.add_parser('db', help='Create database backup')
    db_parser.add_argument('--no-compress', action='store_true', help='Skip compression')
    
    files_parser = subparsers.add_parser('files', help='Create files backup')
    files_parser.add_argument('--include-logs', action='store_true', help='Include log files')
    
    full_parser = subparsers.add_parser('full', help='Create full backup (DB + files)')
    full_parser.add_argument('--no-compress', action='store_true', help='Skip DB compression')
    full_parser.add_argument('--include-logs', action='store_true', help='Include log files')
    
    # Восстановление
    restore_parser = subparsers.add_parser('restore', help='Restore database from backup')
    restore_parser.add_argument('backup_file', help='Backup file path')
    restore_parser.add_argument('--drop-existing', action='store_true', help='Drop existing data')
    
    # Управление
    list_parser = subparsers.add_parser('list', help='List all backups')
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up old backups')
    cleanup_parser.add_argument('--keep', type=int, default=7, help='Number of backups to keep')
    
    verify_parser = subparsers.add_parser('verify', help='Verify backup integrity')
    verify_parser.add_argument('backup_file', help='Backup file path')
    
    # Планировщик
    schedule_parser = subparsers.add_parser('schedule', help='Run backup scheduler')
    schedule_parser.add_argument('--interval', type=int, default=24, help='Backup interval in hours')
    schedule_parser.add_argument('--keep', type=int, default=7, help='Number of backups to keep')
    
    # S3 операции
    s3_parser = subparsers.add_parser('upload', help='Upload backup to S3')
    s3_parser.add_argument('backup_file', help='Backup file path')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    manager = BackupManager()
    
    try:
        if args.command == 'db':
            backup = await manager.create_database_backup(compress=not args.no_compress)
            if backup:
                print(f"✅ Database backup created: {backup}")
            else:
                sys.exit(1)
        
        elif args.command == 'files':
            backup = await manager.create_files_backup(include_logs=args.include_logs)
            if backup:
                print(f"✅ Files backup created: {backup}")
            else:
                sys.exit(1)
        
        elif args.command == 'full':
            backups = await manager.create_full_backup(
                compress_db=not args.no_compress,
                include_logs=args.include_logs
            )
            if backups:
                print(f"✅ Full backup created: {len(backups)} files")
                for backup in backups:
                    print(f"  📁 {backup}")
            else:
                sys.exit(1)
        
        elif args.command == 'restore':
            backup_path = Path(args.backup_file)
            success = await manager.restore_database(backup_path, args.drop_existing)
            if success:
                print("✅ Database restored successfully")
            else:
                sys.exit(1)
        
        elif args.command == 'list':
            backups = manager.list_backups()
            
            print("📊 Available backups:\n")
            
            print("🗄️ Database backups:")
            for backup in backups['database_backups']:
                print(f"  📁 {backup['name']} ({backup['size_mb']:.1f} MB) - {backup['created_at']}")
            
            print(f"\n📁 Files backups:")
            for backup in backups['files_backups']:
                print(f"  📦 {backup['name']} ({backup['size_mb']:.1f} MB) - {backup['created_at']}")
        
        elif args.command == 'cleanup':
            removed = manager.cleanup_old_backups(args.keep)
            print(f"✅ Cleaned up {removed} old backup(s)")
        
        elif args.command == 'verify':
            backup_path = Path(args.backup_file)
            verification = await manager.verify_backup(backup_path)
            
            print(f"🔍 Backup verification results:")
            for key, value in verification.items():
                print(f"  {key}: {value}")
            
            if not verification.get('is_valid', False):
                sys.exit(1)
        
        elif args.command == 'upload':
            backup_path = Path(args.backup_file)
            success = await manager.upload_to_s3(backup_path)
            if success:
                print("✅ Backup uploaded to S3")
            else:
                sys.exit(1)
        
        elif args.command == 'schedule':
            await manager.schedule_backup(args.interval, args.keep)
        
    except KeyboardInterrupt:
        logger.info("🛑 Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Command failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())