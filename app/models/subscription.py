"""
Модели для подписок и платежей
"""
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from enum import Enum
from decimal import Decimal

from sqlalchemy import String, Boolean, Integer, BigInteger, DateTime, Numeric, Enum as SQLEnum, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func, and_

from app.models.base import BaseModel, MetadataMixin
from app.models.user import SubscriptionType


class PaymentMethod(str, Enum):
    """Способ оплаты"""
    TELEGRAM_STARS = "telegram_stars"
    CRYPTOBOT_TON = "cryptobot_ton"
    CRYPTOBOT_BTC = "cryptobot_btc"
    CRYPTOBOT_USDT = "cryptobot_usdt"
    CRYPTOBOT_USDC = "cryptobot_usdc"
    CRYPTOBOT_ETH = "cryptobot_eth"
    PROMO_CODE = "promo_code"
    ADMIN_GRANT = "admin_grant"


class PaymentStatus(str, Enum):
    """Статус платежа"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class SubscriptionStatus(str, Enum):
    """Статус подписки"""
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PENDING = "pending"


class Subscription(BaseModel, MetadataMixin):
    """Модель подписки пользователя"""
    
    __tablename__ = "subscriptions"
    
    # Пользователь
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        index=True,
        comment="ID пользователя"
    )
    
    # Тип и статус подписки
    subscription_type: Mapped[SubscriptionType] = mapped_column(
        SQLEnum(SubscriptionType),
        comment="Тип подписки"
    )
    
    status: Mapped[SubscriptionStatus] = mapped_column(
        SQLEnum(SubscriptionStatus),
        default=SubscriptionStatus.PENDING,
        comment="Статус подписки"
    )
    
    # Временные рамки
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        comment="Дата начала подписки"
    )
    
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        comment="Дата окончания подписки"
    )
    
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата отмены подписки"
    )
    
    # Автопродление
    auto_renew: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Автоматическое продление"
    )
    
    # Связанный платеж
    payment_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        comment="ID связанного платежа"
    )
    
    # Промокод (если использовался)
    promo_code: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Использованный промокод"
    )
    
    # Связи
    user = relationship("User", back_populates="subscriptions", lazy="selectin")
    payment = relationship("Payment", back_populates="subscription", lazy="selectin")
    
    # Индексы
    __table_args__ = (
        Index("idx_subscription_user_status", "user_id", "status"),
        Index("idx_subscription_expires", "expires_at"),
        Index("idx_subscription_auto_renew", "auto_renew", "expires_at"),
    )
    
    def __repr__(self) -> str:
        return f"<Subscription(user_id={self.user_id}, type={self.subscription_type}, status={self.status})>"
    
    @property
    def is_active(self) -> bool:
        """Проверка активности подписки"""
        now = datetime.now(timezone.utc)
        return (
            self.status == SubscriptionStatus.ACTIVE and
            self.starts_at <= now <= self.expires_at
        )
    
    @property
    def is_expired(self) -> bool:
        """Проверка истечения подписки"""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def days_left(self) -> int:
        """Количество дней до истечения"""
        if self.is_expired:
            return 0
        
        delta = self.expires_at - datetime.now(timezone.utc)
        return max(0, delta.days)
    
    @property
    def duration_days(self) -> int:
        """Длительность подписки в днях"""
        delta = self.expires_at - self.starts_at
        return delta.days
    
    async def activate(self, session: AsyncSession) -> None:
        """Активация подписки"""
        self.status = SubscriptionStatus.ACTIVE
        
        # Обновляем пользователя
        from app.models.user import User
        user = await User.get_by_telegram_id(session, self.user_id)
        if user:
            await user.set_premium(session, self.subscription_type, self.expires_at)
        
        await session.flush()
    
    async def cancel(self, session: AsyncSession, reason: str = None) -> None:
        """Отмена подписки"""
        self.status = SubscriptionStatus.CANCELLED
        self.cancelled_at = datetime.now(timezone.utc)
        self.auto_renew = False
        
        if reason:
            self.set_metadata("cancellation_reason", reason)
        
        await session.flush()
    
    async def extend(self, session: AsyncSession, days: int) -> None:
        """Продление подписки"""
        self.expires_at += timedelta(days=days)
        
        # Обновляем пользователя
        from app.models.user import User
        user = await User.get_by_telegram_id(session, self.user_id)
        if user:
            await user.set_premium(session, self.subscription_type, self.expires_at)
        
        await session.flush()
    
    @classmethod
    async def get_active_subscription(
        cls,
        session: AsyncSession,
        user_id: int
    ) -> Optional["Subscription"]:
        """Получение активной подписки пользователя"""
        now = datetime.now(timezone.utc)
        
        result = await session.execute(
            select(cls).where(
                cls.user_id == user_id,
                cls.status == SubscriptionStatus.ACTIVE,
                cls.starts_at <= now,
                cls.expires_at > now
            ).order_by(cls.expires_at.desc())
        )
        
        return result.scalar_one_or_none()
    
    @classmethod
    async def get_expiring_subscriptions(
        cls,
        session: AsyncSession,
        days: int = 3
    ) -> list["Subscription"]:
        """Получение подписок, истекающих в ближайшие N дней"""
        now = datetime.now(timezone.utc)
        future = now + timedelta(days=days)
        
        result = await session.execute(
            select(cls).where(
                cls.status == SubscriptionStatus.ACTIVE,
                cls.expires_at.between(now, future),
                cls.auto_renew == False
            )
        )
        
        return list(result.scalars().all())
    
    @classmethod
    async def create_subscription(
        cls,
        session: AsyncSession,
        user_id: int,
        subscription_type: SubscriptionType,
        payment_method: PaymentMethod,
        duration_days: int,
        promo_code: Optional[str] = None
    ) -> "Subscription":
        """Создание новой подписки"""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=duration_days)
        
        subscription = cls(
            user_id=user_id,
            subscription_type=subscription_type,
            starts_at=now,
            expires_at=expires_at,
            promo_code=promo_code
        )
        
        # Если это промокод или админ, сразу активируем
        if payment_method in [PaymentMethod.PROMO_CODE, PaymentMethod.ADMIN_GRANT]:
            subscription.status = SubscriptionStatus.ACTIVE
        
        session.add(subscription)
        await session.flush()
        
        return subscription


class Payment(BaseModel, MetadataMixin):
    """Модель платежа"""
    
    __tablename__ = "payments"
    
    # Пользователь
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        index=True,
        comment="ID пользователя"
    )
    
    # Основная информация о платеже
    external_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        comment="Внешний ID платежа (от платежной системы)"
    )
    
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SQLEnum(PaymentMethod),
        comment="Способ оплаты"
    )
    
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus),
        default=PaymentStatus.PENDING,
        comment="Статус платежа"
    )
    
    # Суммы
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        comment="Сумма платежа"
    )
    
    currency: Mapped[str] = mapped_column(
        String(10),
        comment="Валюта платежа"
    )
    
    amount_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Сумма в USD для аналитики"
    )
    
    # Комиссии
    fee_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Размер комиссии"
    )
    
    net_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Сумма к зачислению (за вычетом комиссий)"
    )
    
    # Что покупается
    product_type: Mapped[str] = mapped_column(
        String(50),
        default="subscription",
        comment="Тип продукта (subscription, one_time, etc.)"
    )
    
    product_id: Mapped[str] = mapped_column(
        String(100),
        comment="ID продукта"
    )
    
    # Временные метки
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Время завершения платежа"
    )
    
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Время истечения платежной ссылки"
    )
    
    # Связи
    user = relationship("User", lazy="selectin")
    subscription = relationship("Subscription", back_populates="payment", lazy="selectin")
    
    # Индексы
    __table_args__ = (
        Index("idx_payment_user_status", "user_id", "status"),
        Index("idx_payment_external_id", "external_id"),
        Index("idx_payment_method", "payment_method"),
        Index("idx_payment_created", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<Payment(user_id={self.user_id}, amount={self.amount}, status={self.status})>"
    
    @property
    def is_expired(self) -> bool:
        """Проверка истечения платежной ссылки"""
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at
    
    async def mark_as_paid(
        self,
        session: AsyncSession,
        external_id: str = None,
        paid_at: datetime = None
    ) -> None:
        """Отметка платежа как оплаченного"""
        self.status = PaymentStatus.COMPLETED
        self.paid_at = paid_at or datetime.now(timezone.utc)
        
        if external_id:
            self.external_id = external_id
        
        await session.flush()
    
    async def mark_as_failed(
        self,
        session: AsyncSession,
        reason: str = None
    ) -> None:
        """Отметка платежа как неуспешного"""
        self.status = PaymentStatus.FAILED
        
        if reason:
            self.set_metadata("failure_reason", reason)
        
        await session.flush()
    
    async def refund(
        self,
        session: AsyncSession,
        refund_amount: Optional[Decimal] = None,
        reason: str = None
    ) -> None:
        """Возврат платежа"""
        self.status = PaymentStatus.REFUNDED
        
        if refund_amount:
            self.set_metadata("refund_amount", str(refund_amount))
        
        if reason:
            self.set_metadata("refund_reason", reason)
        
        await session.flush()
    
    @classmethod
    async def create_payment(
        cls,
        session: AsyncSession,
        user_id: int,
        amount: Decimal,
        currency: str,
        payment_method: PaymentMethod,
        product_type: str,
        product_id: str,
        expires_minutes: int = 30
    ) -> "Payment":
        """Создание нового платежа"""
        payment = cls(
            user_id=user_id,
            amount=amount,
            currency=currency,
            payment_method=payment_method,
            product_type=product_type,
            product_id=product_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
        )
        
        session.add(payment)
        await session.flush()
        
        return payment
    
    @classmethod
    async def get_by_external_id(
        cls,
        session: AsyncSession,
        external_id: str
    ) -> Optional["Payment"]:
        """Получение платежа по внешнему ID"""
        result = await session.execute(
            select(cls).where(cls.external_id == external_id)
        )
        return result.scalar_one_or_none()
    
    @classmethod
    async def get_user_payments(
        cls,
        session: AsyncSession,
        user_id: int,
        limit: int = 50
    ) -> list["Payment"]:
        """Получение платежей пользователя"""
        result = await session.execute(
            select(cls).where(
                cls.user_id == user_id
            ).order_by(
                cls.created_at.desc()
            ).limit(limit)
        )
        
        return list(result.scalars().all())
    
    @classmethod
    async def get_revenue_stats(
        cls,
        session: AsyncSession,
        days: int = 30
    ) -> Dict[str, Any]:
        """Получение статистики доходов"""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Общий доход
        revenue_result = await session.execute(
            select(func.sum(cls.amount)).where(
                cls.status == PaymentStatus.COMPLETED,
                cls.created_at >= since
            )
        )
        total_revenue = revenue_result.scalar() or 0
        
        # Количество успешных платежей
        count_result = await session.execute(
            select(func.count(cls.id)).where(
                cls.status == PaymentStatus.COMPLETED,
                cls.created_at >= since
            )
        )
        successful_payments = count_result.scalar()
        
        # Доходы по методам оплаты
        method_stats = {}
        for method in PaymentMethod:
            method_result = await session.execute(
                select(
                    func.sum(cls.amount),
                    func.count(cls.id)
                ).where(
                    cls.payment_method == method,
                    cls.status == PaymentStatus.COMPLETED,
                    cls.created_at >= since
                )
            )
            method_data = method_result.first()
            method_stats[method.value] = {
                'revenue': method_data[0] or 0,
                'count': method_data[1] or 0
            }
        
        return {
            'total_revenue': float(total_revenue),
            'successful_payments': successful_payments,
            'avg_payment': float(total_revenue / successful_payments) if successful_payments > 0 else 0,
            'method_distribution': method_stats
        }


class PromoCode(BaseModel, MetadataMixin):
    """Модель промокода"""
    
    __tablename__ = "promo_codes"
    
    # Код
    code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        comment="Промокод"
    )
    
    # Описание
    description: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Описание промокода"
    )
    
    # Тип скидки
    discount_type: Mapped[str] = mapped_column(
        String(20),
        default="percentage",  # percentage, fixed, free
        comment="Тип скидки"
    )
    
    discount_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        comment="Размер скидки"
    )
    
    # Ограничения использования
    usage_limit: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Лимит использований (null = без лимита)"
    )
    
    usage_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="Количество использований"
    )
    
    # Временные ограничения
    valid_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Действителен с"
    )
    
    valid_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Действителен до"
    )
    
    # Ограничения по пользователям
    user_limit: Mapped[int] = mapped_column(
        Integer,
        default=1,
        comment="Сколько раз один пользователь может использовать"
    )
    
    # Статус
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        comment="Активен ли промокод"
    )
    
    # Создатель
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        comment="ID админа, создавшего промокод"
    )
    
    # Индексы
    __table_args__ = (
        Index("idx_promo_code_active", "is_active"),
        Index("idx_promo_code_valid", "valid_from", "valid_until"),
    )
    
    def __repr__(self) -> str:
        return f"<PromoCode(code='{self.code}', discount={self.discount_value})>"
    
    @property
    def is_valid(self) -> bool:
        """Проверка валидности промокода"""
        now = datetime.now(timezone.utc)
        
        # Проверка активности
        if not self.is_active:
            return False
        
        # Проверка временных рамок
        if self.valid_from and now < self.valid_from:
            return False
        
        if self.valid_until and now > self.valid_until:
            return False
        
        # Проверка лимита использований
        if self.usage_limit and self.usage_count >= self.usage_limit:
            return False
        
        return True
    
    @property
    def uses_left(self) -> Optional[int]:
        """Количество оставшихся использований"""
        if not self.usage_limit:
            return None
        
        return max(0, self.usage_limit - self.usage_count)
    
    async def can_be_used_by(self, session: AsyncSession, user_id: int) -> bool:
        """Проверка возможности использования пользователем"""
        if not self.is_valid:
            return False
        
        # Проверяем количество использований пользователем
        usage_result = await session.execute(
            select(func.count(PromoCodeUsage.id)).where(
                PromoCodeUsage.promo_code_id == self.id,
                PromoCodeUsage.user_id == user_id
            )
        )
        user_usage_count = usage_result.scalar()
        
        return user_usage_count < self.user_limit
    
    async def use(self, session: AsyncSession, user_id: int) -> "PromoCodeUsage":
        """Использование промокода"""
        if not await self.can_be_used_by(session, user_id):
            raise ValueError("Промокод не может быть использован")
        
        # Увеличиваем счетчик
        self.usage_count += 1
        
        # Создаем запись об использовании
        usage = PromoCodeUsage(
            promo_code_id=self.id,
            user_id=user_id,
            discount_applied=self.discount_value
        )
        
        session.add(usage)
        await session.flush()
        
        return usage
    
    @classmethod
    async def get_by_code(
        cls,
        session: AsyncSession,
        code: str
    ) -> Optional["PromoCode"]:
        """Получение промокода по коду"""
        result = await session.execute(
            select(cls).where(cls.code == code.upper())
        )
        return result.scalar_one_or_none()
    
    @classmethod
    async def create_promo_code(
        cls,
        session: AsyncSession,
        code: str,
        discount_type: str,
        discount_value: Decimal,
        description: str = None,
        usage_limit: int = None,
        user_limit: int = 1,
        valid_days: int = None,
        created_by: int = None
    ) -> "PromoCode":
        """Создание промокода"""
        promo_code = cls(
            code=code.upper(),
            description=description,
            discount_type=discount_type,
            discount_value=discount_value,
            usage_limit=usage_limit,
            user_limit=user_limit,
            created_by=created_by
        )
        
        if valid_days:
            promo_code.valid_from = datetime.now(timezone.utc)
            promo_code.valid_until = promo_code.valid_from + timedelta(days=valid_days)
        
        session.add(promo_code)
        await session.flush()
        
        return promo_code


class PromoCodeUsage(BaseModel):
    """История использования промокодов"""
    
    __tablename__ = "promo_code_usage"
    
    # Связи
    promo_code_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("promo_codes.id", ondelete="CASCADE"),
        index=True,
        comment="ID промокода"
    )
    
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        index=True,
        comment="ID пользователя"
    )
    
    # Информация об использовании
    discount_applied: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        comment="Примененная скидка"
    )
    
    original_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Первоначальная сумма"
    )
    
    final_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Итоговая сумма после скидки"
    )
    
    # Связанный платеж/подписка
    payment_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        comment="ID связанного платежа"
    )
    
    subscription_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        comment="ID связанной подписки"
    )
    
    # Связи
    promo_code = relationship("PromoCode", lazy="selectin")
    user = relationship("User", lazy="selectin")
    payment = relationship("Payment", lazy="selectin")
    subscription = relationship("Subscription", lazy="selectin")
    
    # Индексы
    __table_args__ = (
        Index("idx_promo_usage_code_user", "promo_code_id", "user_id"),
        Index("idx_promo_usage_date", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<PromoCodeUsage(promo_code_id={self.promo_code_id}, user_id={self.user_id})>"


class Revenue(BaseModel):
    """Таблица для агрегации доходов (для быстрой аналитики)"""
    
    __tablename__ = "revenue"
    
    # Период
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        comment="Дата (день/месяц)"
    )
    
    period_type: Mapped[str] = mapped_column(
        String(10),
        default="daily",  # daily, monthly
        comment="Тип периода"
    )
    
    # Метрики
    total_revenue: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=0,
        comment="Общий доход"
    )
    
    payments_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Количество платежей"
    )
    
    new_subscribers: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Новые подписчики"
    )
    
    active_subscribers: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Активные подписчики на конец периода"
    )
    
    # Доходы по методам
    stars_revenue: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        default=0,
        comment="Доход через Telegram Stars"
    )
    
    crypto_revenue: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        default=0,
        comment="Доход через криптовалюты"
    )
    
    # Индексы
    __table_args__ = (
        Index("idx_revenue_date_type", "date", "period_type"),
    )
    
    @classmethod
    async def calculate_daily_revenue(
        cls,
        session: AsyncSession,
        date: datetime
    ) -> "Revenue":
        """Расчет дневной выручки"""
        start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=1)
        
        # Получаем данные о платежах за день
        payments_result = await session.execute(
            select(
                func.sum(Payment.amount).label('total_revenue'),
                func.count(Payment.id).label('payments_count'),
                func.sum(
                    func.case(
                        (Payment.payment_method == PaymentMethod.TELEGRAM_STARS, Payment.amount),
                        else_=0
                    )
                ).label('stars_revenue'),
                func.sum(
                    func.case(
                        (Payment.payment_method.in_([
                            PaymentMethod.CRYPTOBOT_TON,
                            PaymentMethod.CRYPTOBOT_BTC,
                            PaymentMethod.CRYPTOBOT_USDT,
                            PaymentMethod.CRYPTOBOT_USDC,
                            PaymentMethod.CRYPTOBOT_ETH
                        ]), Payment.amount),
                        else_=0
                    )
                ).label('crypto_revenue')
            ).where(
                Payment.status == PaymentStatus.COMPLETED,
                Payment.created_at >= start_date,
                Payment.created_at < end_date
            )
        )
        
        payment_data = payments_result.first()
        
        # Получаем данные о подписчиках
        new_subs_result = await session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.created_at >= start_date,
                Subscription.created_at < end_date,
                Subscription.status == SubscriptionStatus.ACTIVE
            )
        )
        new_subscribers = new_subs_result.scalar()
        
        active_subs_result = await session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at > end_date
            )
        )
        active_subscribers = active_subs_result.scalar()
        
        # Создаем или обновляем запись
        existing_result = await session.execute(
            select(cls).where(
                cls.date == start_date,
                cls.period_type == "daily"
            )
        )
        
        revenue_record = existing_result.scalar_one_or_none()
        
        if revenue_record:
            # Обновляем существующую запись
            revenue_record.total_revenue = payment_data.total_revenue or 0
            revenue_record.payments_count = payment_data.payments_count or 0
            revenue_record.new_subscribers = new_subscribers
            revenue_record.active_subscribers = active_subscribers
            revenue_record.stars_revenue = payment_data.stars_revenue or 0
            revenue_record.crypto_revenue = payment_data.crypto_revenue or 0
        else:
            # Создаем новую запись
            revenue_record = cls(
                date=start_date,
                period_type="daily",
                total_revenue=payment_data.total_revenue or 0,
                payments_count=payment_data.payments_count or 0,
                new_subscribers=new_subscribers,
                active_subscribers=active_subscribers,
                stars_revenue=payment_data.stars_revenue or 0,
                crypto_revenue=payment_data.crypto_revenue or 0
            )
            session.add(revenue_record)
        
        await session.flush()
        return revenue_record