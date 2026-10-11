from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from catalog.models import (
    AttributeDefinition, Category, Product, ProductAttributeValue, ProductReference,
    ProductType, ProductTypeAttribute, TrademarkGood,
)


class ManufacturerPilotTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_catalog", verbosity=0)

    def test_four_models_and_verbatim_legal_goods(self):
        self.assertEqual(Product.objects.count(), 4)
        self.assertEqual(TrademarkGood.objects.count(), 373)
        self.assertEqual(Category.objects.count(), 11)
        self.assertEqual(ProductType.objects.count(), 2)
        self.assertEqual(ProductReference.objects.count(), 4)

    def test_repeat_does_not_replace_editorial_description(self):
        p = Product.objects.get(mpn="KF552C40BB-16")
        p.description = "Описание редактора"
        p.save(update_fields=["description"])
        call_command("seed_demo_catalog", verbosity=0)
        p.refresh_from_db()
        self.assertEqual(p.description, "Описание редактора")
        self.assertEqual(Product.objects.count(), 4)
        self.assertEqual(ProductReference.objects.count(), 4)
        self.assertEqual(
            ProductAttributeValue.objects.filter(product=p).count(), 8
        )

    def test_ram_and_resistors_have_distinct_attributes(self):
        ram = ProductType.objects.get(slug="ram")
        resistor = ProductType.objects.get(slug="resistors")
        ram_attrs = set(ProductTypeAttribute.objects.filter(product_type=ram).values_list("attribute__code", flat=True))
        resistor_attrs = set(ProductTypeAttribute.objects.filter(product_type=resistor).values_list("attribute__code", flat=True))
        self.assertIn("capacity", ram_attrs)
        self.assertIn("resistance", resistor_attrs)
        self.assertNotIn("capacity", resistor_attrs)
        self.assertNotIn("resistance", ram_attrs)

    def test_cards_show_official_manufacturer_source_and_no_price(self):
        p = Product.objects.get(mpn="RC0603FR-071KL")
        r = self.client.get(reverse("product_detail", args=[p.slug]), secure=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Официальная спецификация производителя")
        self.assertContains(r, "yageogroup.com/component-documentation/download/specsheet/")
        self.assertContains(r, "Актуальных цен и остатков нет")
        self.assertNotContains(r, "Купить за")

    def test_two_ram_models_can_be_compared(self):
        p1 = Product.objects.get(mpn="KF552C40BB-16")
        p2 = Product.objects.get(mpn="KF556C40BB-16")
        r = self.client.get(reverse("catalog_compare"), {"ids": [p1.pk, p2.pk]}, secure=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "5200 МТ/с")
        self.assertContains(r, "5600 МТ/с")
        self.assertContains(r, "different")

    def test_resistor_filter_by_normalized_ohms(self):
        attr = AttributeDefinition.objects.get(code="resistance")
        kind = ProductType.objects.get(slug="resistors")
        r = self.client.get(reverse("catalog_search"), {
            "type": kind.pk,
            f"a_{attr.pk}_min": "950",
            f"a_{attr.pk}_max": "1050",
        }, secure=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "RC0603FR-071KL")
        self.assertNotContains(r, "RC0603FR-0710KL")


class ManufacturerPilotDryRunTests(TestCase):
    def test_dry_run_does_not_save_anything(self):
        call_command("seed_demo_catalog", "--dry-run", verbosity=0)
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(TrademarkGood.objects.count(), 0)
        self.assertEqual(ProductReference.objects.count(), 0)
