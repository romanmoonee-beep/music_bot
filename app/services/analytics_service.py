"""
Сервис аналитики для сбора и анализа метрик
"""
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from enum import Enum
import json

from app.core.database import get_session
from app.core.logging import get_logger
from app.core.config import settings
from app.models.analytics import (
    UserEvent, EventType, SearchEvent, DownloadEvent, 
    PlaybackEvent, UserSession, BotMetrics
)
from app.models.user import User, UserSubscription, SubscriptionType
from app.models.track import Track, TrackPlay
from app.models.playlist import Playlist
from app.models.search import SearchHistory
from app.models.subscription import Payment, PaymentStatus
from app.services.cache_service import system_cache
from sqlalchemy.future import select
from sqlalchemy import func, and_, or_, text
from sqlalchemy.orm import selectinload


class MetricType(str, Enum):
    """Типы метрик"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class Metric:
    """Метрика для отправки"""
    name: str
    value: float
    metric_type: MetricType
    tags: Dict[str, str] = None
    timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = {}
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


class AnalyticsService:
    """Сервис для сбора и анализа метрик"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.metrics_buffer = []
        self.buffer_size = 100
        
    async def track_user_event(
        self,
        user_id: int,
        event_type: EventType,
        event_data: Dict[str, Any] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """Отследить пользовательское событие"""
        try:
            async with get_session() as session:
                event = UserEvent(
                    user_id=user_id,
                    event_type=event_type,
                    event_data=event_data or {},
                    session_id=session_id,
                    created_at=datetime.now(timezone.utc)
                )
                
                session.add(event)
                await session.commit()
                
                # Отправляем метрику
                await self._send_metric(Metric(
                    name="user_event",
                    value=1,
                    metric_type=MetricType.COUNTER,
                    tags={
                        "event_type": event_type.value,
                        "user_id": str(user_id)
                    }
                ))
                
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to track user event: {e}")
            return False
    
    async def track_search_event(
        self,
        user_id: int,
        query: str,
        results_count: int,
        search_time: float,
        sources_used: List[str],
        session_id: Optional[str] = None
    ) -> bool:
        """Отследить событие поиска"""
        try:
            async with get_session() as session:
                search_event = SearchEvent(
                    user_id=user_id,
                    query=query,
                    results_count=results_count,
                    search_time_ms=int(search_time * 1000),
                    sources_used=sources_used,
                    session_id=session_id,
                    created_at=datetime.now(timezone.utc)
                )
                
                session.add(search_event)
                await session.commit()
                
                # Отправляем метрики
                await self._send_metric(Metric(
                    name="search_request",
                    value=1,
                    metric_type=MetricType.COUNTER,
                    tags={"user_id": str(user_id)}
                ))
                
                await self._send_metric(Metric(
                    name="search_time",
                    value=search_time,
                    metric_type=MetricType.TIMER,
                    tags={"sources": ",".join(sources_used)}
                ))
                
                await self._send_metric(Metric(
                    name="search_results",
                    value=results_count,
                    metric_type=MetricType.GAUGE,
                    tags={"query_length": str(len(query))}
                ))
                
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to track search event: {e}")
            return False
    
    async def track_download_event(
        self,
        user_id: int,
        track_id: int,
        source: str,
        success: bool,
        download_time: Optional[float] = None,
        file_size: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """Отследить событие скачивания"""
        try:
            async with get_session() as session:
                download_event = DownloadEvent(
                    user_id=user_id,
                    track_id=track_id,
                    source=source,
                    success=success,
                    download_time_ms=int(download_time * 1000) if download_time else None,
                    file_size_bytes=file_size,
                    session_id=session_id,
                    created_at=datetime.now(timezone.utc)
                )
                
                session.add(download_event)
                await session.commit()
                
                # Отправляем метрики
                await self._send_metric(Metric(
                    name="download_request",
                    value=1,
                    metric_type=MetricType.COUNTER,
                    tags={
                        "user_id": str(user_id),
                        "source": source,
                        "success": str(success).lower()
                    }
                ))
                
                if download_time:
                    await self._send_metric(Metric(
                        name="download_time",
                        value=download_time,
                        metric_type=MetricType.TIMER,
                        tags={"source": source}
                    ))
                
                if file_size:
                    await self._send_metric(Metric(
                        name="download_size",
                        value=file_size,
                        metric_type=MetricType.GAUGE,
                        tags={"source": source}
                    ))
                
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to track download event: {e}")
            return False
    
    async def track_playback_event(
        self,
        user_id: int,
        track_id: int,
        action: str,  # play, pause, stop, skip
        position: Optional[int] = None,
        duration: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """Отследить событие воспроизведения"""
        try:
            async with get_session() as session:
                playback_event = PlaybackEvent(
                    user_id=user_id,
                    track_id=track_id,
                    action=action,
                    position_ms=position,
                    duration_ms=duration,
                    session_id=session_id,
                    created_at=datetime.now(timezone.utc)
                )
                
                session.add(playback_event)
                await session.commit()
                
                # Отправляем метрику
                await self._send_metric(Metric(
                    name="playback_event",
                    value=1,
                    metric_type=MetricType.COUNTER,
                    tags={
                        "user_id": str(user_id),
                        "action": action
                    }
                ))
                
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to track playback event: {e}")
            return False
    
    async def start_user_session(
        self,
        user_id: int,
        session_id: str,
        platform: str = "telegram",
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> bool:
        """Начать пользовательскую сессию"""
        try:
            async with get_session() as session:
                user_session = UserSession(
                    user_id=user_id,
                    session_id=session_id,
                    platform=platform,
                    user_agent=user_agent,
                    ip_address=ip_address,
                    started_at=datetime.now(timezone.utc),
                    is_active=True
                )
                
                session.add(user_session)
                await session.commit()
                
                # Отправляем метрику
                await self._send_metric(Metric(
                    name="session_start",
                    value=1,
                    metric_type=MetricType.COUNTER,
                    tags={
                        "user_id": str(user_id),
                        "platform": platform
                    }
                ))
                
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to start user session: {e}")
            return False
    
    async def end_user_session(
        self,
        session_id: str,
        events_count: Optional[int] = None
    ) -> bool:
        """Завершить пользовательскую сессию"""
        try:
            async with get_session() as session:
                query = select(UserSession).where(
                    UserSession.session_id == session_id,
                    UserSession.is_active == True
                )
                result = await session.execute(query)
                user_session = result.scalar_one_or_none()
                
                if user_session:
                    user_session.ended_at = datetime.now(timezone.utc)
                    user_session.is_active = False
                    user_session.events_count = events_count
                    
                    # Вычисляем длительность сессии
                    duration = user_session.ended_at - user_session.started_at
                    user_session.duration_seconds = int(duration.total_seconds())
                    
                    await session.commit()
                    
                    # Отправляем метрику
                    await self._send_metric(Metric(
                        name="session_duration",
                        value=user_session.duration_seconds,
                        metric_type=MetricType.TIMER,
                        tags={
                            "user_id": str(user_session.user_id),
                            "platform": user_session.platform
                        }
                    ))
                
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to end user session: {e}")
            return False
    
    async def get_user_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Получить аналитику пользователей"""
        try:
            if not start_date:
                start_date = datetime.now(timezone.utc) - timedelta(days=30)
            if not end_date:
                end_date = datetime.now(timezone.utc)
            
            async with get_session() as session:
                # Общие метрики пользователей
                total_users_query = select(func.count(User.id)).where(
                    User.is_deleted == False
                )
                total_users_result = await session.execute(total_users_query)
                total_users = total_users_result.scalar()
                
                # Активные пользователи за период
                active_users_query = select(func.count(func.distinct(UserEvent.user_id))).where(
                    and_(
                        UserEvent.created_at >= start_date,
                        UserEvent.created_at <= end_date
                    )
                )
                active_users_result = await session.execute(active_users_query)
                active_users = active_users_result.scalar()
                
                # Новые пользователи за период
                new_users_query = select(func.count(User.id)).where(
                    and_(
                        User.created_at >= start_date,
                        User.created_at <= end_date,
                        User.is_deleted == False
                    )
                )
                new_users_result = await session.execute(new_users_query)
                new_users = new_users_result.scalar()
                
                # Premium пользователи
                premium_users_query = select(func.count(func.distinct(UserSubscription.user_id))).where(
                    and_(
                        UserSubscription.is_active == True,
                        UserSubscription.subscription_type == SubscriptionType.PREMIUM,
                        UserSubscription.expires_at > datetime.now(timezone.utc)
                    )
                )
                premium_users_result = await session.execute(premium_users_query)
                premium_users = premium_users_result.scalar()
                
                # Средняя длительность сессии
                avg_session_query = select(func.avg(UserSession.duration_seconds)).where(
                    and_(
                        UserSession.started_at >= start_date,
                        UserSession.started_at <= end_date,
                        UserSession.duration_seconds.isnot(None)
                    )
                )
                avg_session_result = await session.execute(avg_session_query)
                avg_session_duration = avg_session_result.scalar() or 0
                
                # Retention rate (пользователи, которые вернулись через неделю)
                week_ago = start_date + timedelta(days=7)
                if week_ago <= end_date:
                    retention_users_query = select(func.count(func.distinct(UserEvent.user_id))).where(
                        and_(
                            UserEvent.user_id.in_(
                                select(UserEvent.user_id).where(
                                    and_(
                                        UserEvent.created_at >= start_date,
                                        UserEvent.created_at < start_date + timedelta(days=1)
                                    )
                                )
                            ),
                            UserEvent.created_at >= week_ago,
                            UserEvent.created_at <= end_date
                        )
                    )
                    retention_users_result = await session.execute(retention_users_query)
                    retention_users = retention_users_result.scalar()
                    
                    retention_rate = (retention_users / new_users * 100) if new_users > 0 else 0
                else:
                    retention_rate = 0
                
                return {
                    "period": {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat()
                    },
                    "total_users": total_users,
                    "active_users": active_users,
                    "new_users": new_users,
                    "premium_users": premium_users,
                    "premium_conversion_rate": round((premium_users / total_users * 100), 2) if total_users > 0 else 0,
                    "avg_session_duration_seconds": round(avg_session_duration, 2),
                    "retention_rate_7d": round(retention_rate, 2)
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get user analytics: {e}")
            return {}
    
    async def get_content_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Получить аналитику контента"""
        try:
            if not start_date:
                start_date = datetime.now(timezone.utc) - timedelta(days=30)
            if not end_date:
                end_date = datetime.now(timezone.utc)
            
            async with get_session() as session:
                # Поисковая активность
                total_searches_query = select(func.count(SearchEvent.id)).where(
                    and_(
                        SearchEvent.created_at >= start_date,
                        SearchEvent.created_at <= end_date
                    )
                )
                total_searches_result = await session.execute(total_searches_query)
                total_searches = total_searches_result.scalar()
                
                # Средний результат поиска
                avg_results_query = select(func.avg(SearchEvent.results_count)).where(
                    and_(
                        SearchEvent.created_at >= start_date,
                        SearchEvent.created_at <= end_date
                    )
                )
                avg_results_result = await session.execute(avg_results_query)
                avg_search_results = avg_results_result.scalar() or 0
                
                # Среднее время поиска
                avg_time_query = select(func.avg(SearchEvent.search_time_ms)).where(
                    and_(
                        SearchEvent.created_at >= start_date,
                        SearchEvent.created_at <= end_date
                    )
                )
                avg_time_result = await session.execute(avg_time_query)
                avg_search_time = avg_time_result.scalar() or 0
                
                # Скачивания
                total_downloads_query = select(func.count(DownloadEvent.id)).where(
                    and_(
                        DownloadEvent.created_at >= start_date,
                        DownloadEvent.created_at <= end_date
                    )
                )
                total_downloads_result = await session.execute(total_downloads_query)
                total_downloads = total_downloads_result.scalar()
                
                # Успешные скачивания
                successful_downloads_query = select(func.count(DownloadEvent.id)).where(
                    and_(
                        DownloadEvent.created_at >= start_date,
                        DownloadEvent.created_at <= end_date,
                        DownloadEvent.success == True
                    )
                )
                successful_downloads_result = await session.execute(successful_downloads_query)
                successful_downloads = successful_downloads_result.scalar()
                
                # Популярные поисковые запросы
                popular_queries_query = select(
                    SearchEvent.query,
                    func.count(SearchEvent.id).label('count')
                ).where(
                    and_(
                        SearchEvent.created_at >= start_date,
                        SearchEvent.created_at <= end_date
                    )
                ).group_by(SearchEvent.query).order_by(
                    func.count(SearchEvent.id).desc()
                ).limit(10)
                
                popular_queries_result = await session.execute(popular_queries_query)
                popular_queries = [
                    {"query": row.query, "count": row.count}
                    for row in popular_queries_result
                ]
                
                # Статистика по источникам
                sources_stats = {}
                downloads_by_source_query = select(
                    DownloadEvent.source,
                    func.count(DownloadEvent.id).label('total'),
                    func.sum(func.cast(DownloadEvent.success, func.INTEGER)).label('successful')
                ).where(
                    and_(
                        DownloadEvent.created_at >= start_date,
                        DownloadEvent.created_at <= end_date
                    )
                ).group_by(DownloadEvent.source)
                
                downloads_by_source_result = await session.execute(downloads_by_source_query)
                for row in downloads_by_source_result:
                    sources_stats[row.source] = {
                        "total_downloads": row.total,
                        "successful_downloads": row.successful or 0,
                        "success_rate": round((row.successful or 0) / row.total * 100, 2) if row.total > 0 else 0
                    }
                
                download_success_rate = (successful_downloads / total_downloads * 100) if total_downloads > 0 else 0
                
                return {
                    "period": {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat()
                    },
                    "search_analytics": {
                        "total_searches": total_searches,
                        "avg_results_per_search": round(avg_search_results, 2),
                        "avg_search_time_ms": round(avg_search_time, 2),
                        "popular_queries": popular_queries
                    },
                    "download_analytics": {
                        "total_downloads": total_downloads,
                        "successful_downloads": successful_downloads,
                        "success_rate": round(download_success_rate, 2),
                        "sources_stats": sources_stats
                    }
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get content analytics: {e}")
            return {}
    
    async def get_realtime_metrics(self) -> Dict[str, Any]:
        """Получить метрики реального времени"""
        try:
            # Проверяем кеш
            cached_metrics = await system_cache.get("realtime_metrics", "metrics")
            if cached_metrics:
                return cached_metrics
            
            now = datetime.now(timezone.utc)
            hour_ago = now - timedelta(hours=1)
            day_ago = now - timedelta(days=1)
            
            async with get_session() as session:
                # Активные пользователи последний час
                active_hour_query = select(func.count(func.distinct(UserEvent.user_id))).where(
                    UserEvent.created_at >= hour_ago
                )
                active_hour_result = await session.execute(active_hour_query)
                active_users_hour = active_hour_result.scalar()
                
                # Активные сессии
                active_sessions_query = select(func.count(UserSession.id)).where(
                    UserSession.is_active == True
                )
                active_sessions_result = await session.execute(active_sessions_query)
                active_sessions = active_sessions_result.scalar()
                
                # Поиски последний час
                searches_hour_query = select(func.count(SearchEvent.id)).where(
                    SearchEvent.created_at >= hour_ago
                )
                searches_hour_result = await session.execute(searches_hour_query)
                searches_hour = searches_hour_result.scalar()
                
                # Скачивания последний час
                downloads_hour_query = select(func.count(DownloadEvent.id)).where(
                    DownloadEvent.created_at >= hour_ago
                )
                downloads_hour_result = await session.execute(downloads_hour_query)
                downloads_hour = downloads_hour_result.scalar()
                
                # Регистрации за день
                registrations_day_query = select(func.count(User.id)).where(
                    and_(
                        User.created_at >= day_ago,
                        User.is_deleted == False
                    )
                )
                registrations_day_result = await session.execute(registrations_day_query)
                registrations_day = registrations_day_result.scalar()
                
                metrics = {
                    "timestamp": now.isoformat(),
                    "active_users_1h": active_users_hour,
                    "active_sessions": active_sessions,
                    "searches_1h": searches_hour,
                    "downloads_1h": downloads_hour,
                    "registrations_24h": registrations_day,
                    "searches_per_minute": round(searches_hour / 60, 2),
                    "downloads_per_minute": round(downloads_hour / 60, 2)
                }
                
                # Кешируем на 1 минуту
                await system_cache.set("realtime_metrics", metrics, ttl=60, cache_type="metrics")
                
                return metrics
                
        except Exception as e:
            self.logger.error(f"Failed to get realtime metrics: {e}")
            return {}
    
    async def get_bot_performance_metrics(self) -> Dict[str, Any]:
        """Получить метрики производительности бота"""
        try:
            now = datetime.now(timezone.utc)
            hour_ago = now - timedelta(hours=1)
            
            async with get_session() as session:
                # Средние времена ответа
                avg_search_time_query = select(func.avg(SearchEvent.search_time_ms)).where(
                    SearchEvent.created_at >= hour_ago
                )
                avg_search_time_result = await session.execute(avg_search_time_query)
                avg_search_time = avg_search_time_result.scalar() or 0
                
                avg_download_time_query = select(func.avg(DownloadEvent.download_time_ms)).where(
                    and_(
                        DownloadEvent.created_at >= hour_ago,
                        DownloadEvent.download_time_ms.isnot(None)
                    )
                )
                avg_download_time_result = await session.execute(avg_download_time_query)
                avg_download_time = avg_download_time_result.scalar() or 0
                
                # Частота ошибок
                total_downloads_hour = await session.execute(
                    select(func.count(DownloadEvent.id)).where(
                        DownloadEvent.created_at >= hour_ago
                    )
                )
                total_downloads = total_downloads_hour.scalar()
                
                failed_downloads_hour = await session.execute(
                    select(func.count(DownloadEvent.id)).where(
                        and_(
                            DownloadEvent.created_at >= hour_ago,
                            DownloadEvent.success == False
                        )
                    )
                )
                failed_downloads = failed_downloads_hour.scalar()
                
                error_rate = (failed_downloads / total_downloads * 100) if total_downloads > 0 else 0
                
                return {
                    "timestamp": now.isoformat(),
                    "avg_search_time_ms": round(avg_search_time, 2),
                    "avg_download_time_ms": round(avg_download_time, 2),
                    "error_rate_percent": round(error_rate, 2),
                    "total_requests_1h": total_downloads,
                    "failed_requests_1h": failed_downloads
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get bot performance metrics: {e}")
            return {}
    
    async def save_bot_metrics(self, metrics_data: Dict[str, Any]) -> bool:
        """Сохранить общие метрики бота"""
        try:
            async with get_session() as session:
                bot_metrics = BotMetrics(
                    timestamp=datetime.now(timezone.utc),
                    metrics_data=metrics_data
                )
                
                session.add(bot_metrics)
                await session.commit()
                
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to save bot metrics: {e}")
            return False
    
    async def _send_metric(self, metric: Metric):
        """Отправить метрику в систему мониторинга"""
        try:
            # Добавляем в буфер
            self.metrics_buffer.append(metric)
            
            # Если буфер заполнен, отправляем метрики
            if len(self.metrics_buffer) >= self.buffer_size:
                await self._flush_metrics()
                
        except Exception as e:
            self.logger.error(f"Failed to send metric: {e}")
    
    async def _flush_metrics(self):
        """Отправить все метрики из буфера"""
        if not self.metrics_buffer:
            return
        
        try:
            # Здесь можно интегрировать с Prometheus, InfluxDB, CloudWatch и т.д.
            # Пока просто логируем
            self.logger.debug(f"Flushing {len(self.metrics_buffer)} metrics")
            
            # Очищаем буфер
            self.metrics_buffer.clear()
            
        except Exception as e:
            self.logger.error(f"Failed to flush metrics: {e}")
    
    async def cleanup_old_data(self, days_to_keep: int = 30) -> Dict[str, int]:
        """Очистка старых аналитических данных"""
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
            deleted_counts = {}
            
            async with get_session() as session:
                # Удаляем старые события
                events_delete = await session.execute(
                    text("DELETE FROM user_events WHERE created_at < :cutoff_date"),
                    {"cutoff_date": cutoff_date}
                )
                deleted_counts["user_events"] = events_delete.rowcount
                
                search_events_delete = await session.execute(
                    text("DELETE FROM search_events WHERE created_at < :cutoff_date"),
                    {"cutoff_date": cutoff_date}
                )
                deleted_counts["search_events"] = search_events_delete.rowcount
                
                download_events_delete = await session.execute(
                    text("DELETE FROM download_events WHERE created_at < :cutoff_date"),
                    {"cutoff_date": cutoff_date}
                )
                deleted_counts["download_events"] = download_events_delete.rowcount
                
                playback_events_delete = await session.execute(
                    text("DELETE FROM playback_events WHERE created_at < :cutoff_date"),
                    {"cutoff_date": cutoff_date}
                )
                deleted_counts["playback_events"] = playback_events_delete.rowcount
                
                # Удаляем старые сессии
                sessions_delete = await session.execute(
                    text("DELETE FROM user_sessions WHERE started_at < :cutoff_date"),
                    {"cutoff_date": cutoff_date}
                )
                deleted_counts["user_sessions"] = sessions_delete.rowcount
                
                await session.commit()
                
                self.logger.info(f"Cleaned up old analytics data: {deleted_counts}")
                return deleted_counts
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup old data: {e}")
            return {}


# Создаем глобальный экземпляр сервиса
analytics_service = AnalyticsService()