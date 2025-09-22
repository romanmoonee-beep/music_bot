# app/bot/handlers/admin.py
"""
Обработчик административных команд
"""
import asyncio
from typing import List, Dict, Any
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.core.logging import get_logger, bot_logger
from app.services.user_service import user_service
from app.services.analytics_service import analytics_service
from app.services.broadcast_service import broadcast_service
from app.services.subscription_service import subscription_service
from app.services.search_service import search_service
from app.bot.keyboards.inline import (
    get_admin_keyboard, get_broadcast_keyboard, 
    get_confirmation_keyboard, get_back_to_menu_keyboard
)
from app.bot.filters.admin import AdminFilter
from app.core.config import settings
from app.models.user import UserStatus, SubscriptionType

router = Router()
logger = get_logger(__name__)

# Применяем фильтр админа ко всем хэндлерам
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


class AdminStates(StatesGroup):
    """Состояния админ панели"""
    main_menu = State()
    user_management = State()
    broadcast_compose = State()
    broadcast_confirm = State()
    user_search = State()
    system_settings = State()


@router.message(Command("admin"))
@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(event, user, **kwargs):
    """Главная панель администратора"""
    try:
        # Получаем основную статистику
        stats = await get_admin_dashboard_stats()
        
        admin_text = (
            "👨‍💼 **Административная панель**\n\n"
            
            f"📊 **Статистика на {datetime.now().strftime('%d.%m.%Y %H:%M')}:**\n"
            f"👥 Всего пользователей: {stats['total_users']:,}\n"
            f"🟢 Активных за 24ч: {stats['active_24h']:,}\n"
            f"👑 Premium подписчиков: {stats['premium_users']:,}\n"
            f"🔍 Поисков сегодня: {stats['searches_today']:,}\n"
            f"📥 Скачиваний сегодня: {stats['downloads_today']:,}\n"
            f"💰 Доходы за месяц: {stats['revenue_month']:,}₽\n\n"
            
            f"⚡ **Система:**\n"
            f"📈 Нагрузка: {stats['system_load']:.1f}%\n"
            f"💾 Память: {stats['memory_usage']:.1f}%\n"
            f"🗄️ База данных: {stats['db_status']}\n"
            f"🔄 Очередь задач: {stats['queue_size']} задач\n\n"
            
            "Выберите раздел для управления:"
        )
        
        keyboard = get_admin_keyboard()
        
        if isinstance(event, Message):
            await event.answer(
                admin_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await event.message.edit_text(
                admin_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await event.answer()
        
        await bot_logger.log_update(
            update_type="admin_panel_access",
            user_id=user.telegram_id,
            admin_action="dashboard_view"
        )
        
    except Exception as e:
        logger.error(f"Error showing user details: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("admin:ban_user:"))
async def ban_user(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Блокировка пользователя"""
    try:
        user_id = callback.data.split(":")[2]
        
        ban_text = (
            "🚫 **Блокировка пользователя**\n\n"
            "Укажите причину блокировки и отправьте следующим сообщением:\n\n"
            "💡 Примеры причин:\n"
            "• Нарушение правил использования\n"
            "• Спам или злоупотребление\n"
            "• Мошенничество\n"
            "• Технические нарушения"
        )
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin:user_detail:{user_id}")
        )
        
        await callback.message.edit_text(
            ban_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await state.update_data(ban_user_id=user_id)
        await state.set_state(AdminStates.user_management)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error initiating user ban: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(AdminStates.user_management, F.text)
async def process_ban_reason(message: Message, admin_user, state: FSMContext, **kwargs):
    """Обработка причины блокировки"""
    try:
        data = await state.get_data()
        user_id = data.get("ban_user_id")
        ban_reason = message.text.strip()
        
        if not user_id:
            await message.answer("❌ Ошибка: пользователь для блокировки не найден")
            return
        
        # Выполняем блокировку
        success = await user_service.ban_user(
            user_id=int(user_id),
            reason=ban_reason,
            banned_by=admin_user.id
        )
        
        if success:
            await message.answer(
                f"✅ **Пользователь заблокирован**\n\n"
                f"🆔 ID: {user_id}\n"
                f"📝 Причина: {ban_reason}\n"
                f"👨‍💼 Заблокировал: {admin_user.first_name or admin_user.username}\n"
                f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                parse_mode="Markdown"
            )
            
            # Логируем блокировку
            await bot_logger.log_update(
                update_type="user_banned",
                user_id=admin_user.telegram_id,
                admin_action="ban_user",
                target_user_id=user_id,
                reason=ban_reason
            )
            
        else:
            await message.answer("❌ Ошибка при блокировке пользователя")
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error processing ban reason: {e}")
        await message.answer("❌ Ошибка при блокировке")


@router.callback_query(F.data.startswith("admin:unban_user:"))
async def unban_user(callback: CallbackQuery, admin_user, **kwargs):
    """Разблокировка пользователя"""
    try:
        user_id = callback.data.split(":")[2]
        
        success = await user_service.unban_user(
            user_id=int(user_id),
            unbanned_by=admin_user.id
        )
        
        if success:
            await callback.answer("✅ Пользователь разблокирован", show_alert=True)
            
            # Обновляем информацию о пользователе
            await show_user_details(callback)
            
            # Логируем разблокировку
            await bot_logger.log_update(
                update_type="user_unbanned",
                user_id=admin_user.telegram_id,
                admin_action="unban_user",
                target_user_id=user_id
            )
            
        else:
            await callback.answer("❌ Ошибка при разблокировке", show_alert=True)
        
    except Exception as e:
        logger.error(f"Error unbanning user: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("admin:grant_premium:"))
async def grant_premium(callback: CallbackQuery, **kwargs):
    """Выдача Premium подписки"""
    try:
        user_id = callback.data.split(":")[2]
        
        premium_text = (
            "👑 **Выдача Premium подписки**\n\n"
            "Выберите длительность подписки:"
        )
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        durations = [
            ("7 дней", "7"),
            ("1 месяц", "30"),
            ("3 месяца", "90"),
            ("1 год", "365"),
            ("Пожизненно", "lifetime")
        ]
        
        for duration_name, duration_days in durations:
            builder.row(
                InlineKeyboardButton(
                    text=f"⏰ {duration_name}",
                    callback_data=f"admin:premium_duration:{user_id}:{duration_days}"
                )
            )
        
        builder.row(
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin:user_detail:{user_id}")
        )
        
        await callback.message.edit_text(
            premium_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error granting premium: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("admin:premium_duration:"))
async def confirm_premium_grant(callback: CallbackQuery, admin_user, **kwargs):
    """Подтверждение выдачи Premium"""
    try:
        parts = callback.data.split(":")
        user_id = parts[2]
        duration = parts[3]
        
        # Выдаем Premium подписку
        if duration == "lifetime":
            subscription_type = SubscriptionType.LIFETIME
            duration_days = None
        else:
            subscription_type = SubscriptionType.PREMIUM_MONTHLY
            duration_days = int(duration)
        
        success = await subscription_service.grant_premium(
            user_id=int(user_id),
            subscription_type=subscription_type,
            duration_days=duration_days,
            granted_by=admin_user.id,
            reason="Admin grant"
        )
        
        if success:
            duration_text = "пожизненно" if duration == "lifetime" else f"на {duration} дн."
            await callback.answer(f"✅ Premium выдан {duration_text}", show_alert=True)
            
            # Обновляем информацию о пользователе
            await show_user_details(callback)
            
            # Логируем выдачу Premium
            await bot_logger.log_update(
                update_type="premium_granted",
                user_id=admin_user.telegram_id,
                admin_action="grant_premium",
                target_user_id=user_id,
                subscription_type=subscription_type.value,
                duration=duration
            )
            
        else:
            await callback.answer("❌ Ошибка при выдаче Premium", show_alert=True)
        
    except Exception as e:
        logger.error(f"Error confirming premium grant: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(callback: CallbackQuery, **kwargs):
    """Система рассылок"""
    try:
        # Получаем статистику рассылок
        broadcast_stats = await broadcast_service.get_broadcast_stats()
        
        broadcast_text = (
            "📢 **Система рассылок**\n\n"
            
            f"📊 **Статистика:**\n"
            f"• Всего рассылок: {broadcast_stats['total_broadcasts']}\n"
            f"• Активных: {broadcast_stats['active_broadcasts']}\n"
            f"• За месяц: {broadcast_stats['broadcasts_month']}\n"
            f"• Успешных доставок: {broadcast_stats['successful_deliveries']}\n\n"
            
            f"👥 **Аудитория:**\n"
            f"• Всего пользователей: {broadcast_stats['total_users']:,}\n"
            f"• Активных: {broadcast_stats['active_users']:,}\n"
            f"• Premium: {broadcast_stats['premium_users']:,}\n"
            f"• Free: {broadcast_stats['free_users']:,}\n\n"
            
            "Выберите тип рассылки:"
        )
        
        keyboard = get_broadcast_keyboard()
        
        await callback.message.edit_text(
            broadcast_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing broadcast panel: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("broadcast:"))
async def create_broadcast(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Создание рассылки"""
    try:
        broadcast_type = callback.data.split(":")[1]
        
        # Определяем целевую аудиторию
        target_counts = {
            "all": await user_service.get_users_count(),
            "premium": await user_service.get_users_count(premium_only=True),
            "free": await user_service.get_users_count(free_only=True),
            "inactive": await user_service.get_users_count(inactive_days=7)
        }
        
        target_names = {
            "all": "всем пользователям",
            "premium": "Premium пользователям", 
            "free": "Free пользователям",
            "inactive": "неактивным пользователям"
        }
        
        target_count = target_counts.get(broadcast_type, 0)
        target_name = target_names.get(broadcast_type, "выбранной аудитории")
        
        compose_text = (
            f"✍️ **Создание рассылки {target_name}**\n\n"
            f"👥 **Получателей:** {target_count:,} чел.\n\n"
            
            "📝 **Напишите сообщение для рассылки:**\n\n"
            
            "💡 **Возможности:**\n"
            "• HTML разметка\n"
            "• Эмодзи\n"
            "• Ссылки\n"
            "• До 4096 символов\n\n"
            
            "⚠️ **Правила:**\n"
            "• Не более 1 рассылки в день\n"
            "• Только важная информация\n"
            "• Соблюдать законодательство\n\n"
            
            "Отправьте сообщение следующим текстом:"
        )
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin:broadcast")
        )
        
        await callback.message.edit_text(
            compose_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await state.update_data(broadcast_type=broadcast_type, target_count=target_count)
        await state.set_state(AdminStates.broadcast_compose)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error creating broadcast: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(AdminStates.broadcast_compose)
async def process_broadcast_message(message: Message, state: FSMContext, **kwargs):
    """Обработка сообщения рассылки"""
    try:
        broadcast_message = message.text or message.caption
        
        if not broadcast_message:
            await message.answer("❌ Сообщение не может быть пустым")
            return
        
        if len(broadcast_message) > 4096:
            await message.answer("❌ Сообщение слишком длинное (максимум 4096 символов)")
            return
        
        data = await state.get_data()
        broadcast_type = data.get("broadcast_type")
        target_count = data.get("target_count")
        
        # Показываем превью рассылки
        preview_text = (
            f"📋 **Превью рассылки**\n\n"
            f"👥 **Получателей:** {target_count:,}\n"
            f"📊 **Тип:** {broadcast_type}\n\n"
            f"📝 **Сообщение:**\n"
            f"─────────────────\n"
            f"{broadcast_message}\n"
            f"─────────────────\n\n"
            f"⚠️ **Подтверждаете отправку?**"
        )
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        builder.row(
            InlineKeyboardButton(
                text="✅ Отправить рассылку",
                callback_data="confirm_broadcast"
            )
        )
        builder.row(
            InlineKeyboardButton(text="📝 Изменить сообщение", callback_data="edit_broadcast"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin:broadcast")
        )
        
        await message.answer(
            preview_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await state.update_data(broadcast_message=broadcast_message)
        await state.set_state(AdminStates.broadcast_confirm)
        
    except Exception as e:
        logger.error(f"Error processing broadcast message: {e}")
        await message.answer("❌ Ошибка при обработке сообщения")


@router.callback_query(F.data == "confirm_broadcast")
async def confirm_broadcast(callback: CallbackQuery, admin_user, state: FSMContext, **kwargs):
    """Подтверждение и запуск рассылки"""
    try:
        data = await state.get_data()
        broadcast_type = data.get("broadcast_type")
        broadcast_message = data.get("broadcast_message")
        target_count = data.get("target_count")
        
        # Создаем задачу рассылки
        broadcast_task = await broadcast_service.create_broadcast(
            message_text=broadcast_message,
            target_type=broadcast_type,
            created_by=admin_user.id
        )
        
        if broadcast_task:
            # Запускаем рассылку в фоне
            asyncio.create_task(
                execute_broadcast(broadcast_task.id, broadcast_message, broadcast_type)
            )
            
            success_text = (
                f"✅ **Рассылка запущена!**\n\n"
                f"🆔 ID рассылки: {broadcast_task.id}\n"
                f"👥 Получателей: {target_count:,}\n"
                f"⏰ Запущена: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"📊 Прогресс можно отслеживать в разделе статистики.\n\n"
                f"⚡ Рассылка выполняется в фоновом режиме."
            )
            
            keyboard = get_back_to_menu_keyboard()
            
            await callback.message.edit_text(
                success_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
            # Логируем запуск рассылки
            await bot_logger.log_update(
                update_type="broadcast_started",
                user_id=admin_user.telegram_id,
                admin_action="broadcast_create",
                broadcast_id=broadcast_task.id,
                target_type=broadcast_type,
                target_count=target_count
            )
            
        else:
            await callback.answer("❌ Ошибка при создании рассылки", show_alert=True)
        
        await state.clear()
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error confirming broadcast: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "admin:analytics")
async def admin_analytics(callback: CallbackQuery, **kwargs):
    """Аналитика и статистика"""
    try:
        # Получаем подробную аналитику
        analytics = await get_detailed_analytics()
        
        analytics_text = (
            "📊 **Детальная аналитика**\n\n"
            
            f"👥 **Пользователи:**\n"
            f"• Всего: {analytics['users']['total']:,}\n"
            f"• Новых за день: +{analytics['users']['new_today']:,}\n"
            f"• Активных за день: {analytics['users']['active_today']:,}\n"
            f"• Retention 7d: {analytics['users']['retention_7d']:.1f}%\n"
            f"• Churn rate: {analytics['users']['churn_rate']:.1f}%\n\n"
            
            f"🔍 **Поиски:**\n"
            f"• За день: {analytics['searches']['today']:,}\n"
            f"• За неделю: {analytics['searches']['week']:,}\n"
            f"• Success rate: {analytics['searches']['success_rate']:.1f}%\n"
            f"• Среднее время: {analytics['searches']['avg_time']:.1f}с\n\n"
            
            f"📥 **Скачивания:**\n"
            f"• За день: {analytics['downloads']['today']:,}\n"
            f"• За неделю: {analytics['downloads']['week']:,}\n"
            f"• Популярный источник: {analytics['downloads']['top_source']}\n\n"
            
            f"💰 **Финансы:**\n"
            f"• Доход за день: {analytics['revenue']['today']:,}₽\n"
            f"• Доход за месяц: {analytics['revenue']['month']:,}₽\n"
            f"• Конверсия: {analytics['revenue']['conversion']:.1f}%\n"
            f"• ARPU: {analytics['revenue']['arpu']:,.0f}₽\n\n"
            
            f"⚡ **Система:**\n"
            f"• Нагрузка CPU: {analytics['system']['cpu_usage']:.1f}%\n"
            f"• Память: {analytics['system']['memory_usage']:.1f}%\n"
            f"• Очередь: {analytics['system']['queue_size']} задач\n"
            f"• Ошибки/час: {analytics['system']['errors_per_hour']}"
        )
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        builder.row(
            InlineKeyboardButton(text="📈 Графики", callback_data="admin:charts"),
            InlineKeyboardButton(text="📊 Отчет", callback_data="admin:report")
        )
        
        builder.row(
            InlineKeyboardButton(text="📤 Экспорт", callback_data="admin:export_analytics"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:analytics")
        )
        
        builder.row(
            InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")
        )
        
        await callback.message.edit_text(
            analytics_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing analytics: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# Вспомогательные функции

async def get_admin_dashboard_stats() -> Dict[str, Any]:
    """Получение статистики для админ панели"""
    try:
        stats = {}
        
        # Статистика пользователей
        stats['total_users'] = await user_service.get_users_count()
        stats['active_24h'] = await user_service.get_active_users_count(hours=24)
        stats['premium_users'] = await user_service.get_users_count(premium_only=True)
        
        # Статистика активности
        stats['searches_today'] = await search_service.get_searches_count(days=1)
        stats['downloads_today'] = await analytics_service.get_downloads_count(days=1)
        
        # Финансовая статистика
        stats['revenue_month'] = await subscription_service.get_revenue(days=30)
        
        # Системная статистика
        stats['system_load'] = await get_system_load()
        stats['memory_usage'] = await get_memory_usage()
        stats['db_status'] = await check_database_status()
        stats['queue_size'] = await get_queue_size()
        
        return stats
        
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        return {}


async def get_user_management_stats() -> Dict[str, Any]:
    """Статистика для управления пользователями"""
    try:
        total = await user_service.get_users_count()
        active = await user_service.get_active_users_count(days=7)
        premium = await user_service.get_users_count(premium_only=True)
        blocked = await user_service.get_users_count(status=UserStatus.BANNED)
        
        new_today = await user_service.get_new_users_count(days=1)
        new_week = await user_service.get_new_users_count(days=7)
        new_month = await user_service.get_new_users_count(days=30)
        
        top_countries = await user_service.get_top_countries(limit=5)
        
        return {
            'total': total,
            'active': active,
            'premium': premium,
            'blocked': blocked,
            'active_percent': (active / total * 100) if total > 0 else 0,
            'premium_percent': (premium / total * 100) if total > 0 else 0,
            'new_today': new_today,
            'new_week': new_week,
            'new_month': new_month,
            'top_countries': top_countries
        }
        
    except Exception as e:
        logger.error(f"Error getting user management stats: {e}")
        return {}


def format_user_brief(user) -> str:
    """Краткая информация о пользователе"""
    name = user.first_name or user.username or f"User{user.telegram_id}"
    status_icon = "🟢" if user.status == UserStatus.ACTIVE else "🔴"
    premium_icon = "👑" if user.subscription_type != SubscriptionType.FREE else "🆓"
    
    return (
        f"{status_icon} {premium_icon} **{name}**\n"
        f"├ ID: `{user.telegram_id}`\n"
        f"├ Username: @{user.username or 'нет'}\n"
        f"└ Регистрация: {user.created_at.strftime('%d.%m.%Y')}\n"
    )


def format_user_details(user, user_stats, subscription) -> str:
    """Детальная информация о пользователе"""
    
    name = user.first_name or user.username or f"User{user.telegram_id}"
    
    # Базовая информация
    details = (
        f"👤 **{name}**\n\n"
        f"🆔 **ID:** `{user.telegram_id}`\n"
        f"👤 **Username:** @{user.username or 'нет'}\n"
        f"📅 **Регистрация:** {user.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"⏰ **Последняя активность:** {user.last_activity_at.strftime('%d.%m.%Y %H:%M') if user.last_activity_at else 'никогда'}\n"
    )
    
    # Статус
    status_text = {
        UserStatus.ACTIVE: "🟢 Активный",
        UserStatus.BANNED: "🔴 Заблокирован",
        UserStatus.INACTIVE: "🟡 Неактивный"
    }
    details += f"📊 **Статус:** {status_text.get(user.status, 'Неизвестно')}\n"
    
    if user.status == UserStatus.BANNED and user.ban_reason:
        details += f"🚫 **Причина блокировки:** {user.ban_reason}\n"
        if user.banned_at:
            details += f"📅 **Дата блокировки:** {user.banned_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    # Подписка
    if subscription:
        sub_names = {
            SubscriptionType.FREE: "🆓 Free",
            SubscriptionType.PREMIUM_MONTHLY: "👑 Premium (месячная)",
            SubscriptionType.PREMIUM_QUARTERLY: "👑 Premium (3 месяца)", 
            SubscriptionType.PREMIUM_YEARLY: "👑 Premium (годовая)",
            SubscriptionType.LIFETIME: "💎 Premium (пожизненная)"
        }
        
        details += f"💎 **Подписка:** {sub_names.get(subscription.subscription_type, 'Неизвестно')}\n"
        
        if subscription.expires_at:
            details += f"⏰ **Действует до:** {subscription.expires_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    # Статистика активности
    if user_stats:
        details += (
            f"\n📊 **Статистика:**\n"
            f"🔍 Поисков: {user_stats.total_searches:,}\n"
            f"📥 Скачиваний: {user_stats.total_downloads:,}\n"
            f"❤️ В избранном: {user_stats.favorite_tracks_count}\n"
            f"📋 Плейлистов: {user_stats.playlists_count}\n"
        )
    
    # Техническая информация
    details += (
        f"\n🔧 **Техническая информация:**\n"
        f"🌐 Язык: {user.language_code or 'не указан'}\n"
        f"🌍 Страна: {user.country_code or 'не указана'}\n"
        f"🏙️ Город: {user.city or 'не указан'}\n"
    )
    
    if user.referrer_id:
        details += f"👥 Пригласил: {user.referrer_id}\n"
    
    return details


def create_user_actions_keyboard(user):
    """Создание клавиатуры с действиями над пользователем"""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    
    # Основные действия
    if user.status == UserStatus.ACTIVE:
        builder.row(
            InlineKeyboardButton(
                text="🚫 Заблокировать",
                callback_data=f"admin:ban_user:{user.id}"
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="✅ Разблокировать",
                callback_data=f"admin:unban_user:{user.id}"
            )
        )
    
    # Premium действия
    if user.subscription_type == SubscriptionType.FREE:
        builder.row(
            InlineKeyboardButton(
                text="👑 Выдать Premium",
                callback_data=f"admin:grant_premium:{user.id}"
            )
        )
    
    # Дополнительные действия
    builder.row(
        InlineKeyboardButton(
            text="📊 Детальная статистика", 
            callback_data=f"admin:user_analytics:{user.id}"
        ),
        InlineKeyboardButton(
            text="💬 Отправить сообщение",
            callback_data=f"admin:message_user:{user.id}"
        )
    )
    
    builder.row(
        InlineKeyboardButton(
            text="⬅️ К поиску",
            callback_data="admin:user_search"
        )
    )
    
    return builder.as_markup()


async def
        logger.error(f"Error showing admin panel: {e}")
        error_text = "❌ Ошибка при загрузке админ панели"
        
        if isinstance(event, Message):
            await event.answer(error_text)
        else:
            await event.answer(error_text, show_alert=True)


@router.callback_query(F.data == "admin:users")
async def admin_user_management(callback: CallbackQuery, **kwargs):
    """Управление пользователями"""
    try:
        # Получаем статистику пользователей
        user_stats = await get_user_management_stats()
        
        users_text = (
            "👥 **Управление пользователями**\n\n"
            
            f"📈 **Статистика:**\n"
            f"• Всего: {user_stats['total']:,}\n"
            f"• Активных: {user_stats['active']:,} ({user_stats['active_percent']:.1f}%)\n"
            f"• Premium: {user_stats['premium']:,} ({user_stats['premium_percent']:.1f}%)\n"
            f"• Заблокированных: {user_stats['blocked']:,}\n\n"
            
            f"🆕 **Новые пользователи:**\n"
            f"• За сегодня: {user_stats['new_today']:,}\n"
            f"• За неделю: {user_stats['new_week']:,}\n"
            f"• За месяц: {user_stats['new_month']:,}\n\n"
            
            f"🌍 **География (топ-5):**\n"
        )
        
        for country, count in user_stats['top_countries']:
            users_text += f"• {country}: {count:,}\n"
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        builder.row(
            InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin:user_search"),
            InlineKeyboardButton(text="📊 Детальная статистика", callback_data="admin:user_stats")
        )
        
        builder.row(
            InlineKeyboardButton(text="🚫 Заблокированные", callback_data="admin:blocked_users"),
            InlineKeyboardButton(text="👑 Premium пользователи", callback_data="admin:premium_users")
        )
        
        builder.row(
            InlineKeyboardButton(text="📤 Экспорт данных", callback_data="admin:export_users"),
            InlineKeyboardButton(text="🗑️ Удалить неактивных", callback_data="admin:cleanup_users")
        )
        
        builder.row(
            InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")
        )
        
        await callback.message.edit_text(
            users_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in user management: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "admin:user_search")
async def admin_user_search(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Поиск пользователя"""
    try:
        search_text = (
            "🔍 **Поиск пользователя**\n\n"
            "Введите для поиска:\n"
            "• Telegram ID\n"
            "• Username (без @)\n"
            "• Имя или фамилию\n\n"
            "Пример: 123456789 или username или Иван"
        )
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin:users")
        )
        
        await callback.message.edit_text(
            search_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await state.set_state(AdminStates.user_search)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in user search: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(AdminStates.user_search)
async def process_user_search(message: Message, state: FSMContext, **kwargs):
    """Обработка поиска пользователя"""
    try:
        search_query = message.text.strip()
        
        # Ищем пользователя
        users = await user_service.search_users(search_query, limit=10)
        
        if not users:
            await message.answer(
                f"❌ Пользователи по запросу '{search_query}' не найдены\n\n"
                "Попробуйте другой запрос или проверьте правильность ввода."
            )
            return
        
        # Формируем результаты поиска
        results_text = f"🔍 **Результаты поиска:** `{search_query}`\n\n"
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        for user in users:
            user_info = format_user_brief(user)
            results_text += f"{user_info}\n"
            
            # Добавляем кнопку для детального просмотра
            builder.row(
                InlineKeyboardButton(
                    text=f"👤 {user.first_name or user.username or str(user.telegram_id)}",
                    callback_data=f"admin:user_detail:{user.id}"
                )
            )
        
        builder.row(
            InlineKeyboardButton(text="🔍 Новый поиск", callback_data="admin:user_search"),
            InlineKeyboardButton(text="⬅️ К управлению", callback_data="admin:users")
        )
        
        await message.answer(
            results_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error processing user search: {e}")
        await message.answer("❌ Ошибка при поиске пользователя")


@router.callback_query(F.data.startswith("admin:user_detail:"))
async def show_user_details(callback: CallbackQuery, **kwargs):
    """Подробная информация о пользователе"""
    try:
        user_id = callback.data.split(":")[2]
        
        # Получаем детальную информацию
        user = await user_service.get_user_by_id(user_id)
        if not user:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        user_stats = await user_service.get_user_stats(user.telegram_id)
        subscription = await user_service.get_user_subscription(user.telegram_id)
        
        # Форматируем детальную информацию
        details_text = format_user_details(user, user_stats, subscription)
        
        # Создаем клавиатуру с действиями
        keyboard = create_user_actions_keyboard(user)
        
        await callback.message.edit_text(
            details_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error admin : {e}")