"""
Inline клавиатуры для музыкального бота
"""
from typing import List, Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.music.base import SearchResult
from app.schemas.playlist import PlaylistResponse


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню бота"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🔍 Поиск музыки", callback_data="search_music"),
        InlineKeyboardButton(text="🔥 Популярное", callback_data="trending")
    )
    builder.row(
        InlineKeyboardButton(text="📋 Мои плейлисты", callback_data="my_playlists"),
        InlineKeyboardButton(text="❤️ Избранное", callback_data="favorites")
    )
    builder.row(
        InlineKeyboardButton(text="🎯 Рекомендации", callback_data="recommendations"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="stats")
    )
    builder.row(
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")
    )
    builder.row(
        InlineKeyboardButton(text="💎 Premium", callback_data="premium")
    )
    
    return builder.as_markup()


def get_search_results_keyboard(
    results: List[SearchResult], 
    page: int = 0, 
    per_page: int = 5
) -> InlineKeyboardMarkup:
    """Клавиатура с результатами поиска"""
    builder = InlineKeyboardBuilder()
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_results = results[start_idx:end_idx]
    
    for i, result in enumerate(page_results):
        # Ограничиваем длину названия
        title = result.title[:30] + "..." if len(result.title) > 30 else result.title
        artist = result.artist[:20] + "..." if len(result.artist) > 20 else result.artist
        
        # Иконка качества
        quality_icon = {
            "ultra": "💎",
            "high": "🔹", 
            "medium": "🔸",
            "low": "🔻"
        }.get(result.audio_quality.value.lower(), "🎵")
        
        # Иконка источника
        source_icon = {
            "vk_audio": "🎵",
            "youtube": "📺",
            "spotify": "🎶"
        }.get(result.source.value.lower(), "🎧")
        
        button_text = f"{quality_icon} {artist} - {title}"
        callback_data = f"track:{result.external_id}:{result.source.value}"
        
        builder.row(
            InlineKeyboardButton(text=button_text, callback_data=callback_data)
        )
    
    # Навигация
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"search_page:{page-1}")
        )
    
    # Показываем текущую страницу
    total_pages = (len(results) - 1) // per_page + 1
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"📄 {page + 1}/{total_pages}", 
            callback_data="current_page"
        )
    )
    
    if end_idx < len(results):
        nav_buttons.append(
            InlineKeyboardButton(text="Далее ➡️", callback_data=f"search_page:{page+1}")
        )
    
    if nav_buttons:
        builder.row(*nav_buttons)
    
    # Дополнительные опции
    builder.row(
        InlineKeyboardButton(text="🔍 Новый поиск", callback_data="new_search"),
        InlineKeyboardButton(text="🏠 Главная", callback_data="main_menu")
    )
    
    return builder.as_markup()


def get_track_actions_keyboard(
    track_id: str, 
    source: str,
    is_premium: bool = False,
    in_favorites: bool = False
) -> InlineKeyboardMarkup:
    """Клавиатура с действиями для трека"""
    builder = InlineKeyboardBuilder()
    
    # Основные действия
    builder.row(
        InlineKeyboardButton(
            text="⬇️ Скачать", 
            callback_data=f"download:{track_id}:{source}"
        ),
        InlineKeyboardButton(
            text="💖" if not in_favorites else "💔",
            callback_data=f"toggle_favorite:{track_id}:{source}"
        )
    )
    
    # Добавить в плейлист
    builder.row(
        InlineKeyboardButton(
            text="➕ В плейлист", 
            callback_data=f"add_to_playlist:{track_id}:{source}"
        ),
        InlineKeyboardButton(
            text="📤 Поделиться", 
            callback_data=f"share:{track_id}:{source}"
        )
    )
    
    # Похожие треки
    builder.row(
        InlineKeyboardButton(
            text="🎵 Похожие", 
            callback_data=f"similar:{track_id}:{source}"
        ),
        InlineKeyboardButton(
            text="👤 Исполнитель", 
            callback_data=f"artist:{track_id}:{source}"
        )
    )
    
    # Premium опции
    if is_premium:
        builder.row(
            InlineKeyboardButton(
                text="💎 320kbps", 
                callback_data=f"download_320kbps:{track_id}:{source}"
            )
        )
    
    # Навигация
    builder.row(
        InlineKeyboardButton(text="⬅️ К результатам", callback_data="back_to_results"),
        InlineKeyboardButton(text="🏠 Главная", callback_data="main_menu")
    )
    
    return builder.as_markup()


