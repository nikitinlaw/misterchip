from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=180, unique=True)
    slug = models.SlugField(max_length=160, unique=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class TrademarkGood(models.Model):
    """Verbatim source wording, legally distinct from concrete products."""
    source_position = models.PositiveIntegerField(unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="trademark_goods")
    original_name = models.TextField()
    nice_class = models.PositiveSmallIntegerField(default=9)

    class Meta:
        ordering = ["source_position"]

    def __str__(self):
        return self.original_name


class Brand(models.Model):
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=160, unique=True)

    def __str__(self):
        return self.name


class ProductType(models.Model):
    """Admin-configurable kind of product: RAM, resistor, SSD, etc."""
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="product_types")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["category", "slug"], name="uniq_product_type_slug")]

    def __str__(self):
        return f"{self.category} / {self.name}"


class AttributeDefinition(models.Model):
    class DataType(models.TextChoices):
        NUMBER = "number", "Число"
        INTEGER = "integer", "Целое число"
        TEXT = "text", "Текст"
        BOOLEAN = "boolean", "Да / нет"
        CHOICE = "choice", "Выбор из списка"

    code = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=160)
    data_type = models.CharField(max_length=12, choices=DataType.choices)
    canonical_unit = models.CharField(max_length=30, blank=True)
    allowed_values = models.JSONField(default=list, blank=True)

    def clean(self):
        if self.data_type == self.DataType.CHOICE and not self.allowed_values:
            raise ValidationError({"allowed_values": "Укажите варианты выбора."})

    def __str__(self):
        return self.name


class ProductTypeAttribute(models.Model):
    product_type = models.ForeignKey(ProductType, on_delete=models.CASCADE, related_name="configured_attributes")
    attribute = models.ForeignKey(AttributeDefinition, on_delete=models.PROTECT)
    required = models.BooleanField(default=False)
    filterable = models.BooleanField(default=True)
    comparable = models.BooleanField(default=True)
    visible = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["product_type", "attribute"], name="uniq_type_attribute")
        ]

    def __str__(self):
        return f"{self.product_type}: {self.attribute}"


class Product(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        REVIEW = "review", "На проверке"
        PUBLISHED = "published", "Опубликован"
        ARCHIVED = "archived", "Архив"

    product_type = models.ForeignKey(ProductType, on_delete=models.PROTECT, related_name="products")
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="products", blank=True, null=True)
    title = models.CharField(max_length=255)
    model = models.CharField(max_length=180, blank=True)
    mpn = models.CharField(max_length=180, blank=True)
    slug = models.SlugField(max_length=255, unique=True, allow_unicode=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


# Extending conversions must be explicit and reviewed; dimensions must match.
UNIT_CONVERSIONS = {
    "Ом": ("Ом", Decimal("1")),
    "кОм": ("Ом", Decimal("1000")),
    "МОм": ("Ом", Decimal("1000000")),
    "Вт": ("Вт", Decimal("1")),
    "мВт": ("Вт", Decimal("0.001")),
    "ГБ": ("ГБ", Decimal("1")),
    "МГц": ("МГц", Decimal("1")),
    "МТ/с": ("МТ/с", Decimal("1")),
}


def normalize_number(value, original_unit, canonical_unit):
    if not canonical_unit:
        if original_unit:
            raise ValidationError("Для характеристики не задана базовая единица.")
        return value
    if original_unit == canonical_unit:
        return value
    source = UNIT_CONVERSIONS.get(original_unit)
    target = UNIT_CONVERSIONS.get(canonical_unit)
    if source is None or target is None or source[0] != target[0]:
        raise ValidationError("Несопоставимые единицы измерения.")
    return value * source[1] / target[1]


class ProductAttributeValue(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="attribute_values")
    attribute = models.ForeignKey(AttributeDefinition, on_delete=models.PROTECT)
    number_value = models.DecimalField(max_digits=22, decimal_places=8, blank=True, null=True)
    integer_value = models.BigIntegerField(blank=True, null=True)
    text_value = models.TextField(blank=True)
    boolean_value = models.BooleanField(blank=True, null=True)
    unit = models.CharField(max_length=30, blank=True)
    normalized_number = models.DecimalField(max_digits=25, decimal_places=8, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "attribute"], name="uniq_product_attribute_value")
        ]

    def clean(self):
        if not self.product_id or not self.attribute_id:
            return
        if not ProductTypeAttribute.objects.filter(
            product_type_id=self.product.product_type_id, attribute_id=self.attribute_id
        ).exists():
            raise ValidationError({"attribute": "Параметр не назначен типу товара."})
        kind = self.attribute.data_type
        self.normalized_number = None
        if kind == AttributeDefinition.DataType.NUMBER:
            if self.number_value is None:
                raise ValidationError({"number_value": "Требуется числовое значение."})
            self.normalized_number = normalize_number(
                self.number_value, self.unit, self.attribute.canonical_unit
            )
        elif kind == AttributeDefinition.DataType.INTEGER and self.integer_value is None:
            raise ValidationError({"integer_value": "Требуется целое число."})
        elif kind == AttributeDefinition.DataType.BOOLEAN and self.boolean_value is None:
            raise ValidationError({"boolean_value": "Требуется значение да/нет."})
        elif kind in (AttributeDefinition.DataType.TEXT, AttributeDefinition.DataType.CHOICE):
            if not self.text_value:
                raise ValidationError({"text_value": "Значение не может быть пустым."})
            if kind == AttributeDefinition.DataType.CHOICE and self.text_value not in self.attribute.allowed_values:
                raise ValidationError({"text_value": "Значение отсутствует в разрешённом списке."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product}: {self.attribute}"


class ProductReference(models.Model):
    """Links to original technical documentation; no third-party files are copied."""

    class Kind(models.TextChoices):
        DATASHEET = "datasheet", "Спецификация производителя"
        MANUAL = "manual", "Инструкция"
        DRIVER = "driver", "Драйвер или утилита"
        OTHER = "other", "Другой технический источник"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="references")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=220)
    url = models.URLField(max_length=1000)
    publisher = models.CharField(max_length=180)
    official = models.BooleanField(default=False)
    verified_on = models.DateField(blank=True, null=True)

    class Meta:
        ordering = ["kind", "title"]
        constraints = [
            models.UniqueConstraint(fields=["product", "url"], name="uniq_product_reference_url"),
        ]

    def __str__(self):
        return f"{self.product}: {self.title}"
