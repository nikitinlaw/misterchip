from datetime import timedelta
from decimal import Decimal
from io import StringIO
from smtplib import SMTPException
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product, ProductType
from .models import Inquiry, Notification, Offer, SellerProfile, Shop
from .notifications import dispatch_notification


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PUBLIC_SITE_URL="https://misterchip.example.test",
)
class InquiryNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(username="mail-seller", email="seller@example.test")
        cls.buyer = user_model.objects.create_user(username="mail-buyer", email="buyer@example.test")
        seller = SellerProfile.objects.create(
            user=cls.owner, legal_name="Тестовый продавец", legal_type="ip",
            inn="100000000000", status="verified",
        )
        cls.shop = Shop.objects.create(seller=seller, name="Тестовый магазин", slug="mail-shop", city="Москва", status="published")
        category = Category.objects.create(name="Тест email", slug="test-mail")
        product_type = ProductType.objects.create(category=category, name="Модуль", slug="module")
        product = Product.objects.create(product_type=product_type, title="Тестовая модель", slug="mail-product", status="published")
        cls.offer = Offer.objects.create(
            shop=cls.shop, product=product, price=Decimal("120.50"), fulfilment="Самовывоз",
            last_confirmed_at=timezone.now(), valid_until=timezone.now() + timedelta(days=3), status="published",
        )
        cls.inquiry = Inquiry.objects.create(
            buyer=cls.buyer, shop=cls.shop, offer=cls.offer, email=cls.buyer.email,
            message="Нужны две штуки", consent_at=timezone.now(),
            consent_version="test-v1", consent_text="Передать контакт выбранному магазину",
            offer_snapshot={"product_title": product.title, "shop_name": cls.shop.name},
        )

    def notification(self, kind="buyer_confirmation", **kwargs):
        return Notification.objects.create(
            inquiry=self.inquiry, kind=kind, event_key=f"test:{kind}",
            recipient=self.buyer.email, **kwargs,
        )

    def test_smtp_error_keeps_record_without_logging_contact_or_exception(self):
        notice = self.notification()
        with patch("market.notifications.EmailMessage.send", side_effect=SMTPException("credential-and-contact-secret")):
            with self.assertLogs("market.notifications", level="WARNING") as logs:
                self.assertFalse(dispatch_notification(notice.pk))
        notice.refresh_from_db()
        self.assertEqual(notice.status, "pending")
        self.assertEqual(notice.attempts, 1)
        self.assertEqual(notice.error_code, "delivery_failed")
        self.assertIsNone(notice.sent_at)
        self.assertTrue(Inquiry.objects.filter(pk=self.inquiry.pk).exists())
        self.assertNotIn("credential-and-contact-secret", " ".join(logs.output))
        self.assertNotIn(self.buyer.email, " ".join(logs.output))

    def test_retry_delivers_once_and_command_output_is_private(self):
        notice = self.notification(last_attempt_at=timezone.now() - timedelta(minutes=2), attempts=1)
        output = StringIO()
        call_command("send_market_notifications", stdout=output)
        notice.refresh_from_db()
        self.assertEqual(notice.status, "sent")
        self.assertEqual(notice.attempts, 2)
        self.assertIsNotNone(notice.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(dispatch_notification(notice.pk))
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(self.buyer.email, output.getvalue())
        self.assertNotIn(self.inquiry.message, output.getvalue())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend")
    def test_file_backend_is_not_reported_as_delivered(self):
        notice = self.notification()
        with patch("market.notifications.EmailMessage.send") as send:
            self.assertFalse(dispatch_notification(notice.pk))
        send.assert_not_called()
        notice.refresh_from_db()
        self.assertEqual(notice.status, "pending")
        self.assertEqual(notice.error_code, "email_backend_not_ready")

    def test_reply_uses_immutable_payload_and_canonical_https_link(self):
        notice = self.notification("buyer_reply", payload={"reply_text": "Первая версия ответа"})
        self.inquiry.reply_text = "Следующий ответ"
        self.inquiry.save(update_fields=["reply_text"])
        self.assertTrue(dispatch_notification(notice.pk))
        self.assertIn("Первая версия ответа", mail.outbox[0].body)
        self.assertNotIn("Следующий ответ", mail.outbox[0].body)
        self.assertIn("https://misterchip.example.test" + reverse("market_inquiry_detail", kwargs={"public_id": self.inquiry.public_id}), mail.outbox[0].body)

    def test_anonymous_confirmation_does_not_expose_private_body_or_access_link(self):
        self.inquiry.buyer = None
        self.inquiry.save(update_fields=["buyer"])
        notice = self.notification()
        self.assertTrue(dispatch_notification(notice.pk))
        self.assertIn(str(self.inquiry.public_id), mail.outbox[0].body)
        self.assertNotIn(self.inquiry.message, mail.outbox[0].body)
        self.assertNotIn(reverse("market_inquiry_detail", kwargs={"public_id": self.inquiry.public_id}), mail.outbox[0].body)

    def test_recent_failed_attempt_waits_before_retry(self):
        notice = self.notification(last_attempt_at=timezone.now())
        call_command("send_market_notifications", stdout=StringIO())
        notice.refresh_from_db()
        self.assertEqual(notice.status, "pending")
        self.assertEqual(notice.attempts, 0)