def get_playlists_keyboard(
    playlists: List[PlaylistResponse], 
    page: int = 0, 
    per_page: int = 8
) -> InlineKeyboardMarkup:
    """Клавиатура со списком плейлистов"""
    builder = InlineKeyboardBuilder()
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_playlists = playlists[start_idx:end_idx]
    
    # Плейлисты по два в ряд
    for i in range(0, len(page_playlists), 2):
        row_buttons = []
        
        # Первый плейлист в ряду
        playlist = page_playlists[i]
        title = playlist.title[:25] + "..." if len(playlist.title) > 25 else playlist.title
        button_text = f"📋 {title} ({playlist.tracks_count})"
        
        row_buttons.append(
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"playlist:{playlist.id}"
            )
        )
        
        # Второй плейлист в ряду (если есть)
        if i + 1 < len(page_playlists):
            playlist2 = page_playlists[i + 1]
            title2 = playlist2.title[:25] + "..." if len(playlist2.title) > 25 else playlist2.title
            button_text2 = f"📋 {title2} ({playlist2.tracks_count})"
            
            row_buttons.append(
                InlineKeyboardButton(
                    text=button_text2,
                    callback_data=f"playlist:{playlist2.id}"
                )
            )
        
        builder.row(*row_buttons)
    
    # Навигация для плейлистов
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"playlists_page:{page-1}")
        )
    
    total_pages = (len(playlists) - 1) // per_page + 1 if playlists else 1
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}", 
            callback_data="current_playlists_page"
        )
    )
    
    if end_idx < len(playlists):
        nav_buttons.append(
            InlineKeyboardButton(text="➡️", callback_data=f"playlists_page:{page+1}")
        )
    
    if nav_buttons:
        builder.row(*nav_buttons)
    
    # Дополнительные действия
    builder.row(
        InlineKeyboardButton(text="➕ Новый плейлист", callback_data="create_playlist"),
        InlineKeyboardButton(text="🔍 Поиск плейлистов", callback_data="search_playlists")
    )
    
    builder.row(
        InlineKeyboardButton(text="🏠 Главная", callback_data="main_menu")
    )
    
    return builder.as_markup()


def get_playlist_actions_keyboard(
    playlist_id: str,
    is_owner: bool = False,
    is_empty: bool = False
) -> InlineKeyboardMarkup:
    """Клавиатура с действиями для плейлиста"""
    builder = InlineKeyboardBuilder()
    
    if not is_empty:
        # Основные действия с плейлистом
        builder.row(
            InlineKeyboardButton(
                text="▶️ Играть все", 
                callback_data=f"play_playlist:{playlist_id}"
            ),
            InlineKeyboardButton(
                text="🔀 Перемешать", 
                callback_data=f"shuffle_playlist:{playlist_id}"
            )
        )
        
        builder.row(
            InlineKeyboardButton(
                text="📋 Треки", 
                callback_data=f"playlist_tracks:{playlist_id}"
            ),
            InlineKeyboardButton(
                text="📊 Статистика", 
                callback_data=f"playlist_stats:{playlist_id}"
            )
        )
    
    # Действия владельца
    if is_owner:
        builder.row(
            InlineKeyboardButton(
                text="✏️ Редактировать", 
                callback_data=f"edit_playlist:{playlist_id}"
            ),
            InlineKeyboardButton(
                text="👥 Доступ", 
                callback_data=f"playlist_sharing:{playlist_id}"
            )
        )
        
        if not is_empty:
            builder.row(
                InlineKeyboardButton(
                    text="📤 Экспорт", 
                    callback_data=f"export_playlist:{playlist_id}"
                ),
                InlineKeyboardButton(
                    text="🗑️ Удалить", 
                    callback_data=f"delete_playlist:{playlist_id}"
                )
            )
    else:
        # Действия для чужих плейлистов
        builder.row(
            InlineKeyboardButton(
                text="📋 Копировать", 
                callback_data=f"copy_playlist:{playlist_id}"
            ),
            InlineKeyboardButton(
                text="📤 Поделиться", 
                callback_data=f"share_playlist:{playlist_id}"
            )
        )
    
    # Навигация
    builder.row(
        InlineKeyboardButton(text="⬅️ К плейлистам", callback_data="my_playlists"),
        InlineKeyboardButton(text="🏠 Главная", callback_data="main_menu")
    )
    
    return builder.as_markup()


