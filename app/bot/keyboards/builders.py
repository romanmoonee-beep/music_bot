"""
Билдеры клавиатур для динамического создания
"""
from typing import List, Dict, Any, Optional, Callable
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from app.services.music.base import SearchResult
from app.schemas.playlist import PlaylistResponse
from app.models.user import User


class DynamicKeyboardBuilder:
    """Динамический строитель клавиатур"""
    
    @staticmethod
    def build_search_results(
        results: List[SearchResult],
        page: int = 0,
        per_page: int = 5,
        show_source: bool = True,
        show_quality: bool = True,
        custom_actions: Optional[List[Dict[str, str]]] = None
    ) -> InlineKeyboardMarkup:
        """Динамичная клавиатура результатов поиска"""
        builder = InlineKeyboardBuilder()
        
        start_idx = page * per_page
        end_idx = start_idx + per_page
        page_results = results[start_idx:end_idx]
        
        for i, result in enumerate(page_results):
            # Формируем текст кнопки
            button_parts = []
            
            # Качество
            if show_quality:
                quality_icons = {
                    "ultra": "💎",
                    "high": "🔹", 
                    "medium": "🔸",
                    "low": "🔻"
                }
                quality_icon = quality_icons.get(result.audio_quality.value.lower(), "🎵")
                button_parts.append(quality_icon)
            
            # Источник
            if show_source:
                source_icons = {
                    "vk_audio": "🎵",
                    "youtube": "📺", 
                    "spotify": "🎶"
                }
                source_icon = source_icons.get(result.source.value.lower(), "🎧")
                button_parts.append(source_icon)
            
            # Название трека
            title = result.title[:25] + "..." if len(result.title) > 25 else result.title
            artist = result.artist[:20] + "