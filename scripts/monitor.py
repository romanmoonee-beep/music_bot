#!/usr/bin/env python3
"""
Скрипт мониторинга системы и здоровья приложения
"""
import asyncio
import sys
import time
import psutil
import aiohttp
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import json

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.logging import get_logger
from app.core.database import get_session, get_database_stats, db_manager
from app.services.music import create_music_aggregator

logger = get_logger(__name__)


class SystemMonitor:
    """Монитор системы и приложения"""
    
    def __init__(self):
        self.start_time = time.time()
        self.checks_history = []
        self.max_history = 100
        
        # Пороги для алертов
        self.thresholds = {
            'cpu_percent': 80,
            'memory_percent': 85,
            'disk_percent': 90,
            'db_connections': 80,
            'response_time_ms': 5000
        }
    
    async def check_system_resources(self) -> Dict[str, Any]:
        """Проверка системных ресурсов"""
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            load_avg = psutil.getloadavg() if hasattr(psutil, 'getloadavg') else (0, 0, 0)
            
            # Память
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # Диск
            disk = psutil.disk_usage('/')
            
            # Сеть
            network = psutil.net_io_counters()
            
            return {
                'cpu': {
                    'percent': cpu_percent,
                    'count': cpu_count,
                    'load_avg_1m': load_avg[0],
                    'load_avg_5m': load_avg[1],
                    'load_avg_15m': load_avg[2],
                    'status': 'warning' if cpu_percent > self.thresholds['cpu_percent'] else 'ok'
                },
                'memory': {
                    'total_gb': memory.total / (1024**3),
                    'available_gb': memory.available / (1024**3),
                    'used_gb': memory.used / (1024**3),
                    'percent': memory.percent,
                    'swap_total_gb': swap.total / (1024**3),
                    'swap_used_gb': swap.used / (1024**3),
                    'swap_percent': swap.percent,
                    'status': 'warning' if memory.percent > self.thresholds['memory_percent'] else 'ok'
                },
                'disk': {
                    'total_gb': disk.total / (1024**3),
                    'used_gb': disk.used / (1024**3),
                    'free_gb': disk.free / (1024**3),
                    'percent': (disk.used / disk.total) * 100,
                    'status': 'warning' if (disk.used / disk.total) * 100 > self.thresholds['disk_percent'] else 'ok'
                },
                'network': {
                    'bytes_sent': network.bytes_sent,
                    'bytes_recv': network.bytes_recv,
                    'packets_sent': network.packets_sent,
                    'packets_recv': network.packets_recv
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to check system resources: {e}")
            return {'error': str(e)}
    
    async def check_database_health(self) -> Dict[str, Any]:
        """Проверка здоровья базы данных"""
        try:
            start_time = time.time()
            
            # Проверка подключения
            connection_ok = await db_manager.check_connection()
            response_time = (time.time() - start_time) * 1000
            
            if not connection_ok:
                return {
                    'status': 'error',
                    'connection': False,
                    'response_time_ms': response_time,
                    'error': 'Cannot connect to database'
                }
            
            # Получение статистики
            stats = await get_database_stats()
            
            # Проверка производительности
            async with get_session() as session:
                # Простой запрос для проверки производительности
                start_query = time.time()
                await session.execute(text("SELECT 1"))
                query_time = (time.time() - start_query) * 1000
                
                # Проверка активных подключений
                active_connections_result = await session.execute(
                    text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
                )
                active_connections = active_connections_result.scalar()
                
                # Проверка заблокированных запросов
                blocked_queries_result = await session.execute(
                    text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type IS NOT NULL")
                )
                blocked_queries = blocked_queries_result.scalar()
                
                # Проверка размера базы данных
                db_size_result = await session.execute(
                    text("SELECT pg_database_size(current_database())")
                )
                db_size_bytes = db_size_result.scalar()
            
            return {
                'status': 'ok',
                'connection': True,
                'response_time_ms': response_time,
                'query_time_ms': query_time,
                'database_size_gb': db_size_bytes / (1024**3),
                'active_connections': active_connections,
                'blocked_queries': blocked_queries,
                'stats': stats,
                'warnings': []
            }
            
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                'status': 'error',
                'connection': False,
                'error': str(e)
            }
    
    async def check_music_services(self) -> Dict[str, Any]:
        """Проверка музыкальных сервисов"""
        try:
            async with create_music_aggregator() as aggregator:
                # Проверка здоровья всех сервисов
                health_results = await aggregator.health_check_all()
                
                # Получение статистики
                service_stats = aggregator.get_service_stats()
                
                # Тестовый поиск
                start_time = time.time()
                test_results = await aggregator.search("test", limit=1)
                search_time = (time.time() - start_time) * 1000
                
                # Подсчет здоровых сервисов
                healthy_services = sum(1 for health in health_results.values() 
                                     if health.get('status') == 'healthy')
                total_services = len(health_results)
                
                return {
                    'status': 'ok' if healthy_services > 0 else 'error',
                    'healthy_services': healthy_services,
                    'total_services': total_services,
                    'health_results': health_results,
                    'service_stats': service_stats,
                    'test_search_time_ms': search_time,
                    'test_results_count': len(test_results)
                }
                
        except Exception as e:
            logger.error(f"Music services health check failed: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def check_external_apis(self) -> Dict[str, Any]:
        """Проверка внешних API"""
        try:
            results = {}
            
            # Проверяем основные сервисы
            apis_to_check = [
                {
                    'name': 'Telegram Bot API',
                    'url': f'https://api.telegram.org/bot{settings.BOT_TOKEN}/getMe',
                    'timeout': 10
                },
                {
                    'name': 'VK API',
                    'url': 'https://api.vk.com/method/utils.getServerTime?v=5.131',
                    'timeout': 10
                },
                {
                    'name': 'YouTube API',
                    'url': 'https://www.googleapis.com/youtube/v3/search?part=snippet&q=test&key=' + (settings.YOUTUBE_API_KEY or 'test'),
                    'timeout': 10
                } if settings.YOUTUBE_API_KEY else None,
                {
                    'name': 'Spotify API',
                    'url': 'https://api.spotify.com/v1/browse/categories',
                    'timeout': 10
                }
            ]
            
            # Фильтруем None значения
            apis_to_check = [api for api in apis_to_check if api is not None]
            
            async with aiohttp.ClientSession() as session:
                for api in apis_to_check:
                    try:
                        start_time = time.time()
                        
                        async with session.get(
                            api['url'],
                            timeout=aiohttp.ClientTimeout(total=api['timeout'])
                        ) as response:
                            response_time = (time.time() - start_time) * 1000
                            
                            results[api['name']] = {
                                'status': 'ok' if response.status < 400 else 'error',
                                'status_code': response.status,
                                'response_time_ms': response_time,
                                'available': response.status < 500
                            }
                            
                    except asyncio.TimeoutError:
                        results[api['name']] = {
                            'status': 'timeout',
                            'available': False,
                            'error': 'Request timeout'
                        }
                    except Exception as e:
                        results[api['name']] = {
                            'status': 'error',
                            'available': False,
                            'error': str(e)
                        }
            
            # Подсчитываем доступные API
            available_apis = sum(1 for result in results.values() 
                               if result.get('available', False))
            total_apis = len(results)
            
            return {
                'status': 'ok' if available_apis > 0 else 'error',
                'available_apis': available_apis,
                'total_apis': total_apis,
                'results': results
            }
            
        except Exception as e:
            logger.error(f"External APIs check failed: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def check_application_health(self) -> Dict[str, Any]:
        """Проверка здоровья приложения"""
        try:
            uptime = time.time() - self.start_time
            
            # Проверяем процессы Python
            python_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
                try:
                    if 'python' in proc.info['name'].lower():
                        python_processes.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'memory_mb': proc.info['memory_info'].rss / (1024 * 1024),
                            'cpu_percent': proc.info['cpu_percent']
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Проверяем логи
            logs_dir = Path(settings.LOGS_DIR)
            log_files = []
            if logs_dir.exists():
                for log_file in logs_dir.glob("*.log"):
                    stat = log_file.stat()
                    log_files.append({
                        'name': log_file.name,
                        'size_mb': stat.st_size / (1024 * 1024),
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
            
            # Проверяем временные файлы
            temp_dir = Path(settings.TEMP_DIR)
            temp_files_count = 0
            temp_files_size = 0
            if temp_dir.exists():
                for temp_file in temp_dir.glob("*"):
                    temp_files_count += 1
                    temp_files_size += temp_file.stat().st_size
            
            return {
                'status': 'ok',
                'uptime_seconds': uptime,
                'uptime_formatted': self._format_uptime(uptime),
                'python_processes': python_processes,
                'log_files': log_files,
                'temp_files': {
                    'count': temp_files_count,
                    'size_mb': temp_files_size / (1024 * 1024)
                },
                'environment': settings.ENVIRONMENT,
                'version': settings.VERSION
            }
            
        except Exception as e:
            logger.error(f"Application health check failed: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def _format_uptime(self, seconds: float) -> str:
        """Форматирование времени работы"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
    async def full_health_check(self) -> Dict[str, Any]:
        """Полная проверка здоровья системы"""
        try:
            logger.info("🔍 Starting full health check...")
            
            start_time = time.time()
            
            # Выполняем все проверки параллельно
            system_task = asyncio.create_task(self.check_system_resources())
            database_task = asyncio.create_task(self.check_database_health())
            music_task = asyncio.create_task(self.check_music_services())
            apis_task = asyncio.create_task(self.check_external_apis())
            app_task = asyncio.create_task(self.check_application_health())
            
            # Ждем завершения всех проверок
            system_health = await system_task
            database_health = await database_task
            music_health = await music_task
            apis_health = await apis_task
            app_health = await app_task
            
            check_duration = time.time() - start_time
            
            # Определяем общий статус
            all_statuses = [
                database_health.get('status'),
                music_health.get('status'),
                apis_health.get('status'),
                app_health.get('status')
            ]
            
            # Проверяем системные ресурсы
            system_warnings = []
            if system_health.get('cpu', {}).get('status') == 'warning':
                system_warnings.append('High CPU usage')
            if system_health.get('memory', {}).get('status') == 'warning':
                system_warnings.append('High memory usage')
            if system_health.get('disk', {}).get('status') == 'warning':
                system_warnings.append('Low disk space')
            
            # Определяем общий статус
            overall_status = 'ok'
            if 'error' in all_statuses:
                overall_status = 'error'
            elif system_warnings or 'warning' in all_statuses:
                overall_status = 'warning'
            
            result = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'overall_status': overall_status,
                'check_duration_ms': check_duration * 1000,
                'system': system_health,
                'database': database_health,
                'music_services': music_health,
                'external_apis': apis_health,
                'application': app_health,
                'warnings': system_warnings
            }
            
            # Сохраняем в историю
            self.checks_history.append(result)
            if len(self.checks_history) > self.max_history:
                self.checks_history.pop(0)
            
            logger.info(f"✅ Health check completed in {check_duration:.2f}s: {overall_status}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Full health check failed: {e}")
            return {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'overall_status': 'error',
                'error': str(e)
            }
    
    async def generate_health_report(self) -> Dict[str, Any]:
        """Генерация отчета о здоровье системы"""
        try:
            # Получаем текущий статус
            current_health = await self.full_health_check()
            
            # Анализируем историю
            history_analysis = self._analyze_history()
            
            # Рекомендации
            recommendations = self._generate_recommendations(current_health)
            
            return {
                'report_generated_at': datetime.now(timezone.utc).isoformat(),
                'current_status': current_health,
                'history_analysis': history_analysis,
                'recommendations': recommendations,
                'summary': {
                    'overall_health': current_health.get('overall_status'),
                    'critical_issues': len([w for w in current_health.get('warnings', [])]),
                    'uptime': current_health.get('application', {}).get('uptime_formatted'),
                    'last_errors': self._get_recent_errors()
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to generate health report: {e}")
            return {'error': str(e)}
    
    def _analyze_history(self) -> Dict[str, Any]:
        """Анализ истории проверок"""
        if not self.checks_history:
            return {'no_data': True}
        
        try:
            # Статистика за последние проверки
            recent_checks = self.checks_history[-10:]  # Последние 10 проверок
            
            status_counts = {}
            avg_response_times = []
            
            for check in recent_checks:
                status = check.get('overall_status', 'unknown')
                status_counts[status] = status_counts.get(status, 0) + 1
                
                if 'check_duration_ms' in check:
                    avg_response_times.append(check['check_duration_ms'])
            
            return {
                'total_checks': len(self.checks_history),
                'recent_checks': len(recent_checks),
                'status_distribution': status_counts,
                'avg_check_duration_ms': sum(avg_response_times) / len(avg_response_times) if avg_response_times else 0,
                'stability_score': status_counts.get('ok', 0) / len(recent_checks) * 100 if recent_checks else 0
            }
            
        except Exception as e:
            logger.error(f"History analysis failed: {e}")
            return {'error': str(e)}
    
    def _generate_recommendations(self, health_data: Dict[str, Any]) -> List[str]:
        """Генерация рекомендаций по улучшению"""
        recommendations = []
        
        try:
            # Системные ресурсы
            system = health_data.get('system', {})
            
            if system.get('cpu', {}).get('percent', 0) > 80:
                recommendations.append("Consider upgrading CPU or optimizing application performance")
            
            if system.get('memory', {}).get('percent', 0) > 85:
                recommendations.append("Memory usage is high - consider adding more RAM or optimizing memory usage")
            
            if system.get('disk', {}).get('percent', 0) > 90:
                recommendations.append("Disk space is critically low - clean up old files or add more storage")
            
            # База данных
            database = health_data.get('database', {})
            
            if database.get('active_connections', 0) > 50:
                recommendations.append("High number of database connections - consider connection pooling optimization")
            
            if database.get('query_time_ms', 0) > 1000:
                recommendations.append("Database queries are slow - check indexes and query optimization")
            
            # Музыкальные сервисы
            music = health_data.get('music_services', {})
            
            if music.get('healthy_services', 0) < music.get('total_services', 0):
                recommendations.append("Some music services are unhealthy - check API credentials and network connectivity")
            
            # Внешние API
            apis = health_data.get('external_apis', {})
            
            if apis.get('available_apis', 0) < apis.get('total_apis', 0):
                recommendations.append("Some external APIs are unavailable - verify API keys and endpoints")
            
            # Приложение
            app = health_data.get('application', {})
            temp_files = app.get('temp_files', {})
            
            if temp_files.get('size_mb', 0) > 100:
                recommendations.append("Large amount of temporary files - consider cleanup")
            
            if not recommendations:
                recommendations.append("System is running well - no immediate actions required")
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Failed to generate recommendations: {e}")
            return ["Error generating recommendations"]
    
    def _get_recent_errors(self) -> List[str]:
        """Получение последних ошибок"""
        try:
            recent_errors = []
            
            for check in reversed(self.checks_history[-5:]):  # Последние 5 проверок
                if check.get('overall_status') == 'error':
                    error_msg = check.get('error', 'Unknown error')
                    timestamp = check.get('timestamp', 'Unknown time')
                    recent_errors.append(f"{timestamp}: {error_msg}")
                
                # Проверяем ошибки в компонентах
                for component in ['database', 'music_services', 'external_apis', 'application']:
                    comp_data = check.get(component, {})
                    if comp_data.get('status') == 'error':
                        error_msg = comp_data.get('error', f'{component} error')
                        timestamp = check.get('timestamp', 'Unknown time')
                        recent_errors.append(f"{timestamp} ({component}): {error_msg}")
            
            return recent_errors[:5]  # Максимум 5 последних ошибок
            
        except Exception as e:
            logger.error(f"Failed to get recent errors: {e}")
            return []
    
    async def monitor_loop(self, interval_seconds: int = 300, alert_webhook: Optional[str] = None):
        """Непрерывный мониторинг"""
        logger.info(f"🔄 Starting monitoring loop: checking every {interval_seconds}s")
        
        while True:
            try:
                # Выполняем проверку
                health = await self.full_health_check()
                
                # Отправляем алерты если есть проблемы
                if health.get('overall_status') in ['error', 'warning'] and alert_webhook:
                    await self._send_alert(health, alert_webhook)
                
                # Выводим краткий статус
                status = health.get('overall_status', 'unknown')
                emoji = "✅" if status == 'ok' else "⚠️" if status == 'warning' else "❌"
                logger.info(f"{emoji} System status: {status}")
                
                # Ждем следующую проверку
                await asyncio.sleep(interval_seconds)
                
            except KeyboardInterrupt:
                logger.info("🛑 Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"❌ Monitoring loop error: {e}")
                await asyncio.sleep(60)  # Короткая пауза при ошибке
    
    async def _send_alert(self, health_data: Dict[str, Any], webhook_url: str):
        """Отправка алерта через webhook"""
        try:
            alert_data = {
                'timestamp': health_data.get('timestamp'),
                'status': health_data.get('overall_status'),
                'warnings': health_data.get('warnings', []),
                'critical_components': [],
                'summary': f"System status: {health_data.get('overall_status')}"
            }
            
            # Определяем критичные компоненты
            for component in ['database', 'music_services', 'application']:
                comp_data = health_data.get(component, {})
                if comp_data.get('status') in ['error', 'warning']:
                    alert_data['critical_components'].append({
                        'component': component,
                        'status': comp_data.get('status'),
                        'error': comp_data.get('error')
                    })
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=alert_data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        logger.info("📢 Alert sent successfully")
                    else:
                        logger.warning(f"⚠️ Alert webhook returned status {response.status}")
                        
        except Exception as e:
            logger.error(f"❌ Failed to send alert: {e}")
    
    def export_metrics(self, format: str = 'json') -> str:
        """Экспорт метрик в различных форматах"""
        try:
            if not self.checks_history:
                return "No data available"
            
            latest_check = self.checks_history[-1]
            
            if format == 'json':
                return json.dumps(latest_check, indent=2)
            
            elif format == 'prometheus':
                # Формат Prometheus metrics
                metrics = []
                
                # Системные метрики
                system = latest_check.get('system', {})
                metrics.append(f"system_cpu_percent {system.get('cpu', {}).get('percent', 0)}")
                metrics.append(f"system_memory_percent {system.get('memory', {}).get('percent', 0)}")
                metrics.append(f"system_disk_percent {system.get('disk', {}).get('percent', 0)}")
                
                # База данных
                database = latest_check.get('database', {})
                metrics.append(f"database_response_time_ms {database.get('response_time_ms', 0)}")
                metrics.append(f"database_active_connections {database.get('active_connections', 0)}")
                
                # Музыкальные сервисы
                music = latest_check.get('music_services', {})
                metrics.append(f"music_services_healthy {music.get('healthy_services', 0)}")
                metrics.append(f"music_services_total {music.get('total_services', 0)}")
                
                return '\n'.join(metrics)
            
            elif format == 'csv':
                # CSV формат
                import csv
                import io
                
                output = io.StringIO()
                writer = csv.writer(output)
                
                # Заголовки
                writer.writerow(['timestamp', 'overall_status', 'cpu_percent', 'memory_percent', 'disk_percent', 'db_response_ms'])
                
                # Данные
                for check in self.checks_history[-10:]:  # Последние 10
                    system = check.get('system', {})
                    database = check.get('database', {})
                    
                    writer.writerow([
                        check.get('timestamp'),
                        check.get('overall_status'),
                        system.get('cpu', {}).get('percent', 0),
                        system.get('memory', {}).get('percent', 0),
                        system.get('disk', {}).get('percent', 0),
                        database.get('response_time_ms', 0)
                    ])
                
                return output.getvalue()
            
            else:
                return "Unsupported format"
                
        except Exception as e:
            logger.error(f"Failed to export metrics: {e}")
            return f"Export error: {e}"


async def main():
    """Основная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(description="System monitoring and health checks")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Одноразовые проверки
    check_parser = subparsers.add_parser('check', help='Run full health check')
    system_parser = subparsers.add_parser('system', help='Check system resources')
    db_parser = subparsers.add_parser('database', help='Check database health')
    music_parser = subparsers.add_parser('music', help='Check music services')
    apis_parser = subparsers.add_parser('apis', help='Check external APIs')
    
    # Отчеты
    report_parser = subparsers.add_parser('report', help='Generate health report')
    metrics_parser = subparsers.add_parser('metrics', help='Export metrics')
    metrics_parser.add_argument('--format', choices=['json', 'prometheus', 'csv'], default='json')
    
    # Мониторинг
    monitor_parser = subparsers.add_parser('monitor', help='Start monitoring loop')
    monitor_parser.add_argument('--interval', type=int, default=300, help='Check interval in seconds')
    monitor_parser.add_argument('--webhook', help='Alert webhook URL')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    monitor = SystemMonitor()
    
    try:
        if args.command == 'check':
            result = await monitor.full_health_check()
            print(json.dumps(result, indent=2))
        
        elif args.command == 'system':
            result = await monitor.check_system_resources()
            print(json.dumps(result, indent=2))
        
        elif args.command == 'database':
            result = await monitor.check_database_health()
            print(json.dumps(result, indent=2))
        
        elif args.command == 'music':
            result = await monitor.check_music_services()
            print(json.dumps(result, indent=2))
        
        elif args.command == 'apis':
            result = await monitor.check_external_apis()
            print(json.dumps(result, indent=2))
        
        elif args.command == 'report':
            result = await monitor.generate_health_report()
            print(json.dumps(result, indent=2))
        
        elif args.command == 'metrics':
            # Сначала делаем проверку чтобы были данные
            await monitor.full_health_check()
            result = monitor.export_metrics(args.format)
            print(result)
        
        elif args.command == 'monitor':
            await monitor.monitor_loop(args.interval, args.webhook)
        
    except KeyboardInterrupt:
        logger.info("🛑 Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Command failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())