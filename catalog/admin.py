from django.contrib import admin

from .models import (
    AttributeDefinition, Brand, Category, Product, ProductAttributeValue,
    ProductType, ProductTypeAttribute, TrademarkGood,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
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
class BrandAdmin(admin.ModelAdmin):
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


class ProductTypeAttributeInline(admin.TabularInline):
    model = ProductTypeAttribute
    extra = 1


@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "active")
    list_filter = ("category",)
    inlines = [ProductTypeAttributeInline]


@admin.register(AttributeDefinition)
class AttributeDefinitionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "data_type", "canonical_unit")
    search_fields = ("name", "code")


class ProductAttributeValueInline(admin.TabularInline):
    model = ProductAttributeValue
    extra = 0

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "attribute":
            object_id = (request.resolver_match.kwargs or {}).get("object_id")
            product = Product.objects.filter(pk=object_id).first() if object_id else None
            if product:
                ids = ProductTypeAttribute.objects.filter(product_type=product.product_type).values_list("attribute_id", flat=True)
                kwargs["queryset"] = AttributeDefinition.objects.filter(pk__in=ids)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "product_type", "brand", "status")
    list_filter = ("status", "product_type")
    search_fields = ("title", "mpn", "model")
    inlines = [ProductAttributeValueInline]
