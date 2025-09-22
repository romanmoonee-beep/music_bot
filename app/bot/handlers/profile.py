# app/bot/handlers/profile.py
"""
Обработчик профиля и статистики пользователя
"""
from typing import Optional
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.core.logging import get_logger, bot_logger
from app.services.user_service import user_service
from app.services.analytics_service import analytics_service
from app.bot.keyboards.inline import (
    get_profile_keyboard, get_settings_keyboard, 
    get_quality_settings_keyboard, get_back_to_menu_keyboard,
    get_confirmation_keyboard
)
from app.bot.utils.formatters import (
    format_user_stats, format_subscription_info, 
    format_listening_history, format_achievements
)

router = Router()
logger = get_logger(__name__)


class ProfileStates(StatesGroup):
    """Состояния для работы с профилем"""
    viewing_profile = State()
    editing_settings = State()
    exporting_data = State()


@router.message(Command("profile"))
@router.callback_query(F.data == "profile")
async def show_profile(event, user, **kwargs):
    """Показать профиль пользователя"""
    try:
        # Получаем статистику пользователя
        user_stats = await user_service.get_user_stats(user.telegram_id)
        
        # Получаем информацию о подписке
        subscription = await user_service.get_user_subscription(user.telegram_id)
        is_premium = await user_service.is_premium_user(user.telegram_id)
        
        # Получаем настройки
        settings = await user_service.get_user_settings(user.telegram_id)
        
        # Формируем текст профиля
        profile_text = await format_profile_info(
            user, user_stats, subscription, is_premium, settings
        )
        
        # Создаем клавиатуру
        keyboard = get_profile_keyboard(is_premium=is_premium)
        
        if isinstance(event, Message):
            await event.answer(
                profile_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            await event.message.edit_text(
                profile_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await event.answer()
        
        await bot_logger.log_update(
            update_type="profile_view",
            user_id=user.telegram_id,
            is_premium=is_premium
        )
        
    except Exception as e:
        logger.error(f"Error showing profile for user {user.id}: {e}")
        error_text = "❌ Ошибка при загрузке профиля. Попробуйте позже."
        
        if isinstance(event, Message):
            await event.answer(error_text)
        else:
            await event.answer(error_text, show_alert=True)


@router.callback_query(F.data == "my_stats")
async def show_detailed_stats(callback: CallbackQuery, user, **kwargs):
    """Показать детальную статистику"""
    try:
        # Получаем расширенную статистику
        detailed_stats = await analytics_service.get_user_detailed_stats(user.id)
        
        # Получаем историю активности
        activity_history = await analytics_service.get_user_activity_timeline(
            user.id, days=30
        )
        
        # Получаем топ треков пользователя
        top_tracks = await analytics_service.get_user_top_tracks(user.id, limit=10)
        
        # Форматируем статистику
        stats_text = format_detailed_stats(
            detailed_stats, activity_history, top_tracks
        )
        
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📊 Экспорт данных", 
                        callback_data="export_user_data"
                    ),
                    InlineKeyboardButton(
                        text="📈 Достижения", 
                        callback_data="user_achievements"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🎵 История прослушивания", 
                        callback_data="listening_history"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К профилю", 
                        callback_data="profile"
                    )
                ]
            ]
        )
        
        await callback.message.edit_text(
            stats_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing detailed stats: {e}")
        await callback.answer("❌ Ошибка при загрузке статистики", show_alert=True)


@router.callback_query(F.data == "listening_history")
async def show_listening_history(callback: CallbackQuery, user, **kwargs):
    """История прослушивания"""
    try:
        # Получаем историю за последние 7 дней
        history = await analytics_service.get_user_listening_history(
            user.id, days=7, limit=50
        )
        
        if not history:
            no_history_text = (
                "🎵 **История прослушивания**\n\n"
                "У вас пока нет истории прослушивания.\n"
                "Начните слушать музыку, чтобы увидеть статистику!"
            )
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ К профилю", callback_data="profile")]
                ]
            )
            
            await callback.message.edit_text(
                no_history_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        # Форматируем историю
        history_text = format_listening_history(history)
        
        # Клавиатура с навигацией
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        builder.row(
            InlineKeyboardButton(
                text="📊 Последние 30 дней", 
                callback_data="history_30d"
            ),
            InlineKeyboardButton(
                text="📈 Весь период", 
                callback_data="history_all"
            )
        )
        
        builder.row(
            InlineKeyboardButton(
                text="🎯 Топ треков", 
                callback_data="top_tracks"
            ),
            InlineKeyboardButton(
                text="🎭 Топ жанров", 
                callback_data="top_genres"
            )
        )
        
        builder.row(
            InlineKeyboardButton(text="⬅️ К статистике", callback_data="my_stats")
        )
        
        await callback.message.edit_text(
            history_text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing listening history: {e}")
        await callback.answer("❌ Ошибка при загрузке истории", show_alert=True)


@router.callback_query(F.data == "user_achievements")
async def show_achievements(callback: CallbackQuery, user, **kwargs):
    """Достижения пользователя"""
    try:
        # Получаем достижения
        achievements = await analytics_service.get_user_achievements(user.id)
        
        # Получаем прогресс по достижениям
        achievements_progress = await analytics_service.get_achievements_progress(user.id)
        
        # Форматируем достижения
        achievements_text = format_achievements(achievements, achievements_progress)
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏆 Все достижения", 
                        callback_data="all_achievements"
                    )
                ],
                [
                    InlineKeyboardButton(text="⬅️ К статистике", callback_data="my_stats")
                ]
            ]
        )
        
        await callback.message.edit_text(
            achievements_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing achievements: {e}")
        await callback.answer("❌ Ошибка при загрузке достижений", show_alert=True)


@router.callback_query(F.data == "settings")
async def show_settings(callback: CallbackQuery, user, **kwargs):
    """Настройки пользователя"""
    try:
        # Получаем текущие настройки
        settings = await user_service.get_user_settings(user.telegram_id)
        
        settings_text = (
            "⚙️ **Настройки**\n\n"
            f"🎵 **Качество аудио:** {settings.get('audio_quality', '192kbps')}\n"
            f"🔔 **Уведомления:** {'включены' if settings.get('notifications_enabled', True) else 'выключены'}\n"
            f"🌐 **Язык:** {settings.get('language_code', 'ru').upper()}\n"
            f"📱 **Автодобавление в избранное:** {'да' if settings.get('auto_add_to_favorites', False) else 'нет'}\n"
            f"🔞 **Контент 18+:** {'показывать' if settings.get('show_explicit', True) else 'скрывать'}\n\n"
            "Выберите настройку для изменения:"
        )
        
        keyboard = get_settings_keyboard()
        
        await callback.message.edit_text(
            settings_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing settings: {e}")
        await callback.answer("❌ Ошибка при загрузке настроек", show_alert=True)


@router.callback_query(F.data == "settings:quality")
async def change_quality_settings(callback: CallbackQuery, user, **kwargs):
    """Изменение качества аудио"""
    try:
        settings = await user_service.get_user_settings(user.telegram_id)
        current_quality = settings.get('audio_quality', '192kbps')
        
        quality_text = (
            "🎵 **Настройка качества аудио**\n\n"
            "Выберите предпочитаемое качество:\n\n"
            "🔻 **128 kbps** - экономия трафика\n"
            "🔸 **192 kbps** - стандартное качество\n"
            "🔹 **256 kbps** - высокое качество\n"
            "💎 **320 kbps** - максимальное качество (Premium)\n\n"
            f"Текущее: **{current_quality}**"
        )
        
        keyboard = get_quality_settings_keyboard(current_quality)
        
        await callback.message.edit_text(
            quality_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing quality settings: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("set_quality:"))
async def set_audio_quality(callback: CallbackQuery, user, **kwargs):
    """Установка качества аудио"""
    try:
        quality = callback.data.split(":")[1]
        
        # Проверяем Premium для 320kbps
        if quality == "320kbps":
            is_premium = await user_service.is_premium_user(user.telegram_id)
            if not is_premium:
                await callback.answer(
                    "💎 Качество 320kbps доступно только для Premium подписчиков!",
                    show_alert=True
                )
                return
        
        # Обновляем настройки
        await user_service.update_user_settings(
            user.telegram_id,
            {"audio_quality": quality}
        )
        
        success_text = (
            "✅ **Качество аудио обновлено**\n\n"
            f"Новое качество: **{quality}**\n\n"
            "Изменения вступят в силу для новых скачиваний."
        )
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ К настройкам", callback_data="settings")]
            ]
        )
        
        await callback.message.edit_text(
            success_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer("Настройки сохранены!")
        
        # Логируем изменение настроек
        await bot_logger.log_update(
            update_type="settings_changed",
            user_id=user.telegram_id,
            setting="audio_quality",
            new_value=quality
        )
        
    except Exception as e:
        logger.error(f"Error setting quality: {e}")
        await callback.answer("❌ Ошибка при сохранении настроек", show_alert=True)


@router.callback_query(F.data == "export_user_data")
async def export_user_data(callback: CallbackQuery, user, state: FSMContext, **kwargs):
    """Экспорт данных пользователя"""
    try:
        # Проверяем, можно ли экспортировать
        last_export = await user_service.get_last_data_export(user.telegram_id)
        if last_export:
            from datetime import datetime, timedelta
            if datetime.utcnow() - last_export < timedelta(days=7):
                await callback.answer(
                    "📊 Экспорт данных доступен раз в неделю. "
                    "Попробуйте позже.",
                    show_alert=True
                )
                return
        
        await callback.answer("📊 Подготавливаем ваши данные...")
        
        # Отправляем сообщение о начале экспорта
        export_msg = await callback.message.edit_text(
            "📊 **Экспорт данных**\n\n"
            "⏳ Собираем ваши данные...\n"
            "Это может занять несколько минут.",
            parse_mode="Markdown"
        )
        
        # Экспортируем данные
        export_data = await user_service.export_user_data(user.telegram_id)
        
        if not export_data:
            await export_msg.edit_text(
                "❌ **Ошибка экспорта**\n\n"
                "Не удалось подготовить данные. Попробуйте позже.",
                parse_mode="Markdown"
            )
            return
        
        # Создаем файл с данными
        import json
        from datetime import datetime
        
        filename = f"my_music_data_{user.telegram_id}_{datetime.now().strftime('%Y%m%d')}.json"
        file_content = json.dumps(export_data, ensure_ascii=False, indent=2)
        
        # Отправляем файл
        file_buffer = BufferedInputFile(
            file_content.encode('utf-8'),
            filename=filename
        )
        
        await callback.message.answer_document(
            document=file_buffer,
            caption=(
                "📊 **Ваши данные**\n\n"
                "В файле содержится:\n"
                "• Профиль и настройки\n"
                "• История поисков\n"
                "• Плейлисты\n"
                "• Статистика прослушиваний\n"
                "• Избранные треки\n\n"
                "🔒 Храните файл в безопасном месте!"
            ),
            parse_mode="Markdown"
        )
        
        # Удаляем сообщение о загрузке
        await export_msg.delete()
        
        # Записываем факт экспорта
        await user_service.record_data_export(user.telegram_id)
        
        await bot_logger.log_update(
            update_type="data_exported",
            user_id=user.telegram_id,
            export_size=len(file_content)
        )
        
    except Exception as e:
        logger.error(f"Error exporting user data: {e}")
        await callback.answer("❌ Ошибка при экспорте данных", show_alert=True)


@router.callback_query(F.data == "delete_account")
async def confirm_delete_account(callback: CallbackQuery, **kwargs):
    """Подтверждение удаления аккаунта"""
    try:
        warning_text = (
            "⚠️ **ВНИМАНИЕ! УДАЛЕНИЕ АККАУНТА**\n\n"
            "Это действие **НЕОБРАТИМО**!\n\n"
            "Будут удалены:\n"
            "• Все ваши плейлисты\n"
            "• История поисков и прослушиваний\n"
            "• Настройки и предпочтения\n"
            "• Подписка (без возврата средств)\n\n"
            "❗ Вы **НЕ СМОЖЕТЕ** восстановить данные!\n\n"
            "Вы действительно хотите удалить аккаунт?"
        )
        
        keyboard = get_confirmation_keyboard("delete_account", "")
        
        await callback.message.edit_text(
            warning_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing delete confirmation: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "confirm:delete_account:")
async def delete_account_confirmed(callback: CallbackQuery, user, **kwargs):
    """Удаление аккаунта после подтверждения"""
    try:
        await callback.answer("🗑️ Удаляем аккаунт...")
        
        # Удаляем все данные пользователя
        deletion_result = await user_service.delete_user_account(user.telegram_id)
        
        if deletion_result:
            farewell_text = (
                "✅ **Аккаунт удален**\n\n"
                "Ваш аккаунт и все связанные данные удалены.\n\n"
                "Спасибо, что пользовались нашим ботом! 👋\n\n"
                "Если передумаете, можете снова написать /start"
            )
            
            await callback.message.edit_text(
                farewell_text,
                reply_markup=None,
                parse_mode="Markdown"
            )
            
            # Логируем удаление аккаунта
            await bot_logger.log_update(
                update_type="account_deleted",
                user_id=user.telegram_id,
                reason="user_request"
            )
        else:
            await callback.answer(
                "❌ Ошибка при удалении аккаунта. Обратитесь в поддержку.",
                show_alert=True
            )
        
    except Exception as e:
        logger.error(f"Error deleting account: {e}")
        await callback.answer("❌ Ошибка при удалении аккаунта", show_alert=True)


# Утилитарные функции

async def format_profile_info(user, user_stats, subscription, is_premium, settings) -> str:
    """Форматирование информации профиля"""
    
    # Определяем имя для отображения
    display_name = user.first_name or user.username or f"User{user.telegram_id}"
    
    # Базовая информация
    profile_text = (
        f"👤 **{display_name}**\n"
        f"🆔 ID: `{user.telegram_id}`\n"
        f"📅 С нами: {format_registration_date(user.created_at)}\n"
    )
    
    # Статус подписки
    if is_premium and subscription:
        if subscription.expires_at:
            days_left = (subscription.expires_at - datetime.utcnow()).days
            profile_text += (
                f"👑 **Premium** (осталось {days_left} дн.)\n"
                f"🔄 Автопродление: {'включено' if subscription.auto_renew else 'выключено'}\n"
            )
        else:
            profile_text += "👑 **Premium** (бессрочно)\n"
    else:
        profile_text += "🆓 **Free пользователь**\n"
    
    profile_text += "\n"
    
    # Статистика
    profile_text += (
        "📊 **Ваша статистика:**\n"
        f"🔍 Поисков: {user_stats.total_searches:,}\n"
        f"📥 Скачиваний: {user_stats.total_downloads:,}\n"
        f"❤️ В избранном: {user_stats.favorite_tracks_count}\n"
        f"📋 Плейлистов: {user_stats.playlists_count}\n"
    )
    
    if user_stats.listening_time_hours > 0:
        profile_text += f"🎧 Прослушано: {user_stats.listening_time_hours:.1f} ч.\n"
    
    if user_stats.most_played_genre:
        profile_text += f"🎭 Любимый жанр: {user_stats.most_played_genre}\n"
    
    # Настройки
    profile_text += (
        f"\n⚙️ **Настройки:**\n"
        f"🎵 Качество: {settings.get('audio_quality', '192kbps')}\n"
        f"🌐 Язык: {settings.get('language_code', 'ru').upper()}\n"
        f"🔔 Уведомления: {'вкл.' if settings.get('notifications_enabled', True) else 'выкл.'}\n"
    )
    
    return profile_text


def format_registration_date(created_at) -> str:
    """Форматирование даты регистрации"""
    from datetime import datetime
    
    days_ago = (datetime.utcnow() - created_at).days
    
    if days_ago == 0:
        return "сегодня"
    elif days_ago == 1:
        return "вчера"
    elif days_ago < 30:
        return f"{days_ago} дн. назад"
    elif days_ago < 365:
        months = days_ago // 30
        return f"{months} мес. назад"
    else:
        years = days_ago // 365
        return f"{years} г. назад"


def format_detailed_stats(detailed_stats, activity_history, top_tracks) -> str:
    """Форматирование детальной статистики"""
    
    text = "📊 **Детальная статистика**\n\n"
    
    # Общие метрики
    text += (
        "🎯 **Общее:**\n"
        f"• Всего сессий: {detailed_stats.get('total_sessions', 0)}\n"
        f"• Среднее время сессии: {detailed_stats.get('avg_session_duration', 0):.1f} мин\n"
        f"• Всего времени в боте: {detailed_stats.get('total_time_hours', 0):.1f} ч\n\n"
    )
    
    # Активность по дням недели
    if 'weekly_activity' in detailed_stats:
        text += "📅 **Активность по дням недели:**\n"
        days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        for i, day in enumerate(days):
            count = detailed_stats['weekly_activity'].get(str(i), 0)
            text += f"• {day}: {count} действий\n"
        text += "\n"
    
    # Топ треки
    if top_tracks:
        text += "🎵 **Ваши топ треки (последний месяц):**\n"
        for i, track in enumerate(top_tracks[:5], 1):
            text += f"{i}. {track['artist']} - {track['title']}\n"
            text += f"   ▫️ Прослушано: {track['play_count']} раз\n"
        text += "\n"
    
    # Активность за последнюю неделю
    if activity_history:
        text += "📈 **Активность за неделю:**\n"
        for day_data in activity_history[-7:]:
            date = day_data['date']
            actions = day_data['actions_count']
            text += f"• {date}: {actions} действий\n"
    
    return text


def format_listening_history(history) -> str:
    """Форматирование истории прослушивания"""
    
    text = "🎵 **История прослушивания**\n\n"
    
    if not history:
        return text + "Пока нет данных о прослушивании."
    
    # Группируем по дням
    from collections import defaultdict
    from datetime import datetime
    
    by_date = defaultdict(list)
    for item in history:
        date = item['timestamp'].date()
        by_date[date].append(item)
    
    # Показываем последние 7 дней
    sorted_dates = sorted(by_date.keys(), reverse=True)
    
    for date in sorted_dates[:7]:
        tracks = by_date[date]
        
        if date == datetime.now().date():
            date_str = "Сегодня"
        elif (datetime.now().date() - date).days == 1:
            date_str = "Вчера"
        else:
            date_str = date.strftime("%d.%m")
        
        text += f"📅 **{date_str}** ({len(tracks)} треков):\n"
        
        for track in tracks[:5]:  # Показываем первые 5 треков дня
            time_str = track['timestamp'].strftime("%H:%M")
            text += f"• {time_str} - {track['artist']} - {track['title']}\n"
        
        if len(tracks) > 5:
            text += f"  ... и ещё {len(tracks) - 5} треков\n"
        
        text += "\n"
    
    return text


def format_achievements(achievements, progress) -> str:
    """Форматирование достижений"""
    
    text = "🏆 **Ваши достижения**\n\n"
    
    if not achievements:
        text += (
            "У вас пока нет достижений.\n"
            "Используйте бот, чтобы получить первые награды!"
        )
        return text
    
    # Полученные достижения
    earned_count = len([a for a in achievements if a.get('earned', False)])
    total_count = len(achievements)
    
    text += f"Получено: **{earned_count}/{total_count}** 🎯\n\n"
    
    # Категории достижений
    categories = {
        'search': '🔍 Поиск',
        'download': '📥 Скачивание',  
        'playlist': '📋 Плейлисты',
        'social': '👥 Социальные',
        'time': '⏰ Активность'
    }
    
    for category, title in categories.items():
        category_achievements = [a for a in achievements if a.get('category') == category]
        if not category_achievements:
            continue
            
        text += f"**{title}:**\n"
        
        for achievement in category_achievements:
            if achievement.get('earned'):
                icon = "✅"
                date_earned = achievement.get('earned_at', '').strftime('%d.%m.%Y') if achievement.get('earned_at') else ''
                text += f"{icon} {achievement['name']} {date_earned}\n"
            else:
                icon = "🔒"
                # Показываем прогресс
                current = progress.get(achievement['id'], {}).get('current', 0)
                required = achievement.get('required', 0)
                text += f"{icon} {achievement['name']} ({current}/{required})\n"
        
        text += "\n"
    
    return text


from datetime import datetime