# app/bot/handlers/inline.py
"""
Обработчик inline запросов для музыкального бота
"""
import hashlib
from typing import List
from aiogram import Router, F
from aiogram.types import (
    InlineQuery, InlineQueryResultAudio, InlineQueryResultArticle,
    InputTextMessageContent, ChosenInlineResult
)

from app.core.logging import get_logger, bot_logger
from app.services.search_service import search_service
from app.services.user_service import user_service
from app.services.analytics_service import analytics_service
from app.services.music.aggregator import music_aggregator
from app.services.search_service import SearchRequest, SearchStrategy
from app.models.track import TrackSource
from app.core.security import user_rate_limiter

router = Router()
logger = get_logger(__name__)


@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery):
    """Обработка inline запросов"""
    try:
        user_id = inline_query.from_user.id
        query = inline_query.query.strip()
        offset = int(inline_query.offset) if inline_query.offset else 0
        
        # Получаем или создаем пользователя
        user = await user_service.get_or_create_user(
            telegram_id=user_id,
            username=inline_query.from_user.username,
            first_name=inline_query.from_user.first_name,
            last_name=inline_query.from_user.last_name,
            language_code=inline_query.from_user.language_code
        )
        
        # Проверяем активность пользователя
        if not user.is_active:
            await inline_query.answer(
                results=[],
                cache_time=1,
                is_personal=True,
                switch_pm_text="⚠️ Аккаунт заблокирован",
                switch_pm_parameter="blocked"
            )
            return
        
        # Проверяем rate limit для inline запросов
        is_premium = await user_service.is_premium_user(user_id)
        rate_allowed = await user_rate_limiter.check_inline_limit(user_id, is_premium)
        
        if not rate_allowed:
            await inline_query.answer(
                results=[],
                cache_time=1,
                is_personal=True,
                switch_pm_text="⏳ Слишком много запросов",
                switch_pm_parameter="rate_limit"
            )
            return
        
        # Если запрос пустой - показываем подсказки
        if not query:
            results = await get_inline_suggestions(user_id)
            await inline_query.answer(
                results=results,
                cache_time=30,
                is_personal=True,
                switch_pm_text="🎵 Найти музыку",
                switch_pm_parameter="search"
            )
            return
        
        # Минимальная длина запроса
        if len(query) < 2:
            await inline_query.answer(
                results=[],
                cache_time=1,
                is_personal=True,
                switch_pm_text="💭 Введите больше символов",
                switch_pm_parameter="short_query"
            )
            return
        
        # Выполняем поиск
        search_results = await perform_inline_search(
            query=query,
            user_id=user.id,
            is_premium=is_premium,
            offset=offset
        )
        
        if not search_results:
            # Результатов не найдено
            no_results = await get_no_results_inline(query)
            await inline_query.answer(
                results=no_results,
                cache_time=5,
                is_personal=True,
                switch_pm_text="🔍 Попробовать в боте",
                switch_pm_parameter=f"search_{hashlib.md5(query.encode()).hexdigest()[:8]}"
            )
            return
        
        # Конвертируем результаты в inline формат
        inline_results = await convert_to_inline_results(search_results, query)
        
        # Определяем есть ли еще результаты
        has_more = len(search_results) >= 10  # Если получили максимум результатов
        next_offset = str(offset + len(search_results)) if has_more else ""
        
        await inline_query.answer(
            results=inline_results,
            cache_time=120,  # 2 минуты кеша
            is_personal=True,
            next_offset=next_offset,
            switch_pm_text="🎵 Открыть в боте",
            switch_pm_parameter=f"inline_{hashlib.md5(query.encode()).hexdigest()[:8]}"
        )
        
        # Логируем inline запрос
        await bot_logger.log_update(
            update_type="inline_query",
            user_id=user_id,
            query=query,
            results_count=len(inline_results),
            offset=offset
        )
        
    except Exception as e:
        logger.error(f"Error handling inline query: {e}")
        
        # Отправляем пустой результат с предложением использовать бота
        await inline_query.answer(
            results=[],
            cache_time=1,
            is_personal=True,
            switch_pm_text="❌ Ошибка поиска - открыть бота",
            switch_pm_parameter="error"
        )


