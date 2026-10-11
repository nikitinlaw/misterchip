from django.contrib import admin, messages
from django.utils import timezone

from .models import Project, ProjectComponent, ProjectResource


@admin.action(description="Опубликовать прошедшие проверку DIY-проекты")
def publish_projects(modeladmin, request, queryset):
    count = queryset.filter(
        status=Project.Status.SUBMITTED, rights_confirmed=True,
    ).update(
        status=Project.Status.PUBLISHED, published_at=timezone.now(),
        reviewed_at=timezone.now(), reviewed_by=request.user,
    )
    modeladmin.message_user(request, f"Опубликовано: {count}", messages.SUCCESS)


@admin.action(description="Отклонить DIY-проекты на проверке")
def reject_projects(modeladmin, request, queryset):
    count = queryset.filter(status=Project.Status.SUBMITTED).update(
        status=Project.Status.REJECTED, reviewed_at=timezone.now(),
        reviewed_by=request.user,
    )
    modeladmin.message_user(request, f"Отклонено: {count}", messages.WARNING)


@admin.action(description="Снять опубликованные DIY-проекты")
def archive_projects(modeladmin, request, queryset):
    count = queryset.filter(status=Project.Status.PUBLISHED).update(
        status=Project.Status.ARCHIVED, reviewed_at=timezone.now(),
        reviewed_by=request.user,
    )
    modeladmin.message_user(request, f"Снято: {count}", messages.WARNING)


class ComponentInline(admin.TabularInline):
    model = ProjectComponent
    extra = 0
    max_num = 50


class ResourceInline(admin.TabularInline):
    model = ProjectResource
    extra = 0
    max_num = 30


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "status", "created_at", "published_at")
    list_filter = ("status", "created_at")
    search_fields = ("title", "author__username")
    readonly_fields = (
        "status", "submitted_at", "reviewed_at", "reviewed_by", "published_at",
    )
    filter_horizontal = ("related_products",)
    inlines = (ComponentInline, ResourceInline)
    actions = (publish_projects, reject_projects, archive_projects)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            fields.append("author")
        return fields

    def has_delete_permission(self, request, obj=None):
        return False
