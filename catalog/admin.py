from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .admin_forms import (
    SpecificationsForm, ProductTypeSettingsForm, TypeAttributeInlineForm,
)
admin.site.site_header = "MISTERCHIP — управление"
admin.site.site_title = "Управление MISTERCHIP"
admin.site.index_title = "Панель управления"


class RussianFieldsMixin:
    """Use readable field labels in Admin without changing database schema."""

    field_labels = {}

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in self.field_labels:
            kwargs.setdefault("label", self.field_labels[db_field.name])
        return super().formfield_for_dbfield(db_field, request, **kwargs)


from .models import (
    AttributeDefinition, Brand, Category, Product,
    ProductType, ProductTypeAttribute, ProductReference, TrademarkGood,
)


@admin.register(Category)
class CategoryAdmin(RussianFieldsMixin, admin.ModelAdmin):
    field_labels = {"name": "Название", "slug": "Адрес (slug)", "order": "Порядок"}
    list_display = ("name", "order")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(TrademarkGood)
class TrademarkGoodAdmin(admin.ModelAdmin):
    list_display = ("source_position", "original_name", "category")
    list_filter = ("category",)
    search_fields = ("original_name",)
    readonly_fields = ("source_position", "original_name", "category", "nice_class")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Brand)
class BrandAdmin(RussianFieldsMixin, admin.ModelAdmin):
    field_labels = {"name": "Название", "slug": "Адрес (slug)"}
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


class ProductTypeAttributeInline(admin.TabularInline):
    model = ProductTypeAttribute
    form = TypeAttributeInlineForm
    extra = 0
    fields = ("attribute", "required", "filterable", "comparable", "visible", "sort_order")
    verbose_name = "Характеристика"
    verbose_name_plural = "Характеристики товара"
    show_change_link = False


@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    form = ProductTypeSettingsForm
    list_display = ("name", "category", "active")
    list_filter = ("category",)
    search_fields = ("name", "slug", "category__name")
    fields = (("category", "name"), ("slug", "active"))
    inlines = [ProductTypeAttributeInline]


@admin.register(AttributeDefinition)
class AttributeDefinitionAdmin(RussianFieldsMixin, admin.ModelAdmin):
    field_labels = {
        "name": "Название", "code": "Код параметра",
        "data_type": "Тип значения", "canonical_unit": "Базовая единица измерения",
        "allowed_values": "Варианты выбора",
    }
    list_display = ("name", "code", "data_type", "canonical_unit")
    search_fields = ("name", "code")


class ProductReferenceInline(admin.TabularInline):
    model = ProductReference
    extra = 0


@admin.register(Product)
class ProductAdmin(RussianFieldsMixin, admin.ModelAdmin):
    field_labels = {
        "product_type": "Тип товара", "brand": "Производитель", "title": "Название",
        "model": "Модель", "mpn": "Артикул производителя", "slug": "Адрес (slug)",
        "description": "Описание", "status": "Статус",
    }
    list_display = ("title", "product_type", "brand", "status", "specifications_link")
    list_filter = ("status", "product_type")
    search_fields = ("title", "mpn", "model")
    inlines = [ProductReferenceInline]

    def get_readonly_fields(self, request, obj=None):
        return ("specifications_link", "product_type") if obj else ()

    @admin.display(description="Характеристики")
    def specifications_link(self, obj):
        if not obj or not obj.pk:
            return "Сначала сохраните модель."
        url = reverse("admin:catalog_product_specifications", args=[obj.pk])
        return format_html('<a href="{}">Настроить характеристики</a>', url)

    def get_urls(self):
        extra = [
            path(
                "<path:object_id>/specifications/",
                self.admin_site.admin_view(self.specifications_view),
                name="catalog_product_specifications",
            )
        ]
        return extra + super().get_urls()

    def specifications_view(self, request, object_id):
        product = self.get_object(request, object_id)
        if product is None:
            raise Http404("Модель не найдена.")
        if not self.has_change_permission(request, product):
            raise PermissionDenied
        form = SpecificationsForm(
            request.POST if request.method == "POST" else None,
            product=product,
        )
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "Характеристики сохранены.")
            return redirect(reverse("admin:catalog_product_change", args=[product.pk]))
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": product,
            "product": product,
            "title": f"Характеристики: {product.title}",
            "form": form,
            "change_url": reverse("admin:catalog_product_change", args=[product.pk]),
            "has_change_permission": True,
        }
        return TemplateResponse(
            request, "admin/catalog/product/specifications.html", context
        )
