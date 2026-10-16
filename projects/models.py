from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Project(models.Model):
    """Hardware DIY project, distinct from an editorial article."""
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        SUBMITTED = "submitted", "На проверке"
        PUBLISHED = "published", "Опубликован"
        REJECTED = "rejected", "Отклонён"
        ARCHIVED = "archived", "Архив"

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="hardware_projects",
    )
    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True)
    summary = models.CharField(max_length=380)
    description = models.TextField()
    assembly_instructions = models.TextField()
    license_notes = models.TextField(blank=True)
    rights_confirmed = models.BooleanField(default=False)
    related_products = models.ManyToManyField(
        "catalog.Product", related_name="hardware_projects", blank=True,
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    published_at = models.DateTimeField(blank=True, null=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="reviewed_hardware_projects", blank=True, null=True,
    )

    class Meta:
        verbose_name = "DIY-проект"
        verbose_name_plural = "DIY-проекты"
        ordering = ["-published_at", "-created_at"]
        indexes = [models.Index(fields=["status", "-published_at"], name="project_public_idx")]

    def __str__(self):
        return self.title


class ProjectComponent(models.Model):
    """Bill of materials: free-text name survives changes to catalog."""
    class Unit(models.TextChoices):
        PIECE = "pcs", "шт."
        SET = "set", "комплект"
        METER = "m", "метр"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="components")
    name = models.CharField(max_length=220)
    quantity = models.DecimalField(
        max_digits=10, decimal_places=3, default=Decimal("1.000"),
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    unit = models.CharField(max_length=5, choices=Unit.choices, default=Unit.PIECE)
    product = models.ForeignKey(
        "catalog.Product", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="project_bom_entries",
    )
    note = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Компонент проекта"
        verbose_name_plural = "Компоненты проектов"
        ordering = ["sort_order", "pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="project_component_positive_qty"),
        ]

    def __str__(self):
        return f"{self.name} — {self.quantity} {self.get_unit_display()}"


class ProjectResource(models.Model):
    """Only external links in MVP; no executable uploads."""
    class Kind(models.TextChoices):
        SCHEMATIC = "schematic", "Электрическая схема"
        PCB = "pcb", "Файлы печатной платы"
        FIRMWARE = "firmware", "Прошивка"
        SOURCE = "source", "Исходный код"
        MODEL_3D = "model3d", "3D-модель для печати"
        VIDEO = "video", "Видеоруководство"
        GUIDE = "guide", "Документация"
        OTHER = "other", "Другой материал"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="resources")
    kind = models.CharField(max_length=15, choices=Kind.choices)
    title = models.CharField(max_length=220)
    url = models.URLField(max_length=1000)
    rights_note = models.CharField(
        max_length=240, blank=True, help_text="Лицензия или право распространения ресурса",
    )

    class Meta:
        verbose_name = "Технический ресурс"
        verbose_name_plural = "Технические ресурсы"
        ordering = ["kind", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["project", "url"], name="uniq_project_resource_url"),
        ]

    def __str__(self):
        return self.title
