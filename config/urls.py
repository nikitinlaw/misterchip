from django.contrib import admin
from django.urls import include, path
from .health import healthz

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("account/", include("accounts.urls")),
    path("articles/", include("editorial.urls")),
    path("projects/", include("projects.urls")),
    path("", include("catalog.urls")),
]
