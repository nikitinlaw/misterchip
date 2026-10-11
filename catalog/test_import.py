from django.core.management import call_command
from django.test import TestCase
from catalog.models import Category, TrademarkGood


class TrademarkCatalogImportTests(TestCase):
    def test_import_bundled_source_verbatim_and_idempotent(self):
        call_command("import_goods", verbosity=0)
        self.assertEqual(Category.objects.count(), 11)
        self.assertEqual(TrademarkGood.objects.count(), 373)
        self.assertEqual(TrademarkGood.objects.get(source_position=1).original_name, "антенны для телекоммуникаций")
        call_command("import_goods", verbosity=0)
        self.assertEqual(TrademarkGood.objects.count(), 373)
        self.assertEqual(TrademarkGood.objects.get(source_position=373).nice_class, 9)

    def test_check_only_does_not_write(self):
        call_command("import_goods", "--check-only", verbosity=0)
        self.assertEqual(TrademarkGood.objects.count(), 0)
