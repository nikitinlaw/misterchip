"""Load the verbatim 373 Nice class 9 entries from XLSX or bundled CSV."""
import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook

from catalog.models import Category, TrademarkGood
from catalog.seed import CATEGORY_SLUGS


class Command(BaseCommand):
    help = "Validate or import RU 948080 goods, preserving the original wording"

    def add_arguments(self, parser):
        default = settings.BASE_DIR / "data" / "trademark_goods_ru948080.csv"
        parser.add_argument("source_file", nargs="?", default=str(default))
        parser.add_argument("--check-only", action="store_true", help="Validate without database changes")

    @staticmethod
    def read_csv(path):
        with open(path, encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            expected = ["source_position", "category", "original_name"]
            if reader.fieldnames != expected:
                raise CommandError("CSV должен содержать три поля: " + ", ".join(expected))
            return [
                (row["source_position"], row["category"], row["original_name"])
                for row in reader
            ]

    @staticmethod
    def read_xlsx(path):
        book = load_workbook(path, read_only=True, data_only=True)
        if "Каталог товаров" not in book.sheetnames:
            raise CommandError("Не найден лист «Каталог товаров».")
        rows = list(book["Каталог товаров"].iter_rows(values_only=True))
        header_at = next((
            i for i, row in enumerate(rows) if len(row) >= 3
            and str(row[0]).strip() == "№ в перечне свидетельства"
            and str(row[1]).strip() == "Категория интернет-магазина"
            and str(row[2]).strip() == "Товар (дословно по свидетельству)"
        ), None)
        if header_at is None:
            raise CommandError("Не найдены точные заголовки трёх исходных колонок.")
        return [tuple(row[:3]) for row in rows[header_at + 1:] if row and row[0] is not None]

    def handle(self, *args, **options):
        source_path = Path(options["source_file"])
        if not source_path.is_file():
            raise CommandError(f"Файл не найден: {source_path}")
        if source_path.suffix.lower() == ".csv":
            raw_rows = self.read_csv(source_path)
        elif source_path.suffix.lower() == ".xlsx":
            raw_rows = self.read_xlsx(source_path)
        else:
            raise CommandError("Поддерживаются только CSV и XLSX.")
        goods = []
        for position_raw, category, original_name in raw_rows:
            try:
                position = int(position_raw)
            except (ValueError, TypeError):
                raise CommandError(f"Некорректный номер позиции: {position_raw!r}")
            if category not in CATEGORY_SLUGS or not isinstance(original_name, str) or not original_name.strip():
                raise CommandError(f"Некорректная категория или название в позиции {position}")
            goods.append((position, category, original_name))
        if len(goods) != 373 or {g[0] for g in goods} != set(range(1, 374)):
            raise CommandError("Ожидалось ровно 373 уникальных номера позиций от 1 до 373.")
        if len({g[2] for g in goods}) != 373:
            raise CommandError("В источнике повторяются дословные названия; требуется проверка.")
        if options["check_only"]:
            self.stdout.write(self.style.SUCCESS("Проверено 373 уникальных записи; БД не изменена."))
            return
        with transaction.atomic():
            categories = {}
            for i, (name, slug) in enumerate(CATEGORY_SLUGS.items(), 1):
                category, _ = Category.objects.update_or_create(
                    name=name, defaults={"slug": slug, "order": i},
                )
                categories[name] = category
            for position, name, original in goods:
                TrademarkGood.objects.update_or_create(
                    source_position=position,
                    defaults={"category": categories[name], "original_name": original, "nice_class": 9},
                )
        self.stdout.write(self.style.SUCCESS("Загружены/обновлены все 373 позиции без изменения текста."))
