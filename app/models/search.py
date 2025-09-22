"""
Модели для поиска и истории поисков
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import String, Boolean, Integer, BigInteger, DateTime, Text, Float, Enum as SQLEnum, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func, and_, desc

from app.models.base import BaseModel, MetadataMixin
from app.models.track import TrackSource


class SearchType(str, Enum):
    """Тип поиска"""
    TEXT = "text"
    VOICE = "voice"
    INLINE = "inline"
    SIMILAR = "similar"
    RECOMMENDATION = "recommendation"


class SearchStatus(str, Enum):
    """Статус поиска"""
    SUCCESS = "success"
    NO_RESULTS = "no_results"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"


class SearchHistory(BaseModel, MetadataMixin):
    """История поисков пользователей"""
    
    __tablename__ = "search_history"
    
    # Пользователь
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        index=True,
        comment="ID пользователя"
    )
    
    # Параметры поиска
    query: Mapped[str] = mapped_column(
        Text,
        comment="Поисковый запрос"
    )
    
    normalized_query: Mapped[str] = mapped_column(
        Text,
        index=True,
        comment="Нормализованный поисковый запрос"
    )
    
    search_type: Mapped[SearchType] = mapped_column(
        SQLEnum(SearchType),
        default=SearchType.TEXT,
        comment="Тип поиска"
    )
    
    # Результаты поиска
    status: Mapped[SearchStatus] = mapped_column(
        SQLEnum(SearchStatus),
        default=SearchStatus.SUCCESS,
        comment="Статус поиска"
    )
    
    results_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Количество найденных результатов"
    )
    
    response_time_ms: Mapped[int] = mapped_column(
        Integer,
        comment="Время ответа в миллисекундах"
    )
    
    # Источники поиска
    sources_used: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        comment="Использованные источники поиска"
    )
    
    primary_source: Mapped[Optional[TrackSource]] = mapped_column(
        SQLEnum(TrackSource),
        nullable=True,
        comment="Основной источник, давший результаты"
    )
    
    # Выбранный результат
    selected_track_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        comment="ID выбранного пользователем трека"
    )
    
    selected_position: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Позиция выбранного трека в результатах"
    )
    
    # Геолокация и контекст
    user_language: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="Язык пользователя"
    )
    
    user_country: Mapped[Optional[str]] = mapped_column(
        String(3),
        nullable=True,
        comment="Страна пользователя"
    )
    
    # Связи
    user = relationship("User", back_populates="searches", lazy="selectin")
    results = relationship("SearchResult", back_populates="search_history", lazy="selectin")
    
    # Индексы
    __table_args__ = (
        Index("idx_search_user_date", "user_id", "created_at"),
        Index("idx_search_query", "normalized_query"),
        Index("idx_search_status", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<SearchHistory(user_id={self.user_id}, query='{self.query[:50]}')>"
    
    @classmethod
    def normalize_query(cls, query: str) -> str:
        """Нормализация поискового запроса"""
        import re
        
        # Приводим к нижнему регистру
        normalized = query.lower().strip()
        
        # Удаляем лишние пробелы
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Удаляем специальные символы (оставляем только буквы, цифры, пробелы, дефисы)
        normalized = re.sub(r'[^\w\s\-]', '', normalized)
        
        return normalized
    
    @classmethod
    async def create_search_record(
        cls,
        session: AsyncSession,
        user_id: int,
        query: str,
        search_type: SearchType = SearchType.TEXT,
        **kwargs
    ) -> "SearchHistory":
        """Создание записи о поиске"""
        search_record = cls(
            user_id=user_id,
            query=query,
            normalized_query=cls.normalize_query(query),
            search_type=search_type,
            **kwargs
        )
        
        session.add(search_record)
        await session.flush()
        return search_record
    
    async def update_results(
        self,
        session: AsyncSession,
        status: SearchStatus,
        results_count: int,
        response_time_ms: int,
        sources_used: List[str],
        primary_source: Optional[TrackSource] = None
    ) -> None:
        """Обновление результатов поиска"""
        self.status = status
        self.results_count = results_count
        self.response_time_ms = response_time_ms
        self.sources_used = sources_used
        self.primary_source = primary_source
        
        await session.flush()
    
    async def mark_track_selected(
        self,
        session: AsyncSession,
        track_id: str,
        position: int
    ) -> None:
        """Отметка выбранного трека"""
        self.selected_track_id = track_id
        self.selected_position = position
        
        await session.flush()
    
    @classmethod
    async def get_user_recent_searches(
        cls,
        session: AsyncSession,
        user_id: int,
        limit: int = 20
    ) -> List["SearchHistory"]:
        """Получение недавних поисков пользователя"""
        result = await session.execute(
            select(cls).where(
                cls.user_id == user_id
            ).order_by(
                cls.created_at.desc()
            ).limit(limit)
        )
        return list(result.scalars().all())
    
    @classmethod
    async def get_popular_queries(
        cls,
        session: AsyncSession,
        hours: int = 24,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Получение популярных запросов за период"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        result = await session.execute(
            select(
                cls.normalized_query,
                func.count(cls.id).label('search_count'),
                func.avg(cls.results_count).label('avg_results'),
                func.avg(cls.response_time_ms).label('avg_response_time')
            ).where(
                cls.created_at >= since,
                cls.status == SearchStatus.SUCCESS
            ).group_by(
                cls.normalized_query
            ).order_by(
                desc('search_count')
            ).limit(limit)
        )
        
        return [
            {
                'query': row.normalized_query,
                'search_count': row.search_count,
                'avg_results': round(row.avg_results, 1),
                'avg_response_time': round(row.avg_response_time, 1)
            }
            for row in result
        ]
    
    @classmethod
    async def get_search_stats(
        cls,
        session: AsyncSession,
        hours: int = 24
    ) -> Dict[str, Any]:
        """Получение статистики поисков"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Общее количество поисков
        total_result = await session.execute(
            select(func.count(cls.id)).where(
                cls.created_at >= since
            )
        )
        total_searches = total_result.scalar()
        
        # Успешные поиски
        success_result = await session.execute(
            select(func.count(cls.id)).where(
                cls.created_at >= since,
                cls.status == SearchStatus.SUCCESS
            )
        )
        successful_searches = success_result.scalar()
        
        # Среднее время ответа
        avg_time_result = await session.execute(
            select(func.avg(cls.response_time_ms)).where(
                cls.created_at >= since,
                cls.status == SearchStatus.SUCCESS
            )
        )
        avg_response_time = avg_time_result.scalar() or 0
        
        # Статистика по источникам
        source_stats = {}
        for source in TrackSource:
            source_result = await session.execute(
                select(func.count(cls.id)).where(
                    cls.created_at >= since,
                    cls.primary_source == source
                )
            )
            source_stats[source.value] = source_result.scalar()
        
        return {
            'total_searches': total_searches,
            'successful_searches': successful_searches,
            'success_rate': (successful_searches / total_searches * 100) if total_searches > 0 else 0,
            'avg_response_time_ms': round(avg_response_time, 1),
            'source_distribution': source_stats
        }


