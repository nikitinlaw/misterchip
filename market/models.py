"""Independent sellers share catalog models, never another shop's private data."""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator, URLValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ValidatedModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SellerProfile(ValidatedModel):
    class LegalType(models.TextChoices):
        IP = "ip", "Индивидуальный предприниматель"
        COMPANY = "company", "Юридическое лицо"

    class Status(models.TextChoices):
        PENDING = "pending", "На проверке"
        VERIFIED = "verified", "Проверен"
        REJECTED = "rejected", "Отклонён"
        SUSPENDED = "suspended", "Приостановлен"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="seller_profile",
    )
    legal_name = models.CharField("Наименование продавца", max_length=255)
    legal_type = models.CharField("Форма продавца", max_length=12, choices=LegalType.choices)
    inn = models.CharField(
        "ИНН", max_length=12,
        validators=[RegexValidator(r"\A(?:[0-9]{10}|[0-9]{12})\Z", "Укажите ИНН из 10 или 12 цифр.")],
    )
    description = models.TextField("О продавце", max_length=3000, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    moderation_note = models.TextField("Замечание проверки", max_length=2000, blank=True)
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="moderated_sellers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Продавец"
        verbose_name_plural = "Продавцы"
        ordering = ["legal_name", "pk"]

    def clean(self):
        self.inn = self.inn.strip()
        expected = 12 if self.legal_type == self.LegalType.IP else 10
        if self.legal_type in self.LegalType.values and self.inn and len(self.inn) != expected:
            raise ValidationError({"inn": f"Для выбранной формы продавца укажите {expected} цифр ИНН."})

    def __str__(self):
        return self.legal_name


class ShopQuerySet(models.QuerySet):
    def public(self):
        return self.filter(
            status="published", seller__status="verified", seller__user__is_active=True,
        )


class Shop(ValidatedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PENDING = "pending", "На проверке"
        PUBLISHED = "published", "Опубликован"
        PAUSED = "paused", "Приостановлен"
        REJECTED = "rejected", "Отклонён"
        ARCHIVED = "archived", "Архив"

    seller = models.ForeignKey(SellerProfile, on_delete=models.PROTECT, related_name="shops")
    name = models.CharField("Название магазина", max_length=180)
    slug = models.SlugField(max_length=200, unique=True, allow_unicode=True)
    city = models.CharField("Город", max_length=120)
    address = models.CharField("Адрес", max_length=400, blank=True)
    description = models.TextField("О магазине", max_length=4000, blank=True)
    public_email = models.EmailField("Публичный email магазина", blank=True)
    public_phone = models.CharField("Публичный телефон магазина", max_length=60, blank=True)
    website = models.URLField(
        "Сайт магазина", max_length=1000, blank=True,
        validators=[URLValidator(schemes=["http", "https"])],
    )
    opening_hours = models.CharField("Режим работы", max_length=250, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    moderation_note = models.TextField("Замечание проверки", max_length=2000, blank=True)
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="moderated_shops",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = ShopQuerySet.as_manager()

    class Meta:
        verbose_name = "Магазин"
        verbose_name_plural = "Магазины"
        ordering = ["name", "pk"]
        permissions = [("moderate_market", "Проверка продавцов магазинов и предложений")]
        indexes = [models.Index(fields=["seller", "status"], name="market_shop_seller_status")]

    @property
    def owner(self):
        return self.seller.user

    @property
    def owner_id(self):
        return self.seller.user_id

    @property
    def is_public(self):
        return (
            self.status == self.Status.PUBLISHED
            and self.seller.status == SellerProfile.Status.VERIFIED
            and self.owner.is_active
        )

    def __str__(self):
        return self.name


class ShopMembership(ValidatedModel):
    class Role(models.TextChoices):
        MANAGER = "manager", "Управляющий магазином"
        OFFERS = "offers", "Предложения"
        INQUIRIES = "inquiries", "Обращения покупателей"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shop_memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.OFFERS)
    is_active = models.BooleanField("Доступ действует", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Сотрудник магазина"
        verbose_name_plural = "Сотрудники магазинов"
        constraints = [models.UniqueConstraint(fields=["shop", "user"], name="market_unique_shop_user")]

    def clean(self):
        if self.shop_id and self.user_id == self.shop.owner_id:
            raise ValidationError({"user": "Владелец уже имеет все права магазина."})

    def __str__(self):
        return f"{self.shop}: {self.user}"


class OfferQuerySet(models.QuerySet):
    def public(self):
        return self.filter(
            status="published", shop__status="published", shop__seller__status="verified",
            shop__seller__user__is_active=True, product__status="published",
        )


class Offer(ValidatedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PENDING = "pending", "На проверке"
        PUBLISHED = "published", "Опубликовано"
        PAUSED = "paused", "Приостановлено"
        REJECTED = "rejected", "Отклонено"
        ARCHIVED = "archived", "Архив"

    class Availability(models.TextChoices):
        IN_STOCK = "in_stock", "В наличии"
        ON_ORDER = "on_order", "Под заказ"
        OUT_OF_STOCK = "out_of_stock", "Нет в наличии"

    class Condition(models.TextChoices):
        NEW = "new", "Новый"
        USED = "used", "Бывший в употреблении"
        REFURBISHED = "refurbished", "Восстановленный"

    shop = models.ForeignKey(Shop, on_delete=models.PROTECT, related_name="offers")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="offers")
    price = models.DecimalField("Цена в рублях", max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency = models.CharField(max_length=3, default="RUB", editable=False, choices=[("RUB", "Рубль")])
    stock_quantity = models.PositiveIntegerField("Количество", null=True, blank=True)
    availability = models.CharField(max_length=16, choices=Availability.choices, default=Availability.IN_STOCK)
    condition = models.CharField(max_length=16, choices=Condition.choices, default=Condition.NEW)
    condition_description = models.TextField("Описание состояния", max_length=1500, blank=True)
    seller_sku = models.CharField("Артикул продавца", max_length=100, blank=True)
    fulfilment = models.CharField("Способ получения", max_length=160)
    lead_time = models.CharField("Срок получения", max_length=160, blank=True)
    comment = models.TextField("Комментарий к предложению", max_length=2000, blank=True)
    external_url = models.URLField(
        "Внешнее предложение", max_length=1000, blank=True,
        validators=[URLValidator(schemes=["http", "https"])],
    )
    valid_until = models.DateTimeField("Сведения актуальны до", null=True, blank=True)
    last_confirmed_at = models.DateTimeField("Последнее подтверждение", null=True, blank=True)
    source = models.CharField(max_length=16, default="manual", editable=False, choices=[("manual", "Вручную")])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    moderation_note = models.TextField("Замечание проверки", max_length=2000, blank=True)
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="moderated_offers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = OfferQuerySet.as_manager()

    class Meta:
        verbose_name = "Предложение магазина"
        verbose_name_plural = "Предложения магазинов"
        ordering = ["price", "pk"]
        constraints = [
            models.CheckConstraint(condition=Q(price__gt=0), name="market_offer_price_positive"),
            models.CheckConstraint(condition=Q(stock_quantity__isnull=True) | Q(stock_quantity__gte=0), name="market_offer_stock_nonnegative"),
            models.UniqueConstraint(
                fields=["shop", "product", "condition", "seller_sku", "fulfilment"],
                condition=Q(status__in=["pending", "published", "paused"]),
                name="market_unique_active_offer",
                violation_error_message="Для этой модели и условий уже есть предложение магазина.",
            ),
        ]
        indexes = [models.Index(fields=["product", "status", "price"], name="market_offer_product_price")]

    @property
    def is_public(self):
        return self.status == self.Status.PUBLISHED and self.shop.is_public and self.product.status == "published"

    @property
    def requires_confirmation(self):
        return not self.last_confirmed_at or not self.valid_until or self.valid_until <= timezone.now()

    @property
    def is_current(self):
        return not self.requires_confirmation

    def clean(self):
        self.seller_sku = self.seller_sku.strip()
        self.fulfilment = self.fulfilment.strip()
        errors = {}
        if self.availability == self.Availability.IN_STOCK and self.stock_quantity == 0:
            errors["stock_quantity"] = "При нулевом количестве выберите «Нет в наличии» или «Под заказ»."
        if self.availability == self.Availability.OUT_OF_STOCK and self.stock_quantity:
            errors["stock_quantity"] = "Для отсутствующего товара количество должно быть нулём или неизвестно."
        if self.condition in (self.Condition.USED, self.Condition.REFURBISHED) and not self.condition_description.strip():
            errors["condition_description"] = "Опишите состояние товара."
        # A parent can become unpublished after this offer was approved. Public
        # queries hide it; publication services check current parent eligibility.
        # Keeping those transition checks out of clean lets sellers correct it.
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.product} — {self.shop}"


class Inquiry(ValidatedModel):
    class Status(models.TextChoices):
        NEW = "new", "Новое"
        VIEWED = "viewed", "Просмотрено"
        RESPONDED = "responded", "Отвечено"
        CLOSED = "closed", "Закрыто"
        CANCELLED = "cancelled", "Отменено"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="market_inquiries",
    )
    shop = models.ForeignKey(Shop, on_delete=models.PROTECT, related_name="inquiries")
    offer = models.ForeignKey(Offer, on_delete=models.PROTECT, related_name="inquiries")
    name = models.CharField("Имя", max_length=120, blank=True)
    email = models.EmailField("Email покупателя")
    phone = models.CharField("Телефон покупателя", max_length=60, blank=True)
    message = models.TextField("Обращение", max_length=5000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW, db_index=True)
    consent_at = models.DateTimeField()
    consent_version = models.CharField(max_length=60)
    consent_text = models.TextField(max_length=1500)
    offer_snapshot = models.JSONField(default=dict)
    reply_text = models.TextField("Последний ответ магазина", max_length=5000, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    reply_count = models.PositiveIntegerField(default=0)
    submission_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Обращение покупателя"
        verbose_name_plural = "Обращения покупателей"
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["shop", "status", "-created_at"], name="market_inquiry_shop_status")]

    def clean(self):
        if self.offer_id and self.shop_id and self.offer.shop_id != self.shop_id:
            raise ValidationError({"shop": "Обращение должно относиться к магазину выбранного предложения."})

    def __str__(self):
        # Identifiers only: display names and logs must not disclose buyer contacts.
        return f"Обращение {self.public_id}"


class Notification(ValidatedModel):
    class Kind(models.TextChoices):
        BUYER_CONFIRMATION = "buyer_confirmation", "Подтверждение покупателю"
        SELLER_NEW = "seller_new", "Новое обращение продавцу"
        BUYER_REPLY = "buyer_reply", "Ответ магазина покупателю"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает отправки"
        SENT = "sent", "Отправлено"

    inquiry = models.ForeignKey(Inquiry, on_delete=models.PROTECT, related_name="notifications")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    event_key = models.CharField(max_length=180, unique=True)
    recipient = models.EmailField()
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(
        max_length=80, blank=True,
        validators=[RegexValidator(r"\A[a-z0-9_]*\Z", "Используйте безопасный код ошибки.")],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Уведомление об обращении"
        verbose_name_plural = "Уведомления об обращениях"
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["status", "created_at"], name="market_notification_pending")]

    def __str__(self):
        return self.event_key


class MarketEvent(models.Model):
    """Private operational audit; never store buyer contacts or free text here."""
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    seller = models.ForeignKey(SellerProfile, on_delete=models.PROTECT, null=True, blank=True)
    shop = models.ForeignKey(Shop, on_delete=models.PROTECT, null=True, blank=True)
    offer = models.ForeignKey(Offer, on_delete=models.PROTECT, null=True, blank=True)
    inquiry = models.ForeignKey(Inquiry, on_delete=models.PROTECT, null=True, blank=True)
    action = models.CharField(max_length=80)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Событие Market"
        verbose_name_plural = "Журнал Market"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.action} #{self.pk}"