@router.chosen_inline_result()
async def handle_chosen_inline_result(chosen_result: ChosenInlineResult):
    """Обработка выбранного inline результата"""
    try:
        user_id = chosen_result.from_user.id
        result_id = chosen_result.result_id
        query = chosen_result.query
        
        # Получаем информацию о выбранном треке
        track_info = parse_inline_result_id(result_id)
        
        if track_info:
            # Логируем выбор трека
            await bot_logger.log_update(
                update_type="inline_result_chosen",
                user_id=user_id,
                query=query,
                track_id=track_info.get("track_id"),
                source=track_info.get("source"),
                position=track_info.get("position", 0)
            )
            
            # Отправляем аналитику
            await analytics_service.track_inline_selection(
                user_id=user_id,
                query=query,
                track_id=track_info.get("track_id"),
                source=track_info.get("source"),
                position=track_info.get("position", 0)
            )
            
            # Обновляем счетчики популярности
            await search_service.update_track_popularity(
                track_id=track_info.get("track_id"),
                source=track_info.get("source"),
                interaction_type="inline_share"
            )
        
    except Exception as e:
        logger.error(f"Error handling chosen inline result: {e}")


async def perform_inline_search(query: str, user_id: int, is_premium: bool, offset: int = 0):
    """Выполнение поиска для inline режима"""
    try:
        # Создаем запрос на поиск
        search_request = SearchRequest(
            query=query,
            user_id=user_id,
            limit=10,  # Меньше результатов для inline
            offset=offset,
            strategy=SearchStrategy.FAST,  # Быстрый поиск для inline
            use_cache=True,
            save_to_history=False  # Не сохраняем inline поиски в историю
        )
        
        # Выполняем поиск
        search_response = await search_service.search(search_request)
        
        if not search_response or not search_response.results:
            return []
        
        return search_response.results[:10]  # Максимум 10 результатов
        
    except Exception as e:
        logger.error(f"Error performing inline search: {e}")
        return []


async def convert_to_inline_results(tracks, query: str) -> List:
    """Конвертация треков в inline результаты"""
    results = []
    
    for i, track in enumerate(tracks):
        try:
            # Создаем уникальный ID для результата
            result_id = create_inline_result_id(track, i)
            
            # Получаем URL для скачивания (если доступен)
            download_url = await get_track_download_url(track)
            
            if download_url:
                # Аудио результат
                audio_result = InlineQueryResultAudio(
                    id=result_id,
                    audio_url=download_url,
                    title=track.title,
                    performer=track.artist,
                    audio_duration=track.duration or 0,
                    caption=format_track_caption(track),
                    parse_mode="HTML",
                    thumb_url=get_track_thumb_url(track)
                )
                results.append(audio_result)
            else:
                # Текстовый результат с информацией о треке
                article_result = InlineQueryResultArticle(
                    id=result_id,
                    title=f"{track.artist} - {track.title}",
                    description=format_track_description(track),
                    thumb_url=get_track_thumb_url(track),
                    input_message_content=InputTextMessageContent(
                        message_text=format_track_share_message(track, query),
                        parse_mode="HTML"
                    )
                )
                results.append(article_result)
                
        except Exception as e:
            logger.error(f"Error converting track to inline result: {e}")
            continue
    
    return results


async def get_inline_suggestions(user_id: int) -> List:
    """Получение предложений для пустого inline запроса"""
    suggestions = []
    
    try:
        # Получаем популярные запросы
        popular_queries = await search_service.get_popular_queries(limit=5)
        
        # Получаем персональные рекомендации
        user_suggestions = await get_user_suggestions(user_id)
        
        # Объединяем предложения
        all_suggestions = user_suggestions + popular_queries
        
        for i, suggestion in enumerate(all_suggestions[:8]):
            suggestion_result = InlineQueryResultArticle(
                id=f"suggestion_{i}_{hashlib.md5(suggestion.encode()).hexdigest()[:8]}",
                title=f"🔍 {suggestion}",
                description="Нажмите для поиска",
                thumb_url="https://your-domain.com/search_icon.png",
                input_message_content=InputTextMessageContent(
                    message_text=f"🎵 Поиск: {suggestion}\n\nИспользуйте @musicbot для поиска музыки!",
                    parse_mode="HTML"
                )
            )
            suggestions.append(suggestion_result)
        
        # Добавляем общие подсказки
        if len(suggestions) < 5:
            general_suggestions = [
                "🎵 популярная музыка",
                "🔥 хиты 2024",
                "🎸 рок музыка",
                "🎧 электронная музыка",
                "🎤 русские хиты"
            ]
            
            for i, suggestion in enumerate(general_suggestions):
                if len(suggestions) >= 8:
                    break
                    
                suggestion_result = InlineQueryResultArticle(
                    id=f"general_{i}",
                    title=suggestion,
                    description="Популярная категория",
                    thumb_url="https://your-domain.com/music_icon.png",
                    input_message_content=InputTextMessageContent(
                        message_text=f"{suggestion}\n\n🎵 Найти музыку: @musicbot",
                        parse_mode="HTML"
                    )
                )
                suggestions.append(suggestion_result)
        
    except Exception as e:
        logger.error(f"Error getting inline suggestions: {e}")
    
    return suggestions


