<<<<<<< HEAD
# app/bot/handlers/search.py
"""
Обработчик поиска музыки
"""
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import Optional, List

from app.bot.keyboards.inline import (
    get_search_results_keyboard,
    get_track_actions_keyboard,
    get_search_filters_keyboard
)
from app.bot.utils.messages import Messages
from app.bot.utils.formatters import format_track_info, format_search_results
from app.services import (
    get_search_service, get_user_service, 
    get_analytics_service, get_music_aggregator
)
from app.services.search_service import SearchRequest, SearchStrategy
from app.models.track import TrackSource
from app.core.logging import get_logger, bot_logger
from app.core.exceptions import (
    RateLimitExceededError, DailyLimitExceededError,
    TrackNotFoundError, DownloadError
)

router = Router()
logger = get_logger(__name__)


class SearchStates(StatesGroup):
    """Состояния поиска"""
    waiting_query = State()
    showing_results = State()
    downloading = State()


@router.message(F.text.startswith("🔍"))
async def handle_search_button(message: Message, state: FSMContext):
    """Обработка нажатия кнопки поиска"""
    await message.answer(
        "🎵 <b>Поиск музыки</b>\n\n"
        "Напишите название трека или исполнителя:\n"
        "• <code>Imagine Dragons - Believer</code>\n"
        "• <code>Тейлор Свифт</code>\n"
        "• <code>лучшие хиты 2024</code>",
        parse_mode="HTML"
    )
    await state.set_state(SearchStates.waiting_query)


@router.callback_query(F.data.startswith("search:"))
async def callback_search(callback: CallbackQuery, state: FSMContext):
    """Обработка поиска из callback"""
    try:
        query = callback.data.split(":", 1)[1]
        await perform_search(callback.message, query, callback.from_user.id, state, is_callback=True)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in search callback: {e}")
        await callback.answer("❌ Ошибка при поиске.", show_alert=True)


@router.message(SearchStates.waiting_query)
async def handle_search_query(message: Message, state: FSMContext):
    """Обработка поискового запроса"""
    try:
        query = message.text.strip()
        
        if len(query) < 2:
            await message.answer(
                "❌ Слишком короткий запрос. Введите минимум 2 символа."
            )
            return
        
        if len(query) > 100:
            await message.answer(
                "❌ Слишком длинный запрос. Максимум 100 символов."
            )
            return
        
        await perform_search(message, query, message.from_user.id, state)
        
    except Exception as e:
        logger.error(f"Error handling search query: {e}")
        await message.answer("❌ Произошла ошибка при поиске.")


