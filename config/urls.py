from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("account/", include("accounts.urls")),
    path("articles/", include("editorial.urls")),
    path("projects/", include("projects.urls")),
    path("", include("catalog.urls")),
]
