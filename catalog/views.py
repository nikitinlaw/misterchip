from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.core.paginator import Paginator

from .models import (
    Brand, Category, Product, ProductAttributeValue, ProductType, ProductTypeAttribute,
)
from .utils import comparison_key, value_display


def home(request):
    categories = Category.objects.all()
    products = (
        Product.objects.filter(status=Product.Status.PUBLISHED)
        .select_related("product_type", "brand")[:20]
    )
    return render(request, "catalog/home.html", {"categories": categories, "products": products})


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("brand", "product_type", "product_type__category"),
        slug=slug, status=Product.Status.PUBLISHED,
    )
    bindings = list(
        ProductTypeAttribute.objects.filter(product_type=product.product_type, visible=True)
        .select_related("attribute").order_by("sort_order", "pk")
    )
    by_attribute = {
        value.attribute_id: value
        for value in product.attribute_values.select_related("attribute")
    }
    characteristics = [
        {"label": cfg.attribute.name, "value": value_display(by_attribute.get(cfg.attribute_id))}
        for cfg in bindings
    ]
    return render(request, "catalog/product_detail.html", {
        "product": product, "characteristics": characteristics,
        "references": product.references.all(),
        "related_articles": product.editorial_articles.filter(
            status="published",
        ).select_related("author")[:6],
        "related_projects": product.hardware_projects.filter(
            status="published",
        ).select_related("author")[:6],
    })


def decimal_filter(request, key, errors):
    raw = request.GET.get(key, "").strip()
    if not raw:
        return None
    try:
        result = Decimal(raw)
        if not result.is_finite():
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError):
        errors.append("Укажите корректное число для фильтра.")
        return None


def search(request):
    query = request.GET.get("q", "").strip()[:120]
    category_slug = request.GET.get("category", "")
    brand_slug = request.GET.get("brand", "")
    type_raw = request.GET.get("type", "")
    product_type = ProductType.objects.filter(pk=type_raw).first() if type_raw.isdecimal() else None
    products = Product.objects.filter(status=Product.Status.PUBLISHED).select_related("product_type", "brand")
    if query:
        products = products.filter(
            Q(title__icontains=query) | Q(model__icontains=query) |
            Q(mpn__icontains=query) | Q(brand__name__icontains=query)
        )
    if category_slug:
        products = products.filter(product_type__category__slug=category_slug)
    if brand_slug:
        products = products.filter(brand__slug=brand_slug)
    filters, errors = [], []
    if product_type:
        products = products.filter(product_type=product_type)
        configurations = list(
            ProductTypeAttribute.objects.filter(product_type=product_type, filterable=True)
            .select_related("attribute").order_by("sort_order", "pk")
        )
        for cfg in configurations:
            attribute = cfg.attribute
            base = f"a_{attribute.pk}"
            kind = attribute.data_type
            if kind in ("number", "integer"):
                min_key, max_key = f"{base}_min", f"{base}_max"
                lower = decimal_filter(request, min_key, errors)
                upper = decimal_filter(request, max_key, errors)
                spec = {
                    "label": attribute.name, "kind": "range",
                    "unit": attribute.canonical_unit,
                    "min_key": min_key, "max_key": max_key,
                    "min_value": request.GET.get(min_key, ""),
                    "max_value": request.GET.get(max_key, ""),
                }
                field = "normalized_number" if kind == "number" else "integer_value"
                if lower is not None:
                    products = products.filter(**{
                        "attribute_values__attribute": attribute,
                        f"attribute_values__{field}__gte": lower,
                    })
                if upper is not None:
                    products = products.filter(**{
                        "attribute_values__attribute": attribute,
                        f"attribute_values__{field}__lte": upper,
                    })
            elif kind == "choice":
                chosen = request.GET.get(base, "")
                spec = {
                    "label": attribute.name, "kind": "choice",
                    "name": base, "value": chosen,
                    "choices": attribute.allowed_values,
                }
                if chosen:
                    if chosen in attribute.allowed_values:
                        products = products.filter(
                            attribute_values__attribute=attribute,
                            attribute_values__text_value=chosen,
                        )
                    else:
                        errors.append(f"Недопустимое значение: {attribute.name}")
            elif kind == "boolean":
                chosen = request.GET.get(base, "")
                spec = {"label": attribute.name, "kind": "boolean", "name": base, "value": chosen}
                if chosen in ("true", "false"):
                    products = products.filter(
                        attribute_values__attribute=attribute,
                        attribute_values__boolean_value=(chosen == "true"),
                    )
                elif chosen:
                    errors.append(f"Недопустимое значение: {attribute.name}")
            else:
                chosen = request.GET.get(base, "").strip()[:80]
                spec = {"label": attribute.name, "kind": "text", "name": base, "value": chosen}
                if chosen:
                    products = products.filter(
                        attribute_values__attribute=attribute,
                        attribute_values__text_value__icontains=chosen,
                    )
            filters.append(spec)
    products = products.distinct().order_by("title", "pk")
    page = Paginator(products, 20).get_page(request.GET.get("page", "1"))
    page_query = request.GET.copy()
    page_query.pop("page", None)
    return render(request, "catalog/search.html", {
        "page": page, "query": query,
        "categories": Category.objects.all(), "types": ProductType.objects.filter(active=True).select_related("category"),
        "brands": Brand.objects.all(),
        "selected_category": category_slug, "selected_brand": brand_slug, "selected_type": product_type,
        "filters": filters, "errors": errors,
        "expand_specs": any(
            spec.get("min_value") or spec.get("max_value") or spec.get("value")
            for spec in filters
        ),
        "pagination_query": page_query.urlencode(),
    })


def compare(request):
    ids = request.GET.getlist("ids")
    if len(ids) == 1 and "," in ids[0]:
        ids = ids[0].split(",")
    if len(ids) < 2 or len(ids) > 4 or any(not value.isdecimal() for value in ids):
        return render(request, "catalog/compare_error.html", {
            "error": "Для сравнения выберите от двух до четырёх моделей."
        }, status=400)
    if len(set(ids)) != len(ids):
        return render(request, "catalog/compare_error.html", {
            "error": "Нельзя сравнить модель саму с собой."
        }, status=400)
    product_map = {
        str(p.pk): p for p in Product.objects.filter(
            pk__in=ids, status=Product.Status.PUBLISHED
        ).select_related("product_type", "brand")
    }
    if len(product_map) != len(ids):
        raise Http404("Модель недоступна для сравнения.")
    products = [product_map[pk] for pk in ids]
    if len({p.product_type_id for p in products}) != 1:
        return render(request, "catalog/compare_error.html", {
            "error": "Нельзя сравнивать товары разных типов: их параметры несопоставимы."
        }, status=400)
    bindings = list(
        ProductTypeAttribute.objects.filter(
            product_type=products[0].product_type, comparable=True, visible=True,
        ).select_related("attribute").order_by("sort_order", "pk")
    )
    stored = ProductAttributeValue.objects.filter(
        product__in=products, attribute_id__in=[b.attribute_id for b in bindings],
    ).select_related("attribute")
    values = {(v.product_id, v.attribute_id): v for v in stored}
    rows = []
    for binding in bindings:
        entries = [values.get((p.pk, binding.attribute_id)) for p in products]
        known = [comparison_key(v) for v in entries if comparison_key(v) is not None]
        rows.append({
            "name": binding.attribute.name,
            "unit": binding.attribute.canonical_unit,
            "values": [value_display(v) for v in entries],
            "different": len(set(known)) > 1,
        })
    return render(request, "catalog/compare.html", {
        "products": products, "rows": rows,
        "product_type": products[0].product_type,
    })
