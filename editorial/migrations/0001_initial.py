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
            name="Article",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=220)),
                ("slug", models.SlugField(allow_unicode=True, max_length=220, unique=True)),
                ("kind", models.CharField(
                    choices=[
                        ("review", "Обзор техники"), ("guide", "Инструкция"),
                        ("diy", "DIY-проект"), ("analysis", "Техническая статья"),
                        ("news", "Новость"),
                    ], default="guide", max_length=16,
                )),
                ("summary", models.CharField(max_length=380)),
                ("body", models.TextField()),
                ("video_url", models.URLField(blank=True)),
                ("source_url", models.URLField(blank=True)),
                ("rights_confirmed", models.BooleanField(default=False)),
                ("status", models.CharField(
                    choices=[
                        ("draft", "Черновик"), ("submitted", "На модерации"),
                        ("published", "Опубликовано"), ("rejected", "Отклонено"),
                        ("archived", "Снято с публикации"),
                    ], db_index=True, default="draft", max_length=16,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="publications", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_publications", to=settings.AUTH_USER_MODEL)),
                ("related_products", models.ManyToManyField(blank=True, related_name="editorial_articles", to="catalog.product")),
            ],
            options={
                "ordering": ["-published_at", "-created_at"],
                "indexes": [models.Index(fields=["status", "-published_at"], name="article_public_idx")],
            },
        ),
    ]