async def get_no_results_inline(query: str) -> List:
    """Результаты когда ничего не найдено"""
    return [
        InlineQueryResultArticle(
            id="no_results",
            title="🚫 Ничего не найдено",
            description=f"По запросу '{query}' результатов нет",
            thumb_url="https://your-domain.com/no_results_icon.png",
            input_message_content=InputTextMessageContent(
                message_text=(
                    f"🔍 Поиск: <b>{query}</b>\n\n"
                    "❌ К сожалению, ничего не найдено.\n\n"
                    "💡 <b>Попробуйте:</b>\n"
                    "• Изменить запрос\n"
                    "• Использовать английский язык\n"
                    "• Указать исполнителя и название\n\n"
                    "🎵 Больше возможностей в @musicbot"
                ),
                parse_mode="HTML"
            )
        )
    ]


async def get_user_suggestions(user_id: int) -> List[str]:
    """Персональные предложения на основе истории пользователя"""
    try:
        # Получаем последние поиски пользователя
        recent_searches = await search_service.get_user_search_history(
            user_id, limit=5
        )
        
        suggestions = []
        
        # Добавляем популярные запросы пользователя
        for search in recent_searches:
            if search.results_count > 0:  # Только успешные поиски
                suggestions.append(search.query)
        
        # Получаем рекомендации на основе жанров
        user_stats = await analytics_service.get_user_music_preferences(user_id)
        
        if user_stats and user_stats.get('favorite_genres'):
            for genre in user_stats['favorite_genres'][:2]:
                suggestions.append(f"{genre} музыка")
        
        return suggestions[:3]  # Максимум 3 персональных предложения
        
    except Exception as e:
        logger.error(f"Error getting user suggestions: {e}")
        return []


async def get_track_download_url(track) -> str:
    """Получение URL для скачивания трека"""
    try:
        # Пытаемся получить прямую ссылку на аудио
        if hasattr(track, 'download_url') and track.download_url:
            return str(track.download_url)
        
        # Пытаемся получить через агрегатор
        track_source = TrackSource(track.source)
        
        async with music_aggregator:
            download_result = await music_aggregator.get_download_url(
                track_id=track.external_id,
                source=track_source
            )
        
        if download_result and download_result.url:
            return download_result.url
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting download URL for track {track.id}: {e}")
        return None


def create_inline_result_id(track, position: int) -> str:
    """Создание ID для inline результата"""
    # Формат: source_trackid_position_hash
    track_data = f"{track.source}_{track.external_id}_{position}"
    track_hash = hashlib.md5(track_data.encode()).hexdigest()[:8]
    return f"{track.source.value}_{track.external_id}_{position}_{track_hash}"


def parse_inline_result_id(result_id: str) -> dict:
    """Парсинг ID inline результата"""
    try:
        parts = result_id.split("_")
        if len(parts) >= 4:
            return {
                "source": parts[0],
                "track_id": parts[1], 
                "position": int(parts[2]),
                "hash": parts[3]
            }
    except:
        pass
    return {}


def format_track_caption(track) -> str:
    """Форматирование подписи для аудио трека"""
    caption = f"🎵 <b>{track.artist} - {track.title}</b>\n"
    
    if track.album:
        caption += f"💿 {track.album}\n"
    
    if track.duration:
        minutes = track.duration // 60
        seconds = track.duration % 60
        caption += f"⏱️ {minutes}:{seconds:02d}\n"
    
    # Добавляем информацию о качестве
    quality_icons = {
        "ultra": "💎",
        "high": "🔹",
        "medium": "🔸", 
        "low": "🔻"
    }
    
    quality_icon = quality_icons.get(track.audio_quality.value.lower(), "🎵")
    caption += f"{quality_icon} {track.audio_quality.value.title()}\n"
    
    # Источник
    source_names = {
        "vk_audio": "VK Music",
        "youtube": "YouTube",
        "spotify": "Spotify"
    }
    
    source_name = source_names.get(track.source.value, track.source.value)
    caption += f"📻 {source_name}\n"
    
    caption += f"\n🤖 Найдено через @musicbot"
    
    return caption


