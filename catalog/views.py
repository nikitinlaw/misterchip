from django.shortcuts import get_object_or_404, render

from .models import Category, Product


def home(request):
    categories = Category.objects.all()
    products = Product.objects.filter(status=Product.Status.PUBLISHED).select_related("product_type", "brand")[:20]
    return render(request, "catalog/home.html", {"categories": categories, "products": products})


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("brand", "product_type", "product_type__category"),
        slug=slug, status=Product.Status.PUBLISHED,
    )
    values = product.attribute_values.select_related("attribute").all()
    return render(request, "catalog/product_detail.html", {"product": product, "values": values})
