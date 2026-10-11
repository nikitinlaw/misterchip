"""Dynamic Django forms for editing verified product specifications."""
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    AttributeDefinition, ProductAttributeValue, ProductTypeAttribute,
    UNIT_CONVERSIONS, normalize_number,
)


class SpecificationsForm(forms.Form):
    """Fields are constructed from ProductTypeAttribute at runtime, not migrations."""

    def __init__(self, *args, product, **kwargs):
        self.product = product
        self.bindings = list(
            ProductTypeAttribute.objects.filter(product_type=product.product_type)
            .select_related("attribute").order_by("sort_order", "pk")
        )
        super().__init__(*args, **kwargs)
        existing = {
            value.attribute_id: value
            for value in ProductAttributeValue.objects.filter(product=product)
        }
        for binding in self.bindings:
            definition = binding.attribute
            key = self.value_key(binding)
            label = definition.name
            kind = definition.data_type
            if kind == AttributeDefinition.DataType.NUMBER:
                field = forms.DecimalField(
                    label=label, required=binding.required, max_digits=22,
                    decimal_places=8,
                )
                current = existing.get(definition.pk)
                if current:
                    self.initial[key] = current.number_value
                self.fields[key] = field
                choices = self.allowed_units(definition.canonical_unit)
                unit_key = self.unit_key(binding)
                self.fields[unit_key] = forms.ChoiceField(
                    label=f"{label}: единица измерения",
                    required=False, choices=choices,
                )
                self.initial[unit_key] = (
                    current.unit if current and current.unit else definition.canonical_unit
                )
            elif kind == AttributeDefinition.DataType.INTEGER:
                self.fields[key] = forms.IntegerField(label=label, required=binding.required)
                if definition.pk in existing:
                    self.initial[key] = existing[definition.pk].integer_value
            elif kind == AttributeDefinition.DataType.BOOLEAN:
                self.fields[key] = forms.TypedChoiceField(
                    label=label, required=binding.required,
                    choices=[("", "Не указано"), ("true", "Да"), ("false", "Нет")],
                    coerce=lambda raw: {"true": True, "false": False}.get(raw),
                    empty_value=None,
                )
                current = existing.get(definition.pk)
                if current and current.boolean_value is not None:
                    self.initial[key] = "true" if current.boolean_value else "false"
            elif kind == AttributeDefinition.DataType.CHOICE:
                self.fields[key] = forms.ChoiceField(
                    label=label, required=binding.required,
                    choices=[("", "Не указано")] +
                    [(str(v), str(v)) for v in definition.allowed_values],
                )
                if definition.pk in existing:
                    self.initial[key] = existing[definition.pk].text_value
            else:
                self.fields[key] = forms.CharField(label=label, required=binding.required)
                if definition.pk in existing:
                    self.initial[key] = existing[definition.pk].text_value

    @staticmethod
    def value_key(binding):
        return f"spec_{binding.attribute_id}"

    @staticmethod
    def unit_key(binding):
        return f"unit_{binding.attribute_id}"

    @staticmethod
    def allowed_units(canonical):
        if not canonical:
            return [("", "Без единицы")]
        if canonical not in UNIT_CONVERSIONS:
            return [(canonical, canonical)]
        dimension = UNIT_CONVERSIONS[canonical][0]
        return [
            (name, name) for name, (base, _) in UNIT_CONVERSIONS.items()
            if base == dimension
        ]

    def clean(self):
        cleaned = super().clean()
        for binding in self.bindings:
            if binding.attribute.data_type != AttributeDefinition.DataType.NUMBER:
                continue
            key = self.value_key(binding)
            number = cleaned.get(key)
            if number is None:
                continue
            unit_key = self.unit_key(binding)
            unit = cleaned.get(unit_key, "")
            try:
                normalize_number(number, unit, binding.attribute.canonical_unit)
            except ValidationError as exc:
                self.add_error(unit_key, exc)
        return cleaned

    @transaction.atomic
    def save(self):
        if not self.is_valid():
            raise ValueError("Невозможно сохранить некорректные характеристики.")
        for binding in self.bindings:
            key = self.value_key(binding)
            value = self.cleaned_data.get(key)
            if value is None or value == "":
                ProductAttributeValue.objects.filter(
                    product=self.product, attribute=binding.attribute
                ).delete()
                continue
            kind = binding.attribute.data_type
            defaults = {
                "number_value": None, "integer_value": None,
                "text_value": "", "boolean_value": None, "unit": "",
                "normalized_number": None,
            }
            if kind == AttributeDefinition.DataType.NUMBER:
                defaults["number_value"] = value
                defaults["unit"] = self.cleaned_data.get(self.unit_key(binding), "")
            elif kind == AttributeDefinition.DataType.INTEGER:
                defaults["integer_value"] = value
            elif kind == AttributeDefinition.DataType.BOOLEAN:
                defaults["boolean_value"] = value
            else:
                defaults["text_value"] = value
            ProductAttributeValue.objects.update_or_create(
                product=self.product, attribute=binding.attribute,
                defaults=defaults,
            )