def get_premium_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для Premium подписки"""
    builder = InlineKeyboardBuilder()
    
    # Планы подписки
    builder.row(
        InlineKeyboardButton(
            text="⭐ 1 месяц - 150 Stars", 
            callback_data="premium_plan:1month"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⭐ 3 месяца - 400 Stars (-12%)", 
            callback_data="premium_plan:3months"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⭐ 1 год - 1400 Stars (-23%)", 
            callback_data="premium_plan:1year"
        )
    )
    
    # Альтернативные способы оплаты
    builder.row(
        InlineKeyboardButton(
            text="💎 Оплата криптой", 
            callback_data="crypto_payment"
        )
    )
    
    # Информация
    builder.row(
        InlineKeyboardButton(
            text="ℹ️ Что даёт Premium", 
            callback_data="premium_benefits"
        ),
        InlineKeyboardButton(
            text="🎁 Промокод", 
            callback_data="promo_code"
        )
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")
    )
    
    return builder.as_markup()


def get_premium_offer_keyboard() -> InlineKeyboardMarkup:
    """Компактная клавиатура с предложением Premium"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(
            text="💎 Получить Premium", 
            callback_data="premium"
        )
    )
    
    return builder.as_markup()


def get_renew_subscription_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для продления подписки"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(
            text="🔄 Продлить подписку", 
            callback_data="premium"
        )
    )
    
    return builder.as_markup()


def get_payment_method_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора способа оплаты"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(
            text="⭐ Telegram Stars", 
            callback_data="payment_method:stars"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="💎 CryptoBot (TON, BTC, USDT)", 
            callback_data="payment_method:crypto"
        )
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="premium")
    )
    
    return builder.as_markup()


def get_crypto_currencies_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора криптовалюты"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="💎 TON", callback_data="crypto_currency:TON"),
        InlineKeyboardButton(text="₿ BTC", callback_data="crypto_currency:BTC")
    )
    builder.row(
        InlineKeyboardButton(text="💵 USDT", callback_data="crypto_currency:USDT"),
        InlineKeyboardButton(text="⚡ USDC", callback_data="crypto_currency:USDC")
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="premium")
    )
    
    return builder.as_markup()


def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настроек"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(
            text="🎵 Качество аудио", 
            callback_data="settings:quality"
        ),
        InlineKeyboardButton(
            text="🔔 Уведомления", 
            callback_data="settings:notifications"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🌐 Язык", 
            callback_data="settings:language"
        ),
        InlineKeyboardButton(
            text="🎯 Рекомендации", 
            callback_data="settings:recommendations"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🗄️ Экспорт данных", 
            callback_data="settings:export_data"
        ),
        InlineKeyboardButton(
            text="🗑️ Удалить аккаунт", 
            callback_data="settings:delete_account"
        )
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")
    )
    
    return builder.as_markup()


