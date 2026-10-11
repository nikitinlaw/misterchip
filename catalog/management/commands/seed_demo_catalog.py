"""Seed four real reference models from manufacturer specifications.

This is a small pilot; no fictitious sellers, reviews, prices, images or stock.
Repeated runs fill missing records, without overwriting editorial changes.
"""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import (
    AttributeDefinition, Brand, Category, Product, ProductAttributeValue,
    ProductReference, ProductType, ProductTypeAttribute,
)


ATTRIBUTE_SCHEMAS = {
    "ram": (
        ("capacity", "Объём памяти", "number", "ГБ", []),
        ("generation", "Тип памяти", "choice", "", ["DDR4", "DDR5"]),
        ("data_rate", "Скорость передачи данных", "number", "МТ/с", []),
        ("cl", "CAS latency (CL)", "integer", "", []),
        ("form_factor", "Форм-фактор", "choice", "", ["DIMM", "SO-DIMM"]),
        ("pins", "Количество контактов", "integer", "", []),
        ("modules", "Модулей в комплекте", "integer", "", []),
        ("xmp_voltage", "Напряжение XMP", "number", "В", []),
    ),
    "resistor": (
        ("resistance", "Сопротивление", "number", "Ом", []),
        ("tolerance", "Допуск", "number", "%", []),
        ("power", "Номинальная мощность", "number", "Вт", []),
        ("package", "Типоразмер корпуса", "choice", "", ["0603 (1608)"]),
        ("technology", "Технология", "choice", "", ["Толстоплёночный"]),
    ),
}

# Each row: manufacturer MPN; category slug; kind; official datasheet URL;
# typed values (value + unit for numerics, string for choices, integer otherwise).
MANUFACTURER_MODELS = [
    {
        "brand": "Kingston", "mpn": "KF552C40BB-16", "kind": "ram",
        "title": "Kingston FURY Beast 16 ГБ DDR5-5200 CL40 (KF552C40BB-16)",
        "description": "Модуль памяти Kingston FURY Beast DDR5 для настольного компьютера: 16 ГБ, профиль XMP 5200 MT/s, CL40. Производитель указывает 288 контактов.",
        "source": "https://www.kingston.com/dataSheets/KF552C40BB-16.pdf",
        "values": {
            "capacity": ("16", "ГБ"), "generation": "DDR5",
            "data_rate": ("5200", "МТ/с"), "cl": 40, "form_factor": "DIMM",
            "pins": 288, "modules": 1, "xmp_voltage": ("1.25", "В"),
        },
    },
    {
        "brand": "Kingston", "mpn": "KF556C40BB-16", "kind": "ram",
        "title": "Kingston FURY Beast 16 ГБ DDR5-5600 CL40 (KF556C40BB-16)",
        "description": "Модуль памяти Kingston FURY Beast DDR5 для настольного компьютера: 16 ГБ, профиль XMP 5600 MT/s, CL40. Производитель указывает 288 контактов.",
        "source": "https://www.kingston.com/datasheets/KF556C40BB-16.pdf",
        "values": {
            "capacity": ("16", "ГБ"), "generation": "DDR5",
            "data_rate": ("5600", "МТ/с"), "cl": 40, "form_factor": "DIMM",
            "pins": 288, "modules": 1, "xmp_voltage": ("1.25", "В"),
        },
    },
    {
        "brand": "YAGEO", "mpn": "RC0603FR-071KL", "kind": "resistor",
        "title": "YAGEO RC0603FR-071KL — резистор 1 кОм, 1%, 0,1 Вт",
        "description": "Стандартный толстоплёночный SMD-резистор YAGEO типоразмера 0603 (1608), сопротивление 1 кОм, допуск 1%, номинальная мощность 0,1 Вт при 70 °C.",
        "source": "https://yageogroup.com/component-documentation/download/specsheet/RC0603FR-071KL",
        "values": {
            "resistance": ("1", "кОм"), "tolerance": ("1", "%"),
            "power": ("0.1", "Вт"), "package": "0603 (1608)",
            "technology": "Толстоплёночный",
        },
    },
    {
        "brand": "YAGEO", "mpn": "RC0603FR-0710KL", "kind": "resistor",
        "title": "YAGEO RC0603FR-0710KL — резистор 10 кОм, 1%, 0,1 Вт",
        "description": "Стандартный толстоплёночный SMD-резистор YAGEO типоразмера 0603 (1608), сопротивление 10 кОм, допуск 1%, номинальная мощность 0,1 Вт при 70 °C.",
        "source": "https://yageogroup.com/component-documentation/download/specsheet/RC0603FR-0710KL",
        "values": {
            "resistance": ("10", "кОм"), "tolerance": ("1", "%"),
            "power": ("0.1", "Вт"), "package": "0603 (1608)",
            "technology": "Толстоплёночный",
        },
    },
]