def format_track_description(track) -> str:
    """Форматирование описания трека для article результата"""
    description_parts = []
    
    if track.album:
        description_parts.append(f"💿 {track.album}")
    
    if track.duration:
        minutes = track.duration // 60
        seconds = track.duration % 60
        description_parts.append(f"⏱️ {minutes}:{seconds:02d}")
    
    if track.genre:
        description_parts.append(f"🎭 {track.genre}")
    
    # Качество и источник
    description_parts.append(f"📻 {track.source.value}")
    description_parts.append(f"🔊 {track.audio_quality.value}")
    
    return " • ".join(description_parts) if description_parts else "Музыкальный трек"


def format_track_share_message(track, query: str) -> str:
    """Форматирование сообщения для отправки трека"""
    message = f"🎵 <b>{track.artist} - {track.title}</b>\n\n"
    
    if track.album:
        message += f"💿 <b>Альбом:</b> {track.album}\n"
    
    if track.year:
        message += f"📅 <b>Год:</b> {track.year}\n"
    
    if track.genre:
        message += f"🎭 <b>Жанр:</b> {track.genre}\n"
    
    if track.duration:
        minutes = track.duration // 60
        seconds = track.duration % 60
        message += f"⏱️ <b>Длительность:</b> {minutes}:{seconds:02d}\n"
    
    # Качество и источник
    quality_text = {
        "ultra": "💎 Максимальное (320kbps)",
        "high": "🔹 Высокое (256kbps)",
        "medium": "🔸 Среднее (192kbps)",
        "low": "🔻 Базовое (128kbps)"
    }
    
    quality_desc = quality_text.get(track.audio_quality.value.lower(), track.audio_quality.value)
    message += f"🔊 <b>Качество:</b> {quality_desc}\n"
    
    source_names = {
        "vk_audio": "VK Music",
        "youtube": "YouTube Music", 
        "spotify": "Spotify"
    }
    
    source_name = source_names.get(track.source.value, track.source.value)
    message += f"📻 <b>Источник:</b> {source_name}\n"
    
    message += f"\n🔍 <b>Найдено по запросу:</b> {query}\n"
    message += f"\n🎧 <b>Скачать и слушать:</b> @musicbot"
    
    return message


def get_track_thumb_url(track) -> str:
    """Получение URL миниатюры трека"""
    # В реальной реализации здесь можно получать обложки альбомов
    # Пока используем стандартную иконку
    
    # Разные иконки для разных источников
    thumb_urls = {
        "vk_audio": "https://your-domain.com/icons/vk_thumb.png",
        "youtube": "https://your-domain.com/icons/youtube_thumb.png", 
        "spotify": "https://your-domain.com/icons/spotify_thumb.png"
    }
    
    return thumb_urls.get(
        track.source.value, 
        "https://your-domain.com/icons/default_music_thumb.png"
    )


# Дополнительные inline команды

@router.inline_query(F.query.startswith("top"))
async def handle_top_inline_query(inline_query: InlineQuery):
    """Обработка запросов топ музыки"""
    try:
        user_id = inline_query.from_user.id
        query = inline_query.query
        
        # Парсим тип топа
        if "weekly" in query.lower() or "неделя" in query.lower():
            top_type = "weekly"
            title = "🔥 Топ недели"
        elif "monthly" in query.lower() or "месяц" in query.lower():
            top_type = "monthly" 
            title = "📈 Топ месяца"
        else:
            top_type = "daily"
            title = "⚡ Топ дня"
        
        # Получаем топ треки
        top_tracks = await search_service.get_trending_tracks(
            period=top_type,
            limit=10
        )
        
        if not top_tracks:
            await inline_query.answer(
                results=[],
                cache_time=60,
                switch_pm_text="📊 Статистика недоступна",
                switch_pm_parameter="no_stats"
            )
            return
        
        # Конвертируем в inline результаты
        results = await convert_to_inline_results(top_tracks, title)
        
        await inline_query.answer(
            results=results,
            cache_time=300,  # 5 минут кеша для топов
            is_personal=False,  # Топы одинаковы для всех
            switch_pm_text="📊 Полная статистика",
            switch_pm_parameter="trending"
        )
        
        # Логируем запрос топа
        await bot_logger.log_update(
            update_type="inline_top_request",
            user_id=user_id,
            top_type=top_type,
            results_count=len(results)
        )
        
    except Exception as e:
        logger.error(f"Error handling top inline query: {e}")
        await inline_query.answer(
            results=[],
            cache_time=1,
            switch_pm_text="❌ Ошибка загрузки топа",
            switch_pm_parameter="error"
        )


