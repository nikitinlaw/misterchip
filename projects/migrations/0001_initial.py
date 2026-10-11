import decimal
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("catalog", "0002_productreference"),
    ]
    operations = [
        migrations.CreateModel(
            name="Project",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=220)),
                ("slug", models.SlugField(allow_unicode=True, max_length=220, unique=True)),
                ("summary", models.CharField(max_length=380)),
                ("description", models.TextField()),
                ("assembly_instructions", models.TextField()),
                ("license_notes", models.TextField(blank=True)),
                ("rights_confirmed", models.BooleanField(default=False)),
                ("status", models.CharField(
                    choices=[
                        ("draft", "Черновик"), ("submitted", "На проверке"),
                        ("published", "Опубликован"), ("rejected", "Отклонён"),
                        ("archived", "Архив"),
                    ],
                    db_index=True, default="draft", max_length=12,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="hardware_projects", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_hardware_projects", to=settings.AUTH_USER_MODEL)),
                ("related_products", models.ManyToManyField(blank=True, related_name="hardware_projects", to="catalog.product")),
            ],
            options={
                "ordering": ["-published_at", "-created_at"],
                "indexes": [models.Index(fields=["status", "-published_at"], name="project_public_idx")],
            },
        ),
        migrations.CreateModel(
            name="ProjectComponent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=220)),
                ("quantity", models.DecimalField(
                    decimal_places=3, default=decimal.Decimal("1.000"), max_digits=10,
                    validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.001"))],
                )),
                ("unit", models.CharField(
                    choices=[("pcs", "шт."), ("set", "комплект"), ("m", "метр")],
                    default="pcs", max_length=5,
                )),
                ("note", models.CharField(blank=True, max_length=300)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="project_bom_entries", to="catalog.product")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="components", to="projects.project")),
            ],
            options={
                "ordering": ["sort_order", "pk"],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="project_component_positive_qty"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ProjectResource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(
                    choices=[
                        ("schematic", "Электрическая схема"), ("pcb", "Файлы печатной платы"),
                        ("firmware", "Прошивка"), ("source", "Исходный код"),
                        ("model3d", "3D-модель для печати"),
                        ("video", "Видеоруководство"), ("guide", "Документация"),
                        ("other", "Другой материал"),
                    ], max_length=15,
                )),
                ("title", models.CharField(max_length=220)),
                ("url", models.URLField(max_length=1000)),
                ("rights_note", models.CharField(blank=True, help_text="Лицензия или право распространения ресурса", max_length=240)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="resources", to="projects.project")),
            ],
            options={
                "ordering": ["kind", "pk"],
                "constraints": [
                    models.UniqueConstraint(fields=("project", "url"), name="uniq_project_resource_url"),
                ],
            },
        ),
    ]
