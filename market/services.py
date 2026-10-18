"""Validated transactional workflows and private outbox for the first Market."""
import logging
import uuid
from functools import partial

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import UserRole
from .models import Inquiry, MarketEvent, Notification, Offer, SellerProfile, Shop, ShopMembership
from .permissions import (
    can_manage_inquiries, can_manage_memberships, can_manage_offers, can_manage_shop,
    can_moderate, inquiries_for_user, shops_for_user,
)

logger = logging.getLogger(__name__)

INQUIRY_CONSENT_VERSION = "market-inquiry-v1"
INQUIRY_CONSENT_TEXT = (
    "Я согласен на обработку указанных мной данных на MISTERCHIP и их передачу "
    "выбранному продавцу для ответа на это обращение."
)

SELLER_FIELDS = {"legal_name", "legal_type", "inn", "description"}
SHOP_FIELDS = {
    "name", "city", "address", "description", "public_email", "public_phone", "website", "opening_hours",
}
OFFER_FIELDS = {
    "product", "price", "stock_quantity", "availability", "condition", "condition_description",
    "seller_sku", "fulfilment", "lead_time", "comment", "external_url", "valid_until",
}
LIVE_OFFER_FIELDS = {"price", "stock_quantity", "availability", "valid_until"}


def _require(condition):
    if not condition:
        raise PermissionDenied("Нет доступа к этому действию.")


def _require_user(actor):
    _require(actor and actor.is_authenticated and actor.is_active)


def _assign(obj, data, allowed):
    """Security fields are never copied from caller-controlled dictionaries."""
    changed = []
    for key in allowed:
        if key in data:
            value = data[key].strip() if isinstance(data[key], str) else data[key]
            if getattr(obj, key, None) != value:
                changed.append(key)
                setattr(obj, key, value)
    return changed


def _event(action, actor=None, seller=None, shop=None, offer=None, inquiry=None, changes=None):
    return MarketEvent.objects.create(
        actor=actor if actor and actor.is_authenticated else None,
        seller=seller, shop=shop, offer=offer, inquiry=inquiry,
        action=action, changes=changes or {},
    )


def _future(value):
    if value is not None:
        if timezone.is_naive(value):
            raise ValidationError({"valid_until": "Укажите дату с часовым поясом."})
        if value <= timezone.now():
            raise ValidationError({"valid_until": "Новая дата актуальности должна быть в будущем."})


def _locked_shop(shop_id):
    # Lock only this shop, not every joined seller/user. All child writes take
    # the shop lock first, including membership changes that revoke permission.
    return Shop.objects.select_for_update(of=("self",)).select_related("seller__user").get(pk=shop_id)


def _locked_offer(offer):
    shop_id = Offer.objects.values_list("shop_id", flat=True).get(pk=offer.pk)
    _locked_shop(shop_id)
    return Offer.objects.select_for_update(of=("self",)).select_related(
        "shop__seller__user", "product",
    ).get(pk=offer.pk)


def _locked_inquiry(inquiry):
    shop_id = Inquiry.objects.values_list("shop_id", flat=True).get(pk=inquiry.pk)
    _locked_shop(shop_id)
    return Inquiry.objects.select_for_update(of=("self",)).select_related(
        "shop__seller__user",
    ).get(pk=inquiry.pk)


def _dispatch_safely(notification_id):
    try:
        from .notifications import dispatch_notification
        dispatch_notification(notification_id)
    except Exception:
        # The inquiry and outbox already committed. No exception text contains PII in logs.
        Notification.objects.filter(pk=notification_id, status=Notification.Status.PENDING).update(error_code="dispatch_error")
        logger.error("Notification dispatch failed; retained for retry", extra={"notification_id": notification_id})


def _enqueue(inquiry, kind, recipient, event_key, payload=None):
    notification, created = Notification.objects.get_or_create(
        event_key=event_key,
        defaults={"inquiry": inquiry, "kind": kind, "recipient": recipient, "payload": payload or {}},
    )
    if created:
        transaction.on_commit(partial(_dispatch_safely, notification.pk))
    return notification


