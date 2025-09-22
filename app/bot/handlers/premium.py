# app/bot/handlers/premium.py
"""
Обработчик Premium функций и подписок
"""
from typing import Optional
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, SuccessfulPayment
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.core.logging import get_logger, bot_logger
from app.services.user_service import user_service
from app.services.payment_service import payment_service
from app.services.subscription_service import subscription_service
from app.services.promo_code_service import promo_code_service
from app.bot.keyboards.inline import (
    get_premium_keyboard, get_premium_offer_keyboard,
    get_payment_method_keyboard, get_crypto_currencies_keyboard,
    get_back_to_menu_keyboard, get_confirmation_keyboard
)
from app.models.user import SubscriptionType
from app.models.subscription import PaymentMethod
from app.core.config import settings

router = Router()
logger = get_logger(__name__)


class PremiumStates(StatesGroup):
    """Состояния для Premium функций"""
    selecting_plan = State()
    entering_promo_code = State()
    processing_payment = State()
    confirming_purchase = State()


@router.message(Command("premium"))
@router.callback_query(F.data == "premium")
async def show_premium_info(event, user, **kwargs):
    """Показать информацию о Premium"""
    try:
        # Проверяем текущий статус подписки
        is_premium = await user_service.is_premium_user(user.telegram_id)
        subscription = await user_service.get_user_subscription(user.telegram_id)
        
        if is_premium and subscription:
            # Пользователь уже Premium
            await show_current_subscription(event, user, subscription)
        else:
            # Предлагаем Premium
            await show_premium_plans(event, user)
        
    except Exception as e:
        logger.error(f"Error showing premium info: {e}")
        error_text = "❌ Ошибка при загрузке информации о Premium"
        
        if isinstance(event, Message):
            await event.answer(error_text)
        else:
            await event.answer(error_text, show_alert=True)


