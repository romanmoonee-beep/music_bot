"""
Сервис для обработки платежей и управления подписками
"""
import asyncio
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import hmac
import aiohttp

from app.core.database import get_session
from app.core.logging import get_logger
from app.core.config import settings
from app.models.user import User, UserSubscription, SubscriptionType
from app.models.subscription import Payment, PaymentStatus, PaymentMethod, PaymentProvider
from app.schemas.payment import (
    PaymentCreate, PaymentResponse, SubscriptionCreate,
    TelegramStarsPayment, CryptoBotPayment
)
from app.services.user_service import user_service
from sqlalchemy.future import select
from sqlalchemy import and_


class PaymentService:
    """Сервис для обработки платежей"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.cryptobot_api_url = "https://pay.crypt.bot/api"
        
        # Настройки подписок
        self.subscription_plans = {
            "1month": {
                "duration_days": 30,
                "stars_price": settings.PREMIUM_PRICE_1M,
                "crypto_price_usd": 2.99,
                "title": "Premium 1 месяц",
                "description": "Доступ ко всем функциям на 1 месяц"
            },
            "3months": {
                "duration_days": 90,
                "stars_price": settings.PREMIUM_PRICE_3M,
                "crypto_price_usd": 7.99,
                "title": "Premium 3 месяца",
                "description": "Доступ ко всем функциям на 3 месяца (-12%)"
            },
            "1year": {
                "duration_days": 365,
                "stars_price": settings.PREMIUM_PRICE_1Y,
                "crypto_price_usd": 23.99,
                "title": "Premium 1 год",
                "description": "Доступ ко всем функциям на 1 год (-23%)"
            }
        }
    
    async def create_telegram_stars_payment(
        self,
        telegram_id: int,
        plan: str,
        bot_username: str
    ) -> Optional[PaymentResponse]:
        """Создать платеж через Telegram Stars"""
        try:
            if plan not in self.subscription_plans:
                self.logger.error(f"Invalid subscription plan: {plan}")
                return None
            
            plan_info = self.subscription_plans[plan]
            
            # Создаем запись платежа
            payment_id = str(uuid.uuid4())
            
            async with get_session() as session:
                user = await user_service.get_user_by_telegram_id(telegram_id)
                if not user:
                    return None
                
                payment = Payment(
                    id=payment_id,
                    user_id=user.id,
                    amount=Decimal(plan_info["stars_price"]),
                    currency="XTR",  # Telegram Stars
                    provider=PaymentProvider.TELEGRAM_STARS,
                    method=PaymentMethod.TELEGRAM_STARS,
                    status=PaymentStatus.PENDING,
                    plan_type=plan,
                    metadata={
                        "telegram_id": telegram_id,
                        "bot_username": bot_username,
                        "plan_duration_days": plan_info["duration_days"],
                        "title": plan_info["title"],
                        "description": plan_info["description"]
                    },
                    created_at=datetime.now(timezone.utc)
                )
                
                session.add(payment)
                await session.commit()
                await session.refresh(payment)
            
            # Формируем ответ для создания Telegram Invoice
            return PaymentResponse(
                payment_id=payment_id,
                amount=plan_info["stars_price"],
                currency="XTR",
                title=plan_info["title"],
                description=plan_info["description"],
                provider_payment_charge_id=None,
                provider_data={
                    "payload": payment_id,
                    "start_parameter": f"pay_{payment_id}",
                    "prices": [{"label": plan_info["title"], "amount": plan_info["stars_price"]}]
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to create Telegram Stars payment: {e}")
            return None
    
    async def create_cryptobot_payment(
        self,
        telegram_id: int,
        plan: str,
        currency: str = "USDT"
    ) -> Optional[PaymentResponse]:
        """Создать платеж через CryptoBot"""
        try:
            if not settings.CRYPTOBOT_API_TOKEN:
                self.logger.error("CryptoBot API token not configured")
                return None
            
            if plan not in self.subscription_plans:
                self.logger.error(f"Invalid subscription plan: {plan}")
                return None
            
            plan_info = self.subscription_plans[plan]
            payment_id = str(uuid.uuid4())
            
            # Создаем платеж в CryptoBot
            cryptobot_data = {
                "asset": currency,
                "amount": str(plan_info["crypto_price_usd"]),
                "description": f"{plan_info['title']} for user {telegram_id}",
                "hidden_message": f"Premium subscription activated for {plan_info['duration_days']} days",
                "paid_btn_name": "callback",
                "paid_btn_url": f"https://t.me/{settings.BOT_USERNAME}?start=payment_{payment_id}",
                "start_parameter": payment_id,
                "allow_comments": False,
                "allow_anonymous": False
            }
            
            headers = {
                "Crypto-Pay-API-Token": settings.CRYPTOBOT_API_TOKEN,
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.cryptobot_api_url}/createInvoice",
                    json=cryptobot_data,
                    headers=headers
                ) as response:
                    
                    if response.status != 200:
                        self.logger.error(f"CryptoBot API error: {response.status}")
                        return None
                    
                    result = await response.json()
                    
                    if not result.get("ok"):
                        self.logger.error(f"CryptoBot error: {result}")
                        return None
                    
                    invoice_data = result["result"]
            
            # Сохраняем платеж в базу
            async with get_session() as db_session:
                user = await user_service.get_user_by_telegram_id(telegram_id)
                if not user:
                    return None
                
                payment = Payment(
                    id=payment_id,
                    user_id=user.id,
                    amount=Decimal(plan_info["crypto_price_usd"]),
                    currency=currency,
                    provider=PaymentProvider.CRYPTOBOT,
                    method=PaymentMethod.CRYPTOCURRENCY,
                    status=PaymentStatus.PENDING,
                    plan_type=plan,
                    external_id=str(invoice_data["invoice_id"]),
                    metadata={
                        "telegram_id": telegram_id,
                        "plan_duration_days": plan_info["duration_days"],
                        "cryptobot_invoice_id": invoice_data["invoice_id"],
                        "pay_url": invoice_data["pay_url"],
                        "mini_app_invoice_url": invoice_data.get("mini_app_invoice_url"),
                        "web_app_invoice_url": invoice_data.get("web_app_invoice_url")
                    },
                    created_at=datetime.now(timezone.utc)
                )
                
                db_session.add(payment)
                await db_session.commit()
                await db_session.refresh(payment)
            
            return PaymentResponse(
                payment_id=payment_id,
                amount=plan_info["crypto_price_usd"],
                currency=currency,
                title=plan_info["title"],
                description=plan_info["description"],
                provider_payment_charge_id=str(invoice_data["invoice_id"]),
                provider_data={
                    "pay_url": invoice_data["pay_url"],
                    "mini_app_url": invoice_data.get("mini_app_invoice_url"),
                    "web_app_url": invoice_data.get("web_app_invoice_url"),
                    "invoice_id": invoice_data["invoice_id"]
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to create CryptoBot payment: {e}")
            return None
    
    async def handle_telegram_stars_webhook(
        self,
        payment_data: Dict[str, Any]
    ) -> bool:
        """Обработать webhook от Telegram Stars"""
        try:
            # Извлекаем данные из pre_checkout_query или successful_payment
            payment_id = payment_data.get("invoice_payload") or payment_data.get("payload")
            
            if not payment_id:
                self.logger.error("No payment ID in Telegram webhook")
                return False
            
            # Находим платеж в базе
            async with get_session() as session:
                query = select(Payment).where(Payment.id == payment_id)
                result = await session.execute(query)
                payment = result.scalar_one_or_none()
                
                if not payment:
                    self.logger.error(f"Payment {payment_id} not found")
                    return False
                
                if payment.status != PaymentStatus.PENDING:
                    self.logger.warning(f"Payment {payment_id} already processed")
                    return True
                
                # Обновляем статус платежа
                payment.status = PaymentStatus.COMPLETED
                payment.processed_at = datetime.now(timezone.utc)
                payment.external_id = payment_data.get("telegram_payment_charge_id")
                
                # Создаем подписку
                success = await self._create_subscription_from_payment(payment)
                
                if success:
                    await session.commit()
                    self.logger.info(f"Telegram Stars payment {payment_id} processed successfully")
                    return True
                else:
                    payment.status = PaymentStatus.FAILED
                    await session.commit()
                    return False
            
        except Exception as e:
            self.logger.error(f"Failed to handle Telegram Stars webhook: {e}")
            return False
    
    async def handle_cryptobot_webhook(
        self,
        webhook_data: Dict[str, Any],
        webhook_signature: str
    ) -> bool:
        """Обработать webhook от CryptoBot"""
        try:
            # Проверяем подпись webhook
            if not self._verify_cryptobot_signature(webhook_data, webhook_signature):
                self.logger.error("Invalid CryptoBot webhook signature")
                return False
            
            update_type = webhook_data.get("update_type")
            if update_type != "invoice_paid":
                return True  # Игнорируем другие типы обновлений
            
            invoice_data = webhook_data.get("payload", {})
            invoice_id = invoice_data.get("invoice_id")
            
            if not invoice_id:
                self.logger.error("No invoice ID in CryptoBot webhook")
                return False
            
            # Находим платеж по external_id
            async with get_session() as session:
                query = select(Payment).where(Payment.external_id == str(invoice_id))
                result = await session.execute(query)
                payment = result.scalar_one_or_none()
                
                if not payment:
                    self.logger.error(f"Payment with invoice_id {invoice_id} not found")
                    return False
                
                if payment.status != PaymentStatus.PENDING:
                    self.logger.warning(f"Payment {payment.id} already processed")
                    return True
                
                # Обновляем платеж
                payment.status = PaymentStatus.COMPLETED
                payment.processed_at = datetime.now(timezone.utc)
                payment.metadata.update({
                    "paid_asset": invoice_data.get("asset"),
                    "paid_amount": invoice_data.get("amount"),
                    "paid_at": invoice_data.get("paid_at"),
                    "hash": invoice_data.get("hash")
                })
                
                # Создаем подписку
                success = await self._create_subscription_from_payment(payment)
                
                if success:
                    await session.commit()
                    self.logger.info(f"CryptoBot payment {payment.id} processed successfully")
                    return True
                else:
                    payment.status = PaymentStatus.FAILED
                    await session.commit()
                    return False
            
        except Exception as e:
            self.logger.error(f"Failed to handle CryptoBot webhook: {e}")
            return False
    
    async def get_payment_status(self, payment_id: str) -> Optional[Dict[str, Any]]:
        """Получить статус платежа"""
        try:
            async with get_session() as session:
                query = select(Payment).where(Payment.id == payment_id)
                result = await session.execute(query)
                payment = result.scalar_one_or_none()
                
                if not payment:
                    return None
                
                return {
                    "payment_id": payment.id,
                    "status": payment.status.value,
                    "amount": float(payment.amount),
                    "currency": payment.currency,
                    "provider": payment.provider.value,
                    "plan_type": payment.plan_type,
                    "created_at": payment.created_at.isoformat(),
                    "processed_at": payment.processed_at.isoformat() if payment.processed_at else None
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get payment status: {e}")
            return None
    
    async def get_user_payments(
        self,
        telegram_id: int,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Получить историю платежей пользователя"""
        try:
            async with get_session() as session:
                user = await user_service.get_user_by_telegram_id(telegram_id)
                if not user:
                    return []
                
                query = select(Payment).where(
                    Payment.user_id == user.id
                ).order_by(
                    Payment.created_at.desc()
                ).limit(limit)
                
                result = await session.execute(query)
                payments = result.scalars().all()
                
                return [
                    {
                        "payment_id": payment.id,
                        "status": payment.status.value,
                        "amount": float(payment.amount),
                        "currency": payment.currency,
                        "provider": payment.provider.value,
                        "plan_type": payment.plan_type,
                        "created_at": payment.created_at.isoformat(),
                        "processed_at": payment.processed_at.isoformat() if payment.processed_at else None
                    }
                    for payment in payments
                ]
                
        except Exception as e:
            self.logger.error(f"Failed to get user payments: {e}")
            return []
    
    async def refund_payment(
        self,
        payment_id: str,
        reason: str = "User request"
    ) -> bool:
        """Возврат платежа"""
        try:
            async with get_session() as session:
                query = select(Payment).where(Payment.id == payment_id)
                result = await session.execute(query)
                payment = result.scalar_one_or_none()
                
                if not payment:
                    self.logger.error(f"Payment {payment_id} not found")
                    return False
                
                if payment.status != PaymentStatus.COMPLETED:
                    self.logger.error(f"Cannot refund payment {payment_id} with status {payment.status}")
                    return False
                
                # Для CryptoBot отправляем API запрос на возврат
                if payment.provider == PaymentProvider.CRYPTOBOT:
                    refund_success = await self._process_cryptobot_refund(payment)
                    if not refund_success:
                        return False
                
                # Обновляем статус платежа
                payment.status = PaymentStatus.REFUNDED
                payment.metadata.update({
                    "refund_reason": reason,
                    "refunded_at": datetime.now(timezone.utc).isoformat()
                })
                
                # Деактивируем связанную подписку
                await self._deactivate_subscription_for_payment(payment)
                
                await session.commit()
                
                self.logger.info(f"Payment {payment_id} refunded successfully")
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to refund payment: {e}")
            return False
    
    async def _create_subscription_from_payment(self, payment: Payment) -> bool:
        """Создать подписку на основе платежа"""
        try:
            plan_info = self.subscription_plans.get(payment.plan_type)
            if not plan_info:
                self.logger.error(f"Unknown plan type: {payment.plan_type}")
                return False
            
            # Деактивируем старые подписки пользователя
            async with get_session() as session:
                old_subs_query = select(UserSubscription).where(
                    UserSubscription.user_id == payment.user_id,
                    UserSubscription.is_active == True
                )
                old_subs_result = await session.execute(old_subs_query)
                old_subscriptions = old_subs_result.scalars().all()
                
                for old_sub in old_subscriptions:
                    old_sub.is_active = False
                    old_sub.updated_at = datetime.now(timezone.utc)
                
                # Создаем новую подписку
                starts_at = datetime.now(timezone.utc)
                expires_at = starts_at + timedelta(days=plan_info["duration_days"])
                
                subscription = UserSubscription(
                    user_id=payment.user_id,
                    subscription_type=SubscriptionType.PREMIUM,
                    payment_method=payment.method,
                    amount=payment.amount,
                    currency=payment.currency,
                    starts_at=starts_at,
                    expires_at=expires_at,
                    is_active=True,
                    auto_renew=False,  # Пока не поддерживаем автопродление
                    payment_id=payment.id,
                    created_at=datetime.now(timezone.utc)
                )
                
                session.add(subscription)
                await session.commit()
                
                self.logger.info(f"Created subscription for user {payment.user_id}")
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to create subscription from payment: {e}")
            return False
    
    async def _deactivate_subscription_for_payment(self, payment: Payment):
        """Деактивировать подписку для платежа"""
        try:
            async with get_session() as session:
                query = select(UserSubscription).where(
                    UserSubscription.payment_id == payment.id
                )
                result = await session.execute(query)
                subscription = result.scalar_one_or_none()
                
                if subscription:
                    subscription.is_active = False
                    subscription.updated_at = datetime.now(timezone.utc)
                    await session.commit()
                    
        except Exception as e:
            self.logger.error(f"Failed to deactivate subscription: {e}")
    
    def _verify_cryptobot_signature(
        self,
        webhook_data: Dict[str, Any],
        signature: str
    ) -> bool:
        """Проверить подпись CryptoBot webhook"""
        try:
            if not settings.CRYPTOBOT_API_TOKEN:
                return False
            
            # Создаем hash от данных webhook
            import json
            data_string = json.dumps(webhook_data, separators=(',', ':'), sort_keys=True)
            
            expected_signature = hmac.new(
                settings.CRYPTOBOT_API_TOKEN.encode(),
                data_string.encode(),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(signature, expected_signature)
            
        except Exception as e:
            self.logger.error(f"Failed to verify CryptoBot signature: {e}")
            return False
    
    async def _process_cryptobot_refund(self, payment: Payment) -> bool:
        """Обработать возврат через CryptoBot"""
        try:
            # CryptoBot API не поддерживает автоматические возвраты
            # Логируем для ручной обработки
            self.logger.warning(f"Manual refund required for CryptoBot payment {payment.id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to process CryptoBot refund: {e}")
            return False
    
    async def get_payment_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Получить аналитику платежей"""
        try:
            if not start_date:
                start_date = datetime.now(timezone.utc) - timedelta(days=30)
            if not end_date:
                end_date = datetime.now(timezone.utc)
            
            async with get_session() as session:
                # Общие метрики
                payments_query = select(Payment).where(
                    and_(
                        Payment.created_at >= start_date,
                        Payment.created_at <= end_date
                    )
                )
                payments_result = await session.execute(payments_query)
                payments = payments_result.scalars().all()
                
                total_payments = len(payments)
                successful_payments = len([p for p in payments if p.status == PaymentStatus.COMPLETED])
                
                total_revenue = sum(
                    float(p.amount) for p in payments 
                    if p.status == PaymentStatus.COMPLETED and p.currency in ['USD', 'USDT']
                )
                
                # Группировка по провайдерам
                provider_stats = {}
                for payment in payments:
                    provider = payment.provider.value
                    if provider not in provider_stats:
                        provider_stats[provider] = {
                            "count": 0,
                            "successful": 0,
                            "revenue": 0
                        }
                    
                    provider_stats[provider]["count"] += 1
                    if payment.status == PaymentStatus.COMPLETED:
                        provider_stats[provider]["successful"] += 1
                        if payment.currency in ['USD', 'USDT']:
                            provider_stats[provider]["revenue"] += float(payment.amount)
                
                # Группировка по планам
                plan_stats = {}
                for payment in payments:
                    if payment.status == PaymentStatus.COMPLETED:
                        plan = payment.plan_type
                        if plan not in plan_stats:
                            plan_stats[plan] = 0
                        plan_stats[plan] += 1
                
                conversion_rate = (successful_payments / total_payments * 100) if total_payments > 0 else 0
                
                return {
                    "period": {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat()
                    },
                    "total_payments": total_payments,
                    "successful_payments": successful_payments,
                    "conversion_rate": round(conversion_rate, 2),
                    "total_revenue_usd": round(total_revenue, 2),
                    "average_payment_usd": round(total_revenue / successful_payments, 2) if successful_payments > 0 else 0,
                    "provider_stats": provider_stats,
                    "plan_popularity": plan_stats
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get payment analytics: {e}")
            return {}


# Создаем глобальный экземпляр сервиса
payment_service = PaymentService()