@transaction.atomic
def save_seller_profile(*, actor, data):
    _require_user(actor)
    seller = SellerProfile.objects.select_for_update().filter(user=actor).first()
    created = seller is None
    if created:
        seller = SellerProfile(user=actor)
    changed = _assign(seller, data, SELLER_FIELDS)
    if not created and (
        {"legal_name", "legal_type", "inn"}.intersection(changed)
        or seller.status in (SellerProfile.Status.REJECTED, SellerProfile.Status.SUSPENDED)
    ):
        seller.status = SellerProfile.Status.PENDING
        seller.moderated_at = None
        seller.moderated_by = None
        seller.moderation_note = ""
    seller.save()
    UserRole.objects.get_or_create(user=actor, role=UserRole.Role.SELLER)
    _event("seller_created" if created else "seller_updated", actor=actor, seller=seller, changes={"fields": sorted(changed)})
    return seller


@transaction.atomic
def moderate_seller(*, actor, seller, status, note=""):
    _require(can_moderate(actor))
    if status not in (SellerProfile.Status.VERIFIED, SellerProfile.Status.REJECTED, SellerProfile.Status.SUSPENDED):
        raise ValidationError("Недопустимое решение проверки продавца.")
    seller = SellerProfile.objects.select_for_update().get(pk=seller.pk)
    before = seller.status
    seller.status = status
    seller.moderation_note = note.strip()
    seller.moderated_at = timezone.now()
    seller.moderated_by = actor
    seller.save()
    _event("seller_moderated", actor=actor, seller=seller, changes={"from": before, "to": status})
    return seller


@transaction.atomic
def save_shop(*, actor, data, shop=None):
    _require_user(actor)
    created = shop is None
    if created:
        seller = SellerProfile.objects.select_for_update().filter(user=actor).first()
        if seller is None:
            raise ValidationError("Сначала заполните сведения продавца.")
        shop = Shop(seller=seller)
    else:
        shop = _locked_shop(shop.pk)
        _require(can_manage_shop(actor, shop))
    changed = _assign(shop, data, SHOP_FIELDS)
    if not shop.slug:
        base = slugify(shop.name, allow_unicode=True)[:180] or "magazin"
        shop.slug = f"{base}-{uuid.uuid4().hex[:10]}"
    if changed and not created:
        shop.status = Shop.Status.PENDING if shop.status == Shop.Status.PUBLISHED else Shop.Status.DRAFT
        shop.moderated_at = None
        shop.moderated_by = None
    shop.save()
    _event("shop_created" if created else "shop_updated", actor=actor, shop=shop, changes={"fields": sorted(changed)})
    return shop


@transaction.atomic
def submit_shop(*, actor, shop):
    shop = _locked_shop(shop.pk)
    _require(can_manage_shop(actor, shop))
    if shop.status not in (Shop.Status.DRAFT, Shop.Status.REJECTED, Shop.Status.PAUSED):
        raise ValidationError("Магазин уже отправлен на проверку или опубликован.")
    if shop.seller.status != SellerProfile.Status.VERIFIED:
        raise ValidationError("Дождитесь подтверждения сведений продавца.")
    if not shop.owner.is_active:
        raise ValidationError("Учётная запись владельца магазина должна быть активна.")
    shop.status = Shop.Status.PENDING
    shop.moderation_note = ""
    shop.save()
    _event("shop_submitted", actor=actor, shop=shop)
    return shop