async def show_current_subscription(event, user, subscription):
    """Показать информацию о текущей подписке"""
    
    # Вычисляем оставшееся время
    if subscription.expires_at:
        days_left = max(0, (subscription.expires_at - datetime.utcnow()).days)
        time_left_text = f"{days_left} дн."
    else:
        time_left_text = "∞"
    
    # Определяем тип подписки
    sub_type_names = {
        SubscriptionType.PREMIUM_MONTHLY: "Premium (месячная)",
        SubscriptionType.PREMIUM_QUARTERLY: "Premium (3 месяца)", 
        SubscriptionType.PREMIUM_YEARLY: "Premium (годовая)",
        SubscriptionType.LIFETIME: "Premium (пожизненная)"
    }
    
    sub_name = sub_type_names.get(subscription.subscription_type, "Premium")
    
    premium_text = (
        "👑 **Ваша Premium подписка**\n\n"
        f"📋 **Тариф:** {sub_name}\n"
        f"⏰ **Осталось:** {time_left_text}\n"
        f"🔄 **Автопродление:** {'включено' if subscription.auto_renew else 'выключено'}\n"
        f"📅 **Активна до:** {subscription.expires_at.strftime('%d.%m.%Y') if subscription.expires_at else '∞'}\n\n"
        
        "💎 **Ваши Premium возможности:**\n"
        "✅ Безлимитные скачивания\n"
        "✅ Качество до 320kbps\n"
        "✅ Без рекламы\n"
        "✅ Приоритетный поиск\n"
        "✅ Расширенная статистика\n"
        "✅ Экспорт плейлистов\n"
        "✅ Ранний доступ к новинкам\n"
        "✅ Техническая поддержка\n"
    )
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    if subscription.expires_at:  # Если не пожизненная
        builder.row(
            InlineKeyboardButton(
                text="🔄 Продлить подписку",
                callback_data="renew_subscription"
            )
        )
        
        if subscription.auto_renew:
            builder.row(
                InlineKeyboardButton(
                    text="❌ Отключить автопродление",
                    callback_data="disable_auto_renew"
                )
            )
        else:
            builder.row(
                InlineKeyboardButton(
                    text="✅ Включить автопродление", 
                    callback_data="enable_auto_renew"
                )
            )
    
    builder.row(
        InlineKeyboardButton(
            text="📊 История платежей",
            callback_data="payment_history"
        )
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")
    )
    
    if isinstance(event, Message):
        await event.answer(
            premium_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    else:
        await event.message.edit_text(
            premium_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        await event.answer()


async def show_premium_plans(event, user):
    """Показать тарифные планы Premium"""
    
    # Получаем статистику для мотивации
    user_stats = await user_service.get_user_stats(user.telegram_id)
    limits = await user_service.check_daily_limits(user.telegram_id)
    
    # Подсчитываем экономию
    potential_savings = calculate_potential_savings(user_stats)
    
    premium_text = (
        "💎 **Получите Premium подписку!**\n\n"
        
        "🚫 **Ваши текущие ограничения:**\n"
        f"• Поиск: {limits['searches_used']}/{limits['searches_limit']} в день\n"
        f"• Скачивания: {limits['downloads_used']}/{limits['downloads_limit']} в день\n"
        f"• Качество: до 192kbps\n"
        f"• Реклама в результатах поиска\n\n"
        
        "👑 **Premium возможности:**\n"
        "✅ **Безлимитные** поиски и скачивания\n"
        "✅ **Высокое качество** до 320kbps\n"
        "✅ **Без рекламы** навсегда\n"
        "✅ **Приоритетный поиск** - результаты первым\n"
        "✅ **Расширенная статистика** и аналитика\n"
        "✅ **Экспорт плейлистов** в любом формате\n"
        "✅ **Ранний доступ** к новым функциям\n"
        "✅ **Техподдержка** в приоритете\n\n"
        
        "💰 **Тарифы:**\n"
        f"📅 **1 месяц** - ⭐ 150 Stars (≈{format_price_rub(150)}₽)\n"
        f"📅 **3 месяца** - ⭐ 400 Stars (≈{format_price_rub(400)}₽) 🔥 -12%\n"
        f"📅 **1 год** - ⭐ 1400 Stars (≈{format_price_rub(1400)}₽) 🔥 -23%\n\n"
    )
    
    if potential_savings > 0:
        premium_text += f"💡 **Ваша экономия:** до {potential_savings}₽ в год\n\n"
    
    premium_text += "⭐ Stars можно купить прямо в Telegram!\n💎 Также доступна оплата криптовалютой"
    
    keyboard = get_premium_keyboard()
    
    if isinstance(event, Message):
        await event.answer(
            premium_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await event.message.edit_text(
            premium_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await event.answer()


@router.callback_query(F.data.startswith("premium_plan:"))
async def select_premium_plan(callback: CallbackQuery, user, state: FSMContext, **kwargs):
    """Выбор тарифного плана"""
    try:
        plan = callback.data.split(":")[1]
        
        # Определяем параметры плана
        plans = {
            "1month": {
                "name": "Premium на 1 месяц",
                "price_stars": 150,
                "duration_days": 30,
                "subscription_type": SubscriptionType.PREMIUM_MONTHLY,
                "discount": 0
            },
            "3months": {
                "name": "Premium на 3 месяца", 
                "price_stars": 400,
                "duration_days": 90,
                "subscription_type": SubscriptionType.PREMIUM_QUARTERLY,
                "discount": 12
            },
            "1year": {
                "name": "Premium на 1 год",
                "price_stars": 1400, 
                "duration_days": 365,
                "subscription_type": SubscriptionType.PREMIUM_YEARLY,
                "discount": 23
            }
        }
        
        plan_info = plans.get(plan)
        if not plan_info:
            await callback.answer("❌ Неверный план", show_alert=True)
            return
        
        # Сохраняем выбранный план
        await state.update_data(selected_plan=plan_info)
        
        # Показываем способы оплаты
        await show_payment_methods(callback, plan_info)
        
    except Exception as e:
        logger.error(f"Error selecting plan: {e}")
        await callback.answer("❌ Ошибка при выборе плана", show_alert=True)


async def show_payment_methods(callback: CallbackQuery, plan_info: dict):
    """Показать способы оплаты"""
    
    discount_text = f" (-{plan_info['discount']}%)" if plan_info['discount'] > 0 else ""
    
    payment_text = (
        f"💳 **Оплата: {plan_info['name']}**\n\n"
        f"💰 **Стоимость:** ⭐ {plan_info['price_stars']} Stars{discount_text}\n"
        f"⏰ **Длительность:** {plan_info['duration_days']} дней\n\n"
        
        "**Выберите способ оплаты:**\n\n"
        
        "⭐ **Telegram Stars** - самый быстрый способ\n"
        "• Оплата прямо в Telegram\n"
        "• Мгновенная активация\n"
        "• Поддерживает карты, Apple Pay, Google Pay\n\n"
        
        "💎 **Криптовалюта** - через CryptoBot\n"
        "• TON, Bitcoin, USDT, USDC\n"
        "• Низкие комиссии\n"
        "• Анонимность платежа"
    )
    
    keyboard = get_payment_method_keyboard()
    
    await callback.message.edit_text(
        payment_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    
    await callback.answer()


@router.callback_query(F.data == "payment_method:stars")
async def pay_with_stars(callback: CallbackQuery, user, state: FSMContext, **kwargs):
    """Оплата через Telegram Stars"""
    try:
        data = await state.get_data()
        plan_info = data.get("selected_plan")
        
        if not plan_info:
            await callback.answer("❌ План не выбран", show_alert=True)
            return
        
        # Создаем счет на оплату
        prices = [LabeledPrice(
            label=plan_info["name"],
            amount=plan_info["price_stars"]
        )]
        
        # Создаем уникальный payload
        import uuid
        payment_payload = f"premium_{user.telegram_id}_{uuid.uuid4().hex[:8]}"
        
        # Сохраняем данные платежа
        await state.update_data(
            payment_payload=payment_payload,
            payment_method=PaymentMethod.TELEGRAM_STARS
        )
        
        await callback.message.answer_invoice(
            title=f"🔥 {plan_info['name']}",
            description=(
                f"Premium подписка на {plan_info['duration_days']} дней\n\n"
                "✅ Безлимитные скачивания\n"
                "✅ Качество 320kbps\n" 
                "✅ Без рекламы\n"
                "✅ Приоритетный поиск"
            ),
            payload=payment_payload,
            provider_token="",  # Для Stars токен не нужен
            currency="XTR",  # Код валюты для Stars
            prices=prices,
            start_parameter="premium_subscription",
            photo_url="https://your-domain.com/premium_image.jpg",  # Опционально
            photo_width=512,
            photo_height=512
        )
        
        await callback.answer("💳 Счет на оплату создан!")
        
        # Логируем создание счета
        await bot_logger.log_update(
            update_type="payment_invoice_created",
            user_id=user.telegram_id,
            payment_method="stars",
            amount=plan_info["price_stars"],
            plan=plan_info["name"]
        )
        
    except Exception as e:
        logger.error(f"Error creating Stars payment: {e}")
        await callback.answer("❌ Ошибка при создании счета", show_alert=True)


@router.callback_query(F.data == "payment_method:crypto")
async def pay_with_crypto(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Оплата криптовалютой"""
    try:
        crypto_text = (
            "💎 **Оплата криптовалютой**\n\n"
            "Выберите валюту для оплаты:\n\n"
            
            "💎 **TON** - быстро и дешево\n"
            "₿ **Bitcoin** - самая популярная\n"
            "💵 **USDT** - стабильная стоимость\n"
            "⚡ **USDC** - стабильная монета США\n\n"
            
            "🔐 Платежи обрабатывает @CryptoBot\n"
            "⚡ Мгновенное зачисление после подтверждения"
        )
        
        keyboard = get_crypto_currencies_keyboard()
        
        await callback.message.edit_text(
            crypto_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing crypto payment: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("crypto_currency:"))
async def select_crypto_currency(callback: CallbackQuery, user, state: FSMContext, **kwargs):
    """Выбор криптовалюты"""
    try:
        currency = callback.data.split(":")[1]
        
        data = await state.get_data()
        plan_info = data.get("selected_plan")
        
        if not plan_info:
            await callback.answer("❌ План не выбран", show_alert=True)
            return
        
        # Создаем криптоплатеж через CryptoBot
        payment_result = await payment_service.create_crypto_payment(
            user_id=user.id,
            amount_stars=plan_info["price_stars"],
            currency=currency,
            subscription_type=plan_info["subscription_type"],
            duration_days=plan_info["duration_days"]
        )
        
        if not payment_result:
            await callback.answer("❌ Ошибка создания платежа", show_alert=True)
            return
        
        # Конвертируем стоимость в выбранную криптовалюту
        crypto_amount = convert_stars_to_crypto(plan_info["price_stars"], currency)
        
        payment_text = (
            f"💎 **Оплата в {currency}**\n\n"
            f"💰 **К оплате:** {crypto_amount} {currency}\n"
            f"📦 **Товар:** {plan_info['name']}\n"
            f"🆔 **ID платежа:** `{payment_result['payment_id']}`\n\n"
            
            f"**Для оплаты:**\n"
            f"1️⃣ Перейдите по ссылке ниже\n"
            f"2️⃣ Оплатите в CryptoBot\n"
            f"3️⃣ Premium активируется автоматически\n\n"
            
            f"⏰ **Ссылка действует:** 30 минут\n"
            f"🔐 **Безопасность:** SSL + блокчейн"
        )
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        builder.row(
            InlineKeyboardButton(
                text=f"💎 Оплатить {crypto_amount} {currency}",
                url=payment_result["payment_url"]
            )
        )
        
        builder.row(
            InlineKeyboardButton(
                text="🔄 Проверить оплату",
                callback_data=f"check_payment:{payment_result['payment_id']}"
            )
        )
        
        builder.row(
            InlineKeyboardButton(text="❌ Отмена", callback_data="premium")
        )
        
        await callback.message.edit_text(
            payment_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
        # Логируем создание криптоплатежа
        await bot_logger.log_update(
            update_type="crypto_payment_created",
            user_id=user.telegram_id,
            payment_id=payment_result['payment_id'],
            currency=currency,
            amount=crypto_amount
        )
        
    except Exception as e:
        logger.error(f"Error creating crypto payment: {e}")
        await callback.answer("❌ Ошибка при создании платежа", show_alert=True)


@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, state: FSMContext):
    """Обработка предварительной проверки оплаты Stars"""
    try:
        # Проверяем payload
        data = await state.get_data()
        expected_payload = data.get("payment_payload")
        
        if pre_checkout_query.invoice_payload != expected_payload:
            await pre_checkout_query.answer(
                ok=False,
                error_message="Неверный идентификатор платежа"
            )
            return
        
        # Все проверки пройдены
        await pre_checkout_query.answer(ok=True)
        
    except Exception as e:
        logger.error(f"Error in pre-checkout: {e}")
        await pre_checkout_query.answer(
            ok=False,
            error_message="Техническая ошибка. Попробуйте позже."
        )


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, user, state: FSMContext, **kwargs):
    """Обработка успешной оплаты Stars"""
    try:
        payment = message.successful_payment
        
        # Получаем данные плана
        data = await state.get_data()
        plan_info = data.get("selected_plan")
        
        if not plan_info:
            logger.error(f"No plan info for successful payment from user {user.id}")
            return
        
        # Создаем подписку
        subscription_result = await subscription_service.create_subscription(
            user_id=user.id,
            subscription_type=plan_info["subscription_type"],
            duration_days=plan_info["duration_days"],
            payment_method=PaymentMethod.TELEGRAM_STARS,
            payment_id=payment.telegram_payment_charge_id,
            amount_paid=payment.total_amount
        )
        
        if subscription_result:
            # Успешно создана подписка
            success_text = (
                "🎉 **Premium активирован!**\n\n"
                f"✅ Подписка: {plan_info['name']}\n"
                f"📅 Активна до: {format_subscription_end_date(plan_info['duration_days'])}\n"
                f"💳 Оплачено: ⭐ {payment.total_amount} Stars\n\n"
                
                "🚀 **Теперь вам доступно:**\n"
                "• Безлимитные скачивания\n"
                "• Качество до 320kbps\n"
                "• Приоритетный поиск\n"
                "• Расширенная статистика\n"
                "• И многое другое!\n\n"
                
                "Спасибо за покупку! 💎"
            )
            
            keyboard = get_back_to_menu_keyboard()
            
            await message.answer(
                success_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
            # Логируем успешную оплату
            await bot_logger.log_update(
                update_type="premium_activated",
                user_id=user.telegram_id,
                subscription_type=plan_info["subscription_type"].value,
                payment_amount=payment.total_amount,
                duration_days=plan_info["duration_days"]
            )
            
            # Отправляем уведомление в админ чат (если настроен)
            if settings.ADMIN_CHAT_ID:
                admin_text = (
                    f"💰 **Новая Premium подписка!**\n\n"
                    f"👤 Пользователь: {user.telegram_id}\n"
                    f"📦 План: {plan_info['name']}\n" 
                    f"💳 Сумма: {payment.total_amount} Stars\n"
                    f"📅 До: {format_subscription_end_date(plan_info['duration_days'])}"
                )
                
                try:
                    from app.bot.main import music_bot
                    await music_bot.bot.send_message(
                        chat_id=settings.ADMIN_CHAT_ID,
                        text=admin_text,
                        parse_mode="Markdown"
                    )
                except:
                    pass  # Игнорируем ошибки отправки в админ чат
            
        else:
            # Ошибка активации подписки
            await message.answer(
                "❌ Ошибка активации Premium.\n\n"
                "Оплата прошла успешно, но возникла техническая ошибка.\n"
                "Обратитесь в поддержку: @support"
            )
            
        # Очищаем состояние
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error processing successful payment: {e}")
        await message.answer(
            "❌ Ошибка при обработке платежа.\n"
            "Обратитесь в поддержку: @support"
        )


@router.callback_query(F.data.startswith("check_payment:"))
async def check_payment_status(callback: CallbackQuery, user, **kwargs):
    """Проверка статуса криптоплатежа"""
    try:
        payment_id = callback.data.split(":")[1]
        
        # Проверяем статус платежа
        payment_status = await payment_service.check_payment_status(payment_id)
        
        if payment_status == "paid":
            # Платеж прошел - активируем подписку
            subscription_activated = await payment_service.activate_subscription_by_payment(
                payment_id, user.id
            )
            
            if subscription_activated:
                await callback.answer("✅ Оплата подтверждена! Premium активирован!", show_alert=True)
                await show_premium_info(callback, user)
            else:
                await callback.answer("❌ Ошибка активации подписки", show_alert=True)
                
        elif payment_status == "pending":
            await callback.answer("⏳ Платеж обрабатывается...", show_alert=True)
            
        elif payment_status == "expired":
            await callback.answer("⏰ Счет истек. Создайте новый", show_alert=True)
            
        else:
            await callback.answer("❌ Платеж не найден или отклонен", show_alert=True)
            
    except Exception as e:
        logger.error(f"Error checking payment: {e}")
        await callback.answer("❌ Ошибка проверки платежа", show_alert=True)


@router.callback_query(F.data == "promo_code")
async def enter_promo_code(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Ввод промокода"""
    try:
        promo_text = (
            "🎁 **Промокод**\n\n"
            "Введите промокод для получения скидки:\n\n"
            "💡 **Где взять промокод:**\n"
            "• В нашем канале @musicbot_news\n"
            "• В акциях и розыгрышах\n"
            "• От рефералов\n\n"
            "Отправьте промокод следующим сообщением"
        )
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="❌ Отмена", callback_data="premium")
        )
        
        await callback.message.edit_text(
            promo_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await state.set_state(PremiumStates.entering_promo_code)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error entering promo code: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(PremiumStates.entering_promo_code)
async def process_promo_code(message: Message, user, state: FSMContext, **kwargs):
    """Обработка промокода"""
    try:
        promo_code = message.text.strip().upper()
        
        # Проверяем промокод
        promo_result = await promo_code_service.validate_promo_code(
            promo_code, user.telegram_id
        )
        
        if not promo_result.is_valid:
            error_text = (
                f"❌ **Промокод недействителен**\n\n"
                f"Причина: {promo_result.error_message}\n\n"
                "Попробуйте другой промокод или вернитесь к выбору тарифа"
            )
            
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(text="🔄 Другой код", callback_data="promo_code"),
                InlineKeyboardButton(text="⬅️ К тарифам", callback_data="premium")
            )
            
            await message.answer(
                error_text,
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )
            return
        
        # Промокод действителен
        await state.update_data(promo_code=promo_code, promo_discount=promo_result.discount_value)
        await state.clear()
        
        success_text = (
            f"🎉 **Промокод принят!**\n\n"
            f"🎁 **Код:** {promo_code}\n"
            f"💰 **Скидка:** {promo_result.discount_value}"
        )
        
        if promo_result.discount_type == "percentage":
            success_text += "%\n"
        elif promo_result.discount_type == "fixed":
            success_text += " Stars\n"
        elif promo_result.discount_type == "free":
            success_text += " (бесплатно!)\n"
        
        success_text += f"\n💎 Выберите тариф для применения скидки:"
        
        keyboard = get_premium_keyboard()
        
        await message.answer(
            success_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        # Логируем использование промокода
        await bot_logger.log_update(
            update_type="promo_code_applied",
            user_id=user.telegram_id,
            promo_code=promo_code,
            discount_value=promo_result.discount_value
        )
        
    except Exception as e:
        logger.error(f"Error processing promo code: {e}")
        await message.answer("❌ Ошибка при обработке промокода")


@router.callback_query(F.data == "premium_benefits")
async def show_premium_benefits(callback: CallbackQuery, **kwargs):
    """Подробная информация о Premium возможностях"""
    try:
        benefits_text = (
            "💎 **Подробно о Premium**\n\n"
            
            "🚀 **Снятие ограничений:**\n"
            "• ∞ Безлимитные поиски (вместо 30/день)\n"
            "• ∞ Безлимитные скачивания (вместо 10/день)\n"
            "• 🚫 Полное отсутствие рекламы\n\n"
            
            "🔊 **Качество звука:**\n"
            "• 💎 До 320 kbps (CD качество)\n"
            "• 🎧 Поддержка всех форматов\n"
            "• 📈 Автовыбор лучшего источника\n\n"
            
            "⚡ **Приоритеты:**\n"
            "• 🥇 Первоочередная обработка запросов\n"
            "• 🔍 Доступ к эксклюзивным источникам\n"
            "• ⚡ Быстрее результаты поиска\n\n"
            
            "📊 **Расширенная статистика:**\n"
            "• 📈 Детальная аналитика прослушиваний\n"
            "• 🎯 Персональные рекомендации\n"
            "• 🏆 Достижения и награды\n"
            "• 📅 История за весь период\n\n"
            
            "🛠️ **Дополнительные возможности:**\n"
            "• 📤 Экспорт плейлистов (Spotify, Apple Music)\n"
            "• 💾 Backup всех данных\n"
            "• 🔄 Синхронизация между устройствами\n"
            "• 🎵 Умные плейлисты\n\n"
            
            "👨‍💻 **Поддержка:**\n"
            "• 📞 Приоритетная техподдержка\n"
            "• 🆕 Ранний доступ к новым функциям\n"
            "• 💬 Прямая связь с разработчиками\n\n"
            
            "💡 **Экономия:**\n"
            "• 📱 Замена 5+ музыкальных сервисов\n"
            "• 💸 Стоимость от 5₽ в день\n"
            "• 🎁 Регулярные акции и скидки"
        )
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="💎 Купить Premium", callback_data="premium")
        )
        builder.row(
            InlineKeyboardButton(text="🎁 У меня есть промокод", callback_data="promo_code")
        )
        builder.row(
            InlineKeyboardButton(text="⬅️ Назад", callback_data="premium")
        )
        
        await callback.message.edit_text(
            benefits_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing premium benefits: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "payment_history")
async def show_payment_history(callback: CallbackQuery, user, **kwargs):
    """История платежей пользователя"""
    try:
        # Получаем историю платежей
        payments = await payment_service.get_user_payments(user.id, limit=20)
        
        if not payments:
            history_text = (
                "📋 **История платежей**\n\n"
                "У вас пока нет платежей.\n"
                "Оформите Premium подписку, чтобы увидеть историю!"
            )
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💎 Купить Premium", callback_data="premium")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="premium")]
                ]
            )
            
            await callback.message.edit_text(
                history_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        # Форматируем историю платежей
        history_text = "📋 **История платежей**\n\n"
        
        for payment in payments:
            status_icon = {
                "completed": "✅",
                "pending": "⏳", 
                "failed": "❌",
                "refunded": "🔄"
            }.get(payment.status, "❓")
            
            payment_date = payment.created_at.strftime("%d.%m.%Y %H:%M")
            
            history_text += (
                f"{status_icon} **{payment.amount} Stars** - {payment.product_type}\n"
                f"📅 {payment_date} | {payment.payment_method.value}\n"
            )
            
            if payment.status == "completed" and hasattr(payment, 'subscription'):
                history_text += f"✨ Premium до {payment.subscription.expires_at.strftime('%d.%m.%Y')}\n"
            
            history_text += "\n"
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="📧 Запросить чек", callback_data="request_receipt")
        )
        builder.row(
            InlineKeyboardButton(text="⬅️ К подписке", callback_data="premium")
        )
        
        await callback.message.edit_text(
            history_text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error showing payment history: {e}")
        await callback.answer("❌ Ошибка при загрузке истории", show_alert=True)


@router.callback_query(F.data == "disable_auto_renew")
async def disable_auto_renew(callback: CallbackQuery, user, **kwargs):
    """Отключение автопродления"""
    try:
        success = await subscription_service.disable_auto_renew(user.id)
        
        if success:
            await callback.answer("✅ Автопродление отключено", show_alert=True)
            await show_premium_info(callback, user)
            
            # Логируем изменение настроек
            await bot_logger.log_update(
                update_type="auto_renew_disabled",
                user_id=user.telegram_id
            )
        else:
            await callback.answer("❌ Ошибка при отключении автопродления", show_alert=True)
            
    except Exception as e:
        logger.error(f"Error disabling auto renew: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "enable_auto_renew")
async def enable_auto_renew(callback: CallbackQuery, user, **kwargs):
    """Включение автопродления"""
    try:
        success = await subscription_service.enable_auto_renew(user.id)
        
        if success:
            await callback.answer("✅ Автопродление включено", show_alert=True)
            await show_premium_info(callback, user)
            
            # Логируем изменение настроек
            await bot_logger.log_update(
                update_type="auto_renew_enabled",
                user_id=user.telegram_id
            )
        else:
            await callback.answer("❌ Ошибка при включении автопродления", show_alert=True)
            
    except Exception as e:
        logger.error(f"Error enabling auto renew: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "renew_subscription")
async def renew_subscription(callback: CallbackQuery, user, **kwargs):
    """Продление подписки"""
    try:
        # Получаем текущую подписку
        current_subscription = await user_service.get_user_subscription(user.telegram_id)
        
        if not current_subscription:
            await callback.answer("❌ Активная подписка не найдена", show_alert=True)
            return
        
        renew_text = (
            "🔄 **Продление подписки**\n\n"
            f"📋 **Текущий тариф:** {current_subscription.subscription_type.value}\n"
            f"📅 **Действует до:** {current_subscription.expires_at.strftime('%d.%m.%Y')}\n\n"
            
            "Выберите период продления:\n\n"
            "💡 **При продлении:**\n"
            "• Время добавляется к текущей подписке\n"
            "• Действующая скидка сохраняется\n"
            "• Никаких перерывов в обслуживании"
        )
        
        keyboard = get_premium_keyboard()
        
        await callback.message.edit_text(
            renew_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error renewing subscription: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# Утилитарные функции

def format_price_rub(stars: int) -> int:
    """Конвертация Stars в рубли для отображения"""
    # Примерный курс: 1 Star ≈ 1.3 рублей
    return int(stars * 1.3)


def calculate_potential_savings(user_stats) -> int:
    """Расчет потенциальной экономии пользователя"""
    
    # Базовая экономия на основе использования
    base_savings = 0
    
    # Если пользователь активный - показываем экономию
    if user_stats.total_downloads > 50:
        base_savings += 500  # Экономия на альтернативных сервисах
    
    if user_stats.total_searches > 100:
        base_savings += 300  # Экономия времени
    
    if user_stats.playlists_count > 5:
        base_savings += 200  # Экономия на управлении музыкой
    
    return min(base_savings, 2000)  # Максимум 2000₽ экономии


def convert_stars_to_crypto(stars: int, currency: str) -> str:
    """Конвертация Stars в криптовалюту"""
    
    # Примерные курсы (в реальности брать с API)
    rates = {
        "TON": stars * 0.15,    # 1 Star ≈ 0.15 TON
        "BTC": stars * 0.000003, # 1 Star ≈ 0.000003 BTC  
        "USDT": stars * 0.013,   # 1 Star ≈ $0.013
        "USDC": stars * 0.013    # 1 Star ≈ $0.013
    }
    
    amount = rates.get(currency, stars * 0.013)
    
    # Форматируем в зависимости от валюты
    if currency in ["BTC"]:
        return f"{amount:.8f}"
    elif currency in ["TON", "USDT", "USDC"]:
        return f"{amount:.2f}"
    else:
        return f"{amount:.4f}"


def format_subscription_end_date(duration_days: int) -> str:
    """Форматирование даты окончания подписки"""
    from datetime import datetime, timedelta
    
    end_date = datetime.utcnow() + timedelta(days=duration_days)
    return end_date.strftime("%d.%m.%Y")


from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup