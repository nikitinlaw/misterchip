# Generated for MISTERCHIP: external technical references, no stored vendor PDFs.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ProductReference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(
                    choices=[
                        ("datasheet", "Спецификация производителя"),
                        ("manual", "Инструкция"),
                        ("driver", "Драйвер или утилита"),
                        ("other", "Другой технический источник"),
                    ], max_length=20,
                )),
                ("title", models.CharField(max_length=220)),
                ("url", models.URLField(max_length=1000)),
                ("publisher", models.CharField(max_length=180)),
                ("official", models.BooleanField(default=False)),
                ("verified_on", models.DateField(blank=True, null=True)),
                ("product", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="references", to="catalog.product",
                )),
            ],
            options={
                "ordering": ["kind", "title"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("product", "url"),
                        name="uniq_product_reference_url",
                    ),
                ],
            },
        ),
    ]
