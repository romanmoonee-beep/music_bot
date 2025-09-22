"""
Сервис умного поиска с кешированием и агрегацией источников
"""
import asyncio
import time
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass

from app.core.logging import get_logger
from app.core.config import settings
from app.services.music.aggregator import MusicAggregator, SearchStrategy
from app.services.music.base import SearchResult, ServiceError
from app.services.cache_service import track_cache, system_cache
from app.models.track import TrackSource
from app.models.search import SearchHistory, SearchSuggestion
from app.models.user import User
from app.core.database import get_session
from sqlalchemy.future import select
from sqlalchemy import func, and_


@dataclass
class SearchRequest:
    """Запрос на поиск"""
    query: str
    user_id: Optional[int] = None
    sources: Optional[List[TrackSource]] = None
    limit: int = 50
    strategy: SearchStrategy = SearchStrategy.COMPREHENSIVE
    use_cache: bool = True
    save_to_history: bool = True


@dataclass
class SearchResponse:
    """Ответ поиска"""
    results: List[SearchResult]
    total_found: int
    search_time: float
    sources_used: List[str]
    cached: bool = False
    suggestions: List[str] = None
    corrected_query: Optional[str] = None


class SearchService:
    """Сервис умного поиска"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.aggregator = None
        self._init_aggregator()
    
    def _init_aggregator(self):
        """Инициализация агрегатора музыкальных сервисов"""
        try:
            self.aggregator = MusicAggregator()
            self.logger.info("Music aggregator initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize music aggregator: {e}")
    
    async def search(self, search_request: SearchRequest) -> SearchResponse:
        """Основной метод поиска"""
        start_time = time.time()
        
        try:
            # Нормализуем запрос
            normalized_query = self._normalize_query(search_request.query)
            if not normalized_query:
                return SearchResponse(
                    results=[],
                    total_found=0,
                    search_time=0.0,
                    sources_used=[],
                    suggestions=await self._get_search_suggestions(search_request.query)
                )
            
            # Проверяем кеш
            cached_results = None
            if search_request.use_cache:
                cache_key = self._make_search_cache_key(
                    normalized_query,
                    search_request.sources,
                    search_request.limit
                )
                cached_results = await track_cache.get_cached_search_results(
                    cache_key,
                    "search"
                )
            
            if cached_results:
                search_time = time.time() - start_time
                return SearchResponse(
                    results=cached_results,
                    total_found=len(cached_results),
                    search_time=search_time,
                    sources_used=["cache"],
                    cached=True
                )
            
            # Проверяем орфографию и предлагаем исправления
            corrected_query = await self._check_spelling(normalized_query)
            
            # Выполняем поиск через агрегатор
            if not self.aggregator:
                self._init_aggregator()
            
            if not self.aggregator:
                raise ServiceError("Music aggregator not available")
            
            async with self.aggregator:
                results = await self.aggregator.search(
                    query=corrected_query or normalized_query,
                    limit=search_request.limit,
                    strategy=search_request.strategy,
                    sources=search_request.sources,
                    timeout=30.0
                )
            
            # Пост-обработка результатов
            processed_results = await self._post_process_results(
                results,
                normalized_query,
                search_request.user_id
            )
            
            # Кешируем результаты
            if search_request.use_cache and processed_results:
                await track_cache.cache_search_results(
                    cache_key,
                    processed_results,
                    "search"
                )
            
            # Сохраняем в историю поиска
            if search_request.save_to_history and search_request.user_id:
                await self._save_to_search_history(
                    search_request.user_id,
                    normalized_query,
                    len(processed_results)
                )
            
            # Обновляем поисковые подсказки
            await self._update_search_suggestions(normalized_query, len(processed_results))
            
            search_time = time.time() - start_time
            sources_used = list(set(result.source.value for result in processed_results))
            
            return SearchResponse(
                results=processed_results,
                total_found=len(processed_results),
                search_time=search_time,
                sources_used=sources_used,
                corrected_query=corrected_query,
                suggestions=await self._get_search_suggestions(normalized_query)
            )
            
        except Exception as e:
            self.logger.error(f"Search failed: {e}")
            search_time = time.time() - start_time
            
            return SearchResponse(
                results=[],
                total_found=0,
                search_time=search_time,
                sources_used=[],
                suggestions=await self._get_search_suggestions(search_request.query)
            )
    
    async def search_similar(
        self,
        track_id: str,
        source: TrackSource,
        user_id: Optional[int] = None,
        limit: int = 20
    ) -> SearchResponse:
        """Поиск похожих треков"""
        start_time = time.time()
        
        try:
            # Проверяем кеш
            cache_key = f"similar:{source.value}:{track_id}:{limit}"
            cached_results = await track_cache.get_cached_search_results(
                cache_key,
                "similar"
            )
            
            if cached_results:
                search_time = time.time() - start_time
                return SearchResponse(
                    results=cached_results,
                    total_found=len(cached_results),
                    search_time=search_time,
                    sources_used=["cache"],
                    cached=True
                )
            
            # Ищем через агрегатор
            if not self.aggregator:
                self._init_aggregator()
            
            results = []
            if self.aggregator and source in self.aggregator.services:
                service = self.aggregator.services[source]
                async with service:
                    similar_tracks = await service.get_similar_tracks(track_id, limit)
                    results.extend(similar_tracks)
            
            # Пост-обработка
            processed_results = await self._post_process_results(
                results,
                f"similar:{track_id}",
                user_id
            )
            
            # Кешируем
            if processed_results:
                await track_cache.cache_search_results(
                    cache_key,
                    processed_results,
                    "similar"
                )
            
            search_time = time.time() - start_time
            
            return SearchResponse(
                results=processed_results,
                total_found=len(processed_results),
                search_time=search_time,
                sources_used=[source.value]
            )
            
        except Exception as e:
            self.logger.error(f"Similar search failed: {e}")
            return SearchResponse(
                results=[],
                total_found=0,
                search_time=time.time() - start_time,
                sources_used=[]
            )
    
    async def get_trending_tracks(
        self,
        limit: int = 50,
        force_refresh: bool = False
    ) -> SearchResponse:
        """Получить популярные треки"""
        start_time = time.time()
        
        try:
            # Проверяем кеш
            cached_results = None
            if not force_refresh:
                cached_results = await system_cache.get_cached_trending_tracks()
            
            if cached_results:
                search_time = time.time() - start_time
                return SearchResponse(
                    results=cached_results,
                    total_found=len(cached_results),
                    search_time=search_time,
                    sources_used=["cache"],
                    cached=True
                )
            
            # Собираем популярные треки из разных источников
            if not self.aggregator:
                self._init_aggregator()
            
            all_results = []
            sources_used = []
            
            if self.aggregator:
                async with self.aggregator:
                    for source, service in self.aggregator.services.items():
                        try:
                            trending = await service.get_popular_tracks(limit=limit//3)
                            all_results.extend(trending)
                            sources_used.append(source.value)
                        except Exception as e:
                            self.logger.warning(f"Failed to get trending from {source.value}: {e}")
            
            # Пост-обработка и дедупликация
            processed_results = await self._post_process_results(
                all_results,
                "trending",
                None
            )
            
            # Ограничиваем результат
            processed_results = processed_results[:limit]
            
            # Кешируем на 30 минут
            if processed_results:
                await system_cache.cache_trending_tracks(processed_results)
            
            search_time = time.time() - start_time
            
            return SearchResponse(
                results=processed_results,
                total_found=len(processed_results),
                search_time=search_time,
                sources_used=sources_used
            )
            
        except Exception as e:
            self.logger.error(f"Trending search failed: {e}")
            return SearchResponse(
                results=[],
                total_found=0,
                search_time=time.time() - start_time,
                sources_used=[]
            )
    
    async def get_recommendations(
        self,
        user_id: int,
        limit: int = 30
    ) -> SearchResponse:
        """Получить персональные рекомендации"""
        start_time = time.time()
        
        try:
            # Проверяем кеш
            cached_results = await system_cache.get_cached_recommendations(user_id)
            if cached_results:
                search_time = time.time() - start_time
                return SearchResponse(
                    results=cached_results,
                    total_found=len(cached_results),
                    search_time=search_time,
                    sources_used=["cache"],
                    cached=True
                )
            
            # Получаем историю пользователя
            user_history = await self._get_user_listening_history(user_id)
            if not user_history:
                # Если истории нет, возвращаем популярные треки
                return await self.get_trending_tracks(limit)
            
            # Анализируем предпочтения
            preferences = await self._analyze_user_preferences(user_history)
            
            # Ищем рекомендации на основе предпочтений
            recommendations = await self._generate_recommendations(
                preferences,
                user_history,
                limit
            )
            
            # Кешируем рекомендации
            if recommendations:
                await system_cache.cache_recommendations(user_id, recommendations)
            
            search_time = time.time() - start_time
            
            return SearchResponse(
                results=recommendations,
                total_found=len(recommendations),
                search_time=search_time,
                sources_used=["recommendations"]
            )
            
        except Exception as e:
            self.logger.error(f"Recommendations failed: {e}")
            return SearchResponse(
                results=[],
                total_found=0,
                search_time=time.time() - start_time,
                sources_used=[]
            )
    
    async def get_search_history(
        self,
        user_id: int,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Получить историю поиска пользователя"""
        try:
            async with get_session() as session:
                query = select(SearchHistory).where(
                    SearchHistory.user_id == user_id
                ).order_by(
                    SearchHistory.searched_at.desc()
                ).limit(limit)
                
                result = await session.execute(query)
                history = result.scalars().all()
                
                return [
                    {
                        "query": item.query,
                        "results_count": item.results_count,
                        "searched_at": item.searched_at,
                        "search_time": item.search_time
                    }
                    for item in history
                ]
                
        except Exception as e:
            self.logger.error(f"Failed to get search history: {e}")
            return []
    
    async def get_popular_searches(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Получить популярные поисковые запросы"""
        try:
            async with get_session() as session:
                # Группируем по запросам и считаем количество
                query = select(
                    SearchHistory.query,
                    func.count(SearchHistory.id).label('search_count'),
                    func.max(SearchHistory.searched_at).label('last_searched')
                ).where(
                    SearchHistory.searched_at >= datetime.now(timezone.utc).date()
                ).group_by(
                    SearchHistory.query
                ).order_by(
                    func.count(SearchHistory.id).desc()
                ).limit(limit)
                
                result = await session.execute(query)
                popular = result.all()
                
                return [
                    {
                        "query": item.query,
                        "search_count": item.search_count,
                        "last_searched": item.last_searched
                    }
                    for item in popular
                ]
                
        except Exception as e:
            self.logger.error(f"Failed to get popular searches: {e}")
            return []
    
    def _normalize_query(self, query: str) -> str:
        """Нормализация поискового запроса"""
        if not query:
            return ""
        
        # Убираем лишние пробелы
        normalized = " ".join(query.strip().split())
        
        # Убираем специальные символы (кроме основных)
        import re
        normalized = re.sub(r'[^\w\s\-()[\].,!?\'"А-Яа-яЁё]', '', normalized)
        
        # Ограничиваем длину
        if len(normalized) > 200:
            normalized = normalized[:200]
        
        return normalized
    
    def _make_search_cache_key(
        self,
        query: str,
        sources: Optional[List[TrackSource]],
        limit: int
    ) -> str:
        """Создать ключ кеша для поиска"""
        sources_str = ""
        if sources:
            sources_str = "-".join(sorted(s.value for s in sources))
        else:
            sources_str = "all"
        
        import hashlib
        query_hash = hashlib.md5(query.encode()).hexdigest()
        
        return f"{query_hash}:{sources_str}:{limit}"
    
    async def _post_process_results(
        self,
        results: List[SearchResult],
        query: str,
        user_id: Optional[int]
    ) -> List[SearchResult]:
        """Пост-обработка результатов поиска"""
        if not results:
            return []
        
        # Удаляем дубликаты
        unique_results = self._deduplicate_results(results)
        
        # Фильтруем некачественные результаты
        filtered_results = self._filter_results(unique_results)
        
        # Сортируем по релевантности
        sorted_results = self._sort_by_relevance(filtered_results, query)
        
        # Добавляем пользовательский скоринг (если есть user_id)
        if user_id:
            scored_results = await self._apply_user_scoring(sorted_results, user_id)
        else:
            scored_results = sorted_results
        
        return scored_results
    
    def _deduplicate_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """Удаление дубликатов"""
        seen = set()
        unique_results = []
        
        for result in results:
            # Создаем ключ для дедупликации
            key = f"{result.artist.lower()}:{result.title.lower()}"
            
            if key not in seen:
                seen.add(key)
                unique_results.append(result)
        
        return unique_results
    
    def _filter_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """Фильтрация некачественных результатов"""
        filtered = []
        
        for result in results:
            # Пропускаем треки без названия или исполнителя
            if not result.title or not result.artist:
                continue
            
            # Пропускаем слишком короткие или длинные треки
            if result.duration:
                if result.duration < 10 or result.duration > 7200:  # 10 сек - 2 часа
                    continue
            
            # Пропускаем треки с подозрительными названиями
            suspicious_words = ['interview', 'podcast', 'audiobook', 'speech']
            if any(word in result.title.lower() for word in suspicious_words):
                continue
            
            filtered.append(result)
        
        return filtered
    
    def _sort_by_relevance(
        self,
        results: List[SearchResult],
        query: str
    ) -> List[SearchResult]:
        """Сортировка по релевантности"""
        def relevance_score(result: SearchResult) -> float:
            score = 0.0
            
            query_lower = query.lower()
            title_lower = result.title.lower()
            artist_lower = result.artist.lower()
            
            # Точное совпадение названия
            if title_lower == query_lower:
                score += 100
            elif query_lower in title_lower:
                score += 50
            
            # Точное совпадение исполнителя
            if artist_lower == query_lower:
                score += 80
            elif query_lower in artist_lower:
                score += 40
            
            # Совпадение слов
            query_words = set(query_lower.split())
            title_words = set(title_lower.split())
            artist_words = set(artist_lower.split())
            
            # Пересечение слов с названием
            title_intersection = len(query_words & title_words)
            if title_intersection > 0:
                score += title_intersection * 10
            
            # Пересечение слов с исполнителем
            artist_intersection = len(query_words & artist_words)
            if artist_intersection > 0:
                score += artist_intersection * 8
            
            # Бонус за качество источника
            source_bonus = {
                TrackSource.SPOTIFY: 10,
                TrackSource.VK_AUDIO: 8,
                TrackSource.YOUTUBE: 6
            }
            score += source_bonus.get(result.source, 0)
            
            # Бонус за качество аудио
            quality_bonus = {
                "ultra": 5,
                "high": 3,
                "medium": 1,
                "low": 0
            }
            score += quality_bonus.get(result.audio_quality.value.lower(), 0)
            
            return score
        
        return sorted(results, key=relevance_score, reverse=True)
    
    async def _apply_user_scoring(
        self,
        results: List[SearchResult],
        user_id: int
    ) -> List[SearchResult]:
        """Применить пользовательский скоринг"""
        # Здесь можно добавить логику на основе:
        # - Истории прослушиваний пользователя
        # - Предпочитаемых жанров
        # - Любимых исполнителей
        # - Времени дня (утром - энергичная музыка, вечером - спокойная)
        
        # Пока возвращаем без изменений
        return results
    
    async def _check_spelling(self, query: str) -> Optional[str]:
        """Проверка орфографии и предложение исправлений"""
        # Здесь можно интегрировать с сервисом проверки орфографии
        # Например, Yandex.Speller или собственный словарь
        
        # Простая логика для распространенных ошибок
        corrections = {
            'беливер': 'believer',
            'имаджин драгонс': 'imagine dragons',
            'тейлор свифт': 'taylor swift',
            'ед ширан': 'ed sheeran'
        }
        
        query_lower = query.lower()
        for mistake, correction in corrections.items():
            if mistake in query_lower:
                return query_lower.replace(mistake, correction)
        
        return None
    
    async def _get_search_suggestions(self, query: str) -> List[str]:
        """Получить поисковые подсказки"""
        try:
            if len(query) < 2:
                return []
            
            async with get_session() as session:
                # Ищем подсказки в базе
                suggestions_query = select(SearchSuggestion).where(
                    SearchSuggestion.query.ilike(f"{query}%")
                ).order_by(
                    SearchSuggestion.popularity.desc()
                ).limit(5)
                
                result = await session.execute(suggestions_query)
                suggestions = result.scalars().all()
                
                return [s.query for s in suggestions]
                
        except Exception as e:
            self.logger.error(f"Failed to get search suggestions: {e}")
            return []
    
    async def _save_to_search_history(
        self,
        user_id: int,
        query: str,
        results_count: int
    ) -> None:
        """Сохранить в историю поиска"""
        try:
            async with get_session() as session:
                search_history = SearchHistory(
                    user_id=user_id,
                    query=query,
                    results_count=results_count,
                    searched_at=datetime.now(timezone.utc)
                )
                
                session.add(search_history)
                await session.commit()
                
        except Exception as e:
            self.logger.error(f"Failed to save search history: {e}")
    
    async def _update_search_suggestions(
        self,
        query: str,
        results_count: int
    ) -> None:
        """Обновить поисковые подсказки"""
        try:
            if len(query) < 2 or results_count == 0:
                return
            
            async with get_session() as session:
                # Ищем существующую подсказку
                existing_query = select(SearchSuggestion).where(
                    SearchSuggestion.query == query
                )
                result = await session.execute(existing_query)
                suggestion = result.scalar_one_or_none()
                
                if suggestion:
                    # Увеличиваем популярность
                    suggestion.popularity += 1
                    suggestion.last_used = datetime.now(timezone.utc)
                else:
                    # Создаем новую подсказку
                    suggestion = SearchSuggestion(
                        query=query,
                        popularity=1,
                        created_at=datetime.now(timezone.utc),
                        last_used=datetime.now(timezone.utc)
                    )
                    session.add(suggestion)
                
                await session.commit()
                
        except Exception as e:
            self.logger.error(f"Failed to update search suggestions: {e}")
    
    async def _get_user_listening_history(self, user_id: int) -> List[Dict[str, Any]]:
        """Получить историю прослушиваний пользователя"""
        try:
            # Здесь должна быть логика получения истории из TrackPlay
            # Пока возвращаем заглушку
            return []
        except Exception as e:
            self.logger.error(f"Failed to get user listening history: {e}")
            return []
    
    async def _analyze_user_preferences(
        self,
        history: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Анализ предпочтений пользователя"""
        preferences = {
            'favorite_genres': [],
            'favorite_artists': [],
            'preferred_decades': [],
            'audio_quality_preference': 'medium',
            'average_track_length': 240
        }
        
        if not history:
            return preferences
        
        # Анализируем жанры
        genre_counts = {}
        artist_counts = {}
        decades = []
        
        for item in history:
            if 'genre' in item and item['genre']:
                genre = item['genre']
                genre_counts[genre] = genre_counts.get(genre, 0) + 1
            
            if 'artist' in item and item['artist']:
                artist = item['artist']
                artist_counts[artist] = artist_counts.get(artist, 0) + 1
            
            if 'year' in item and item['year']:
                decade = (item['year'] // 10) * 10
                decades.append(decade)
        
        # Топ жанры
        preferences['favorite_genres'] = sorted(
            genre_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]
        
        # Топ исполнители
        preferences['favorite_artists'] = sorted(
            artist_counts.items(), key=lambda x: x[1], reverse=True
        )[:10]
        
        # Предпочитаемые десятилетия
        if decades:
            from collections import Counter
            decade_counts = Counter(decades)
            preferences['preferred_decades'] = [
                decade for decade, count in decade_counts.most_common(3)
            ]
        
        return preferences
    
    async def _generate_recommendations(
        self,
        preferences: Dict[str, Any],
        history: List[Dict[str, Any]],
        limit: int
    ) -> List[SearchResult]:
        """Генерация рекомендаций на основе предпочтений"""
        recommendations = []
        
        try:
            if not self.aggregator:
                return recommendations
            
            # Рекомендации на основе любимых исполнителей
            favorite_artists = preferences.get('favorite_artists', [])
            for artist, _ in favorite_artists[:3]:
                try:
                    async with self.aggregator:
                        artist_tracks = await self.aggregator.search(
                            query=artist,
                            limit=5,
                            strategy=SearchStrategy.QUALITY_FIRST
                        )
                        recommendations.extend(artist_tracks)
                except Exception as e:
                    self.logger.warning(f"Failed to get recommendations for artist {artist}: {e}")
            
            # Рекомендации на основе жанров
            favorite_genres = preferences.get('favorite_genres', [])
            for genre, _ in favorite_genres[:2]:
                try:
                    # Ищем популярные треки в жанре
                    genre_query = f"{genre} popular"
                    async with self.aggregator:
                        genre_tracks = await self.aggregator.search(
                            query=genre_query,
                            limit=5,
                            strategy=SearchStrategy.COMPREHENSIVE
                        )
                        recommendations.extend(genre_tracks)
                except Exception as e:
                    self.logger.warning(f"Failed to get recommendations for genre {genre}: {e}")
            
            # Пост-обработка рекомендаций
            processed_recommendations = await self._post_process_results(
                recommendations,
                "recommendations",
                None
            )
            
            return processed_recommendations[:limit]
            
        except Exception as e:
            self.logger.error(f"Failed to generate recommendations: {e}")
            return []
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка работоспособности сервиса поиска"""
        try:
            start_time = time.time()
            
            # Проверяем агрегатор
            aggregator_health = {"status": "unknown"}
            if self.aggregator:
                aggregator_health = await self.aggregator.health_check()
            
            # Проверяем кеш
            cache_health = await track_cache.get_cache_stats()
            
            # Простой тестовый поиск
            test_search = await self.search(SearchRequest(
                query="test",
                limit=1,
                save_to_history=False
            ))
            
            response_time = time.time() - start_time
            
            return {
                "service": "search",
                "status": "healthy",
                "response_time_ms": round(response_time * 1000, 2),
                "aggregator": aggregator_health,
                "cache": cache_health,
                "test_search": {
                    "results_count": test_search.total_found,
                    "search_time": test_search.search_time
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            return {
                "service": "search",
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }


# Создаем глобальный экземпляр сервиса
search_service = SearchService()