async def perform_search(
    message: Message, 
    query: str, 
    user_id: int, 
    state: FSMContext,
    is_callback: bool = False
):
    """Выполнение поиска музыки"""
    try:
        user_service = get_user_service()
        search_service = get_search_service()
        analytics_service = get_analytics_service()
        
        # Проверяем лимиты пользователя
        is_premium = await user_service.is_premium_user(user_id)
        limits_info = await user_service.check_daily_limits(user_id)
        
        # Проверяем лимит поисков
        from app.core.security import user_rate_limiter
        search_allowed = await user_rate_limiter.check_search_limit(user_id, is_premium)
        
        if not search_allowed:
            await message.answer(
                "⏳ <b>Лимит поисков исчерпан</b>\n\n"
                f"{'Premium' if is_premium else 'Бесплатный'} аккаунт: "
                f"{'100' if is_premium else '20'} поисков в минуту\n\n"
                "Попробуйте через минуту или оформите Premium подписку.",
                parse_mode="HTML"
            )
            return
        
        # Отправляем сообщение о поиске
        if is_callback:
            search_msg = await message.edit_text(
                f"🔍 <b>Поиск:</b> <i>{query}</i>\n\n"
                "⏳ Ищем в музыкальных сервисах...",
                parse_mode="HTML"
            )
        else:
            search_msg = await message.answer(
                f"🔍 <b>Поиск:</b> <i>{query}</i>\n\n"
                "⏳ Ищем в музыкальных сервисах...",
                parse_mode="HTML"
            )
        
        # Создаем запрос на поиск
        search_request = SearchRequest(
            query=query,
            user_id=user_id,
            limit=20 if is_premium else 10,
            strategy=SearchStrategy.COMPREHENSIVE,
            use_cache=True,
            save_to_history=True
        )
        
        # Выполняем поиск
        search_response = await search_service.search(search_request)
        
        # Логируем поиск
        await bot_logger.log_search(
            user_id=user_id,
            query=query,
            results_count=search_response.total_found,
            duration=search_response.search_time,
            source=",".join(search_response.sources_used)
        )
        
        # Трекаем аналитику
        await analytics_service.track_search_event(
            user_id=user_id,
            query=query,
            results_count=search_response.total_found,
            search_time=search_response.search_time,
            sources_used=search_response.sources_used
        )
        
        if not search_response.results:
            # Результатов не найдено
            no_results_text = Messages.get_no_search_results_message(
                query=query,
                suggestions=search_response.suggestions
            )
            
            # Клавиатура с предложениями
            keyboard = None
            if search_response.suggestions:
                keyboard = get_search_suggestions_keyboard(search_response.suggestions)
            
            await search_msg.edit_text(
                text=no_results_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        
        # Форматируем результаты
        results_text = format_search_results(
            query=query,
            results=search_response.results[:5],  # Показываем первые 5
            total_found=search_response.total_found,
            search_time=search_response.search_time,
            cached=search_response.cached
        )
        
        # Создаем клавиатуру с результатами
        keyboard = get_search_results_keyboard(
            results=search_response.results[:10],
            page=0,
            total_pages=(len(search_response.results) - 1) // 10 + 1,
            query=query
        )
        
        # Обновляем сообщение с результатами
        await search_msg.edit_text(
            text=results_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Сохраняем результаты в состояние для пагинации
        await state.update_data({
            "search_results": [result.dict() for result in search_response.results],
            "current_query": query,
            "current_page": 0
        })
        
        await state.set_state(SearchStates.showing_results)
        
    except RateLimitExceededError as e:
        await message.answer(
            "⏳ <b>Слишком много запросов</b>\n\n"
            "Пожалуйста, подождите немного перед следующим поиском.",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error in perform_search: {e}")
        await message.answer(
            "❌ <b>Ошибка поиска</b>\n\n"
            "Попробуйте другой запрос или повторите позже.",
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("track:"))
async def callback_track_action(callback: CallbackQuery, state: FSMContext):
    """Обработка действий с треком"""
    try:
        action_data = callback.data.split(":", 2)
        if len(action_data) < 3:
            await callback.answer("❌ Неверный формат данных.")
            return
        
        action = action_data[1]  # download, info, add_playlist, etc.
        track_index = int(action_data[2])
        
        # Получаем данные из состояния
        data = await state.get_data()
        search_results = data.get("search_results", [])
        
        if track_index >= len(search_results):
            await callback.answer("❌ Трек не найден.")
            return
        
        track_data = search_results[track_index]
        
        if action == "download":
            await handle_track_download(callback, track_data, state)
        elif action == "info":
            await handle_track_info(callback, track_data)
        elif action == "add_playlist":
            await handle_add_to_playlist(callback, track_data, state)
        else:
            await callback.answer("❌ Неизвестное действие.")
            
    except Exception as e:
        logger.error(f"Error in track action callback: {e}")
        await callback.answer("❌ Ошибка при выполнении действия.")


async def handle_track_download(callback: CallbackQuery, track_data: dict, state: FSMContext):
    """Обработка скачивания трека"""
    try:
        user_service = get_user_service()
        music_aggregator = get_music_aggregator()
        analytics_service = get_analytics_service()
        
        user_id = callback.from_user.id
        
        # Проверяем лимиты
        is_premium = await user_service.is_premium_user(user_id)
        limits_info = await user_service.check_daily_limits(user_id)
        
        if not limits_info["can_download"]:
            # Превышен дневной лимит
            limit_text = Messages.get_download_limit_message(
                limits=limits_info,
                is_premium=is_premium
            )
            
            await callback.answer(limit_text, show_alert=True)
            return
        
        # Отправляем уведомление о начале загрузки
        await callback.answer("⏳ Подготавливаем трек к скачиванию...")
        
        # Обновляем сообщение
        download_msg = await callback.message.edit_text(
            f"📥 <b>Скачиваем:</b> {track_data['artist']} - {track_data['title']}\n\n"
            "⏳ Получаем ссылку на скачивание...",
            parse_mode="HTML"
        )
        
        await state.set_state(SearchStates.downloading)
        
        # Получаем ссылку на скачивание
        track_source = TrackSource(track_data["source"])
        
        async with music_aggregator:
            download_result = await music_aggregator.get_download_url(
                track_id=track_data["external_id"],
                source=track_source
            )
        
        if not download_result:
            await download_msg.edit_text(
                f"❌ <b>Ошибка скачивания</b>\n\n"
                f"Не удалось получить ссылку для трека:\n"
                f"<b>{track_data['artist']} - {track_data['title']}</b>\n\n"
                "Попробуйте другой трек или повторите позже.",
                parse_mode="HTML"
            )
            return
        
        # Скачиваем файл
        await download_msg.edit_text(
            f"📥 <b>Скачиваем:</b> {track_data['artist']} - {track_data['title']}\n\n"
            "⬇️ Загружаем аудиофайл...",
            parse_mode="HTML"
        )
        
        # Загружаем аудио через aiohttp
        import aiohttp
        import io
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                download_result.url,
                headers=download_result.headers or {}
            ) as response:
                
                if response.status != 200:
                    raise DownloadError(f"HTTP {response.status}")
                
                audio_data = await response.read()
        
        # Создаем метаданные для файла
        filename = f"{track_data['artist']} - {track_data['title']}.mp3"
        filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.'))[:100]
        
        # Отправляем аудиофайл
        audio_file = BufferedInputFile(audio_data, filename=filename)
        
        # Формируем описание
        caption = format_track_info(track_data, include_download_info=True)
        
        await callback.message.answer_audio(
            audio=audio_file,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_track_actions_keyboard(
                track_data,
                include_download=False  # Уже скачан
            )
        )
        
        # Удаляем сообщение о загрузке
        await download_msg.delete()
        
        # Логируем скачивание
        await bot_logger.log_download(
            user_id=user_id,
            track_id=track_data["external_id"],
            track_title=f"{track_data['artist']} - {track_data['title']}",
            source=track_data["source"],
            duration=0,  # Будет измерено в другом месте
            file_size=len(audio_data)
        )
        
        # Трекаем аналитику
        await analytics_service.track_download_event(
            user_id=user_id,
            track_id=track_data["external_id"],
            source=track_data["source"],
            success=True,
            file_size=len(audio_data)
        )
        
        # Возвращаемся к состоянию результатов поиска
        await state.set_state(SearchStates.showing_results)
        
    except Exception as e:
        logger.error(f"Error downloading track: {e}")
        
        try:
            await callback.message.edit_text(
                f"❌ <b>Ошибка скачивания</b>\n\n"
                f"Не удалось скачать трек:\n"
                f"<b>{track_data.get('artist', 'Unknown')} - {track_data.get('title', 'Unknown')}</b>\n\n"
                "Попробуйте другой трек или повторите позже.",
                parse_mode="HTML"
            )
        except:
            await callback.answer("❌ Ошибка при скачивании трека.", show_alert=True)


async def handle_track_info(callback: CallbackQuery, track_data: dict):
    """Показать подробную информацию о треке"""
    try:
        info_text = Messages.get_detailed_track_info(track_data)
        
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📥 Скачать", callback_data=f"track:download:{track_data.get('index', 0)}"),
                    InlineKeyboardButton(text="➕ В плейлист", callback_data=f"track:add_playlist:{track_data.get('index', 0)}")
                ],
                [InlineKeyboardButton(text="🔙 К результатам", callback_data="back_to_results")]
            ]
        )
        
        await callback.message.edit_text(
            text=info_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing track info: {e}")
        await callback.answer("❌ Ошибка при получении информации о треке.")


async def handle_add_to_playlist(callback: CallbackQuery, track_data: dict, state: FSMContext):
    """Добавление трека в плейлист"""
    try:
        from app.services import get_playlist_service
        
        playlist_service = get_playlist_service()
        user_id = callback.from_user.id
        
        # Получаем плейлисты пользователя
        playlists = await playlist_service.get_user_playlists(user_id, limit=10)
        
        if not playlists:
            # Нет плейлистов - предлагаем создать
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Создать плейлист", callback_data="create_playlist")],
                    [InlineKeyboardButton(text="🔙 К результатам", callback_data="back_to_results")]
                ]
            )
            
            await callback.message.edit_text(
                "📋 <b>У вас нет плейлистов</b>\n\n"
                "Создайте первый плейлист, чтобы добавлять в него треки!",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await callback.answer()
            return
        
        # Показываем список плейлистов
        from app.bot.keyboards.inline import get_playlists_keyboard
        
        keyboard = get_playlists_keyboard(
            playlists=playlists,
            action="add_track",
            track_index=track_data.get('index', 0)
        )
        
        await callback.message.edit_text(
            f"📋 <b>Выберите плейлист</b>\n\n"
            f"Трек: <b>{track_data['artist']} - {track_data['title']}</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error adding to playlist: {e}")
        await callback.answer("❌ Ошибка при добавлении в плейлист.")


@router.callback_query(F.data.startswith("page:"))
async def callback_search_pagination(callback: CallbackQuery, state: FSMContext):
    """Пагинация результатов поиска"""
    try:
        page = int(callback.data.split(":")[1])
        
        # Получаем данные из состояния
        data = await state.get_data()
        search_results = data.get("search_results", [])
        query = data.get("current_query", "")
        
        if not search_results:
            await callback.answer("❌ Результаты поиска не найдены.")
            return
        
        # Вычисляем диапазон результатов для страницы
        results_per_page = 10
        start_idx = page * results_per_page
        end_idx = min(start_idx + results_per_page, len(search_results))
        
        if start_idx >= len(search_results):
            await callback.answer("❌ Страница не найдена.")
            return
        
        page_results = search_results[start_idx:end_idx]
        total_pages = (len(search_results) - 1) // results_per_page + 1
        
        # Форматируем результаты для страницы
        results_text = format_search_results(
            query=query,
            results=page_results,
            total_found=len(search_results),
            search_time=0,  # Не показываем время для кешированных результатов
            cached=True,
            page=page + 1,
            total_pages=total_pages
        )
        
        # Создаем клавиатуру
        keyboard = get_search_results_keyboard(
            results=page_results,
            page=page,
            total_pages=total_pages,
            query=query
        )
        
        await callback.message.edit_text(
            text=results_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Обновляем текущую страницу в состоянии
        await state.update_data(current_page=page)
        
        await callback.answer(f"📄 Страница {page + 1} из {total_pages}")
        
    except Exception as e:
        logger.error(f"Error in search pagination: {e}")
        await callback.answer("❌ Ошибка при переходе на страницу.")


@router.callback_query(F.data == "back_to_results")
async def callback_back_to_results(callback: CallbackQuery, state: FSMContext):
    """Возврат к результатам поиска"""
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        search_results = data.get("search_results", [])
        query = data.get("current_query", "")
        current_page = data.get("current_page", 0)
        
        if not search_results:
            await callback.answer("❌ Результаты поиска не найдены.")
            return
        
        # Показываем текущую страницу результатов
        results_per_page = 10
        start_idx = current_page * results_per_page
        end_idx = min(start_idx + results_per_page, len(search_results))
        page_results = search_results[start_idx:end_idx]
        total_pages = (len(search_results) - 1) // results_per_page + 1
        
        results_text = format_search_results(
            query=query,
            results=page_results,
            total_found=len(search_results),
            search_time=0,
            cached=True,
            page=current_page + 1,
            total_pages=total_pages
        )
        
        keyboard = get_search_results_keyboard(
            results=page_results,
            page=current_page,
            total_pages=total_pages,
            query=query
        )
        
        await callback.message.edit_text(
            text=results_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await state.set_state(SearchStates.showing_results)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error returning to results: {e}")
        await callback.answer("❌ Ошибка при возврате к результатам.")


@router.callback_query(F.data.startswith("filter:"))
async def callback_search_filter(callback: CallbackQuery, state: FSMContext):
    """Фильтрация результатов поиска"""
    try:
        filter_type = callback.data.split(":")[1]
        
        # Получаем данные из состояния
        data = await state.get_data()
        query = data.get("current_query", "")
        
        if not query:
            await callback.answer("❌ Запрос не найден.")
            return
        
        # Определяем источники для поиска
        sources = None
        if filter_type == "vk":
            sources = [TrackSource.VK_AUDIO]
        elif filter_type == "youtube":
            sources = [TrackSource.YOUTUBE]
        elif filter_type == "spotify":
            sources = [TrackSource.SPOTIFY]
        
        # Повторяем поиск с фильтром
        search_service = get_search_service()
        
        search_request = SearchRequest(
            query=query,
            user_id=callback.from_user.id,
            sources=sources,
            limit=20,
            strategy=SearchStrategy.COMPREHENSIVE,
            use_cache=True,
            save_to_history=False  # Не сохраняем повторный поиск
        )
        
        # Показываем индикатор загрузки
        await callback.answer("🔄 Применяем фильтр...")
        
        await callback.message.edit_text(
            f"🔍 <b>Поиск с фильтром:</b> <i>{query}</i>\n\n"
            "⏳ Фильтруем результаты...",
            parse_mode="HTML"
        )
        
        # Выполняем поиск
        search_response = await search_service.search(search_request)
        
        if not search_response.results:
            await callback.message.edit_text(
                f"❌ <b>Ничего не найдено</b>\n\n"
                f"По запросу <i>{query}</i> с применённым фильтром результатов не найдено.\n\n"
                "Попробуйте убрать фильтр или изменить запрос.",
                parse_mode="HTML"
            )
            return
        
        # Показываем отфильтрованные результаты
        results_text = format_search_results(
            query=query,
            results=search_response.results[:5],
            total_found=search_response.total_found,
            search_time=search_response.search_time,
            cached=search_response.cached,
            filter_applied=filter_type.upper()
        )
        
        keyboard = get_search_results_keyboard(
            results=search_response.results[:10],
            page=0,
            total_pages=(len(search_response.results) - 1) // 10 + 1,
            query=query,
            filter_type=filter_type
        )
        
        await callback.message.edit_text(
            text=results_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Обновляем состояние
        await state.update_data({
            "search_results": [result.dict() for result in search_response.results],
            "current_filter": filter_type
        })
        
    except Exception as e:
        logger.error(f"Error in search filter: {e}")
        await callback.answer("❌ Ошибка при применении фильтра.")


def get_search_suggestions_keyboard(suggestions: List[str]):
    """Создание клавиатуры с предложениями поиска"""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    
    keyboard = []
    
    for suggestion in suggestions[:5]:  # Максимум 5 предложений
        keyboard.append([
            InlineKeyboardButton(
                text=f"🔍 {suggestion}",
                callback_data=f"search:{suggestion}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Обработка текстовых сообщений как поисковых запросов
@router.message(F.text, ~F.text.startswith('/'))
async def handle_text_as_search(message: Message, state: FSMContext):
    """Обработка обычного текста как поискового запроса"""
    current_state = await state.get_state()
    
    # Если мы не в специальном состоянии, предлагаем поиск
    if current_state is None:
        query = message.text.strip()
        
        if len(query) >= 2:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"🔍 Найти: {query[:30]}{'...' if len(query) > 30 else ''}",
                        callback_data=f"search:{query}"
                    )],
                    [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
                ]
            )
            
            await message.answer(
                f"🎵 <b>Хотите найти музыку?</b>\n\n"
                f"Запрос: <i>{query}</i>",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
=======
# app/bot/handlers/search.py
"""
Обработчик поиска музыки
"""
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import Optional, List

from app.bot.keyboards.inline import (
    get_search_results_keyboard,
    get_track_actions_keyboard,
    get_search_filters_keyboard
)
from app.bot.utils.messages import Messages
from app.bot.utils.formatters import format_track_info, format_search_results
from app.services import (
    get_search_service, get_user_service, 
    get_analytics_service, get_music_aggregator
)
from app.services.search_service import SearchRequest, SearchStrategy
from app.models.track import TrackSource
from app.core.logging import get_logger, bot_logger
from app.core.exceptions import (
    RateLimitExceededError, DailyLimitExceededError,
    TrackNotFoundError, DownloadError
)

router = Router()
logger = get_logger(__name__)


class SearchStates(StatesGroup):
    """Состояния поиска"""
    waiting_query = State()
    showing_results = State()
    downloading = State()


@router.message(F.text.startswith("🔍"))
async def handle_search_button(message: Message, state: FSMContext):
    """Обработка нажатия кнопки поиска"""
    await message.answer(
        "🎵 <b>Поиск музыки</b>\n\n"
        "Напишите название трека или исполнителя:\n"
        "• <code>Imagine Dragons - Believer</code>\n"
        "• <code>Тейлор Свифт</code>\n"
        "• <code>лучшие хиты 2024</code>",
        parse_mode="HTML"
    )
    await state.set_state(SearchStates.waiting_query)


@router.callback_query(F.data.startswith("search:"))
async def callback_search(callback: CallbackQuery, state: FSMContext):
    """Обработка поиска из callback"""
    try:
        query = callback.data.split(":", 1)[1]
        await perform_search(callback.message, query, callback.from_user.id, state, is_callback=True)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in search callback: {e}")
        await callback.answer("❌ Ошибка при поиске.", show_alert=True)


@router.message(SearchStates.waiting_query)
async def handle_search_query(message: Message, state: FSMContext):
    """Обработка поискового запроса"""
    try:
        query = message.text.strip()
        
        if len(query) < 2:
            await message.answer(
                "❌ Слишком короткий запрос. Введите минимум 2 символа."
            )
            return
        
        if len(query) > 100:
            await message.answer(
                "❌ Слишком длинный запрос. Максимум 100 символов."
            )
            return
        
        await perform_search(message, query, message.from_user.id, state)
        
    except Exception as e:
        logger.error(f"Error handling search query: {e}")
        await message.answer("❌ Произошла ошибка при поиске.")


async def perform_search(
    message: Message, 
    query: str, 
    user_id: int, 
    state: FSMContext,
    is_callback: bool = False
):
    """Выполнение поиска музыки"""
    try:
        user_service = get_user_service()
        search_service = get_search_service()
        analytics_service = get_analytics_service()
        
        # Проверяем лимиты пользователя
        is_premium = await user_service.is_premium_user(user_id)
        limits_info = await user_service.check_daily_limits(user_id)
        
        # Проверяем лимит поисков
        from app.core.security import user_rate_limiter
        search_allowed = await user_rate_limiter.check_search_limit(user_id, is_premium)
        
        if not search_allowed:
            await message.answer(
                "⏳ <b>Лимит поисков исчерпан</b>\n\n"
                f"{'Premium' if is_premium else 'Бесплатный'} аккаунт: "
                f"{'100' if is_premium else '20'} поисков в минуту\n\n"
                "Попробуйте через минуту или оформите Premium подписку.",
                parse_mode="HTML"
            )
            return
        
        # Отправляем сообщение о поиске
        if is_callback:
            search_msg = await message.edit_text(
                f"🔍 <b>Поиск:</b> <i>{query}</i>\n\n"
                "⏳ Ищем в музыкальных сервисах...",
                parse_mode="HTML"
            )
        else:
            search_msg = await message.answer(
                f"🔍 <b>Поиск:</b> <i>{query}</i>\n\n"
                "⏳ Ищем в музыкальных сервисах...",
                parse_mode="HTML"
            )
        
        # Создаем запрос на поиск
        search_request = SearchRequest(
            query=query,
            user_id=user_id,
            limit=20 if is_premium else 10,
            strategy=SearchStrategy.COMPREHENSIVE,
            use_cache=True,
            save_to_history=True
        )
        
        # Выполняем поиск
        search_response = await search_service.search(search_request)
        
        # Логируем поиск
        await bot_logger.log_search(
            user_id=user_id,
            query=query,
            results_count=search_response.total_found,
            duration=search_response.search_time,
            source=",".join(search_response.sources_used)
        )
        
        # Трекаем аналитику
        await analytics_service.track_search_event(
            user_id=user_id,
            query=query,
            results_count=search_response.total_found,
            search_time=search_response.search_time,
            sources_used=search_response.sources_used
        )
        
        if not search_response.results:
            # Результатов не найдено
            no_results_text = Messages.get_no_search_results_message(
                query=query,
                suggestions=search_response.suggestions
            )
            
            # Клавиатура с предложениями
            keyboard = None
            if search_response.suggestions:
                keyboard = get_search_suggestions_keyboard(search_response.suggestions)
            
            await search_msg.edit_text(
                text=no_results_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        
        # Форматируем результаты
        results_text = format_search_results(
            query=query,
            results=search_response.results[:5],  # Показываем первые 5
            total_found=search_response.total_found,
            search_time=search_response.search_time,
            cached=search_response.cached
        )
        
        # Создаем клавиатуру с результатами
        keyboard = get_search_results_keyboard(
            results=search_response.results[:10],
            page=0,
            total_pages=(len(search_response.results) - 1) // 10 + 1,
            query=query
        )
        
        # Обновляем сообщение с результатами
        await search_msg.edit_text(
            text=results_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Сохраняем результаты в состояние для пагинации
        await state.update_data({
            "search_results": [result.dict() for result in search_response.results],
            "current_query": query,
            "current_page": 0
        })
        
        await state.set_state(SearchStates.showing_results)
        
    except RateLimitExceededError as e:
        await message.answer(
            "⏳ <b>Слишком много запросов</b>\n\n"
            "Пожалуйста, подождите немного перед следующим поиском.",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error in perform_search: {e}")
        await message.answer(
            "❌ <b>Ошибка поиска</b>\n\n"
            "Попробуйте другой запрос или повторите позже.",
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("track:"))
async def callback_track_action(callback: CallbackQuery, state: FSMContext):
    """Обработка действий с треком"""
    try:
        action_data = callback.data.split(":", 2)
        if len(action_data) < 3:
            await callback.answer("❌ Неверный формат данных.")
            return
        
        action = action_data[1]  # download, info, add_playlist, etc.
        track_index = int(action_data[2])
        
        # Получаем данные из состояния
        data = await state.get_data()
        search_results = data.get("search_results", [])
        
        if track_index >= len(search_results):
            await callback.answer("❌ Трек не найден.")
            return
        
        track_data = search_results[track_index]
        
        if action == "download":
            await handle_track_download(callback, track_data, state)
        elif action == "info":
            await handle_track_info(callback, track_data)
        elif action == "add_playlist":
            await handle_add_to_playlist(callback, track_data, state)
        else:
            await callback.answer("❌ Неизвестное действие.")
            
    except Exception as e:
        logger.error(f"Error in track action callback: {e}")
        await callback.answer("❌ Ошибка при выполнении действия.")


async def handle_track_download(callback: CallbackQuery, track_data: dict, state: FSMContext):
    """Обработка скачивания трека"""
    try:
        user_service = get_user_service()
        music_aggregator = get_music_aggregator()
        analytics_service = get_analytics_service()
        
        user_id = callback.from_user.id
        
        # Проверяем лимиты
        is_premium = await user_service.is_premium_user(user_id)
        limits_info = await user_service.check_daily_limits(user_id)
        
        if not limits_info["can_download"]:
            # Превышен дневной лимит
            limit_text = Messages.get_download_limit_message(
                limits=limits_info,
                is_premium=is_premium
            )
            
            await callback.answer(limit_text, show_alert=True)
            return
        
        # Отправляем уведомление о начале загрузки
        await callback.answer("⏳ Подготавливаем трек к скачиванию...")
        
        # Обновляем сообщение
        download_msg = await callback.message.edit_text(
            f"📥 <b>Скачиваем:</b> {track_data['artist']} - {track_data['title']}\n\n"
            "⏳ Получаем ссылку на скачивание...",
            parse_mode="HTML"
        )
        
        await state.set_state(SearchStates.downloading)
        
        # Получаем ссылку на скачивание
        track_source = TrackSource(track_data["source"])
        
        async with music_aggregator:
            download_result = await music_aggregator.get_download_url(
                track_id=track_data["external_id"],
                source=track_source
            )
        
        if not download_result:
            await download_msg.edit_text(
                f"❌ <b>Ошибка скачивания</b>\n\n"
                f"Не удалось получить ссылку для трека:\n"
                f"<b>{track_data['artist']} - {track_data['title']}</b>\n\n"
                "Попробуйте другой трек или повторите позже.",
                parse_mode="HTML"
            )
            return
        
        # Скачиваем файл
        await download_msg.edit_text(
            f"📥 <b>Скачиваем:</b> {track_data['artist']} - {track_data['title']}\n\n"
            "⬇️ Загружаем аудиофайл...",
            parse_mode="HTML"
        )
        
        # Загружаем аудио через aiohttp
        import aiohttp
        import io
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                download_result.url,
                headers=download_result.headers or {}
            ) as response:
                
                if response.status != 200:
                    raise DownloadError(f"HTTP {response.status}")
                
                audio_data = await response.read()
        
        # Создаем метаданные для файла
        filename = f"{track_data['artist']} - {track_data['title']}.mp3"
        filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.'))[:100]
        
        # Отправляем аудиофайл
        audio_file = BufferedInputFile(audio_data, filename=filename)
        
        # Формируем описание
        caption = format_track_info(track_data, include_download_info=True)
        
        await callback.message.answer_audio(
            audio=audio_file,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_track_actions_keyboard(
                track_data,
                include_download=False  # Уже скачан
            )
        )
        
        # Удаляем сообщение о загрузке
        await download_msg.delete()
        
        # Логируем скачивание
        await bot_logger.log_download(
            user_id=user_id,
            track_id=track_data["external_id"],
            track_title=f"{track_data['artist']} - {track_data['title']}",
            source=track_data["source"],
            duration=0,  # Будет измерено в другом месте
            file_size=len(audio_data)
        )
        
        # Трекаем аналитику
        await analytics_service.track_download_event(
            user_id=user_id,
            track_id=track_data["external_id"],
            source=track_data["source"],
            success=True,
            file_size=len(audio_data)
        )
        
        # Возвращаемся к состоянию результатов поиска
        await state.set_state(SearchStates.showing_results)
        
    except Exception as e:
        logger.error(f"Error downloading track: {e}")
        
        try:
            await callback.message.edit_text(
                f"❌ <b>Ошибка скачивания</b>\n\n"
                f"Не удалось скачать трек:\n"
                f"<b>{track_data.get('artist', 'Unknown')} - {track_data.get('title', 'Unknown')}</b>\n\n"
                "Попробуйте другой трек или повторите позже.",
                parse_mode="HTML"
            )
        except:
            await callback.answer("❌ Ошибка при скачивании трека.", show_alert=True)


async def handle_track_info(callback: CallbackQuery, track_data: dict):
    """Показать подробную информацию о треке"""
    try:
        info_text = Messages.get_detailed_track_info(track_data)
        
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📥 Скачать", callback_data=f"track:download:{track_data.get('index', 0)}"),
                    InlineKeyboardButton(text="➕ В плейлист", callback_data=f"track:add_playlist:{track_data.get('index', 0)}")
                ],
                [InlineKeyboardButton(text="🔙 К результатам", callback_data="back_to_results")]
            ]
        )
        
        await callback.message.edit_text(
            text=info_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing track info: {e}")
        await callback.answer("❌ Ошибка при получении информации о треке.")


async def handle_add_to_playlist(callback: CallbackQuery, track_data: dict, state: FSMContext):
    """Добавление трека в плейлист"""
    try:
        from app.services import get_playlist_service
        
        playlist_service = get_playlist_service()
        user_id = callback.from_user.id
        
        # Получаем плейлисты пользователя
        playlists = await playlist_service.get_user_playlists(user_id, limit=10)
        
        if not playlists:
            # Нет плейлистов - предлагаем создать
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Создать плейлист", callback_data="create_playlist")],
                    [InlineKeyboardButton(text="🔙 К результатам", callback_data="back_to_results")]
                ]
            )
            
            await callback.message.edit_text(
                "📋 <b>У вас нет плейлистов</b>\n\n"
                "Создайте первый плейлист, чтобы добавлять в него треки!",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await callback.answer()
            return
        
        # Показываем список плейлистов
        from app.bot.keyboards.inline import get_playlists_keyboard
        
        keyboard = get_playlists_keyboard(
            playlists=playlists,
            action="add_track",
            track_index=track_data.get('index', 0)
        )
        
        await callback.message.edit_text(
            f"📋 <b>Выберите плейлист</b>\n\n"
            f"Трек: <b>{track_data['artist']} - {track_data['title']}</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error adding to playlist: {e}")
        await callback.answer("❌ Ошибка при добавлении в плейлист.")


@router.callback_query(F.data.startswith("page:"))
async def callback_search_pagination(callback: CallbackQuery, state: FSMContext):
    """Пагинация результатов поиска"""
    try:
        page = int(callback.data.split(":")[1])
        
        # Получаем данные из состояния
        data = await state.get_data()
        search_results = data.get("search_results", [])
        query = data.get("current_query", "")
        
        if not search_results:
            await callback.answer("❌ Результаты поиска не найдены.")
            return
        
        # Вычисляем диапазон результатов для страницы
        results_per_page = 10
        start_idx = page * results_per_page
        end_idx = min(start_idx + results_per_page, len(search_results))
        
        if start_idx >= len(search_results):
            await callback.answer("❌ Страница не найдена.")
            return
        
        page_results = search_results[start_idx:end_idx]
        total_pages = (len(search_results) - 1) // results_per_page + 1
        
        # Форматируем результаты для страницы
        results_text = format_search_results(
            query=query,
            results=page_results,
            total_found=len(search_results),
            search_time=0,  # Не показываем время для кешированных результатов
            cached=True,
            page=page + 1,
            total_pages=total_pages
        )
        
        # Создаем клавиатуру
        keyboard = get_search_results_keyboard(
            results=page_results,
            page=page,
            total_pages=total_pages,
            query=query
        )
        
        await callback.message.edit_text(
            text=results_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Обновляем текущую страницу в состоянии
        await state.update_data(current_page=page)
        
        await callback.answer(f"📄 Страница {page + 1} из {total_pages}")
        
    except Exception as e:
        logger.error(f"Error in search pagination: {e}")
        await callback.answer("❌ Ошибка при переходе на страницу.")


@router.callback_query(F.data == "back_to_results")
async def callback_back_to_results(callback: CallbackQuery, state: FSMContext):
    """Возврат к результатам поиска"""
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        search_results = data.get("search_results", [])
        query = data.get("current_query", "")
        current_page = data.get("current_page", 0)
        
        if not search_results:
            await callback.answer("❌ Результаты поиска не найдены.")
            return
        
        # Показываем текущую страницу результатов
        results_per_page = 10
        start_idx = current_page * results_per_page
        end_idx = min(start_idx + results_per_page, len(search_results))
        page_results = search_results[start_idx:end_idx]
        total_pages = (len(search_results) - 1) // results_per_page + 1
        
        results_text = format_search_results(
            query=query,
            results=page_results,
            total_found=len(search_results),
            search_time=0,
            cached=True,
            page=current_page + 1,
            total_pages=total_pages
        )
        
        keyboard = get_search_results_keyboard(
            results=page_results,
            page=current_page,
            total_pages=total_pages,
            query=query
        )
        
        await callback.message.edit_text(
            text=results_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await state.set_state(SearchStates.showing_results)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error returning to results: {e}")
        await callback.answer("❌ Ошибка при возврате к результатам.")


@router.callback_query(F.data.startswith("filter:"))
async def callback_search_filter(callback: CallbackQuery, state: FSMContext):
    """Фильтрация результатов поиска"""
    try:
        filter_type = callback.data.split(":")[1]
        
        # Получаем данные из состояния
        data = await state.get_data()
        query = data.get("current_query", "")
        
        if not query:
            await callback.answer("❌ Запрос не найден.")
            return
        
        # Определяем источники для поиска
        sources = None
        if filter_type == "vk":
            sources = [TrackSource.VK_AUDIO]
        elif filter_type == "youtube":
            sources = [TrackSource.YOUTUBE]
        elif filter_type == "spotify":
            sources = [TrackSource.SPOTIFY]
        
        # Повторяем поиск с фильтром
        search_service = get_search_service()
        
        search_request = SearchRequest(
            query=query,
            user_id=callback.from_user.id,
            sources=sources,
            limit=20,
            strategy=SearchStrategy.COMPREHENSIVE,
            use_cache=True,
            save_to_history=False  # Не сохраняем повторный поиск
        )
        
        # Показываем индикатор загрузки
        await callback.answer("🔄 Применяем фильтр...")
        
        await callback.message.edit_text(
            f"🔍 <b>Поиск с фильтром:</b> <i>{query}</i>\n\n"
            "⏳ Фильтруем результаты...",
            parse_mode="HTML"
        )
        
        # Выполняем поиск
        search_response = await search_service.search(search_request)
        
        if not search_response.results:
            await callback.message.edit_text(
                f"❌ <b>Ничего не найдено</b>\n\n"
                f"По запросу <i>{query}</i> с применённым фильтром результатов не найдено.\n\n"
                "Попробуйте убрать фильтр или изменить запрос.",
                parse_mode="HTML"
            )
            return
        
        # Показываем отфильтрованные результаты
        results_text = format_search_results(
            query=query,
            results=search_response.results[:5],
            total_found=search_response.total_found,
            search_time=search_response.search_time,
            cached=search_response.cached,
            filter_applied=filter_type.upper()
        )
        
        keyboard = get_search_results_keyboard(
            results=search_response.results[:10],
            page=0,
            total_pages=(len(search_response.results) - 1) // 10 + 1,
            query=query,
            filter_type=filter_type
        )
        
        await callback.message.edit_text(
            text=results_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Обновляем состояние
        await state.update_data({
            "search_results": [result.dict() for result in search_response.results],
            "current_filter": filter_type
        })
        
    except Exception as e:
        logger.error(f"Error in search filter: {e}")
        await callback.answer("❌ Ошибка при применении фильтра.")


def get_search_suggestions_keyboard(suggestions: List[str]):
    """Создание клавиатуры с предложениями поиска"""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    
    keyboard = []
    
    for suggestion in suggestions[:5]:  # Максимум 5 предложений
        keyboard.append([
            InlineKeyboardButton(
                text=f"🔍 {suggestion}",
                callback_data=f"search:{suggestion}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Обработка текстовых сообщений как поисковых запросов
@router.message(F.text, ~F.text.startswith('/'))
async def handle_text_as_search(message: Message, state: FSMContext):
    """Обработка обычного текста как поискового запроса"""
    current_state = await state.get_state()
    
    # Если мы не в специальном состоянии, предлагаем поиск
    if current_state is None:
        query = message.text.strip()
        
        if len(query) >= 2:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"🔍 Найти: {query[:30]}{'...' if len(query) > 30 else ''}",
                        callback_data=f"search:{query}"
                    )],
                    [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
                ]
            )
            
            await message.answer(
                f"🎵 <b>Хотите найти музыку?</b>\n\n"
                f"Запрос: <i>{query}</i>",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
>>>>>>> a6dfd6a (upd commit)
