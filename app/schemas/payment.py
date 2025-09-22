"""
Pydantic схемы для платежей и подписок
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, validator

from app.models.user import SubscriptionType
from app.models.subscription import PaymentMethod, PaymentStatus, SubscriptionStatus


class PaymentBase(BaseModel):
    """Базовая схема платежа"""
    amount: Decimal = Field(..., gt=0, description="Сумма платежа")
    currency: str = Field(..., min_length=3, max_length=10, description="Валюта")
    payment_method: PaymentMethod = Field(..., description="Способ оплаты")
    product_type: str = Field("subscription", description="Тип продукта")
    product_id: str = Field(..., description="ID продукта")


class PaymentCreate(PaymentBase):
    """Создание платежа"""
    user_id: int = Field(..., description="ID пользователя")
    expires_minutes: int = Field(30, ge=5, le=1440, description="Время жизни платежа в минутах")
    return_url: Optional[str] = Field(None, description="URL для возврата после оплаты")
    webhook_url: Optional[str] = Field(None, description="URL для уведомлений")


class PaymentResponse(PaymentBase):
    """Ответ с данными платежа"""
    id: str
    user_id: int
    external_id: Optional[str]
    status: PaymentStatus
    amount_usd: Optional[Decimal]
    fee_amount: Optional[Decimal]
    net_amount: Optional[Decimal]
    paid_at: Optional[datetime]
    expires_at: Optional[datetime]
    is_expired: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class PaymentLink(BaseModel):
    """Ссылка для оплаты"""
    payment_id: str
    payment_url: str
    qr_code_url: Optional[str] = None
    amount: Decimal
    currency: str
    expires_at: datetime
    instructions: Dict[str, Any] = Field(default_factory=dict)


class PaymentWebhook(BaseModel):
    """Webhook уведомление о платеже"""
    payment_id: str
    external_id: str
    status: PaymentStatus
    amount: Decimal
    currency: str
    paid_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None
    signature: Optional[str] = None


class PaymentConfirmation(BaseModel):
    """Подтверждение платежа"""
    payment_id: str
    transaction_id: str
    amount_paid: Decimal
    currency: str
    payment_proof: Optional[str] = None


class SubscriptionCreate(BaseModel):
    """Создание подписки"""
    user_id: int = Field(..., description="ID пользователя")
    subscription_type: SubscriptionType = Field(..., description="Тип подписки")
    payment_method: PaymentMethod = Field(..., description="Способ оплаты")
    duration_days: int = Field(..., gt=0, description="Длительность в днях")
    promo_code: Optional[str] = Field(None, description="Промокод")
    auto_renew: bool = Field(False, description="Автопродление")


class SubscriptionResponse(BaseModel):
    """Ответ с данными подписки"""
    id: str
    user_id: int
    subscription_type: SubscriptionType
    status: SubscriptionStatus
    starts_at: datetime
    expires_at: datetime
    cancelled_at: Optional[datetime]
    auto_renew: bool
    payment_id: Optional[str]
    promo_code: Optional[str]
    is_active: bool
    is_expired: bool
    days_left: int
    duration_days: int
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class SubscriptionUpdate(BaseModel):
    """Обновление подписки"""
    auto_renew: Optional[bool] = None
    expires_at: Optional[datetime] = None


class SubscriptionCancel(BaseModel):
    """Отмена подписки"""
    reason: Optional[str] = Field(None, max_length=500, description="Причина отмены")
    immediate: bool = Field(False, description="Немедленная отмена или в конце периода")


class PromoCodeCreate(BaseModel):
    """Создание промокода"""
    code: str = Field(..., min_length=3, max_length=50, description="Код")
    description: Optional[str] = Field(None, max_length=255, description="Описание")
    discount_type: str = Field("percentage", description="Тип скидки: percentage, fixed, free")
    discount_value: Decimal = Field(..., gt=0, description="Размер скидки")
    usage_limit: Optional[int] = Field(None, ge=1, description="Лимит использований")
    user_limit: int = Field(1, ge=1, description="Лимит на пользователя")
    valid_days: Optional[int] = Field(None, ge=1, description="Срок действия в днях")
    
    @validator('code')
    def validate_code(cls, v):
        return v.upper().strip()
    
    @validator('discount_type')
    def validate_discount_type(cls, v):
        allowed_types = ['percentage', 'fixed', 'free']
        if v not in allowed_types:
            raise ValueError(f'Discount type must be one of {allowed_types}')
        return v


class PromoCodeResponse(BaseModel):
    """Ответ с данными промокода"""
    id: str
    code: str
    description: Optional[str]
    discount_type: str
    discount_value: Decimal
    usage_limit: Optional[int]
    usage_count: int
    user_limit: int
    valid_from: Optional[datetime]
    valid_until: Optional[datetime]
    is_active: bool
    is_valid: bool
    uses_left: Optional[int]
    created_by: Optional[int]
    created_at: datetime
    
    class Config:
        from_attributes = True


class PromoCodeValidation(BaseModel):
    """Валидация промокода"""
    code: str = Field(..., description="Промокод для проверки")
    user_id: int = Field(..., description="ID пользователя")
    subscription_type: Optional[SubscriptionType] = None


class PromoCodeValidationResponse(BaseModel):
    """Результат валидации промокода"""
    is_valid: bool
    discount_value: Optional[Decimal] = None
    discount_type: Optional[str] = None
    error_message: Optional[str] = None
    original_price: Optional[Decimal] = None
    discounted_price: Optional[Decimal] = None


class RevenueStats(BaseModel):
    """Статистика доходов"""
    period: str = Field(..., description="Период статистики")
    total_revenue: Decimal
    successful_payments: int
    failed_payments: int
    success_rate: float
    avg_payment_amount: Decimal
    method_distribution: Dict[PaymentMethod, Dict[str, Any]]
    currency_distribution: Dict[str, Decimal]
    refunds_amount: Decimal
    net_revenue: Decimal


class PaymentAnalytics(BaseModel):
    """Аналитика платежей"""
    date_from: datetime
    date_to: datetime
    total_payments: int
    successful_payments: int
    failed_payments: int
    pending_payments: int
    total_amount: Decimal
    avg_amount: Decimal
    conversion_rate: float
    popular_methods: List[Dict[str, Any]]
    hourly_distribution: Dict[int, int]
    geographical_distribution: Dict[str, Any]


class SubscriptionAnalytics(BaseModel):
    """Аналитика подписок"""
    active_subscriptions: int
    new_subscriptions: int
    cancelled_subscriptions: int
    expired_subscriptions: int
    renewal_rate: float
    churn_rate: float
    avg_subscription_duration: float
    ltv: Decimal  # Lifetime Value
    mrr: Decimal  # Monthly Recurring Revenue
    arr: Decimal  # Annual Recurring Revenue
    subscription_distribution: Dict[SubscriptionType, int]


class PaymentRefund(BaseModel):
    """Возврат платежа"""
    payment_id: str
    refund_amount: Optional[Decimal] = Field(None, description="Сумма возврата (по умолчанию полная)")
    reason: str = Field(..., min_length=3, max_length=500, description="Причина возврата")
    notify_user: bool = Field(True, description="Уведомить пользователя")


class PaymentDispute(BaseModel):
    """Спор по платежу"""
    payment_id: str
    dispute_type: str = Field(..., description="Тип спора: chargeback, complaint, fraud")
    description: str = Field(..., max_length=2000)
    evidence: Optional[List[str]] = Field(None, description="Доказательства")
    amount_disputed: Optional[Decimal] = None


class BillingInfo(BaseModel):
    """Информация для выставления счета"""
    user_id: int
    full_name: Optional[str] = None
    email: Optional[str] = None
    company_name: Optional[str] = None
    tax_id: Optional[str] = None
    address: Optional[Dict[str, str]] = None
    billing_preferences: Dict[str, Any] = Field(default_factory=dict)


class Invoice(BaseModel):
    """Счет"""
    id: str
    user_id: int
    invoice_number: str
    amount: Decimal
    currency: str
    status: str
    issue_date: datetime
    due_date: datetime
    items: List[Dict[str, Any]]
    billing_info: Optional[BillingInfo] = None
    payment_id: Optional[str] = None


class PaymentMethod(BaseModel):
    """Способ оплаты пользователя"""
    id: str
    user_id: int
    method_type: str = Field(..., description="card, wallet, bank_account")
    provider: str = Field(..., description="Провайдер платежей")
    masked_info: str = Field(..., description="Замаскированная информация")
    is_default: bool = False
    expires_at: Optional[datetime] = None
    created_at: datetime


class PaymentSettings(BaseModel):
    """Настройки платежей"""
    user_id: int
    default_payment_method: Optional[str] = None
    auto_pay_enabled: bool = False
    payment_notifications: bool = True
    receipt_email: Optional[str] = None
    preferred_currency: str = "USD"
    billing_cycle_day: int = Field(1, ge=1, le=28)


class PricingPlan(BaseModel):
    """Тарифный план"""
    id: str
    name: str
    description: str
    subscription_type: SubscriptionType
    price_monthly: Decimal
    price_yearly: Optional[Decimal] = None
    features: List[str]
    limits: Dict[str, Any]
    is_popular: bool = False
    is_active: bool = True
    trial_days: int = 0


class PaymentIntent(BaseModel):
    """Намерение платежа"""
    user_id: int
    amount: Decimal
    currency: str
    description: str
    payment_methods: List[PaymentMethod]
    metadata: Optional[Dict[str, Any]] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class SubscriptionUpgrade(BaseModel):
    """Апгрейд подписки"""
    subscription_id: str
    new_subscription_type: SubscriptionType
    prorate: bool = True
    effective_date: Optional[datetime] = None


class SubscriptionDowngrade(BaseModel):
    """Даунгрейд подписки"""
    subscription_id: str
    new_subscription_type: SubscriptionType
    effective_date: Optional[datetime] = None
    reason: Optional[str] = None


class TaxCalculation(BaseModel):
    """Расчет налогов"""
    user_id: int
    amount: Decimal
    currency: str
    country_code: str
    tax_rate: float
    tax_amount: Decimal
    total_amount: Decimal
    tax_details: Dict[str, Any]


class PaymentReceipt(BaseModel):
    """Чек об оплате"""
    payment_id: str
    receipt_number: str
    amount: Decimal
    currency: str
    payment_method: str
    transaction_date: datetime
    items: List[Dict[str, Any]]
    tax_info: Optional[TaxCalculation] = None
    receipt_url: str