@router.inline_query(F.query.startswith("genre:"))
async def handle_genre_inline_query(inline_query: InlineQuery):
    """Обработка поиска по жанрам"""
    try:
        user_id = inline_query.from_user.id
        query = inline_query.query
        
        # Извлекаем жанр
        genre = query.replace("genre:", "").strip()
        
        if not genre:
            await inline_query.answer(
                results=[],
                cache_time=1,
                switch_pm_text="🎭 Укажите жанр",
                switch_pm_parameter="genres"
            )
            return
        
        # Получаем треки по жанру
        genre_tracks = await search_service.search_by_genre(
            genre=genre,
            limit=10
        )
        
        if not genre_tracks:
            no_genre_result = InlineQueryResultArticle(
                id="no_genre_tracks",
                title=f"🎭 Жанр: {genre}",
                description="Треки не найдены",
                input_message_content=InputTextMessageContent(
                    message_text=f"🎭 Поиск по жанру: <b>{genre}</b>\n\n❌ Треки не найдены.\n\n🎵 Попробуйте @musicbot",
                    parse_mode="HTML"
                )
            )
            
            await inline_query.answer(
                results=[no_genre_result],
                cache_time=60,
                switch_pm_text="🎭 Все жанры",
                switch_pm_parameter="genres"
            )
            return
        
        # Конвертируем результаты
        results = await convert_to_inline_results(genre_tracks, f"Жанр: {genre}")
        
        await inline_query.answer(
            results=results,
            cache_time=600,  # 10 минут кеша для жанров
            is_personal=False,
            switch_pm_text=f"🎭 Больше {genre}",
            switch_pm_parameter=f"genre_{genre.lower()}"
        )
        
        # Логируем поиск по жанру
        await bot_logger.log_update(
            update_type="inline_genre_search",
            user_id=user_id,
            genre=genre,
            results_count=len(results)
        )
        
    except Exception as e:
        logger.error(f"Error handling genre inline query: {e}")
        await inline_query.answer(
            results=[],
            cache_time=1,
            switch_pm_text="❌ Ошибка поиска жанра",
            switch_pm_parameter="error"
        )


@router.inline_query(F.query.startswith("artist:"))
async def handle_artist_inline_query(inline_query: InlineQuery):
    """Обработка поиска по исполнителю"""
    try:
        user_id = inline_query.from_user.id
        query = inline_query.query
        offset = int(inline_query.offset) if inline_query.offset else 0
        
        # Извлекаем имя исполнителя
        artist_name = query.replace("artist:", "").strip()
        
        if not artist_name:
            await inline_query.answer(
                results=[],
                cache_time=1,
                switch_pm_text="🎤 Укажите исполнителя",
                switch_pm_parameter="artists"
            )
            return
        
        # Поиск треков исполнителя
        search_request = SearchRequest(
            query=artist_name,
            user_id=await user_service.get_user_by_telegram_id(user_id),
            limit=10,
            offset=offset,
            strategy=SearchStrategy.ARTIST_FOCUS,
            use_cache=True,
            save_to_history=False
        )
        
        search_response = await search_service.search(search_request)
        
        if not search_response or not search_response.results:
            no_artist_result = InlineQueryResultArticle(
                id="no_artist_tracks",
                title=f"🎤 Исполнитель: {artist_name}",
                description="Треки не найдены",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"🎤 Поиск исполнителя: <b>{artist_name}</b>\n\n"
                        "❌ Треки не найдены.\n\n"
                        "💡 Попробуйте:\n"
                        "• Проверить правописание\n"
                        "• Использовать английское название\n\n"
                        "🎵 Расширенный поиск: @musicbot"
                    ),
                    parse_mode="HTML"
                )
            )
            
            await inline_query.answer(
                results=[no_artist_result],
                cache_time=60,
                switch_pm_text=f"🎤 Найти {artist_name}",
                switch_pm_parameter=f"artist_{hashlib.md5(artist_name.encode()).hexdigest()[:8]}"
            )
            return
        
        # Конвертируем результаты
        results = await convert_to_inline_results(
            search_response.results, 
            f"Исполнитель: {artist_name}"
        )
        
        # Определяем есть ли еще результаты
        has_more = len(search_response.results) >= 10
        next_offset = str(offset + len(search_response.results)) if has_more else ""
        
        await inline_query.answer(
            results=results,
            cache_time=300,  # 5 минут кеша
            is_personal=False,
            next_offset=next_offset,
            switch_pm_text=f"🎤 Все треки {artist_name}",
            switch_pm_parameter=f"artist_{hashlib.md5(artist_name.encode()).hexdigest()[:8]}"
        )
        
        # Логируем поиск исполнителя
        await bot_logger.log_update(
            update_type="inline_artist_search", 
            user_id=user_id,
            artist=artist_name,
            results_count=len(results),
            offset=offset
        )
        
    except Exception as e:
        logger.error(f"Error handling artist inline query: {e}")
        await inline_query.answer(
            results=[],
            cache_time=1,
            switch_pm_text="❌ Ошибка поиска исполнителя",
            switch_pm_parameter="error"
        )