def get_quality_settings_keyboard(current_quality: str = "192kbps") -> InlineKeyboardMarkup:
    """Клавиатура настройки качества аудио"""
    builder = InlineKeyboardBuilder()
    
    qualities = [
        ("🔻 128kbps", "128kbps"),
        ("🔸 192kbps", "192kbps"), 
        ("🔹 256kbps", "256kbps"),
        ("💎 320kbps", "320kbps")
    ]
    
    for text, quality in qualities:
        if quality == current_quality:
            text = f"✅ {text}"
        
        builder.row(
            InlineKeyboardButton(
                text=text,
                callback_data=f"set_quality:{quality}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="settings")
    )
    
    return builder.as_markup()


def get_confirmation_keyboard(action: str, item_id: str = "") -> InlineKeyboardMarkup:
    """Клавиатура подтверждения действия"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(
            text="✅ Да",
            callback_data=f"confirm:{action}:{item_id}"
        ),
        InlineKeyboardButton(
            text="❌ Нет",
            callback_data=f"cancel:{action}"
        )
    )
    
    return builder.as_markup()


def get_add_to_playlist_keyboard(
    playlists: List[PlaylistResponse], 
    track_id: str, 
    source: str
) -> InlineKeyboardMarkup:
    """Клавиатура добавления трека в плейлист"""
    builder = InlineKeyboardBuilder()
    
    # Существующие плейлисты
    for playlist in playlists[:8]:  # Показываем максимум 8 плейлистов
        title = playlist.title[:30] + "..." if len(playlist.title) > 30 else playlist.title
        builder.row(
            InlineKeyboardButton(
                text=f"📋 {title}",
                callback_data=f"add_track_to_playlist:{playlist.id}:{track_id}:{source}"
            )
        )
    
    # Создать новый плейлист
    builder.row(
        InlineKeyboardButton(
            text="➕ Создать новый плейлист",
            callback_data=f"create_playlist_with_track:{track_id}:{source}"
        )
    )
    
    # Назад
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"track:{track_id}:{source}"
        )
    )
    
    return builder.as_markup()


def get_trending_categories_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура категорий популярной музыки"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🔥 Топ недели", callback_data="trending:week"),
        InlineKeyboardButton(text="📈 Восходящие", callback_data="trending:rising")
    )
    builder.row(
        InlineKeyboardButton(text="🆕 Новинки", callback_data="trending:new"),
        InlineKeyboardButton(text="👑 Классика", callback_data="trending:classic")
    )
    builder.row(
        InlineKeyboardButton(text="🎭 По жанрам", callback_data="genres"),
        InlineKeyboardButton(text="🌍 По странам", callback_data="countries")
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")
    )
    
    return builder.as_markup()


def get_genres_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора жанров"""
    builder = InlineKeyboardBuilder()
    
    genres = [
        ("🎸 Rock", "rock"),
        ("🎤 Pop", "pop"),
        ("🎵 Hip-Hop", "hip-hop"),
        ("🎹 Electronic", "electronic"),
        ("🎺 Jazz", "jazz"),
        ("🎻 Classical", "classical"),
        ("🪕 Folk", "folk"),
        ("🎷 Blues", "blues")
    ]
    
    # По два жанра в ряд
    for i in range(0, len(genres), 2):
        row_buttons = [
            InlineKeyboardButton(
                text=genres[i][0],
                callback_data=f"genre:{genres[i][1]}"
            )
        ]
        
        if i + 1 < len(genres):
            row_buttons.append(
                InlineKeyboardButton(
                    text=genres[i + 1][0],
                    callback_data=f"genre:{genres[i + 1][1]}"
                )
            )
        
        builder.row(*row_buttons)
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="trending")
    )
    
    return builder.as_markup()


def get_inline_search_keyboard(track: SearchResult) -> InlineKeyboardMarkup:
    """Клавиатура для inline режима"""
    builder = InlineKeyboardBuilder()
    
    # Кнопка для отправки трека в чат
    builder.row(
        InlineKeyboardButton(
            text="🎧 Отправить в чат",
            callback_data=f"send_to_chat:{track.external_id}:{track.source.value}"
        )
    )
    
    return builder.as_markup()


