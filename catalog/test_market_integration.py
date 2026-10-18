from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from market.models import Offer, SellerProfile, Shop
from .models import Category, Product, ProductType


class CatalogMarketTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Тест Market", slug="market-catalog-test")
        product_type = ProductType.objects.create(category=category, name="Модуль", slug="module")
        cls.product = Product.objects.create(product_type=product_type, title="Модель с предложениями", slug="market-test-product", status="published")
        cls.offers = []
        for number, price in [(1, "250.00"), (2, "190.50")]:
            user = get_user_model().objects.create_user(username=f"catalog-seller-{number}", email=f"private-seller-{number}@example.test")
            seller = SellerProfile.objects.create(user=user, legal_name=f"Продавец {number}", legal_type="ip", inn=f"10000000000{number}", status="verified")
            shop = Shop.objects.create(seller=seller, name=f"Магазин {number}", slug=f"catalog-shop-{number}", city="Москва", status="published")
            cls.offers.append(Offer.objects.create(
                shop=shop, product=cls.product, price=Decimal(price), status="published", fulfilment="Самовывоз",
                valid_until=timezone.now() + timedelta(days=1), last_confirmed_at=timezone.now(),
            ))

    def test_two_shops_share_one_model_with_sorted_prices_and_private_contacts(self):
        response = self.client.get(reverse("product_detail", args=[self.product.slug]), secure=True)
        self.assertEqual(response.status_code, 200)
        for offer in self.offers:
            self.assertContains(response, offer.shop.name)
            self.assertContains(response, reverse("market_inquiry_create", args=[offer.pk]))
            self.assertNotContains(response, offer.shop.owner.email)
        self.assertEqual(list(response.context["offers"].values_list("price", flat=True)), [Decimal("190.50"), Decimal("250.00")])
        self.assertEqual(Product.objects.filter(pk=self.product.pk).count(), 1)

    def test_expired_offer_is_explicit_and_unknown_quantity_is_not_zero(self):
        offer = self.offers[0]
        offer.valid_until = timezone.now() - timedelta(minutes=1)
        offer.save(update_fields=["valid_until"])
        response = self.client.get(reverse("product_detail", args=[self.product.slug]), secure=True)
        self.assertContains(response, "Цена и наличие требуют подтверждения")
        self.assertContains(response, "количество не указано")
        self.assertNotContains(response, "0 шт.")

    def test_paused_or_unverified_shop_does_not_leak_into_product_page(self):
        first, second = self.offers
        first.shop.status = "paused"
        first.shop.save(update_fields=["status"])
        seller = second.shop.seller
        seller.status = "suspended"
        seller.save(update_fields=["status"])
        response = self.client.get(reverse("product_detail", args=[self.product.slug]), secure=True)
        self.assertNotContains(response, first.shop.name)
        self.assertNotContains(response, second.shop.name)
        self.assertContains(response, "Предложений пока нет")
