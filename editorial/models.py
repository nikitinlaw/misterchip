from django.conf import settings
from django.db import models


class Article(models.Model):
    """Editorial content published only after staff review; plain text body."""
    class Kind(models.TextChoices):
        REVIEW = "review", "Обзор техники"
        GUIDE = "guide", "Инструкция"
        DIY = "diy", "DIY-проект"
        ANALYSIS = "analysis", "Техническая статья"
        NEWS = "news", "Новость"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        SUBMITTED = "submitted", "На модерации"
        PUBLISHED = "published", "Опубликовано"
        REJECTED = "rejected", "Отклонено"
        ARCHIVED = "archived", "Снято с публикации"

    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.GUIDE)
    summary = models.CharField(max_length=380)
    body = models.TextField()
    video_url = models.URLField(blank=True)
    source_url = models.URLField(blank=True)
    rights_confirmed = models.BooleanField(default=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="publications",
    )
    related_products = models.ManyToManyField(
        "catalog.Product", blank=True, related_name="editorial_articles",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    published_at = models.DateTimeField(blank=True, null=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name="reviewed_publications",
    )

    class Meta:
        verbose_name = "Публикация"
        verbose_name_plural = "Публикации"
        ordering = ["-published_at", "-created_at"]
        indexes = [models.Index(fields=["status", "-published_at"], name="article_public_idx")]

    def __str__(self):
        return self.title