@transaction.atomic
def set_shop_status(*, actor, shop, status, note=""):
    shop = _locked_shop(shop.pk)
    moderator = can_moderate(actor)
    if status in (Shop.Status.PUBLISHED, Shop.Status.REJECTED):
        _require(moderator)
        if shop.status != Shop.Status.PENDING:
            raise ValidationError("Решение применяется к магазину на проверке.")
        if status == Shop.Status.PUBLISHED and (
            shop.seller.status != SellerProfile.Status.VERIFIED or not shop.owner.is_active
        ):
            raise ValidationError("Для публикации нужны проверенный продавец и активный владелец.")
    elif status in (Shop.Status.PAUSED, Shop.Status.ARCHIVED):
        _require(moderator or can_manage_shop(actor, shop))
    else:
        raise ValidationError("Недопустимый переход состояния магазина.")
    before = shop.status
    shop.status = status
    if moderator:
        shop.moderation_note = note.strip()
        shop.moderated_at = timezone.now()
        shop.moderated_by = actor
    shop.save()
    _event("shop_status", actor=actor, shop=shop, changes={"from": before, "to": status})
    return shop


@transaction.atomic
def save_membership(*, actor, shop, user, role, is_active=True):
    shop = _locked_shop(shop.pk)
    _require(can_manage_memberships(actor, shop))
    if user.pk == shop.owner_id:
        raise ValidationError({"user": "Права владельца не изменяются через сотрудников."})
    if is_active and not user.is_active:
        raise ValidationError({"user": "Сотрудник должен иметь активную учётную запись."})
    membership = ShopMembership.objects.select_for_update().filter(shop=shop, user=user).first()
    if membership is None:
        membership = ShopMembership(shop=shop, user=user)
    membership.role = role
    membership.is_active = is_active
    membership.save()
    _event("membership_updated", actor=actor, shop=shop, changes={"user_id": user.pk, "role": role, "active": is_active})
    return membership


@transaction.atomic
def save_offer(*, actor, data, shop, offer=None):
    shop = _locked_shop(shop.pk)
    _require(can_manage_offers(actor, shop))
    created = offer is None
    if created:
        offer = Offer(shop=shop)
        before = {}
    else:
        offer = Offer.objects.select_for_update(of=("self",)).select_related(
            "shop__seller__user", "product",
        ).filter(pk=offer.pk, shop=shop).first()
        _require(offer is not None)
        before = {"price": str(offer.price), "stock_quantity": offer.stock_quantity, "availability": offer.availability}
    changed = _assign(offer, data, OFFER_FIELDS)
    if offer.product_id is None or offer.product.status != "published":
        raise ValidationError({"product": "Выберите опубликованную модель каталога."})
    if "valid_until" in changed:
        _future(offer.valid_until)
    if changed and not created:
        if offer.status == Offer.Status.PUBLISHED:
            if set(changed) - LIVE_OFFER_FIELDS:
                offer.status = Offer.Status.PENDING
                offer.moderated_at = None
                offer.moderated_by = None
        else:
            offer.status = Offer.Status.DRAFT
            offer.moderated_at = None
            offer.moderated_by = None
    if set(changed) & LIVE_OFFER_FIELDS:
        offer.last_confirmed_at = timezone.now()
    offer.save()
    after = {"price": str(offer.price), "stock_quantity": offer.stock_quantity, "availability": offer.availability}
    _event("offer_created" if created else "offer_updated", actor=actor, shop=shop, offer=offer, changes={"fields": sorted(changed), "before": before, "after": after})
    return offer


@transaction.atomic
def submit_offer(*, actor, offer):
    offer = _locked_offer(offer)
    _require(can_manage_offers(actor, offer.shop))
    if offer.status not in (Offer.Status.DRAFT, Offer.Status.REJECTED, Offer.Status.PAUSED):
        raise ValidationError("Предложение уже отправлено на проверку или опубликовано.")
    if not offer.shop.is_public:
        raise ValidationError("Сначала опубликуйте проверенный магазин.")
    if offer.product.status != "published":
        raise ValidationError("Предложение можно публиковать только для опубликованной модели.")
    offer.status = Offer.Status.PENDING
    offer.moderation_note = ""
    offer.save()
    _event("offer_submitted", actor=actor, shop=offer.shop, offer=offer)
    return offer


