"""HTTP coverage for Market publication, private membership and inquiry boundaries."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product, ProductType

from .models import Inquiry, Notification, Offer, SellerProfile, Shop, ShopMembership
from .services import INQUIRY_CONSENT_TEXT, INQUIRY_CONSENT_VERSION, save_offer
from .views import NONCE_SESSION_KEY, NONCE_TTL


class MarketViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        for name in ("owner", "other_owner", "buyer", "outsider", "offer_clerk", "inquiry_clerk", "manager", "new_staff"):
            setattr(cls, name, users.objects.create_user(
                username=name, email=f"{name}@example.test", password="StrongMarketPass123!",
            ))
        cls.staff = users.objects.create_user(
            username="staff_only", email="staff_only@example.test", password="StrongMarketPass123!", is_staff=True,
        )
        cls.seller = SellerProfile.objects.create(
            user=cls.owner, legal_name="ООО Первый магазин", legal_type="company",
            inn="7701234567", status=SellerProfile.Status.VERIFIED,
        )
        cls.other_seller = SellerProfile.objects.create(
            user=cls.other_owner, legal_name="ООО Второй магазин", legal_type="company",
            inn="7707654321", status=SellerProfile.Status.VERIFIED,
        )
        cls.shop = Shop.objects.create(
            seller=cls.seller, name="Магазин компонентов", slug="магазин-компонентов",
            city="Москва", status=Shop.Status.PUBLISHED, public_email="public-shop@example.test",
        )
        cls.other_shop = Shop.objects.create(
            seller=cls.other_seller, name="Другой магазин", slug="other-shop", city="Казань",
            status=Shop.Status.PUBLISHED,
        )
        category = Category.objects.create(name="Электронные компоненты", slug="electronics")
        product_type = ProductType.objects.create(category=category, name="Резистор", slug="resistor")
        cls.product = Product.objects.create(
            product_type=product_type, title="Проверенная модель", slug="reference-part",
            status=Product.Status.PUBLISHED,
        )
        cls.draft_product = Product.objects.create(
            product_type=product_type, title="Неопубликованная модель", slug="draft-part", status=Product.Status.DRAFT,
        )
        cls.offer = Offer.objects.create(
            shop=cls.shop, product=cls.product, price=Decimal("150.00"), stock_quantity=3,
            fulfilment="Самовывоз", status=Offer.Status.PUBLISHED,
            valid_until=timezone.now() + timedelta(days=3), last_confirmed_at=timezone.now(),
        )
        cls.other_offer = Offer.objects.create(
            shop=cls.other_shop, product=cls.product, price=Decimal("180.00"), stock_quantity=2,
            fulfilment="Доставка", status=Offer.Status.PUBLISHED,
            valid_until=timezone.now() + timedelta(days=3), last_confirmed_at=timezone.now(),
        )
        for user, role in (
            (cls.offer_clerk, ShopMembership.Role.OFFERS),
            (cls.inquiry_clerk, ShopMembership.Role.INQUIRIES),
            (cls.manager, ShopMembership.Role.MANAGER),
        ):
            ShopMembership.objects.create(shop=cls.shop, user=user, role=role)

    def setUp(self):
        cache.clear()

    def _inquiry(self, *, buyer=None, shop=None, offer=None, message="Проверьте наличие перед покупкой."):
        offer = offer or self.offer
        return Inquiry.objects.create(
            buyer=buyer, shop=shop or offer.shop, offer=offer, name="Имя покупателя",
            email=buyer.email if buyer else "guest-private@example.test", phone="+7 900 000 1122",
            message=message, consent_at=timezone.now(), consent_version=INQUIRY_CONSENT_VERSION,
            consent_text=INQUIRY_CONSENT_TEXT,
            offer_snapshot={"product_title": offer.product.title, "shop_name": offer.shop.name, "price": str(offer.price)},
        )

    def _inquiry_payload(self, *, client=None, offer=None, **changes):
        client = client or self.client
        offer = offer or self.offer
        response = client.get(reverse("market_inquiry_create", args=[offer.pk]), secure=True)
        self.assertEqual(response.status_code, 200)
        payload = {
            "name": "Покупатель", "email": "anonymous-private@example.test", "phone": "+7 900 000 9988",
            "message": "Секретный вопрос о наличии и доставке.", "consent": "on",
            "submission_key": response.context["form"]["submission_key"].value(),
        }
        payload.update(changes)
        return payload

    def _offer_payload(self, **changes):
        payload = {
            "product": self.product.pk, "price": "150.00", "stock_quantity": "3",
            "availability": "in_stock", "condition": "new", "condition_description": "",
            "seller_sku": "", "fulfilment": "Самовывоз", "lead_time": "", "comment": "",
            "external_url": "", "valid_until": (timezone.now() + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M"),
        }
        payload.update(changes)
        return payload

    def _shop_payload(self, **changes):
        payload = {
            "name": self.shop.name, "city": self.shop.city, "address": "", "description": "",
            "public_email": self.shop.public_email, "public_phone": "", "website": "", "opening_hours": "",
        }
        payload.update(changes)
        return payload

    def test_public_shop_supports_unicode_slug_and_hides_private_contacts(self):
        inquiry = self._inquiry(buyer=self.buyer)
        response = self.client.get(reverse("market_shop_detail", args=[self.shop.slug]), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.shop.public_email)
        self.assertContains(response, self.product.title)
        for private in (self.owner.email, self.offer_clerk.email, inquiry.email, inquiry.phone, inquiry.message):
            self.assertNotContains(response, private)

    def test_unpublished_shop_offer_and_product_are_not_public(self):
        self.other_shop.status = Shop.Status.PENDING
        self.other_shop.save()
        response = self.client.get(reverse("market_shop_list"), secure=True)
        self.assertNotContains(response, self.other_shop.name)
        self.assertEqual(self.client.get(reverse("market_shop_detail", args=[self.other_shop.slug]), secure=True).status_code, 404)
        self.assertEqual(self.client.get(reverse("market_inquiry_create", args=[self.other_offer.pk]), secure=True).status_code, 404)
        self.offer.status = Offer.Status.DRAFT
        self.offer.save()
        self.assertEqual(self.client.get(reverse("market_inquiry_create", args=[self.offer.pk]), secure=True).status_code, 404)
        Offer.objects.filter(pk=self.offer.pk).update(status=Offer.Status.PUBLISHED)
        self.product.status = Product.Status.DRAFT
        self.product.save()
        response = self.client.get(reverse("market_shop_detail", args=[self.shop.slug]), secure=True)
        self.assertNotContains(response, self.product.title)

    def test_expired_offer_stays_visible_with_confirmation_label(self):
        Offer.objects.filter(pk=self.offer.pk).update(valid_until=timezone.now() - timedelta(minutes=1))
        response = self.client.get(reverse("market_shop_detail", args=[self.shop.slug]), secure=True)
        self.assertContains(response, self.product.title)
        self.assertContains(response, "Цена и наличие требуют подтверждения")
        self.assertContains(response, "Уточнить у магазина")
        self.assertContains(response, "Последняя указанная цена")

    def test_anonymous_inquiry_success_contains_only_receipt_and_is_idempotent(self):
        payload = self._inquiry_payload()
        url = reverse("market_inquiry_create", args=[self.offer.pk])
        response = self.client.post(url, payload, secure=True)
        self.assertEqual(response.status_code, 302)
        inquiry = Inquiry.objects.get()
        self.assertIsNone(inquiry.buyer_id)
        self.assertEqual(inquiry.shop_id, self.shop.pk)
        self.assertEqual(inquiry.consent_text, INQUIRY_CONSENT_TEXT)
        receipt = self.client.get(response["Location"], secure=True)
        self.assertContains(receipt, str(inquiry.public_id))
        self.assertContains(receipt, "Обращение принято")
        for private in (inquiry.name, inquiry.email, inquiry.phone, inquiry.message, self.owner.email):
            self.assertNotContains(receipt, private)
        self.assertIn("no-store", receipt["Cache-Control"])
        repeat = self.client.post(url, payload, secure=True)
        self.assertEqual(repeat["Location"], response["Location"])
        self.assertEqual(Inquiry.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertEqual(Client().get(response["Location"], secure=True).status_code, 404)

    def test_authenticated_inquiry_uses_account_email_and_server_bound_objects(self):
        self.client.force_login(self.buyer)
        payload = self._inquiry_payload(email="forged@example.test", buyer=self.outsider.pk, shop=self.other_shop.pk)
        response = self.client.post(reverse("market_inquiry_create", args=[self.offer.pk]), payload, secure=True)
        self.assertEqual(response.status_code, 302)
        inquiry = Inquiry.objects.get()
        self.assertEqual(inquiry.email, self.buyer.email)
        self.assertEqual(inquiry.buyer_id, self.buyer.pk)
        self.assertEqual(inquiry.shop_id, self.shop.pk)
        self.assertFalse(Notification.objects.filter(recipient="forged@example.test").exists())
        own = self.client.get(reverse("market_inquiry_detail", args=[inquiry.public_id]), secure=True)
        self.assertContains(own, inquiry.message)
        self.assertContains(own, 'content="noindex,nofollow"')

    def test_consent_is_explicit_and_unchecked(self):
        response = self.client.get(reverse("market_inquiry_create", args=[self.offer.pk]), secure=True)
        self.assertFalse(response.context["form"]["consent"].value())
        payload = self._inquiry_payload(consent="")
        response = self.client.post(reverse("market_inquiry_create", args=[self.offer.pk]), payload, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("consent", response.context["form"].errors)
        self.assertEqual(Inquiry.objects.count(), 0)

    def test_inquiry_preserves_original_offer_terms_after_seller_changes_offer(self):
        original_terms = {
            "availability": Offer.Availability.ON_ORDER,
            "condition": Offer.Condition.USED,
            "condition_description": "Проверен, небольшая царапина на корпусе.",
            "fulfilment": "Самовывоз из пункта на Тверской",
            "lead_time": "Через три рабочих дня",
            "seller_sku": "ORIGINAL-42",
            "comment": "В комплекте оригинальная упаковка.",
            "external_url": "https://shop.example.test/original-offer",
        }
        Offer.objects.filter(pk=self.offer.pk).update(**original_terms)
        self.offer.refresh_from_db()
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("market_inquiry_create", args=[self.offer.pk]),
            self._inquiry_payload(), secure=True,
        )
        self.assertEqual(response.status_code, 302)
        inquiry = Inquiry.objects.get()
        original_snapshot = inquiry.offer_snapshot.copy()
        expected = {
            **original_terms, "price": "150.00", "stock_quantity": 3,
            "availability_label": "Под заказ", "condition_label": "Бывший в употреблении",
        }
        for field, value in expected.items():
            self.assertEqual(original_snapshot[field], value, field)

        changed = save_offer(actor=self.owner, shop=self.shop, offer=self.offer, data={
            "price": Decimal("275.00"), "stock_quantity": 0,
            "availability": Offer.Availability.OUT_OF_STOCK, "condition": Offer.Condition.NEW,
            "condition_description": "Совершенно другая партия.",
            "fulfilment": "Курьерская доставка из нового склада", "lead_time": "Через неделю",
            "seller_sku": "REPLACEMENT-99", "comment": "Упаковка оплачивается отдельно.",
            "external_url": "https://shop.example.test/replacement-offer",
        })
        self.assertEqual(changed.status, Offer.Status.PENDING)
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.offer_snapshot, original_snapshot)
        detail = self.client.get(reverse("market_inquiry_detail", args=[inquiry.public_id]), secure=True)
        for original in (
            "150.00", expected["availability_label"], expected["condition_label"],
            *(original_terms[field] for field in (
                "condition_description", "fulfilment", "lead_time", "seller_sku", "comment", "external_url",
            )),
        ):
            self.assertContains(detail, original)
        for replacement in (
            "275.00", "Нет в наличии", changed.condition_description, changed.fulfilment,
            changed.lead_time, changed.seller_sku, changed.comment, changed.external_url,
        ):
            self.assertNotContains(detail, replacement)

    def test_nonce_is_session_offer_and_actor_bound(self):
        other_client = Client()
        payload = self._inquiry_payload(client=other_client)
        url = reverse("market_inquiry_create", args=[self.offer.pk])
        response = self.client.post(url, payload, secure=True)
        self.assertContains(response, "Откройте форму заново")
        payload = self._inquiry_payload()
        response = self.client.post(reverse("market_inquiry_create", args=[self.other_offer.pk]), payload, secure=True)
        self.assertContains(response, "Откройте форму заново")
        self.client.force_login(self.buyer)
        response = self.client.post(url, payload, secure=True)
        self.assertContains(response, "Откройте форму заново")
        self.assertEqual(Inquiry.objects.count(), 0)

    def test_forged_or_expired_nonce_cannot_submit(self):
        payload = self._inquiry_payload()
        real_nonce = str(payload["submission_key"])
        payload["submission_key"] = str(uuid.uuid4())
        url = reverse("market_inquiry_create", args=[self.offer.pk])
        self.assertContains(self.client.post(url, payload, secure=True), "Откройте форму заново")
        session = self.client.session
        entries = session[NONCE_SESSION_KEY]
        entries[real_nonce]["created"] -= NONCE_TTL + 1
        session[NONCE_SESSION_KEY] = entries
        session.save()
        payload["submission_key"] = real_nonce
        self.assertContains(self.client.post(url, payload, secure=True), "Откройте форму заново")
        self.assertEqual(Inquiry.objects.count(), 0)

    def test_private_inquiry_uuid_is_not_a_reading_capability(self):
        inquiry = self._inquiry(buyer=self.buyer)
        detail = reverse("market_inquiry_detail", args=[inquiry.public_id])
        seller_detail = reverse("market_seller_inquiry_detail", args=[inquiry.public_id])
        self.assertEqual(self.client.get(detail, secure=True).status_code, 302)
        for actor in (self.outsider, self.other_owner, self.offer_clerk, self.staff):
            self.client.force_login(actor)
            self.assertEqual(self.client.get(detail, secure=True).status_code, 404)
            self.assertEqual(self.client.get(seller_detail, secure=True).status_code, 404)
            self.assertEqual(self.client.post(seller_detail, {"action": "reply", "reply_text": "Чужой ответ"}, secure=True).status_code, 404)
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.reply_text, "")

    def test_membership_scopes_dashboard_and_sensitive_actions(self):
        inquiry = self._inquiry(buyer=self.buyer)
        self.client.force_login(self.offer_clerk)
        dashboard = self.client.get(reverse("market_shop_dashboard", args=[self.shop.pk]), secure=True)
        self.assertContains(dashboard, "Добавить предложение")
        self.assertNotContains(dashboard, str(inquiry.public_id))
        self.assertEqual(self.client.get(reverse("market_shop_members", args=[self.shop.pk]), secure=True).status_code, 404)
        self.assertEqual(self.client.get(reverse("market_shop_edit", args=[self.shop.pk]), secure=True).status_code, 404)
        self.client.force_login(self.inquiry_clerk)
        dashboard = self.client.get(reverse("market_shop_dashboard", args=[self.shop.pk]), secure=True)
        self.assertContains(dashboard, str(inquiry.public_id))
        self.assertNotContains(dashboard, "Добавить предложение")
        self.assertEqual(self.client.get(reverse("market_offer_edit", args=[self.offer.pk]), secure=True).status_code, 404)
        ShopMembership.objects.filter(shop=self.shop, user=self.inquiry_clerk).update(is_active=False)
        self.assertEqual(self.client.get(reverse("market_shop_dashboard", args=[self.shop.pk]), secure=True).status_code, 404)

    def test_foreign_shop_and_offer_edits_are_denied_before_validation(self):
        self.client.force_login(self.owner)
        for url, payload in (
            (reverse("market_shop_edit", args=[self.other_shop.pk]), self._shop_payload(name="Подмена")),
            (reverse("market_offer_edit", args=[self.other_offer.pk]), self._offer_payload(price="1.00")),
        ):
            self.assertEqual(self.client.get(url, secure=True).status_code, 404)
            self.assertEqual(self.client.post(url, payload, secure=True).status_code, 404)
        self.other_offer.refresh_from_db()
        self.other_shop.refresh_from_db()
        self.assertEqual(self.other_offer.price, Decimal("180.00"))
        self.assertEqual(self.other_shop.name, "Другой магазин")

    def test_seller_application_cannot_self_verify_or_grant_admin_roles(self):
        self.client.force_login(self.outsider)
        response = self.client.post(reverse("market_seller_profile"), {
            "legal_name": "ООО Новый продавец", "legal_type": "company", "inn": "7701112233",
            "description": "Техника и электронные компоненты", "status": "verified",
            "user": self.owner.pk, "is_staff": "on", "roles": ["seller", "editor"],
        }, secure=True)
        self.assertEqual(response.status_code, 302)
        seller = SellerProfile.objects.get(user=self.outsider)
        self.assertEqual(seller.status, SellerProfile.Status.PENDING)
        self.assertTrue(self.outsider.business_roles.filter(role="seller").exists())
        self.assertFalse(self.outsider.business_roles.filter(role="editor").exists())
        self.outsider.refresh_from_db()
        self.assertFalse(self.outsider.is_staff)

    def test_new_offer_has_server_selected_shop_and_draft_status(self):
        self.client.force_login(self.offer_clerk)
        response = self.client.post(reverse("market_offer_create", args=[self.shop.pk]), self._offer_payload(
            seller_sku="NEW", shop=self.other_shop.pk, status="published", source="import",
        ), secure=True)
        self.assertEqual(response.status_code, 302)
        offer = Offer.objects.get(seller_sku="NEW")
        self.assertEqual(offer.shop_id, self.shop.pk)
        self.assertEqual(offer.status, Offer.Status.DRAFT)
        self.assertEqual(offer.source, "manual")
        invalid = self.client.post(reverse("market_offer_create", args=[self.shop.pk]), self._offer_payload(
            product=self.draft_product.pk, seller_sku="DRAFT-PRODUCT",
        ), secure=True)
        self.assertEqual(invalid.status_code, 200)
        self.assertIn("product", invalid.context["form"].errors)
        self.assertFalse(Offer.objects.filter(seller_sku="DRAFT-PRODUCT").exists())

    def test_published_shop_edits_require_review(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("market_shop_edit", args=[self.shop.pk]), self._shop_payload(
            description="Новые публичные сведения магазина",
        ), secure=True)
        self.assertEqual(response.status_code, 302)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.status, Shop.Status.PENDING)
        self.assertFalse(Shop.objects.public().filter(pk=self.shop.pk).exists())

    def test_offer_price_changes_stay_live_but_terms_require_review(self):
        self.client.force_login(self.offer_clerk)
        url = reverse("market_offer_edit", args=[self.offer.pk])
        response = self.client.post(url, self._offer_payload(price="175.00"), secure=True)
        self.assertEqual(response.status_code, 302)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.price, Decimal("175.00"))
        self.assertEqual(self.offer.status, Offer.Status.PUBLISHED)
        response = self.client.post(url, self._offer_payload(price="175.00", fulfilment="Курьерская доставка"), secure=True)
        self.assertEqual(response.status_code, 302)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, Offer.Status.PENDING)

    def test_hidden_shop_and_offer_remain_editable_during_seller_review(self):
        SellerProfile.objects.filter(pk=self.seller.pk).update(status=SellerProfile.Status.PENDING)
        self.client.force_login(self.owner)
        response = self.client.post(reverse("market_shop_edit", args=[self.shop.pk]), self._shop_payload(
            description="Исправленные сведения магазина",
        ), secure=True)
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("market_offer_edit", args=[self.offer.pk]), self._offer_payload(
            price="160.00",
        ), secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Shop.objects.public().filter(pk=self.shop.pk).exists())
        self.assertFalse(Offer.objects.public().filter(pk=self.offer.pk).exists())

    def test_owner_manages_members_without_public_email_directory(self):
        self.client.force_login(self.owner)
        url = reverse("market_shop_members", args=[self.shop.pk])
        response = self.client.get(url, secure=True)
        self.assertNotContains(response, self.new_staff.email)
        self.assertNotContains(response, self.offer_clerk.email)
        response = self.client.post(url, {"username": self.new_staff.username, "role": "inquiries"}, secure=True)
        self.assertEqual(response.status_code, 302)
        member = ShopMembership.objects.get(shop=self.shop, user=self.new_staff)
        update = reverse("market_membership_update", args=[self.shop.pk, member.pk])
        self.assertEqual(self.client.get(update, secure=True).status_code, 405)
        response = self.client.post(update, {"role": "offers"}, secure=True)
        self.assertEqual(response.status_code, 302)
        member.refresh_from_db()
        self.assertFalse(member.is_active)
        self.assertEqual(member.role, "offers")
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(url, {"username": self.outsider.username, "role": "manager"}, secure=True).status_code, 404)

    def test_shop_and_offer_pause_archive_are_post_only_and_scoped(self):
        self.client.force_login(self.owner)
        shop_url = reverse("market_shop_visibility", args=[self.shop.pk])
        offer_url = reverse("market_offer_visibility", args=[self.offer.pk])
        for url in (shop_url, offer_url):
            self.assertEqual(self.client.get(url, secure=True).status_code, 405)
        self.client.post(offer_url, {"status": "paused"}, secure=True)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, Offer.Status.PAUSED)
        self.client.post(reverse("market_offer_submit", args=[self.offer.pk]), secure=True)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, Offer.Status.PENDING)
        self.client.post(offer_url, {"status": "archived"}, secure=True)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, Offer.Status.ARCHIVED)
        self.client.post(shop_url, {"status": "paused"}, secure=True)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.status, Shop.Status.PAUSED)
        self.client.post(reverse("market_shop_submit", args=[self.shop.pk]), secure=True)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.status, Shop.Status.PENDING)
        self.client.post(shop_url, {"status": "published"}, secure=True)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.status, Shop.Status.PENDING)
        self.client.post(shop_url, {"status": "archived"}, secure=True)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.status, Shop.Status.ARCHIVED)
        self.client.force_login(self.other_owner)
        self.assertEqual(self.client.post(shop_url, {"status": "paused"}, secure=True).status_code, 404)
        self.assertEqual(self.client.post(offer_url, {"status": "paused"}, secure=True).status_code, 404)

    def test_buyer_can_only_cancel_their_own_active_inquiry_by_post(self):
        inquiry = self._inquiry(buyer=self.buyer)
        url = reverse("market_inquiry_cancel", args=[inquiry.public_id])
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(url, secure=True).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url, secure=True).status_code, 404)
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(url, secure=True).status_code, 405)
        response = self.client.post(url, secure=True)
        self.assertEqual(response.status_code, 302)
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.status, Inquiry.Status.CANCELLED)

    def test_seller_reads_explicitly_marks_and_replies_without_get_mutations(self):
        inquiry = self._inquiry(buyer=self.buyer)
        self.client.force_login(self.inquiry_clerk)
        url = reverse("market_seller_inquiry_detail", args=[inquiry.public_id])
        response = self.client.get(url, secure=True)
        self.assertContains(response, inquiry.email)
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.status, Inquiry.Status.NEW)
        self.client.post(url, {"action": "status", "status": "viewed"}, secure=True)
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.status, Inquiry.Status.VIEWED)
        response = self.client.post(url, {"action": "reply", "reply_text": "Есть в наличии, можно забрать сегодня."}, secure=True)
        self.assertEqual(response.status_code, 302)
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.status, Inquiry.Status.RESPONDED)
        self.assertEqual(Notification.objects.filter(kind=Notification.Kind.BUYER_REPLY).count(), 1)
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("market_inquiry_detail", args=[inquiry.public_id]), secure=True)
        self.assertContains(response, inquiry.reply_text)

    def test_dashboard_paginates_more_than_one_hundred_inquiries(self):
        rows = [Inquiry(
            buyer=self.buyer, shop=self.shop, offer=self.offer, email=self.buyer.email,
            message=f"Обращение покупателя номер {number}", consent_at=timezone.now(),
            consent_version=INQUIRY_CONSENT_VERSION, consent_text=INQUIRY_CONSENT_TEXT,
        ) for number in range(105)]
        Inquiry.objects.bulk_create(rows)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("market_shop_dashboard", args=[self.shop.pk]), {
            "inquiries_page": 6, "offers_page": 1,
        }, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["inquiries"].paginator.count, 105)
        self.assertEqual(len(response.context["inquiries"]), 5)
        self.assertContains(response, str(rows[0].public_id))
        self.assertContains(response, "offers_page=1&amp;inquiries_page=5#inquiries")

    def test_forms_render_and_inquiry_post_requires_csrf(self):
        self.client.force_login(self.owner)
        for name, args in (
            ("market_seller_dashboard", []), ("market_seller_profile", []),
            ("market_shop_create", []), ("market_shop_edit", [self.shop.pk]),
            ("market_offer_create", [self.shop.pk]), ("market_offer_edit", [self.offer.pk]),
            ("market_offer_confirm", [self.offer.pk]), ("market_my_inquiries", []),
        ):
            response = self.client.get(reverse(name, args=args), secure=True)
            self.assertEqual(response.status_code, 200, name)
            self.assertContains(response, 'content="noindex,nofollow"')
            self.assertIn("no-store", response["Cache-Control"])
        strict_client = Client(enforce_csrf_checks=True)
        payload = self._inquiry_payload(client=strict_client)
        url = reverse("market_inquiry_create", args=[self.offer.pk])
        self.assertEqual(strict_client.post(url, payload, secure=True).status_code, 403)
        self.assertEqual(Inquiry.objects.count(), 0)
