"""Russian display names for catalogue administration; metadata-only."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("catalog", "0002_productreference")]

    operations = [
        migrations.AlterModelOptions(name="category", options={"ordering":["order","name"],"verbose_name":"Раздел каталога","verbose_name_plural":"Разделы каталога"}),
        migrations.AlterModelOptions(name="trademarkgood", options={"ordering":["source_position"],"verbose_name":"Товар из свидетельства","verbose_name_plural":"Товары из свидетельства"}),
        migrations.AlterModelOptions(name="brand", options={"verbose_name":"Производитель","verbose_name_plural":"Производители"}),
        migrations.AlterModelOptions(name="producttype", options={"verbose_name":"Тип товара","verbose_name_plural":"Типы товаров"}),
        migrations.AlterModelOptions(name="attributedefinition", options={"verbose_name":"Характеристика","verbose_name_plural":"Характеристики"}),
        migrations.AlterModelOptions(name="producttypeattribute", options={"ordering":["sort_order","id"],"verbose_name":"Характеристика типа товара","verbose_name_plural":"Характеристики типа товара"}),
        migrations.AlterModelOptions(name="product", options={"verbose_name":"Модель товара","verbose_name_plural":"Модели товаров"}),
        migrations.AlterModelOptions(name="productattributevalue", options={"verbose_name":"Значение характеристики","verbose_name_plural":"Значения характеристик"}),
        migrations.AlterModelOptions(name="productreference", options={"ordering":["kind","title"],"verbose_name":"Источник документации","verbose_name_plural":"Источники документации"}),
    ]