@transaction.atomic
def set_offer_status(*, actor, offer, status, note=""):
    offer = _locked_offer(offer)
    moderator = can_moderate(actor)
    if status in (Offer.Status.PUBLISHED, Offer.Status.REJECTED):
        _require(moderator)
        if offer.status != Offer.Status.PENDING:
            raise ValidationError("Решение применяется к предложению на проверке.")
        if status == Offer.Status.PUBLISHED and (
            not offer.shop.is_public or offer.product.status != "published"
        ):
            raise ValidationError("Для публикации нужны опубликованные магазин и модель каталога.")
    elif status in (Offer.Status.PAUSED, Offer.Status.ARCHIVED):
        _require(moderator or can_manage_offers(actor, offer.shop))
    else:
        raise ValidationError("Недопустимый переход состояния предложения.")
    before = offer.status
    offer.status = status
    if moderator:
        offer.moderation_note = note.strip()
        offer.moderated_at = timezone.now()
        offer.moderated_by = actor
    offer.save()
    _event("offer_status", actor=actor, shop=offer.shop, offer=offer, changes={"from": before, "to": status})
    return offer


@transaction.atomic
def confirm_offer(*, actor, offer, valid_until):
    offer = _locked_offer(offer)
    _require(can_manage_offers(actor, offer.shop))
    if offer.status != Offer.Status.PUBLISHED:
        raise ValidationError("Подтверждение актуальности доступно опубликованному предложению.")
    if valid_until is None:
        raise ValidationError({"valid_until": "Укажите срок актуальности."})
    _future(valid_until)
    offer.valid_until = valid_until
    offer.last_confirmed_at = timezone.now()
    offer.save()
    _event("offer_confirmed", actor=actor, shop=offer.shop, offer=offer, changes={"valid_until": valid_until.isoformat()})
    return offer


def _snapshot(offer):
    return {
        "product_id": offer.product_id, "product_title": offer.product.title,
        "shop_id": offer.shop_id, "shop_name": offer.shop.name,
        "seller_name": offer.shop.seller.legal_name, "price": str(offer.price),
        "currency": offer.currency, "availability": offer.availability,
        "availability_label": offer.get_availability_display(),
        "stock_quantity": offer.stock_quantity,
        "condition": offer.condition, "condition_label": offer.get_condition_display(),
        "condition_description": offer.condition_description,
        "fulfilment": offer.fulfilment, "lead_time": offer.lead_time,
        "seller_sku": offer.seller_sku, "comment": offer.comment,
        "external_url": offer.external_url,
        "last_confirmed_at": offer.last_confirmed_at.isoformat() if offer.last_confirmed_at else None,
        "valid_until": offer.valid_until.isoformat() if offer.valid_until else None,
        "requires_confirmation": offer.requires_confirmation,
    }


def _same_submission(inquiry, offer, buyer, email, data):
    return (
        inquiry.offer_id == offer.pk and inquiry.buyer_id == (buyer.pk if buyer else None)
        and inquiry.email == email and inquiry.message == str(data.get("message", "")).strip()
    )


