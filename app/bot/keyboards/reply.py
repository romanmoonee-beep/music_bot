"""
Reply клавиатуры для музыкального бота
"""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def get_main_reply_keyboard(is_premium: bool = False) -> ReplyKeyboardMarkup:
    """Основная reply клавиатура"""
    builder = ReplyKeyboardBuilder()
    
    # Первый ряд - основные функции
    builder.row(
        KeyboardButton(text="🔍 Поиск"),
        KeyboardButton(text="🔥 Популярное")
    )
    
    # Второй ряд - плейлисты и избранное
    builder.row(
        KeyboardButton(text="📋 Плейлисты"),
        KeyboardButton(text="❤️ Избранное")
    )
    
    # Третий ряд - профиль и настройки
    builder.row(
        KeyboardButton(text="👤 Профиль"),
        KeyboardButton(text="⚙️ Настройки")
    )
    
    # Четвертый ряд - Premium или помощь
    if is_premium:
        builder.row(
            KeyboardButton(text="💎 Premium"),
            KeyboardButton(text="🆘 Помощь")
        )
    else:
        builder.row(
            KeyboardButton(text="💎 Получить Premium"),
            KeyboardButton(text="🆘 Помощь")
        )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def get_search_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для поиска"""
    builder = ReplyKeyboardBuilder()
    
    # Быстрые поисковые запросы
    builder.row(
        KeyboardButton(text="🎤 Популярные исполнители"),
        KeyboardButton(text="🎵 Новинки 2024")
    )
    
    builder.row(
        KeyboardButton(text="🎸 Рок"),
        KeyboardButton(text="🎹 Поп")
    )
    
    builder.row(
        KeyboardButton(text="🎧 Электронная"),
        KeyboardButton(text="🎺 Джаз")
    )
    
    # Специальные функции
    builder.row(
        KeyboardButton(text="🎯 Рекомендации"),
        KeyboardButton(text="🔀 Случайная")
    )
    
    # Возврат в главное меню
    builder.row(
        KeyboardButton(text="🏠 Главное меню")
    )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def get_playlist_management_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура управления плейлистами"""
    builder = ReplyKeyboardBuilder()
    
    # Основные действия
    builder.row(
        KeyboardButton(text="📋 Мои плейлисты"),
        KeyboardButton(text="➕ Создать плейлист")
    )
    
    builder.row(
        KeyboardButton(text="🔍 Найти плейлист"),
        KeyboardButton(text="📊 Статистика")
    )
    
    # Публичные плейлисты
    builder.row(
        KeyboardButton(text="🌟 Популярные плейлисты"),
        KeyboardButton(text="🎭 По жанрам")
    )
    
    # Импорт/экспорт
    builder.row(
        KeyboardButton(text="📥 Импорт"),
        KeyboardButton(text="📤 Экспорт")
    )
    
    # Назад
    builder.row(
        KeyboardButton(text="🏠 Главное меню")
    )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def get_premium_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура Premium функций"""
    builder = ReplyKeyboardBuilder()
    
    # Premium функции
    builder.row(
        KeyboardButton(text="💎 Мой Premium"),
        KeyboardButton(text="📊 Расширенная статистика")
    )
    
    builder.row(
        KeyboardButton(text="🎵 Высокое качество"),
        KeyboardButton(text="📥 Массовое скачивание")
    )
    
    builder.row(
        KeyboardButton(text="🎯 Умные рекомендации"),
        KeyboardButton(text="🚫 Без рекламы")
    )
    
    # Управление подпиской
    builder.row(
        KeyboardButton(text="🔄 Продлить подписку"),
        KeyboardButton(text="📋 История платежей")
    )
    
    # Назад
    builder.row(
        KeyboardButton(text="🏠 Главное меню")
    )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def get_settings_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура настроек"""
    builder = ReplyKeyboardBuilder()
    
    # Основные настройки
    builder.row(
        KeyboardButton(text="🎵 Качество аудио"),
        KeyboardButton(text="🔔 Уведомления")
    )
    
    builder.row(
        KeyboardButton(text="🌐 Язык интерфейса"),
        KeyboardButton(text="🎯 Рекомендации")
    )
    
    # Приватность и данные
    builder.row(
        KeyboardButton(text="🔒 Приватность"),
        KeyboardButton(text="📊 Мои данные")
    )
    
    # Дополнительные настройки
    builder.row(
        KeyboardButton(text="🎨 Тема оформления"),
        KeyboardButton(text="⚡ Быстрые действия")
    )
    
    # Экспорт и удаление
    builder.row(
        KeyboardButton(text="📦 Экспорт данных"),
        KeyboardButton(text="🗑️ Удалить аккаунт")
    )
    
    # Назад
    builder.row(
        KeyboardButton(text="🏠 Главное меню")
    )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """Административная клавиатура"""
    builder = ReplyKeyboardBuilder()
    
    # Управление пользователями
    builder.row(
        KeyboardButton(text="👥 Пользователи"),
        KeyboardButton(text="📊 Аналитика")
    )
    
    # Контент и модерация
    builder.row(
        KeyboardButton(text="🎵 Модерация контента"),
        KeyboardButton(text="📋 Плейлисты")
    )
    
    # Финансы и платежи
    builder.row(
        KeyboardButton(text="💰 Платежи"),
        KeyboardButton(text="💎 Подписки")
    )
    
    # Рассылки и уведомления
    builder.row(
        KeyboardButton(text="📢 Рассылка"),
        KeyboardButton(text="🔔 Уведомления")
    )
    
    # Система и настройки
    builder.row(
        KeyboardButton(text="⚙️ Настройки системы"),
        KeyboardButton(text="🔧 Техническое")
    )
    
    # Логи и мониторинг
    builder.row(
        KeyboardButton(text="📝 Логи"),
        KeyboardButton(text="📈 Мониторинг")
    )
    
    # Выход из админки
    builder.row(
        KeyboardButton(text="🚪 Обычный режим")
    )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура отмены"""
    builder = ReplyKeyboardBuilder()
    
    builder.row(
        KeyboardButton(text="❌ Отмена")
    )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def get_yes_no_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура подтверждения (Да/Нет)"""
    builder = ReplyKeyboardBuilder()
    
    builder.row(
        KeyboardButton(text="✅ Да"),
        KeyboardButton(text="❌ Нет")
    )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def get_contact_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для отправки контакта"""
    builder = ReplyKeyboardBuilder()
    
    builder.row(
        KeyboardButton(text="📱 Поделиться контактом", request_contact=True)
    )
    
    builder.row(
        KeyboardButton(text="❌ Отмена")
    )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def get_location_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для отправки местоположения"""
    builder = ReplyKeyboardBuilder()
    
    builder.row(
        KeyboardButton(text="📍 Поделиться местоположением", request_location=True)
    )
    
    builder.row(
        KeyboardButton(text="❌ Отмена")
    )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def get_language_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура выбора языка"""
    builder = ReplyKeyboardBuilder()
    
    # Популярные языки
    builder.row(
        KeyboardButton(text="🇷🇺 Русский"),
        KeyboardButton(text="🇺🇸 English")
    )
    
    builder.row(
        KeyboardButton(text="🇺🇦 Українська"),
        KeyboardButton(text="🇰🇿 Қазақша")
    )
    
    builder.row(
        KeyboardButton(text="🇪🇸 Español"),
        KeyboardButton(text="🇫🇷 Français")
    )
    
    builder.row(
        KeyboardButton(text="🇩🇪 Deutsch"),
        KeyboardButton(text="🇮🇹 Italiano")
    )
    
    # Назад
    builder.row(
        KeyboardButton(text="⬅️ Назад")
    )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def get_quality_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура выбора качества аудио"""
    builder = ReplyKeyboardBuilder()
    
    # Качества аудио
    builder.row(
        KeyboardButton(text="🔻 128 kbps"),
        KeyboardButton(text="🔸 192 kbps")
    )
    
    builder.row(
        KeyboardButton(text="🔹 256 kbps"),
        KeyboardButton(text="💎 320 kbps")
    )
    
    # Автоматическое качество
    builder.row(
        KeyboardButton(text="🤖 Автоматически")
    )
    
    # Назад
    builder.row(
        KeyboardButton(text="⬅️ Назад")
    )
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def remove_keyboard() -> ReplyKeyboardMarkup:
    """Убрать клавиатуру"""
    from aiogram.types import ReplyKeyboardRemove
    return ReplyKeyboardRemove()


# Утилитарные функции

def create_quick_keyboard(buttons: list, row_width: int = 2) -> ReplyKeyboardMarkup:
    """Создать быструю клавиатуру из списка кнопок"""
    builder = ReplyKeyboardBuilder()
    
    # Добавляем кнопки
    for i in range(0, len(buttons), row_width):
        row_buttons = []
        for j in range(i, min(i + row_width, len(buttons))):
            row_buttons.append(KeyboardButton(text=buttons[j]))
        builder.row(*row_buttons)
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def create_menu_keyboard(menu_items: dict) -> ReplyKeyboardMarkup:
    """Создать клавиатуру меню из словаря"""
    builder = ReplyKeyboardBuilder()
    
    for text, callback in menu_items.items():
        builder.row(KeyboardButton(text=text))
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)