class SearchResult(BaseModel, MetadataMixin):
    """Результаты поиска"""
    
    __tablename__ = "search_results"
    
    # Связь с историей поиска
    search_history_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("search_history.id", ondelete="CASCADE"),
        index=True,
        comment="ID записи в истории поиска"
    )
    
    # Найденный трек
    track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tracks.id", ondelete="CASCADE"),
        index=True,
        comment="ID найденного трека"
    )
    
    # Позиция в результатах
    position: Mapped[int] = mapped_column(
        Integer,
        comment="Позиция в результатах поиска"
    )
    
    # Оценка релевантности
    relevance_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        comment="Оценка релевантности результата"
    )
    
    # Источник результата
    source: Mapped[TrackSource] = mapped_column(
        SQLEnum(TrackSource),
        comment="Источник найденного трека"
    )
    
    # Был ли выбран пользователем
    was_selected: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Был ли результат выбран пользователем"
    )
    
    # Связи
    search_history = relationship("SearchHistory", back_populates="results", lazy="selectin")
    track = relationship("Track", back_populates="search_results", lazy="selectin")
    
    # Индексы
    __table_args__ = (
        Index("idx_search_result_history", "search_history_id", "position"),
        Index("idx_search_result_track", "track_id"),
        Index("idx_search_result_relevance", "relevance_score"),
    )
    
    def __repr__(self) -> str:
        return f"<SearchResult(search_id={self.search_history_id}, track_id={self.track_id}, position={self.position})>"


