"""
Обработчик плейлистов
"""
from typing import List, Optional
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.core.logging import get_logger, bot_logger
from app.services.playlist_service import playlist_service
from app.services.user_service import user_service
from app.schemas.playlist import PlaylistCreate, PlaylistUpdate, PlaylistTrackAdd
from app.bot.keyboards.inline import (
    get_playlists_keyboard, get_playlist_actions_keyboard, 
    get_add_to_playlist_keyboard, get_confirmation_keyboard,
    get_back_to_menu_keyboard
)
from app.bot.keyboards.reply import get_cancel_keyboard
from app.bot.keyboards.builders import DynamicKeyboardBuilder

playlist_router = Router()
logger = get_logger(__name__)


class PlaylistStates(StatesGroup):
    """Состояния для работы с плейлистами"""
    waiting_for_name = State()
    waiting_for_description = State()
    editing_name = State()
    editing_description = State()


@playlist_router.message(Command("playlists"))
@playlist_router.callback_query(F.data == "my_playlists")
async def show_my_playlists(event, user, **kwargs):
    """Показать плейлисты пользователя"""
    try:
        # Получаем плейлисты пользователя
        playlists = await playlist_service.get_user_playlists(user.id, limit=50)
        
        if not playlists:
            no_playlists_text = (
                "📋 **У вас пока нет плейлистов**\n\n"
                "Создайте свой первый плейлист и начните собирать любимую музыку!\n\n"
                "💡 **Советы:**\n"
                "• Создавайте тематические плейлисты\n"
                "• Добавляйте описания для удобства\n"
                "• Делитесь с друзьями"
            )
            
            keyboard = get_back_to_menu_keyboard()
            
            if isinstance(event, Message):
                await event.answer(
                    no_playlists_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            else:
                await event.message.edit_text(
                    no_playlists_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            return
        
        # Создаем клавиатуру с плейлистами
        keyboard = get_playlists_keyboard(playlists)
        
        playlists_text = (
            f"📋 **Ваши плейлисты ({len(playlists)})**\n\n"
            "Выберите плейлист для просмотра или управления:"
        )
        
        if isinstance(event, Message):
            await event.answer(
                playlists_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await event.message.edit_text(
                playlists_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        
        await bot_logger.log_update(
            update_type="playlists_view",
            user_id=user.telegram_id,
            playlists_count=len(playlists)
        )
        
    except Exception as e:
        logger.error(f"Error showing playlists for user {user.id}: {e}")
        error_text = "❌ Ошибка при загрузке плейлистов. Попробуйте позже."
        
        if isinstance(event, Message):
            await event.answer(error_text)
        else:
            await event.answer(error_text, show_alert=True)


@playlist_router.callback_query(F.data.startswith("playlist:"))
async def show_playlist_details(callback: CallbackQuery, user, **kwargs):
    """Показать детали плейлиста"""
    try:
        playlist_id = callback.data.split(":")[1]
        
        # Получаем плейлист
        playlist = await playlist_service.get_playlist_by_id(int(playlist_id), user.id)
        
        if not playlist:
            await callback.answer("❌ Плейлист не найден", show_alert=True)
            return
        
        # Проверяем права
        is_owner = playlist.created_by_id == user.id
        is_empty = len(playlist.tracks) == 0 if playlist.tracks else True
        
        # Получаем статистику
        stats = await playlist_service.get_playlist_stats(int(playlist_id))
        
        # Форматируем информацию
        playlist_text = format_playlist_info(playlist, stats, is_owner)
        
        # Создаем клавиатуру
        keyboard = get_playlist_actions_keyboard(
            playlist_id, 
            is_owner=is_owner, 
            is_empty=is_empty
        )
        
        await callback.message.edit_text(
            playlist_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing playlist details: {e}")
        await callback.answer("❌ Ошибка при загрузке плейлиста", show_alert=True)


@playlist_router.callback_query(F.data == "create_playlist")
async def start_create_playlist(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Начать создание плейлиста"""
    try:
        create_text = (
            "📋 **Создание нового плейлиста**\n\n"
            "Введите название для вашего плейлиста:\n\n"
            "💡 **Советы:**\n"
            "• Используйте понятное название\n"
            "• Максимум 100 символов\n"
            "• Можно использовать эмодзи"
        )
        
        keyboard = get_cancel_keyboard()
        
        await callback.message.edit_text(
            create_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await state.set_state(PlaylistStates.waiting_for_name)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error starting playlist creation: {e}")
        await callback.answer("❌ Ошибка при создании плейлиста", show_alert=True)


@playlist_router.message(PlaylistStates.waiting_for_name)
async def process_playlist_name(message: Message, state: FSMContext, user, **kwargs):
    """Обработать название плейлиста"""
    try:
        name = message.text.strip()
        
        if len(name) > 100:
            await message.answer(
                "❌ Название слишком длинное. Максимум 100 символов.\n"
                "Попробуйте ещё раз:"
            )
            return
        
        if len(name) < 1:
            await message.answer(
                "❌ Название не может быть пустым.\n"
                "Попробуйте ещё раз:"
            )
            return
        
        # Сохраняем название
        await state.update_data(name=name)
        
        description_text = (
            f"📋 **Плейлист: "{name}"**\n\n"
            "Добавьте описание (необязательно):\n\n"
            "💡 **Примеры:**\n"
            "• Моя любимая музыка для тренировок\n"
            "• Релакс музыка для сна\n"
            "• Хиты 2024 года\n\n"
            "Или нажмите «Пропустить» чтобы создать без описания."
        )
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="➡️ Пропустить", callback_data="skip_description"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_creation")
        )
        
        await message.answer(
            description_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await state.set_state(PlaylistStates.waiting_for_description)
        
    except Exception as e:
        logger.error(f"Error processing playlist name: {e}")
        await message.answer("❌ Ошибка при обработке названия")


@playlist_router.message(PlaylistStates.waiting_for_description)
async def process_playlist_description(message: Message, state: FSMContext, user, **kwargs):
    """Обработать описание плейлиста"""
    try:
        description = message.text.strip()
        
        if len(description) > 500:
            await message.answer(
                "❌ Описание слишком длинное. Максимум 500 символов.\n"
                "Попробуйте ещё раз:"
            )
            return
        
        # Сохраняем описание
        await state.update_data(description=description)
        
        # Создаем плейлист
        await create_playlist_final(message, state, user, description)
        
    except Exception as e:
        logger.error(f"Error processing playlist description: {e}")
        await message.answer("❌ Ошибка при обработке описания")


@playlist_router.callback_query(F.data == "skip_description")
async def skip_description(callback: CallbackQuery, state: FSMContext, user, **kwargs):
    """Пропустить описание"""
    try:
        await create_playlist_final(callback.message, state, user, None)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error skipping description: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


async def create_playlist_final(message: Message, state: FSMContext, user, description: Optional[str]):
    """Финальное создание плейлиста"""
    try:
        data = await state.get_data()
        name = data.get('name')
        
        if not name:
            await message.answer("❌ Ошибка: название не найдено")
            return
        
        # Создаем плейлист
        playlist_data = PlaylistCreate(
            name=name,
            description=description,
            is_public=False  # По умолчанию приватный
        )
        
        playlist = await playlist_service.create_playlist(user.id, playlist_data)
        
        if not playlist:
            await message.answer("❌ Ошибка при создании плейлиста")
            return
        
        success_text = (
            f"✅ **Плейлист создан!**\n\n"
            f"📋 **Название:** {name}\n"
        )
        
        if description:
            success_text += f"📝 **Описание:** {description}\n"
        
        success_text += (
            f"🔒 **Приватность:** Приватный\n"
            f"🆔 **ID:** {playlist.id}\n\n"
            "Теперь вы можете добавлять в него треки!"
        )
        
        # Клавиатура с действиями
        keyboard = get_playlist_actions_keyboard(str(playlist.id), is_owner=True, is_empty=True)
        
        await message.answer(
            success_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await state.clear()
        
        await bot_logger.log_update(
            update_type="playlist_created",
            user_id=user.telegram_id,
            playlist_id=str(playlist.id),
            playlist_name=name
        )
        
    except Exception as e:
        logger.error(f"Error creating playlist: {e}")
        await message.answer("❌ Ошибка при создании плейлиста")


@playlist_router.callback_query(F.data.startswith("add_to_playlist:"))
async def show_add_to_playlist(callback: CallbackQuery, user, **kwargs):
    """Показать список плейлистов для добавления трека"""
    try:
        parts = callback.data.split(":")
        track_id = parts[1]
        source = parts[2]
        
        # Получаем плейлисты пользователя
        playlists = await playlist_service.get_user_playlists(user.id, limit=20)
        
        if not playlists:
            no_playlists_text = (
                "📋 **У вас нет плейлистов**\n\n"
                "Создайте плейлист, чтобы добавлять в него треки."
            )
            
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(
                    text="➕ Создать плейлист", 
                    callback_data=f"create_playlist_with_track:{track_id}:{source}"
                )
            )
            builder.row(
                InlineKeyboardButton(
                    text="⬅️ Назад", 
                    callback_data=f"track:{track_id}:{source}"
                )
            )
            
            await callback.message.edit_text(
                no_playlists_text,
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        # Создаем клавиатуру выбора плейлиста
        keyboard = get_add_to_playlist_keyboard(playlists, track_id, source)
        
        select_text = (
            "📋 **Выберите плейлист**\n\n"
            "В какой плейлист добавить трек?"
        )
        
        await callback.message.edit_text(
            select_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing add to playlist: {e}")
        await callback.answer("❌ Ошибка при загрузке плейлистов", show_alert=True)


@playlist_router.callback_query(F.data.startswith("add_track_to_playlist:"))
async def add_track_to_playlist(callback: CallbackQuery, user, **kwargs):
    """Добавить трек в плейлист"""
    try:
        parts = callback.data.split(":")
        playlist_id = int(parts[1])
        track_id = parts[2]
        source = parts[3]
        
        # Получаем информацию о плейлисте
        playlist = await playlist_service.get_playlist_by_id(playlist_id, user.id)
        if not playlist:
            await callback.answer("❌ Плейлист не найден", show_alert=True)
            return
        
        # Добавляем трек
        track_data = PlaylistTrackAdd(track_id=track_id)
        success = await playlist_service.add_track_to_playlist(playlist_id, user.id, track_data)
        
        if success:
            success_text = (
                f"✅ **Трек добавлен в плейлист!**\n\n"
                f"📋 **Плейлист:** {playlist.name}\n"
                f"🎵 **Треков:** {len(playlist.tracks) + 1 if playlist.tracks else 1}"
            )
            
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(
                    text="📋 Открыть плейлист", 
                    callback_data=f"playlist:{playlist_id}"
                )
            )
            builder.row(
                InlineKeyboardButton(
                    text="➕ В другой плейлист", 
                    callback_data=f"add_to_playlist:{track_id}:{source}"
                )
            )
            builder.row(
                InlineKeyboardButton(
                    text="⬅️ К треку", 
                    callback_data=f"track:{track_id}:{source}"
                )
            )
            
            await callback.message.edit_text(
                success_text,
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )
            
            await bot_logger.log_update(
                update_type="track_added_to_playlist",
                user_id=user.telegram_id,
                playlist_id=str(playlist_id),
                track_id=track_id
            )
        else:
            await callback.answer("❌ Не удалось добавить трек. Возможно, он уже есть в плейлисте.", show_alert=True)
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error adding track to playlist: {e}")
        await callback.answer("❌ Ошибка при добавлении трека", show_alert=True)


@playlist_router.callback_query(F.data.startswith("delete_playlist:"))
async def confirm_delete_playlist(callback: CallbackQuery, **kwargs):
    """Подтверждение удаления плейлиста"""
    try:
        playlist_id = callback.data.split(":")[1]
        
        confirm_text = (
            "⚠️ **Удаление плейлиста**\n\n"
            "Вы действительно хотите удалить этот плейлист?\n"
            "Это действие нельзя отменить."
        )
        
        keyboard = get_confirmation_keyboard("delete_playlist", playlist_id)
        
        await callback.message.edit_text(
            confirm_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error confirming playlist deletion: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@playlist_router.callback_query(F.data.startswith("confirm:delete_playlist:"))
async def delete_playlist_confirmed(callback: CallbackQuery, user, **kwargs):
    """Удалить плейлист после подтверждения"""
    try:
        playlist_id = int(callback.data.split(":")[2])
        
        success = await playlist_service.delete_playlist(playlist_id, user.id)
        
        if success:
            success_text = "✅ Плейлист успешно удален"
            keyboard = get_back_to_menu_keyboard()
            
            await callback.message.edit_text(
                success_text,
                reply_markup=keyboard
            )
            
            await bot_logger.log_update(
                update_type="playlist_deleted",
                user_id=user.telegram_id,
                playlist_id=str(playlist_id)
            )
        else:
            await callback.answer("❌ Не удалось удалить плейлист", show_alert=True)
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error deleting playlist: {e}")
        await callback.answer("❌ Ошибка при удалении", show_alert=True)


def format_playlist_info(playlist, stats: dict, is_owner: bool) -> str:
    """Форматирование информации о плейлисте"""
    text = f"📋 **{playlist.name}**\n\n"
    
    if playlist.description:
        text += f"📝 {playlist.description}\n\n"
    
    # Основная информация
    tracks_count = stats.get('tracks_count', 0)
    total_duration = stats.get('total_duration', 0)
    
    text += f"🎵 **Треков:** {tracks_count}\n"
    
    if total_duration > 0:
        hours = total_duration // 3600
        minutes = (total_duration % 3600) // 60
        if hours > 0:
            text += f"⏱️ **Длительность:** {hours}ч {minutes}мин\n"
        else:
            text += f"⏱️ **Длительность:** {minutes}мин\n"
    
    # Приватность
    privacy_text = "🔒 Приватный" if not playlist.is_public else "🌐 Публичный"
    text += f"👁️ **Доступ:** {privacy_text}\n"
    
    # Жанры
    genres = stats.get('genres', [])
    if genres:
        genres_text = ", ".join(genres[:3])
        if len(genres) > 3:
            genres_text += f" и ещё {len(genres) - 3}"
        text += f"🎭 **Жанры:** {genres_text}\n"
    
    # Информация о создателе
    if is_owner:
        created_at = stats.get('created_at')
        if created_at:
            text += f"📅 **Создан:** {created_at.strftime('%d.%m.%Y')}\n"
    
    return text


# Отмена состояний
@playlist_router.callback_query(F.data.in_(["cancel", "cancel_creation"]))
@playlist_router.message(F.text == "❌ Отмена")
async def cancel_action(event, state: FSMContext, **kwargs):
    """Отмена текущего действия"""
    try:
        await state.clear()
        
        cancel_text = "❌ Действие отменено"
        keyboard = get_back_to_menu_keyboard()
        
        if isinstance(event, Message):
            await event.answer(cancel_text, reply_markup=keyboard)
        else:
            await event.message.edit_text(cancel_text, reply_markup=keyboard)
            await event.answer()
            
    except Exception as e:
        logger.error(f"Error cancelling action: {e}")


from aiogram.types import InlineKeyboardButton