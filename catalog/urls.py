from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("catalog/search/", views.search, name="catalog_search"),
    path("catalog/compare/", views.compare, name="catalog_compare"),
    path("product/<slug:slug>/", views.product_detail, name="product_detail"),
]
