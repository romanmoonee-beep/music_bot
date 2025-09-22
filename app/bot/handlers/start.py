<<<<<<< HEAD
# app/bot/handlers/start.py
"""
Обработчик команды /start и основного меню
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import Optional

from app.bot.keyboards.inline import (
    get_main_menu_keyboard,
    get_premium_keyboard,
    get_help_keyboard
)
from app.bot.utils.messages import Messages
from app.services import get_user_service, get_analytics_service
from app.core.logging import get_logger, bot_logger

router = Router()
logger = get_logger(__name__)


class MainStates(StatesGroup):
    """Состояния главного меню"""
    main_menu = State()
    waiting_search = State()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    try:
        user_service = get_user_service()
        analytics_service = get_analytics_service()
        
        # Получаем или создаем пользователя
        user = await user_service.get_or_create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            language_code=message.from_user.language_code
        )
        
        # Проверяем Premium статус
        is_premium = await user_service.is_premium_user(message.from_user.id)
        
        # Получаем статистику пользователя
        user_stats = await user_service.get_user_stats(message.from_user.id)
        
        # Трекаем событие
        await analytics_service.track_user_event(
            user_id=user.id,
            event_type="start_command",
            event_data={
                "source": "telegram",
                "is_new_user": user_stats.tracks_downloaded == 0
            }
        )
        
        # Формируем приветственное сообщение
        welcome_text = Messages.get_welcome_message(
            user_name=user.first_name or "Музыкальный меломан",
            is_premium=is_premium,
            tracks_count=user_stats.tracks_downloaded
        )
        
        # Отправляем главное меню
        await message.answer(
            text=welcome_text,
            reply_markup=get_main_menu_keyboard(is_premium=is_premium),
            parse_mode="HTML"
        )
        
        # Устанавливаем состояние
        await state.set_state(MainStates.main_menu)
        
        await bot_logger.log_update(
            update_type="start_command",
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            command="/start"
        )
        
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await message.answer(
            "❌ Произошла ошибка при запуске бота. Попробуйте позже.",
            reply_markup=get_main_menu_keyboard(is_premium=False)
        )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    try:
        help_text = Messages.get_help_message()
        
        await message.answer(
            text=help_text,
            reply_markup=get_help_keyboard(),
            parse_mode="HTML"
        )
        
        await bot_logger.log_update(
            update_type="help_command",
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            command="/help"
        )
        
    except Exception as e:
        logger.error(f"Error in help command: {e}")
        await message.answer("❌ Ошибка при получении справки.")


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    """Обработчик команды /menu - показать главное меню"""
    try:
        user_service = get_user_service()
        
        # Проверяем Premium статус
        is_premium = await user_service.is_premium_user(message.from_user.id)
        
        menu_text = Messages.get_main_menu_message(is_premium=is_premium)
        
        await message.answer(
            text=menu_text,
            reply_markup=get_main_menu_keyboard(is_premium=is_premium),
            parse_mode="HTML"
        )
        
        await state.set_state(MainStates.main_menu)
        
    except Exception as e:
        logger.error(f"Error in menu command: {e}")
        await message.answer("❌ Ошибка при показе меню.")


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    try:
        user_service = get_user_service()
        
        # Проверяем Premium статус
        is_premium = await user_service.is_premium_user(callback.from_user.id)
        
        menu_text = Messages.get_main_menu_message(is_premium=is_premium)
        
        await callback.message.edit_text(
            text=menu_text,
            reply_markup=get_main_menu_keyboard(is_premium=is_premium),
            parse_mode="HTML"
        )
        
        await state.set_state(MainStates.main_menu)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in main menu callback: {e}")
        await callback.answer("❌ Ошибка при показе меню.")


@router.callback_query(F.data == "about")
async def callback_about(callback: CallbackQuery):
    """Информация о боте"""
    try:
        about_text = Messages.get_about_message()
        
        # Создаем клавиатуру с кнопкой "Назад"
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="main_menu")]
            ]
        )
        
        await callback.message.edit_text(
            text=about_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in about callback: {e}")
        await callback.answer("❌ Ошибка при получении информации.")


@router.callback_query(F.data == "stats")
async def callback_stats(callback: CallbackQuery):
    """Статистика пользователя"""
    try:
        user_service = get_user_service()
        
        # Получаем статистику пользователя
        user_stats = await user_service.get_user_stats(callback.from_user.id)
        
        # Проверяем лимиты
        limits_info = await user_service.check_daily_limits(callback.from_user.id)
        
        stats_text = Messages.get_user_stats_message(
            stats=user_stats,
            limits=limits_info
        )
        
        # Создаем клавиатуру
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📊 Детальная статистика", callback_data="detailed_stats"),
                    InlineKeyboardButton(text="👑 Premium", callback_data="premium_info")
                ],
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="main_menu")]
            ]
        )
        
        await callback.message.edit_text(
            text=stats_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in stats callback: {e}")
        await callback.answer("❌ Ошибка при получении статистики.")


@router.callback_query(F.data == "support")
async def callback_support(callback: CallbackQuery):
    """Поддержка пользователей"""
    try:
        support_text = Messages.get_support_message()
        
        # Создаем клавиатуру с контактами
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="💬 Чат поддержки", url="https://t.me/music_bot_support"),
                    InlineKeyboardButton(text="📧 Email", url="mailto:support@musicbot.com")
                ],
                [
                    InlineKeyboardButton(text="🐛 Сообщить об ошибке", callback_data="report_bug"),
                    InlineKeyboardButton(text="💡 Предложить идею", callback_data="suggest_feature")
                ],
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="main_menu")]
            ]
        )
        
        await callback.message.edit_text(
            text=support_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in support callback: {e}")
        await callback.answer("❌ Ошибка при получении информации о поддержке.")


@router.message(F.text.in_(["/start", "🏠 Главное меню", "🔙 В меню"]))
async def text_main_menu(message: Message, state: FSMContext):
    """Обработка текстовых команд для главного меню"""
    await cmd_menu(message, state)


@router.message(F.text == "❓ Помощь")
async def text_help(message: Message):
    """Обработка текстовой команды помощи"""
    await cmd_help(message)


# Обработчик неизвестных команд в главном меню
@router.message(MainStates.main_menu)
async def handle_main_menu_text(message: Message):
    """Обработка текста в главном меню"""
    try:
        # Если это не команда, предлагаем поиск
        if not message.text.startswith('/'):
            search_text = Messages.get_search_suggestion(message.text)
            
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"🔍 Найти: {message.text[:30]}...", 
                        callback_data=f"search:{message.text}"
                    )],
                    [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
                ]
            )
            
            await message.answer(
                text=search_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            # Неизвестная команда
            await message.answer(
                "❓ Неизвестная команда. Используйте /help для получения списка команд.",
                reply_markup=get_main_menu_keyboard(is_premium=False)
            )
            
    except Exception as e:
        logger.error(f"Error handling main menu text: {e}")
        await message.answer("❌ Произошла ошибка.")
=======
# app/bot/handlers/start.py
"""
Обработчик команды /start и основного меню
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import Optional

