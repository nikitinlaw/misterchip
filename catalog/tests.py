from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import (
    AttributeDefinition, Brand, Category, Product, ProductAttributeValue,
    ProductType, ProductTypeAttribute, normalize_number,
)


class FlexibleCharacteristicsTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Компоненты", slug="components")
        self.ram = ProductType.objects.create(category=self.category, name="Оперативная память", slug="ram")
        self.resistor = ProductType.objects.create(category=self.category, name="Резистор", slug="resistor")
        self.resistance = AttributeDefinition.objects.create(
            code="resistance", name="Сопротивление", data_type="number", canonical_unit="Ом"
        )
        self.ram_type = AttributeDefinition.objects.create(
            code="ddr", name="Тип DDR", data_type="choice", allowed_values=["DDR4", "DDR5"]
        )
        ProductTypeAttribute.objects.create(product_type=self.resistor, attribute=self.resistance)
        ProductTypeAttribute.objects.create(product_type=self.ram, attribute=self.ram_type)
        self.resistor_product = Product.objects.create(
            product_type=self.resistor, title="Резистор тестовый", slug="resistor-test", status="published",
        )
        self.ram_product = Product.objects.create(
            product_type=self.ram, title="Модуль памяти", slug="ram-test", status="published",
        )

    def test_1000_ohms_equals_one_kilohm(self):
        self.assertEqual(normalize_number(Decimal("1"), "кОм", "Ом"), Decimal("1000"))
        value = ProductAttributeValue.objects.create(
            product=self.resistor_product, attribute=self.resistance,
            number_value=Decimal("1"), unit="кОм",
        )
        self.assertEqual(value.normalized_number, Decimal("1000"))

    def test_ram_cannot_use_resistor_attribute(self):
        with self.assertRaises(ValidationError):
            ProductAttributeValue.objects.create(
                product=self.ram_product, attribute=self.resistance,
                number_value=Decimal("10"), unit="Ом",
            )

    def test_choices_validated(self):
        with self.assertRaises(ValidationError):
            ProductAttributeValue.objects.create(
                product=self.ram_product, attribute=self.ram_type, text_value="DDR99",
            )
        ProductAttributeValue.objects.create(product=self.ram_product, attribute=self.ram_type, text_value="DDR5")
        self.assertEqual(self.ram_product.attribute_values.count(), 1)

    def test_public_card(self):
        self.assertContains(self.client.get(reverse("product_detail", args=["ram-test"]), secure=True), "Модуль памяти")
        self.ram_product.status = Product.Status.DRAFT
        self.ram_product.save()
        self.assertEqual(self.client.get(reverse("product_detail", args=["ram-test"])).status_code, 404)
