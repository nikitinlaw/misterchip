from datetime import timedelta
from decimal import Decimal
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product, ProductType
from .models import Inquiry, MarketEvent, Notification, Offer, SellerProfile, Shop, ShopMembership
from .permissions import (
    can_manage_inquiries, can_manage_memberships, can_manage_offers, can_manage_shop,
    can_moderate, inquiries_for_user, shops_for_user,
)
from .services import (
    INQUIRY_CONSENT_TEXT, INQUIRY_CONSENT_VERSION,
    confirm_offer, create_inquiry, moderate_seller, reply_to_inquiry, save_membership,
    save_offer, save_seller_profile, save_shop, set_inquiry_status, set_offer_status,
    set_shop_status, submit_offer, submit_shop,
)


class MarketServiceTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="owner", email="owner@example.test", password="pass")
        self.other = users.objects.create_user(username="other", email="other@example.test", password="pass")
        self.buyer = users.objects.create_user(username="buyer", email="buyer@example.test", password="pass")
        self.employee = users.objects.create_user(username="employee", email="employee@example.test", password="pass")
        self.moderator = users.objects.create_superuser(username="moderator", email="moderator@example.test", password="pass")
        self.kind = ProductType.objects.create(
            category=Category.objects.create(name="Компьютеры", slug="computers"), name="Память", slug="memory",
        )
        self.product = Product.objects.create(
            product_type=self.kind, title="Память Model A", slug="memory-model-a", status=Product.Status.PUBLISHED,
        )
        self.hidden_product = Product.objects.create(
            product_type=self.kind, title="Непроверенная модель", slug="hidden-model", status=Product.Status.DRAFT,
        )
        self.seller, self.shop = self.create_shop(self.owner, "Магазин А", "1234567890")
        self.other_seller, self.other_shop = self.create_shop(self.other, "Магазин Б", "1234567891")
        self.offer = self.create_offer(self.owner, self.shop)

    def create_shop(self, user, name, inn):
        seller = save_seller_profile(actor=user, data={
            "legal_name": name, "legal_type": "company", "inn": inn,
        })
        seller = moderate_seller(actor=self.moderator, seller=seller, status="verified")
        shop = save_shop(actor=user, data={"name": name, "city": "Москва", "public_email": "public@example.test"})
        shop = submit_shop(actor=user, shop=shop)
        shop = set_shop_status(actor=self.moderator, shop=shop, status="published")
        return seller, shop

    def offer_data(self, **values):
        return {
            "product": self.product, "price": Decimal("1499.90"), "stock_quantity": 3,
            "availability": "in_stock", "condition": "new", "fulfilment": "Самовывоз",
            "valid_until": timezone.now() + timedelta(days=2), **values,
        }

    def create_offer(self, user, shop, **values):
        offer = save_offer(actor=user, shop=shop, data=self.offer_data(**values))
        offer = submit_offer(actor=user, offer=offer)
        return set_offer_status(actor=self.moderator, offer=offer, status="published")

    def inquiry_data(self, **values):
        return {"name": "Покупатель", "email": "guest@example.test", "phone": "+7 000 000 00 00", "message": "Подтвердите наличие и способ получения.", **values}

    def create_request(self, **kwargs):
        return create_inquiry(offer=self.offer, data=self.inquiry_data(), consent=True, **kwargs)

    def test_happy_path_two_shops_share_product_without_owning_specification(self):
        second_offer = self.create_offer(self.other, self.other_shop, price=Decimal("1550.00"))
        self.assertEqual(Offer.objects.public().filter(product=self.product).count(), 2)
        self.assertEqual(self.offer.product_id, second_offer.product_id)
        self.assertTrue(self.offer.is_current)
        self.assertEqual(self.shop.owner, self.owner)
        self.assertEqual(self.owner.seller_profile, self.seller)

    def test_input_cannot_forge_profile_owner_or_verification(self):
        seller = save_seller_profile(actor=self.employee, data={
            "legal_name": "ИП Сотрудник", "legal_type": "ip", "inn": "123456789012",
            "user": self.owner, "status": "verified", "moderated_by": self.employee,
        })
        self.assertEqual(seller.user, self.employee)
        self.assertEqual(seller.status, SellerProfile.Status.PENDING)
        self.assertIsNone(seller.moderated_by)

    def test_private_owner_and_public_contact_are_separate(self):
        inquiry = self.create_request()
        seller_notice = inquiry.notifications.get(kind=Notification.Kind.SELLER_NEW)
        self.assertEqual(seller_notice.recipient, self.owner.email)
        self.assertNotEqual(seller_notice.recipient, self.shop.public_email)

    def test_seller_legal_changes_hide_public_shops_until_review(self):
        save_seller_profile(actor=self.owner, data={"legal_name": "Новое юридическое имя"})
        self.assertFalse(Shop.objects.public().filter(pk=self.shop.pk).exists())
        self.assertFalse(Offer.objects.public().filter(pk=self.offer.pk).exists())

    def test_rejected_seller_can_resubmit_without_becoming_verified(self):
        moderate_seller(actor=self.moderator, seller=self.seller, status="rejected", note="Уточните сведения")
        seller = save_seller_profile(actor=self.owner, data={"description": "Сведения дополнены"})
        self.assertEqual(seller.status, SellerProfile.Status.PENDING)
        self.assertIsNone(seller.moderated_by)
        self.assertEqual(seller.moderation_note, "")
        self.assertFalse(Shop.objects.public().filter(pk=self.shop.pk).exists())

    def test_hidden_parent_does_not_prevent_corrections_or_bypass_publication_check(self):
        save_seller_profile(actor=self.owner, data={"legal_name": "Новое юридическое имя"})
        offer = save_offer(actor=self.owner, shop=self.shop, offer=self.offer, data={"price": Decimal("1400.00")})
        self.assertEqual(offer.status, Offer.Status.PUBLISHED)
        self.assertFalse(Offer.objects.public().filter(pk=offer.pk).exists())
        shop = save_shop(actor=self.owner, shop=self.shop, data={"name": "Уточнённый магазин"})
        self.assertEqual(shop.status, Shop.Status.PENDING)
        with self.assertRaises(ValidationError):
            set_shop_status(actor=self.moderator, shop=shop, status="published")
        offer = save_offer(actor=self.owner, shop=shop, offer=offer, data={"comment": "Уточнение"})
        with self.assertRaises(ValidationError):
            set_offer_status(actor=self.moderator, offer=offer, status="published")

    def test_shop_update_requires_review_and_cannot_transfer_owner(self):
        shop = save_shop(actor=self.owner, shop=self.shop, data={
            "name": "Новое название", "seller": self.other_seller, "status": "published",
        })
        self.assertEqual(shop.seller_id, self.seller.pk)
        self.assertEqual(shop.status, Shop.Status.PENDING)
        self.assertFalse(Offer.objects.public().filter(shop=shop).exists())

    def test_ordinary_staff_and_seller_roles_do_not_grant_other_shop_access(self):
        self.employee.is_staff = True
        self.employee.save()
        self.assertFalse(can_moderate(self.employee))
        self.assertFalse(can_manage_offers(self.employee, self.shop))
        self.assertFalse(shops_for_user(self.employee).exists())
        with self.assertRaises(PermissionDenied):
            save_shop(actor=self.other, shop=self.shop, data={"name": "Чужое изменение"})
        with self.assertRaises(PermissionDenied):
            save_offer(actor=self.other, shop=self.shop, offer=self.offer, data={"price": Decimal("1")})
        with self.assertRaises(PermissionDenied):
            save_offer(actor=self.other, shop=self.other_shop, offer=self.offer, data={"price": Decimal("1")})

    def test_membership_scope_revocation_and_owner_protection(self):
        save_membership(actor=self.owner, shop=self.shop, user=self.employee, role="offers")
        self.assertTrue(can_manage_offers(self.employee, self.shop))
        self.assertFalse(can_manage_inquiries(self.employee, self.shop))
        self.assertFalse(can_manage_shop(self.employee, self.shop))
        self.assertFalse(can_manage_memberships(self.employee, self.shop))
        save_membership(actor=self.owner, shop=self.shop, user=self.employee, role="manager")
        self.assertTrue(can_manage_shop(self.employee, self.shop))
        self.assertTrue(can_manage_inquiries(self.employee, self.shop))
        with self.assertRaises(PermissionDenied):
            save_membership(actor=self.employee, shop=self.shop, user=self.buyer, role="manager")
        with self.assertRaises(ValidationError):
            save_membership(actor=self.owner, shop=self.shop, user=self.owner, role="offers")
        save_membership(actor=self.owner, shop=self.shop, user=self.employee, role="manager", is_active=False)
        self.assertFalse(can_manage_offers(self.employee, self.shop))
        self.assertFalse(shops_for_user(self.employee).exists())

    def test_explicit_moderation_permission_does_not_read_buyer_contacts(self):
        self.employee.user_permissions.add(Permission.objects.get(codename="moderate_market"))
        self.assertTrue(can_moderate(self.employee))
        self.assertFalse(can_manage_inquiries(self.employee, self.shop))
        inquiry = self.create_request()
        self.assertFalse(inquiries_for_user(self.employee).filter(pk=inquiry.pk).exists())

    def test_owner_can_revoke_membership_of_inactive_account(self):
        save_membership(actor=self.owner, shop=self.shop, user=self.employee, role="inquiries")
        self.employee.is_active = False
        self.employee.save()
        member = save_membership(actor=self.owner, shop=self.shop, user=self.employee, role="inquiries", is_active=False)
        self.assertFalse(member.is_active)
        with self.assertRaises(ValidationError):
            save_membership(actor=self.owner, shop=self.shop, user=self.employee, role="inquiries", is_active=True)

    def test_offer_creation_ignores_protected_fields_and_validates_public_product(self):
        offer = save_offer(actor=self.owner, shop=self.shop, data=self.offer_data(
            seller_sku="extra", status="published", shop=self.other_shop, source="api",
            last_confirmed_at=timezone.now() + timedelta(days=100),
        ))
        self.assertEqual(offer.status, Offer.Status.DRAFT)
        self.assertEqual(offer.shop_id, self.shop.pk)
        self.assertEqual(offer.source, "manual")
        self.assertLess(offer.last_confirmed_at, timezone.now())
        with self.assertRaises(ValidationError):
            save_offer(actor=self.owner, shop=self.shop, data=self.offer_data(product=self.hidden_product))

    def test_new_offer_cannot_be_published_by_owner_or_without_submission(self):
        offer = save_offer(actor=self.owner, shop=self.shop, data=self.offer_data(seller_sku="new"))
        with self.assertRaises(PermissionDenied):
            set_offer_status(actor=self.owner, offer=offer, status="published")
        with self.assertRaises(ValidationError):
            set_offer_status(actor=self.moderator, offer=offer, status="published")

    def test_live_price_update_is_audited_but_material_edit_requires_review(self):
        updated = save_offer(actor=self.owner, shop=self.shop, offer=self.offer, data={"price": Decimal("1350.00")})
        self.assertEqual(updated.status, Offer.Status.PUBLISHED)
        event = MarketEvent.objects.filter(offer=updated, action="offer_updated").first()
        self.assertEqual(event.changes["before"]["price"], "1499.90")
        self.assertEqual(event.changes["after"]["price"], "1350.00")
        # Mutating an instance before calling the service must not hide a difference.
        updated.comment = "Новое условие получения"
        updated = save_offer(actor=self.owner, shop=self.shop, offer=updated, data={"comment": updated.comment})
        self.assertEqual(updated.status, Offer.Status.PENDING)
        self.product.refresh_from_db()
        self.assertEqual(self.product.title, "Память Model A")

    def test_price_quantity_condition_and_url_validation(self):
        cases = [
            {"price": Decimal("0")}, {"price": Decimal("-1")},
            {"stock_quantity": -1}, {"stock_quantity": 0, "availability": "in_stock"},
            {"condition": "used", "condition_description": ""},
            {"external_url": "javascript:alert(1)"}, {"external_url": "ftp://example.com/file"},
        ]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                save_offer(actor=self.owner, shop=self.shop, data=self.offer_data(**values))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Offer.objects.filter(pk=self.offer.pk).update(price=Decimal("0"))

    def test_active_duplicate_blocked_but_independent_shop_allowed(self):
        duplicate = save_offer(actor=self.owner, shop=self.shop, data=self.offer_data())
        with self.assertRaises(ValidationError):
            submit_offer(actor=self.owner, offer=duplicate)
        other_offer = self.create_offer(self.other, self.other_shop)
        self.assertNotEqual(self.offer.pk, other_offer.pk)

    def test_expired_offer_remains_public_and_is_honestly_unconfirmed(self):
        Offer.objects.filter(pk=self.offer.pk).update(valid_until=timezone.now() - timedelta(hours=1))
        self.offer.refresh_from_db()
        self.assertTrue(self.offer.requires_confirmation)
        self.assertTrue(Offer.objects.public().filter(pk=self.offer.pk).exists())
        request = self.create_request()
        self.assertTrue(request.offer_snapshot["requires_confirmation"])
        confirmed = confirm_offer(actor=self.owner, offer=self.offer, valid_until=timezone.now() + timedelta(days=1))
        self.assertFalse(confirmed.requires_confirmation)
        with self.assertRaises(ValidationError):
            confirm_offer(actor=self.owner, offer=confirmed, valid_until=timezone.now() - timedelta(seconds=1))

    def test_anonymous_inquiry_consent_snapshot_and_two_private_notifications(self):
        inquiry = self.create_request(actor=AnonymousUser())
        self.assertIsNone(inquiry.buyer_id)
        self.assertEqual(inquiry.shop_id, self.shop.pk)
        self.assertEqual(inquiry.consent_version, INQUIRY_CONSENT_VERSION)
        self.assertEqual(inquiry.consent_text, INQUIRY_CONSENT_TEXT)
        self.assertEqual(inquiry.offer_snapshot["price"], "1499.90")
        self.assertEqual(inquiry.notifications.count(), 2)
        self.assertEqual(inquiry.notifications.filter(status="pending").count(), 2)
        self.assertNotIn(inquiry.email, str(inquiry))
        self.assertNotIn(inquiry.email, str(MarketEvent.objects.filter(inquiry=inquiry).first().changes))
        self.assertFalse(inquiries_for_user(AnonymousUser()).exists())

    def test_no_consent_invalid_email_or_hidden_offer_does_not_create_request(self):
        with self.assertRaises(ValidationError):
            create_inquiry(offer=self.offer, data=self.inquiry_data(), consent=False)
        with self.assertRaises(ValidationError):
            create_inquiry(offer=self.offer, data=self.inquiry_data(email="invalid"), consent=True)
        set_offer_status(actor=self.owner, offer=self.offer, status="paused")
        with self.assertRaises(ValidationError):
            self.create_request()
        self.assertFalse(Inquiry.objects.exists())
        self.assertFalse(Notification.objects.exists())

    def test_authenticated_buyer_email_is_not_overridden_by_input(self):
        inquiry = self.create_request(actor=self.buyer)
        self.assertEqual(inquiry.email, self.buyer.email)
        self.assertEqual(inquiry.buyer_id, self.buyer.pk)

    def test_nonce_repeat_is_idempotent_and_mismatched_repeat_denied(self):
        nonce = uuid.uuid4()
        first = self.create_request(submission_key=nonce)
        second = self.create_request(submission_key=nonce)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Inquiry.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), 2)
        with self.assertRaises(ValidationError):
            create_inquiry(offer=self.offer, data=self.inquiry_data(email="different@example.test"), consent=True, submission_key=nonce)

    def test_dispatch_error_retains_request_and_retryable_outbox_without_private_error(self):
        with patch("market.notifications.dispatch_notification", side_effect=RuntimeError("SECRET password buyer@example.test")):
            with self.captureOnCommitCallbacks(execute=True):
                inquiry = self.create_request()
        self.assertTrue(Inquiry.objects.filter(pk=inquiry.pk).exists())
        self.assertEqual(Notification.objects.filter(status="pending", error_code="dispatch_error").count(), 2)
        self.assertFalse(Notification.objects.filter(error_code__contains="SECRET").exists())

    def test_outbox_write_failure_rolls_back_inquiry(self):
        with patch("market.services._enqueue", side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(RuntimeError):
                self.create_request()
        self.assertFalse(Inquiry.objects.exists())

    def test_buyer_and_authorized_shop_only_can_read_and_change_request(self):
        inquiry = self.create_request(actor=self.buyer)
        self.assertTrue(inquiries_for_user(self.buyer).filter(pk=inquiry.pk).exists())
        self.assertTrue(inquiries_for_user(self.owner).filter(pk=inquiry.pk).exists())
        self.assertFalse(inquiries_for_user(self.other).filter(pk=inquiry.pk).exists())
        with self.assertRaises(PermissionDenied):
            set_inquiry_status(actor=self.other, inquiry=inquiry, status="viewed")
        with self.assertRaises(PermissionDenied):
            reply_to_inquiry(actor=self.buyer, inquiry=inquiry, text="Чужой ответ")
        inquiry = set_inquiry_status(actor=self.owner, inquiry=inquiry, status="viewed")
        inquiry = set_inquiry_status(actor=self.buyer, inquiry=inquiry, status="cancelled")
        with self.assertRaises(ValidationError):
            reply_to_inquiry(actor=self.owner, inquiry=inquiry, text="Поздний ответ")

    def test_inquiry_rejects_mismatched_offer_shop(self):
        inquiry = self.create_request()
        inquiry.shop = self.other_shop
        with self.assertRaises(ValidationError):
            inquiry.save()

    def test_replies_have_immutable_private_snapshot_and_unique_event_keys(self):
        inquiry = self.create_request(actor=self.buyer)
        reply_to_inquiry(actor=self.owner, inquiry=inquiry, text="Первый ответ")
        reply_to_inquiry(actor=self.owner, inquiry=inquiry, text="Уточнённый ответ")
        notices = list(Notification.objects.filter(kind="buyer_reply").order_by("id"))
        self.assertEqual([notice.payload["reply_text"] for notice in notices], ["Первый ответ", "Уточнённый ответ"])
        self.assertNotEqual(notices[0].event_key, notices[1].event_key)
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.reply_count, 2)
        self.assertEqual(inquiry.status, Inquiry.Status.RESPONDED)
        self.assertEqual(inquiry.reply_text, "Уточнённый ответ")

    def test_tax_identifier_must_match_entity_type_and_ascii_digits(self):
        for inn in ("123456789012", "１２３４５６７８９０"):
            seller = SellerProfile(user=self.employee, legal_name="Компания", legal_type="company", inn=inn)
            with self.subTest(inn=inn), self.assertRaises(ValidationError):
                seller.full_clean()

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_moderation_admin_prevents_raw_state_edits_and_private_inquiry_access(self):
        self.employee.is_staff = True
        self.employee.save()
        self.employee.user_permissions.add(Permission.objects.get(codename="moderate_market"))
        self.client.force_login(self.employee)
        response = self.client.get(reverse("admin:market_shop_changelist"), secure=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse("admin:market_shop_change", args=[self.shop.pk]), {
            "status": "archived", "seller": self.other_seller.pk, "_save": "Сохранить",
        }, secure=True)
        self.assertEqual(response.status_code, 302)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.status, Shop.Status.PUBLISHED)
        self.assertEqual(self.shop.seller_id, self.seller.pk)
        self.assertEqual(self.client.get(reverse("admin:market_inquiry_changelist"), secure=True).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:market_notification_changelist"), secure=True).status_code, 403)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_admin_publish_action_requires_submission(self):
        offer = save_offer(actor=self.owner, shop=self.shop, data=self.offer_data(seller_sku="admin-test"))
        self.client.force_login(self.moderator)
        url = reverse("admin:market_offer_changelist")
        data = {"action": "publish_offers", "_selected_action": [str(offer.pk)]}
        self.assertEqual(self.client.post(url, data, secure=True).status_code, 302)
        offer.refresh_from_db()
        self.assertEqual(offer.status, Offer.Status.DRAFT)
        submit_offer(actor=self.owner, offer=offer)
        self.assertEqual(self.client.post(url, data, secure=True).status_code, 302)
        offer.refresh_from_db()
        self.assertEqual(offer.status, Offer.Status.PUBLISHED)