class SearchSuggestion(BaseModel):
    """Поисковые подсказки"""
    
    __tablename__ = "search_suggestions"
    
    # Текст подсказки
    suggestion: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        comment="Текст подсказки"
    )
    
    # Нормализованный текст
    normalized_suggestion: Mapped[str] = mapped_column(
        String(255),
        index=True,
        comment="Нормализованный текст подсказки"
    )
    
    # Статистика использования
    usage_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="Количество использований"
    )
    
    success_rate: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        comment="Процент успешных поисков"
    )
    
    # Категория подсказки
    category: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Категория подсказки (артист, жанр, и т.д.)"
    )
    
    # Связанные треки
    related_tracks: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="ID связанных треков"
    )
    
    # Индексы
    __table_args__ = (
        Index("idx_suggestion_normalized", "normalized_suggestion"),
        Index("idx_suggestion_usage", "usage_count"),
        Index("idx_suggestion_category", "category"),
    )
    
    @classmethod
    async def get_suggestions(
        cls,
        session: AsyncSession,
        query: str,
        limit: int = 10
    ) -> List["SearchSuggestion"]:
        """Получение подсказок для запроса"""
        normalized_query = SearchHistory.normalize_query(query)
        
        result = await session.execute(
            select(cls).where(
                cls.normalized_suggestion.like(f"{normalized_query}%")
            ).order_by(
                cls.usage_count.desc(),
                cls.success_rate.desc()
            ).limit(limit)
        )
        
        return list(result.scalars().all())
    
    @classmethod
    async def update_or_create(
        cls,
        session: AsyncSession,
        suggestion: str,
        was_successful: bool = True
    ) -> "SearchSuggestion":
        """Обновление или создание подсказки"""
        normalized = SearchHistory.normalize_query(suggestion)
        
        # Ищем существующую подсказку
        result = await session.execute(
            select(cls).where(
                cls.normalized_suggestion == normalized
            )
        )
        
        suggestion_obj = result.scalar_one_or_none()
        
        if suggestion_obj:
            # Обновляем существующую
            suggestion_obj.usage_count += 1
            
            # Пересчитываем success_rate (упрощенная формула)
            if was_successful:
                suggestion_obj.success_rate = (
                    (suggestion_obj.success_rate * (suggestion_obj.usage_count - 1) + 100) /
                    suggestion_obj.usage_count
                )
            else:
                suggestion_obj.success_rate = (
                    suggestion_obj.success_rate * (suggestion_obj.usage_count - 1) /
                    suggestion_obj.usage_count
                )
        else:
            # Создаем новую
            suggestion_obj = cls(
                suggestion=suggestion,
                normalized_suggestion=normalized,
                usage_count=1,
                success_rate=100.0 if was_successful else 0.0
            )
            session.add(suggestion_obj)
        
        await session.flush()
        return suggestion_obj


class PopularQuery(BaseModel):
    """Популярные запросы (кешированная таблица)"""
    
    __tablename__ = "popular_queries"
    
    # Запрос
    query: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        comment="Популярный запрос"
    )
    
    # Статистика
    search_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Количество поисков"
    )
    
    avg_results: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        comment="Среднее количество результатов"
    )
    
    avg_response_time: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        comment="Среднее время ответа"
    )
    
    # Период статистики
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        comment="Начало периода статистики"
    )
    
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        comment="Конец периода статистики"
    )
    
    # Индексы
    __table_args__ = (
        Index("idx_popular_query_count", "search_count"),
        Index("idx_popular_query_period", "period_start", "period_end"),
    )
    
    @classmethod
    async def refresh_popular_queries(
        cls,
        session: AsyncSession,
        hours: int = 24,
        limit: int = 100
    ) -> None:
        """Обновление таблицы популярных запросов"""
        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(hours=hours)
        
        # Получаем популярные запросы из истории
        popular_data = await SearchHistory.get_popular_queries(
            session, hours=hours, limit=limit
        )
        
        # Очищаем старые данные
        await session.execute(
            cls.__table__.delete().where(
                cls.period_end <= period_start
            )
        )
        
        # Добавляем новые данные
        for data in popular_data:
            popular_query = cls(
                query=data['query'],
                search_count=data['search_count'],
                avg_results=data['avg_results'],
                avg_response_time=data['avg_response_time'],
                period_start=period_start,
                period_end=period_end
            )
            session.add(popular_query)
        
        await session.commit()