# Вспомогательные функции для специальных inline команд

async def get_inline_help_results() -> List:
    """Помощь по inline командам"""
    help_results = [
        InlineQueryResultArticle(
            id="inline_help",
            title="❓ Как использовать inline режим",
            description="Инструкция по использованию бота",
            thumb_url="https://your-domain.com/icons/help_icon.png",
            input_message_content=InputTextMessageContent(
                message_text=(
                    "🎵 <b>Inline режим @musicbot</b>\n\n"
                    
                    "📝 <b>Основные команды:</b>\n"
                    "• <code>@musicbot название трека</code> - поиск музыки\n"
                    "• <code>@musicbot top daily</code> - топ дня\n"
                    "• <code>@musicbot genre:рок</code> - поиск по жанру\n"
                    "• <code>@musicbot artist:исполнитель</code> - треки исполнителя\n\n"
                    
                    "💡 <b>Примеры:</b>\n"
                    "• <code>@musicbot Imagine Dragons Believer</code>\n"
                    "• <code>@musicbot genre:electronic</code>\n" 
                    "• <code>@musicbot artist:Billie Eilish</code>\n\n"
                    
                    "🚀 <b>Возможности:</b>\n"
                    "• Быстрый поиск в любом чате\n"
                    "• Отправка музыки друзьям\n"
                    "• Доступ к топам и жанрам\n"
                    "• Персональные рекомендации\n\n"
                    
                    "🤖 Полные возможности в @musicbot"
                ),
                parse_mode="HTML"
            )
        )
    ]
    
    return help_results


# Обработка ошибок inline запросов

async def handle_inline_error(inline_query: InlineQuery, error_message: str):
    """Обработка ошибок в inline режиме"""
    try:
        error_result = InlineQueryResultArticle(
            id="inline_error",
            title="❌ Произошла ошибка",
            description=error_message,
            thumb_url="https://your-domain.com/icons/error_icon.png",
            input_message_content=InputTextMessageContent(
                message_text=(
                    f"❌ <b>Ошибка inline режима</b>\n\n"
                    f"{error_message}\n\n"
                    "🔄 Попробуйте:\n"
                    "• Повторить запрос\n"
                    "• Использовать другие слова\n"
                    "• Открыть @musicbot\n\n"
                    "🆘 Если проблема повторяется - сообщите в поддержку"
                ),
                parse_mode="HTML"
            )
        )
        
        await inline_query.answer(
            results=[error_result],
            cache_time=1,
            switch_pm_text="🤖 Открыть бота",
            switch_pm_parameter="error_recovery"
        )
        
    except Exception as e:
        logger.error(f"Error handling inline error: {e}")


# Inline статистика и аналитика

async def track_inline_usage(user_id: int, query_type: str, query: str, results_count: int):
    """Трекинг использования inline режима"""
    try:
        await analytics_service.track_inline_usage(
            user_id=user_id,
            query_type=query_type,
            query=query,
            results_count=results_count,
            timestamp=datetime.utcnow()
        )
        
    except Exception as e:
        logger.error(f"Error tracking inline usage: {e}")


from datetime import datetime