from app.bot.keyboards.inline import (
    get_main_menu_keyboard,
    get_premium_keyboard,
    get_help_keyboard
)
from app.bot.utils.messages import Messages
from app.services import get_user_service, get_analytics_service
from app.core.logging import get_logger, bot_logger

router = Router()
logger = get_logger(__name__)


class MainStates(StatesGroup):
    """Состояния главного меню"""
    main_menu = State()
    waiting_search = State()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    try:
        user_service = get_user_service()
        analytics_service = get_analytics_service()
        
        # Получаем или создаем пользователя
        user = await user_service.get_or_create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            language_code=message.from_user.language_code
        )
        
        # Проверяем Premium статус
        is_premium = await user_service.is_premium_user(message.from_user.id)
        
        # Получаем статистику пользователя
        user_stats = await user_service.get_user_stats(message.from_user.id)
        
        # Трекаем событие
        await analytics_service.track_user_event(
            user_id=user.id,
            event_type="start_command",
            event_data={
                "source": "telegram",
                "is_new_user": user_stats.tracks_downloaded == 0
            }
        )
        
        # Формируем приветственное сообщение
        welcome_text = Messages.get_welcome_message(
            user_name=user.first_name or "Музыкальный меломан",
            is_premium=is_premium,
            tracks_count=user_stats.tracks_downloaded
        )
        
        # Отправляем главное меню
        await message.answer(
            text=welcome_text,
            reply_markup=get_main_menu_keyboard(is_premium=is_premium),
            parse_mode="HTML"
        )
        
        # Устанавливаем состояние
        await state.set_state(MainStates.main_menu)
        
        await bot_logger.log_update(
            update_type="start_command",
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            command="/start"
        )
        
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await message.answer(
            "❌ Произошла ошибка при запуске бота. Попробуйте позже.",
            reply_markup=get_main_menu_keyboard(is_premium=False)
        )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    try:
        help_text = Messages.get_help_message()
        
        await message.answer(
            text=help_text,
            reply_markup=get_help_keyboard(),
            parse_mode="HTML"
        )
        
        await bot_logger.log_update(
            update_type="help_command",
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            command="/help"
        )
        
    except Exception as e:
        logger.error(f"Error in help command: {e}")
        await message.answer("❌ Ошибка при получении справки.")


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    """Обработчик команды /menu - показать главное меню"""
    try:
        user_service = get_user_service()
        
        # Проверяем Premium статус
        is_premium = await user_service.is_premium_user(message.from_user.id)
        
        menu_text = Messages.get_main_menu_message(is_premium=is_premium)
        
        await message.answer(
            text=menu_text,
            reply_markup=get_main_menu_keyboard(is_premium=is_premium),
            parse_mode="HTML"
        )
        
        await state.set_state(MainStates.main_menu)
        
    except Exception as e:
        logger.error(f"Error in menu command: {e}")
        await message.answer("❌ Ошибка при показе меню.")


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    try:
        user_service = get_user_service()
        
        # Проверяем Premium статус
        is_premium = await user_service.is_premium_user(callback.from_user.id)
        
        menu_text = Messages.get_main_menu_message(is_premium=is_premium)
        
        await callback.message.edit_text(
            text=menu_text,
            reply_markup=get_main_menu_keyboard(is_premium=is_premium),
            parse_mode="HTML"
        )
        
        await state.set_state(MainStates.main_menu)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in main menu callback: {e}")
        await callback.answer("❌ Ошибка при показе меню.")