TYPES = {
    "ram": ("Компьютеры и комплектующие", "Оперативная память", "ram"),
    "resistor": ("Радиодетали и электронные компоненты", "Резисторы", "resistors"),
}


class Command(BaseCommand):
    help = "Seed four sourced real models for pilot comparison; no seller prices"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Validate inside a rolled-back transaction",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        call_command("import_goods", verbosity=0)
        types = {}
        definitions = {}
        for kind, (category_name, type_name, slug) in TYPES.items():
            category = Category.objects.get(name=category_name)
            product_type, _ = ProductType.objects.get_or_create(
                category=category, slug=slug, defaults={"name": type_name},
            )
            types[kind] = product_type
            for idx, (code, name, data_type, unit, choices) in enumerate(
                ATTRIBUTE_SCHEMAS[kind], start=1
            ):
                attr, _ = AttributeDefinition.objects.get_or_create(
                    code=code, defaults={
                        "name": name, "data_type": data_type,
                        "canonical_unit": unit, "allowed_values": choices,
                    },
                )
                if (
                    attr.data_type != data_type
                    or attr.canonical_unit != unit
                    or (data_type == "choice" and set(choices) - set(attr.allowed_values))
                ):
                    raise CommandError(
                        f"Настройка существующей характеристики {code} несовместима с пилотом."
                    )
                definitions[code] = attr
                ProductTypeAttribute.objects.get_or_create(
                    product_type=product_type, attribute=attr,
                    defaults={
                        "required": True, "visible": True,
                        "filterable": True, "comparable": True, "sort_order": idx,
                    },
                )
        for row in MANUFACTURER_MODELS:
            brand, _ = Brand.objects.get_or_create(
                name=row["brand"], defaults={"slug": row["brand"].lower()},
            )
            product_type = types[row["kind"]]
            slug = row["mpn"].lower()
            existing = Product.objects.filter(brand=brand, mpn=row["mpn"]).first()
            if existing is not None and existing.product_type_id != product_type.pk:
                raise CommandError(f"Конфликт типа товара для {row['mpn']}.")
            product, _ = Product.objects.get_or_create(
                brand=brand, mpn=row["mpn"],
                defaults={
                    "product_type": product_type, "title": row["title"],
                    "model": row["mpn"], "slug": slug, "description": row["description"],
                    "status": Product.Status.PUBLISHED,
                },
            )
            for code, raw in row["values"].items():
                attr = definitions[code]
                payload = {}
                if attr.data_type == AttributeDefinition.DataType.NUMBER:
                    payload = {"number_value": Decimal(raw[0]), "unit": raw[1]}
                elif attr.data_type == AttributeDefinition.DataType.INTEGER:
                    payload = {"integer_value": raw}
                else:
                    payload = {"text_value": raw}
                ProductAttributeValue.objects.get_or_create(
                    product=product, attribute=attr, defaults=payload,
                )
            ProductReference.objects.get_or_create(
                product=product, url=row["source"],
                defaults={
                    "kind": ProductReference.Kind.DATASHEET,
                    "title": "Официальная спецификация производителя",
                    "publisher": row["brand"],
                    "official": True,
                    "verified_on": date(2026, 10, 11),
                },
            )
        if options["dry_run"]:
            transaction.set_rollback(True)
            self.stdout.write("Проверка успешна; изменения отменены (--dry-run).")
        else:
            self.stdout.write(self.style.SUCCESS(
                "Пилотные четыре модели и ссылки на документацию загружены."
            ))
