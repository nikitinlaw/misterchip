from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from catalog.models import (
    AttributeDefinition, Brand, Category, Product, ProductAttributeValue,
    ProductType, ProductTypeAttribute,
)


class PublicCatalogTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Комплектующие", slug="parts")
        brand = Brand.objects.create(name="Тест", slug="test-brand")
        self.resistor = ProductType.objects.create(category=category, name="Резистор", slug="resistor")
        self.ram = ProductType.objects.create(category=category, name="Оперативная память", slug="ram")
        self.resistance = AttributeDefinition.objects.create(
            name="Сопротивление", code="resistance",
            data_type="number", canonical_unit="Ом",
        )
        self.ddr = AttributeDefinition.objects.create(
            name="Поколение DDR", code="ddr", data_type="choice", allowed_values=["DDR4", "DDR5"],
        )
        ProductTypeAttribute.objects.create(
            product_type=self.resistor, attribute=self.resistance, comparable=True, filterable=True
        )
        ProductTypeAttribute.objects.create(
            product_type=self.ram, attribute=self.ddr, comparable=True, filterable=True
        )
        self.first = Product.objects.create(
            product_type=self.resistor, brand=brand, title="Резистор 1", slug="resistor-1", status="published"
        )
        self.second = Product.objects.create(
            product_type=self.resistor, brand=brand, title="Резистор 2", slug="resistor-2", status="published"
        )
        self.third = Product.objects.create(
            product_type=self.ram, brand=brand, title="Память DDR5", slug="ram-5", status="published"
        )
        ProductAttributeValue.objects.create(
            product=self.first, attribute=self.resistance, number_value=Decimal("1"), unit="кОм"
        )
        ProductAttributeValue.objects.create(
            product=self.second, attribute=self.resistance, number_value=Decimal("2000"), unit="Ом"
        )
        ProductAttributeValue.objects.create(
            product=self.third, attribute=self.ddr, text_value="DDR5"
        )

    def test_filter_layout_and_comparison_controls(self):
        response = self.client.get(reverse("catalog_search"), secure=True)
        self.assertContains(response, 'class="filter-form"')
        self.assertContains(response, 'class="catalog-results"')
        for field in ('q', 'category', 'type', 'brand'):
            self.assertContains(response, 'name="' + field + '"')
        self.assertContains(response, 'name="ids"', count=3)
        self.assertContains(response, 'Применить фильтры')

    def test_search_numeric_range_in_canonical_units(self):
        response = self.client.get(reverse("catalog_search"), {
            "type": str(self.resistor.pk),
            f"a_{self.resistance.pk}_min": "900",
            f"a_{self.resistance.pk}_max": "1100",
        }, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Резистор 1")
        self.assertNotContains(response, "Резистор 2")
        self.assertNotContains(response, "Память DDR5")

    def test_choice_filter_only_for_type(self):
        response = self.client.get(reverse("catalog_search"), {
            "type": str(self.ram.pk), f"a_{self.ddr.pk}": "DDR5",
            f"a_{self.resistance.pk}_min": "300",
        }, secure=True)
        self.assertContains(response, "Память DDR5")
        self.assertNotContains(response, "Резистор 1")

    def test_compare_same_type(self):
        response = self.client.get(reverse("catalog_compare"), {
            "ids": [str(self.first.pk), str(self.second.pk)]
        }, secure=True)
        self.assertContains(response, "Сопротивление")
        self.assertContains(response, "1 кОм")
        self.assertContains(response, "2000 Ом")
        self.assertContains(response, "different")

    def test_compare_different_types_rejected(self):
        response = self.client.get(reverse("catalog_compare"), {
            "ids": [str(self.first.pk), str(self.third.pk)]
        }, secure=True)
        self.assertEqual(response.status_code, 400)

    def test_compare_draft_not_leaked(self):
        self.second.status = Product.Status.DRAFT
        self.second.save()
        response = self.client.get(reverse("catalog_compare"), {
            "ids": [str(self.first.pk), str(self.second.pk)]
        }, secure=True)
        self.assertEqual(response.status_code, 404)

    def test_compare_rejects_duplicate_and_excess(self):
        self.assertEqual(self.client.get(reverse("catalog_compare"), {
            "ids": [str(self.first.pk), str(self.first.pk)]
        }, secure=True).status_code, 400)
        self.assertEqual(self.client.get(reverse("catalog_compare"), {
            "ids": ["1", "2", "3", "4", "5"]
        }, secure=True).status_code, 400)

    def test_pagination_keeps_specification_filters(self):
        for idx in range(22):
            product = Product.objects.create(
                product_type=self.resistor, brand=self.first.brand,
                title=f"Резистор запасной {idx}", slug=f"spare-{idx}",
                status="published",
            )
            ProductAttributeValue.objects.create(
                product=product, attribute=self.resistance,
                number_value=Decimal("1000"), unit="Ом",
            )
        response = self.client.get(reverse("catalog_search"), {
            "type": str(self.resistor.pk), "q": "Резистор", "brand": "test-brand",
            f"a_{self.resistance.pk}_min": "900",
        }, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["page"].has_next())
        self.assertIn(f"a_{self.resistance.pk}_min=900", response.context["pagination_query"])
        self.assertIn("brand=test-brand", response.context["pagination_query"])