@transaction.atomic
def create_inquiry(*, offer, data, actor=None, consent=False, submission_key=None):
    if consent is not True:
        raise ValidationError({"consent": "Для отправки обращения нужно согласие на передачу данных продавцу."})
    buyer = None
    if actor and actor.is_authenticated:
        _require_user(actor)
        buyer = actor
    # Authenticated buyers cannot use this endpoint to send confirmations to somebody else.
    email = buyer.email if buyer else str(data.get("email", "")).strip()
    if submission_key:
        try:
            submission_key = uuid.UUID(str(submission_key))
        except (ValueError, AttributeError, TypeError):
            raise ValidationError("Повторите отправку через форму обращения.")
        prior = Inquiry.objects.filter(submission_key=submission_key).first()
        if prior:
            if not _same_submission(prior, offer, buyer, email, data):
                raise ValidationError("Повторите отправку через форму обращения.")
            return prior
    offer = _locked_offer(offer)
    if not offer.is_public:
        raise ValidationError("Это предложение сейчас недоступно для обращения.")
    inquiry = Inquiry(
        buyer=buyer, shop=offer.shop, offer=offer,
        name=str(data.get("name", "")).strip(), email=email,
        phone=str(data.get("phone", "")).strip(), message=str(data.get("message", "")).strip(),
        consent_at=timezone.now(), consent_version=INQUIRY_CONSENT_VERSION,
        consent_text=INQUIRY_CONSENT_TEXT, offer_snapshot=_snapshot(offer), submission_key=submission_key,
    )
    # A savepoint also handles concurrent repeats of the same form nonce.
    try:
        with transaction.atomic():
            inquiry.save()
    except (IntegrityError, ValidationError):
        prior = Inquiry.objects.filter(submission_key=submission_key).first() if submission_key else None
        if prior and _same_submission(prior, offer, buyer, email, data):
            return prior
        raise
    prefix = f"inquiry:{inquiry.pk}:created"
    _enqueue(inquiry, Notification.Kind.BUYER_CONFIRMATION, inquiry.email, f"{prefix}:buyer")
    _enqueue(inquiry, Notification.Kind.SELLER_NEW, offer.shop.owner.email, f"{prefix}:seller")
    _event("inquiry_created", actor=buyer, shop=offer.shop, offer=offer, inquiry=inquiry)
    return inquiry


INQUIRY_TRANSITIONS = {
    Inquiry.Status.NEW: {Inquiry.Status.VIEWED, Inquiry.Status.RESPONDED, Inquiry.Status.CLOSED, Inquiry.Status.CANCELLED},
    Inquiry.Status.VIEWED: {Inquiry.Status.RESPONDED, Inquiry.Status.CLOSED, Inquiry.Status.CANCELLED},
    Inquiry.Status.RESPONDED: {Inquiry.Status.CLOSED, Inquiry.Status.CANCELLED},
    Inquiry.Status.CLOSED: set(),
    Inquiry.Status.CANCELLED: set(),
}


@transaction.atomic
def set_inquiry_status(*, actor, inquiry, status):
    _require_user(actor)
    inquiry = _locked_inquiry(inquiry)
    own_cancel = inquiry.buyer_id == actor.pk and status == Inquiry.Status.CANCELLED
    _require(own_cancel or can_manage_inquiries(actor, inquiry.shop))
    if status == inquiry.status:
        return inquiry
    if status not in INQUIRY_TRANSITIONS[inquiry.status]:
        raise ValidationError("Этот переход состояния обращения недоступен.")
    before = inquiry.status
    inquiry.status = status
    inquiry.save()
    _event("inquiry_status", actor=actor, shop=inquiry.shop, inquiry=inquiry, changes={"from": before, "to": status})
    return inquiry


@transaction.atomic
def reply_to_inquiry(*, actor, inquiry, text):
    inquiry = _locked_inquiry(inquiry)
    _require(can_manage_inquiries(actor, inquiry.shop))
    if inquiry.status in (Inquiry.Status.CLOSED, Inquiry.Status.CANCELLED):
        raise ValidationError("Нельзя ответить на закрытое или отменённое обращение.")
    text = text.strip()
    if not text:
        raise ValidationError({"text": "Введите ответ покупателю."})
    inquiry.reply_text = text
    inquiry.replied_at = timezone.now()
    inquiry.reply_count += 1
    inquiry.status = Inquiry.Status.RESPONDED
    inquiry.save()
    _enqueue(
        inquiry, Notification.Kind.BUYER_REPLY, inquiry.email,
        f"inquiry:{inquiry.pk}:reply:{inquiry.reply_count}:buyer",
        {"reply_text": text, "reply_number": inquiry.reply_count},
    )
    _event("inquiry_replied", actor=actor, shop=inquiry.shop, inquiry=inquiry, changes={"reply_number": inquiry.reply_count})
    return inquiry
