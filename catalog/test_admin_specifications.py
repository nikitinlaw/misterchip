from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import (
    AttributeDefinition, Category, Product, ProductAttributeValue,
    ProductType, ProductTypeAttribute,
)


class SpecificationAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="editor", email="editor@example.test", password="StrongTest123!"
        )
        self.client.force_login(self.user)
        group = Category.objects.create(name="Компоненты", slug="components")
        self.ram = ProductType.objects.create(category=group, name="Оперативная память", slug="ram")
        self.resistor = ProductType.objects.create(category=group, name="Резистор", slug="resistor")
        self.resistance = AttributeDefinition.objects.create(
            code="resistance", name="Сопротивление", data_type="number", canonical_unit="Ом"
        )
        self.memory = AttributeDefinition.objects.create(
            code="ddr", name="Поколение DDR", data_type="choice", allowed_values=["DDR4", "DDR5"]
        )
        ProductTypeAttribute.objects.create(
            product_type=self.resistor, attribute=self.resistance, required=True
        )
        ProductTypeAttribute.objects.create(
            product_type=self.ram, attribute=self.memory, required=True
        )
        self.part = Product.objects.create(
            product_type=self.resistor, title="Резистор A", slug="resistor-a",
        )
        self.ram_part = Product.objects.create(
            product_type=self.ram, title="Память B", slug="memory-b",
        )

    def spec_url(self, product):
        return reverse("admin:catalog_product_specifications", args=[product.pk])

    def test_dynamic_fields_depend_on_type(self):
        a = self.client.get(self.spec_url(self.part), secure=True)
        b = self.client.get(self.spec_url(self.ram_part), secure=True)
        self.assertEqual(a.status_code, 200)
        self.assertContains(a, "Сопротивление")
        self.assertNotContains(a, "Поколение DDR")
        self.assertContains(b, "Поколение DDR")
        self.assertNotContains(b, "Сопротивление")

    def test_light_branded_admin_and_compact_types(self):
        response = self.client.get(
            reverse("admin:catalog_producttype_change", args=[self.resistor.pk]),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'catalog/admin.')
        self.assertContains(response, 'catalog/misterchip-logo.')
        self.assertContains(response, "Характеристики товара")
        self.assertContains(response, "Обязательная")
        self.assertContains(response, "Название типа")

    def test_spec_editor_has_one_title_and_combined_units(self):
        response = self.client.get(self.spec_url(self.part), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="mc-spec-grid"')
        self.assertContains(response, "Единица измерения: Сопротивление")
        self.assertEqual(response.content.count(b"<h1>"), 1)

    def test_decimal_initial_display_omits_unnecessary_zeros(self):
        ProductAttributeValue.objects.create(
            product=self.part, attribute=self.resistance,
            number_value=Decimal("10.00000000"), unit="Ом",
        )
        response = self.client.get(self.spec_url(self.part), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="10"')
        self.assertNotContains(response, 'value="10.00000000"')

    def test_save_and_normalize_resistance(self):
        url = self.spec_url(self.part)
        resp = self.client.post(
            url, {"spec_%s" % self.resistance.pk: "1", "unit_%s" % self.resistance.pk: "кОм"},
            secure=True,
        )
        self.assertEqual(resp.status_code, 302)
        saved = ProductAttributeValue.objects.get(product=self.part, attribute=self.resistance)
        self.assertEqual(saved.normalized_number, Decimal("1000"))
        self.assertEqual(saved.unit, "кОм")

    def test_required_attribute_is_checked(self):
        response = self.client.post(self.spec_url(self.part), {}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProductAttributeValue.objects.count(), 0)

    def test_new_attribute_available_without_migration(self):
        new_attribute = AttributeDefinition.objects.create(
            code="tolerance", name="Допуск", data_type="number", canonical_unit=""
        )
        ProductTypeAttribute.objects.create(product_type=self.resistor, attribute=new_attribute)
        response = self.client.get(self.spec_url(self.part), secure=True)
        self.assertContains(response, "Допуск")
        self.assertNotContains(self.client.get(self.spec_url(self.ram_part), secure=True), "Допуск")

    def test_text_choices_and_optional_removal(self):
        response = self.client.post(
            self.spec_url(self.ram_part),
            {f"spec_{self.memory.pk}": "DDR5"}, secure=True,
        )
        self.assertEqual(response.status_code, 302)
        val = ProductAttributeValue.objects.get(product=self.ram_part, attribute=self.memory)
        self.assertEqual(val.text_value, "DDR5")
        # When the administrator makes the attribute optional it may be cleared.
        binding = ProductTypeAttribute.objects.get(product_type=self.ram, attribute=self.memory)
        binding.required = False
        binding.save(update_fields=["required"])
        response = self.client.post(self.spec_url(self.ram_part), {}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProductAttributeValue.objects.filter(product=self.ram_part).exists())

    def test_non_staff_user_cannot_edit_specs(self):
        other = get_user_model().objects.create_user(
            username="buyer", email="buyer@example.test", password="StrongTest123!"
        )
        self.client.force_login(other)
        response = self.client.get(self.spec_url(self.part), secure=True)
        self.assertIn(response.status_code, (302, 403))