def get_profile_keyboard(is_premium: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура профиля пользователя"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats"),
        InlineKeyboardButton(text="🎵 История", callback_data="my_history")
    )
    
    builder.row(
        InlineKeyboardButton(text="❤️ Избранное", callback_data="favorites"),
        InlineKeyboardButton(text="📋 Плейлисты", callback_data="my_playlists")
    )
    
    if is_premium:
        builder.row(
            InlineKeyboardButton(text="💎 Premium статус", callback_data="premium_status"),
            InlineKeyboardButton(text="📱 Экспорт", callback_data="export_data")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="💎 Получить Premium", callback_data="premium")
        )
    
    builder.row(
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
        InlineKeyboardButton(text="🆘 Помощь", callback_data="help")
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")
    )
    
    return builder.as_markup()


def get_help_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура помощи"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="❓ FAQ", callback_data="faq"),
        InlineKeyboardButton(text="📘 Гид", callback_data="guide")
    )
    
    builder.row(
        InlineKeyboardButton(text="💬 Поддержка", url="https://t.me/support"),
        InlineKeyboardButton(text="📢 Канал", url="https://t.me/musicbot_news")
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")
    )
    
    return builder.as_markup()


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура админ панели"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users"),
        InlineKeyboardButton(text="📊 Аналитика", callback_data="admin:analytics")
    )
    
    builder.row(
        InlineKeyboardButton(text="💰 Платежи", callback_data="admin:payments"),
        InlineKeyboardButton(text="🎵 Контент", callback_data="admin:content")
    )
    
    builder.row(
        InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast"),
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin:settings")
    )
    
    builder.row(
        InlineKeyboardButton(text="🌐 Веб-панель", url="https://admin.musicbot.com")
    )
    
    return builder.as_markup()


def get_broadcast_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для рассылки"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="👥 Всем пользователям", callback_data="broadcast:all"),
        InlineKeyboardButton(text="💎 Premium", callback_data="broadcast:premium")
    )
    
    builder.row(
        InlineKeyboardButton(text="🆓 Free пользователи", callback_data="broadcast:free"),
        InlineKeyboardButton(text="😴 Неактивные", callback_data="broadcast:inactive")
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main")
    )
    
    return builder.as_markup()


def get_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """Простая клавиатура возврата в главное меню"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")
    )
    
    return builder.as_markup()


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура отмены действия"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
    )
    
    return builder.as_markup()


# Утилитарные функции для работы с клавиатурами

def add_navigation_buttons(
    builder: InlineKeyboardBuilder,
    page: int,
    total_pages: int,
    callback_prefix: str,
    back_callback: str = "main_menu"
) -> None:
    """Добавить кнопки навигации"""
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"{callback_prefix}:{page-1}"
            )
        )
    
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data="current_page"
        )
    )
    
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"{callback_prefix}:{page+1}"
            )
        )
    
    if nav_buttons:
        builder.row(*nav_buttons)
    
    # Кнопка назад
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)
    )


def create_paginated_keyboard(
    items: List[tuple],  # (text, callback_data)
    page: int = 0,
    per_page: int = 8,
    callback_prefix: str = "page",
    back_callback: str = "main_menu"
) -> InlineKeyboardMarkup:
    """Создать пагинированную клавиатуру"""
    builder = InlineKeyboardBuilder()
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_items = items[start_idx:end_idx]
    
    # Добавляем элементы страницы
    for text, callback_data in page_items:
        builder.row(
            InlineKeyboardButton(text=text, callback_data=callback_data)
        )
    
    # Добавляем навигацию
    total_pages = (len(items) - 1) // per_page + 1 if items else 1
    add_navigation_buttons(builder, page, total_pages, callback_prefix, back_callback)
    
    return builder.as_markup()