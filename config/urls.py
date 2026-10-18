from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from .health import healthz

urlpatterns = [
    path(
        "yandex_10e74506a1dcf479.html",
        TemplateView.as_view(template_name="yandex_10e74506a1dcf479.html"),
        name="yandex_verification",
    ),
    path("healthz/", healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("account/", include("accounts.urls")),
    path("articles/", include("editorial.urls")),
    path("projects/", include("projects.urls")),
    path("", include("catalog.urls")),
]