@router.callback_query(F.data == "about")
async def callback_about(callback: CallbackQuery):
    """Информация о боте"""
    try:
        about_text = Messages.get_about_message()
        
        # Создаем клавиатуру с кнопкой "Назад"
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="main_menu")]
            ]
        )
        
        await callback.message.edit_text(
            text=about_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in about callback: {e}")
        await callback.answer("❌ Ошибка при получении информации.")


@router.callback_query(F.data == "stats")
async def callback_stats(callback: CallbackQuery):
    """Статистика пользователя"""
    try:
        user_service = get_user_service()
        
        # Получаем статистику пользователя
        user_stats = await user_service.get_user_stats(callback.from_user.id)
        
        # Проверяем лимиты
        limits_info = await user_service.check_daily_limits(callback.from_user.id)
        
        stats_text = Messages.get_user_stats_message(
            stats=user_stats,
            limits=limits_info
        )
        
        # Создаем клавиатуру
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📊 Детальная статистика", callback_data="detailed_stats"),
                    InlineKeyboardButton(text="👑 Premium", callback_data="premium_info")
                ],
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="main_menu")]
            ]
        )
        
        await callback.message.edit_text(
            text=stats_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in stats callback: {e}")
        await callback.answer("❌ Ошибка при получении статистики.")


@router.callback_query(F.data == "support")
async def callback_support(callback: CallbackQuery):
    """Поддержка пользователей"""
    try:
        support_text = Messages.get_support_message()
        
        # Создаем клавиатуру с контактами
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="💬 Чат поддержки", url="https://t.me/music_bot_support"),
                    InlineKeyboardButton(text="📧 Email", url="mailto:support@musicbot.com")
                ],
                [
                    InlineKeyboardButton(text="🐛 Сообщить об ошибке", callback_data="report_bug"),
                    InlineKeyboardButton(text="💡 Предложить идею", callback_data="suggest_feature")
                ],
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="main_menu")]
            ]
        )
        
        await callback.message.edit_text(
            text=support_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in support callback: {e}")
        await callback.answer("❌ Ошибка при получении информации о поддержке.")


@router.message(F.text.in_(["/start", "🏠 Главное меню", "🔙 В меню"]))
async def text_main_menu(message: Message, state: FSMContext):
    """Обработка текстовых команд для главного меню"""
    await cmd_menu(message, state)


@router.message(F.text == "❓ Помощь")
async def text_help(message: Message):
    """Обработка текстовой команды помощи"""
    await cmd_help(message)


# Обработчик неизвестных команд в главном меню
@router.message(MainStates.main_menu)
async def handle_main_menu_text(message: Message):
    """Обработка текста в главном меню"""
    try:
        # Если это не команда, предлагаем поиск
        if not message.text.startswith('/'):
            search_text = Messages.get_search_suggestion(message.text)
            
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"🔍 Найти: {message.text[:30]}...", 
                        callback_data=f"search:{message.text}"
                    )],
                    [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
                ]
            )
            
            await message.answer(
                text=search_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            # Неизвестная команда
            await message.answer(
                "❓ Неизвестная команда. Используйте /help для получения списка команд.",
                reply_markup=get_main_menu_keyboard(is_premium=False)
            )
            
    except Exception as e:
        logger.error(f"Error handling main menu text: {e}")
        await message.answer("❌ Произошла ошибка.")
>>>>>>> a6dfd6a (upd commit)
