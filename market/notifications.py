"""Persistent inquiry email delivery; a transport failure never loses an inquiry."""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Notification

log = logging.getLogger(__name__)
DELIVERY_BACKENDS = {
    "django.core.mail.backends.smtp.EmailBackend",
    "django.core.mail.backends.locmem.EmailBackend",  # Isolated automated tests.
}


def _url(name, inquiry):
    return settings.PUBLIC_SITE_URL.rstrip("/") + reverse(
        name, kwargs={"public_id": inquiry.public_id},
    )


def notification_message(notification):
    inquiry = notification.inquiry
    reference = str(inquiry.public_id)
    snapshot = inquiry.offer_snapshot or {}
    product = snapshot.get("product_title") or snapshot.get("title") or inquiry.offer.product.title
    shop = snapshot.get("shop_name") or inquiry.shop.name
    if notification.kind == "seller_new":
        subject = f"Новое обращение {reference} — MISTERCHIP"
        body = (
            f"В магазин «{shop}» поступило обращение по предложению «{product}».\n\n"
            f"Номер обращения: {reference}\n"
            "Текст, контакт покупателя и обработка обращения доступны в кабинете магазина:\n"
            f"{_url('market_seller_inquiry_detail', inquiry)}\n\n"
            "Для просмотра войдите в учётную запись с доступом к этому магазину."
        )
    elif notification.kind == "buyer_confirmation":
        subject = f"Ваше обращение {reference} принято — MISTERCHIP"
        body = (
            f"Обращение по предложению «{product}» сохранено в кабинете магазина «{shop}».\n\n"
            f"Номер обращения: {reference}\n"
            "Цену, наличие, доставку и порядок оплаты подтвердит продавец. "
            "Это обращение в магазин, оно не является подтверждением покупки.\n"
        )
        if inquiry.buyer_id:
            body += f"\nВаше обращение: {_url('market_inquiry_detail', inquiry)}\n"
        body += "\nЕсли вы не отправляли обращение, проигнорируйте письмо."
    elif notification.kind == "buyer_reply":
        subject = f"Ответ магазина по обращению {reference} — MISTERCHIP"
        payload = notification.payload or {}
        reply = payload.get("reply_text", payload.get("text", ""))
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("Missing immutable reply payload")
        body = f"Магазин «{shop}» ответил на обращение {reference}:\n\n{reply}\n"
        if inquiry.buyer_id:
            body += f"\nОткрыть обращение: {_url('market_inquiry_detail', inquiry)}\n"
        body += "\nОкончательные условия покупки согласовываются непосредственно с магазином."
    else:
        raise ValueError("Unsupported notification kind")
    return subject, body


def dispatch_notification(notification_id):
    """Serialize attempts per message; leave failed delivery pending for retry.

    SMTP can acknowledge a message just before a process crash. This outbox has
    at-least-once delivery semantics; event_key prevents duplicate enqueueing.
    File/console backends do not count as an email sent to the recipient.
    """
    with transaction.atomic():
        notification = Notification.objects.select_for_update(of=("self",)).select_related(
            "inquiry__shop", "inquiry__offer__product",
        ).get(pk=notification_id)
        if notification.status == "sent":
            return True
        notification.last_attempt_at = timezone.now()
        if settings.EMAIL_BACKEND not in DELIVERY_BACKENDS:
            notification.error_code = "email_backend_not_ready"
            notification.save(update_fields=["last_attempt_at", "error_code"])
            return False
        notification.attempts += 1
        try:
            subject, body = notification_message(notification)
            connection = get_connection(fail_silently=False, timeout=min(settings.EMAIL_TIMEOUT, 5))
            sent = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[notification.recipient],
                connection=connection,
                headers={"X-Misterchip-Notification": str(notification.pk)},
            ).send(fail_silently=False)
            if sent != 1:
                raise RuntimeError("Transport did not accept the message")
        except Exception:
            # No exception text, recipient, message or credentials in logs.
            notification.error_code = "delivery_failed"
            notification.save(update_fields=["attempts", "last_attempt_at", "error_code"])
            log.warning("Market notification %s remains pending", notification.pk)
            return False
        notification.status = "sent"
        notification.sent_at = timezone.now()
        notification.error_code = ""
        notification.save(update_fields=[
            "status", "sent_at", "attempts", "last_attempt_at", "error_code",
        ])
        return True


def retry_pending_notifications(*, limit=50):
    threshold = timezone.now() - timedelta(minutes=1)
    from django.db.models import Q
    ids = list(Notification.objects.filter(status="pending").filter(
        Q(last_attempt_at__isnull=True) | Q(last_attempt_at__lt=threshold),
    ).order_by("pk").values_list("pk", flat=True)[:limit])
    sent = 0
    for notification_id in ids:
        try:
            sent += bool(dispatch_notification(notification_id))
        except Notification.DoesNotExist:
            continue
    return len(ids), sent
