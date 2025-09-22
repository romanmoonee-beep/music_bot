"""
Инициализация модуля клавиатур
"""

from app.bot.keyboards.inline import (
    get_main_menu_keyboard,
    get_search_results_keyboard,
    get_track_actions_keyboard,
    get_playlists_keyboard,
    get_playlist_actions_keyboard,
    get_premium_keyboard,
    get_premium_offer_keyboard,
    get_renew_subscription_keyboard,
    get_payment_method_keyboard,
    get_crypto_currencies_keyboard,
    get_settings_keyboard,
    get_quality_settings_keyboard,
    get_confirmation_keyboard,
    get_add_to_playlist_keyboard,
    get_trending_categories_keyboard,
    get_genres_keyboard,
    get_inline_search_keyboard,
    get_profile_keyboard,
    get_help_keyboard,
    get_admin_keyboard,
    get_broadcast_keyboard,
    get_back_to_menu_keyboard,
    get_cancel_keyboard,
    add_navigation_buttons,
    create_paginated_keyboard
)

from app.bot.keyboards.reply import (
    get_main_reply_keyboard,
    get_search_keyboard,
    get_playlist_management_keyboard,
    get_premium_keyboard as get_premium_reply_keyboard,
    get_settings_keyboard as get_settings_reply_keyboard,
    get_admin_keyboard as get_admin_reply_keyboard,
    get_cancel_keyboard as get_cancel_reply_keyboard,
    get_yes_no_keyboard,
    get_contact_keyboard,
    get_location_keyboard,
    get_language_keyboard,
    get_quality_keyboard as get_quality_reply_keyboard,
    remove_keyboard,
    create_quick_keyboard,
    create_menu_keyboard
)

from app.bot.keyboards.builders import (
    DynamicKeyboardBuilder,
    ConditionalKeyboardBuilder,
    PaginatedKeyboardBuilder,
    truncate_text,
    format_number,
    get_quality_icon,
    get_source_icon
)

__all__ = [
    # Inline keyboards
    "get_main_menu_keyboard",
    "get_search_results_keyboard", 
    "get_track_actions_keyboard",
    "get_playlists_keyboard",
    "get_playlist_actions_keyboard",
    "get_premium_keyboard",
    "get_premium_offer_keyboard",
    "get_renew_subscription_keyboard",
    "get_payment_method_keyboard",
    "get_crypto_currencies_keyboard",
    "get_settings_keyboard",
    "get_quality_settings_keyboard",
    "get_confirmation_keyboard",
    "get_add_to_playlist_keyboard",
    "get_trending_categories_keyboard",
    "get_genres_keyboard",
    "get_inline_search_keyboard",
    "get_profile_keyboard",
    "get_help_keyboard",
    "get_admin_keyboard",
    "get_broadcast_keyboard",
    "get_back_to_menu_keyboard",
    "get_cancel_keyboard",
    "add_navigation_buttons",
    "create_paginated_keyboard",
    
    # Reply keyboards
    "get_main_reply_keyboard",
    "get_search_keyboard",
    "get_playlist_management_keyboard",
    "get_premium_reply_keyboard",
    "get_settings_reply_keyboard", 
    "get_admin_reply_keyboard",
    "get_cancel_reply_keyboard",
    "get_yes_no_keyboard",
    "get_contact_keyboard",
    "get_location_keyboard",
    "get_language_keyboard",
    "get_quality_reply_keyboard",
    "remove_keyboard",
    "create_quick_keyboard",
    "create_menu_keyboard",
    
    # Builders
    "DynamicKeyboardBuilder",
    "ConditionalKeyboardBuilder", 
    "PaginatedKeyboardBuilder",
    "truncate_text",
    "format_number",
    "get_quality_icon",
    "get_source_icon"
]