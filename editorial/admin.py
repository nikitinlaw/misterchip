from django.contrib import admin, messages
from django.utils import timezone

from .models import Article


@admin.action(description="Опубликовать проверенные материалы")
def publish_selected(modeladmin, request, queryset):
    count = queryset.filter(
        status=Article.Status.SUBMITTED, rights_confirmed=True
    ).update(
        status=Article.Status.PUBLISHED, published_at=timezone.now(),
        reviewed_at=timezone.now(), reviewed_by=request.user,
    )
    modeladmin.message_user(request, f"Опубликовано: {count}", messages.SUCCESS)


@admin.action(description="Отклонить материалы на модерации")
def reject_selected(modeladmin, request, queryset):
    count = queryset.filter(status=Article.Status.SUBMITTED).update(
        status=Article.Status.REJECTED, reviewed_at=timezone.now(),
        reviewed_by=request.user,
    )
    modeladmin.message_user(request, f"Отклонено: {count}", messages.WARNING)


@admin.action(description="Снять опубликованные материалы с публикации")
def archive_selected(modeladmin, request, queryset):
    count = queryset.filter(status=Article.Status.PUBLISHED).update(
        status=Article.Status.ARCHIVED, reviewed_at=timezone.now(),
        reviewed_by=request.user,
    )
    modeladmin.message_user(request, f"Снято: {count}", messages.WARNING)


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "author", "status", "submitted_at", "published_at")
    list_filter = ("status", "kind")
    search_fields = ("title", "author__username", "summary")
    filter_horizontal = ("related_products",)
    readonly_fields = ("status", "submitted_at", "published_at", "reviewed_at", "reviewed_by")
    actions = (publish_selected, reject_selected, archive_selected)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            fields.append("author")
        return fields

    def has_delete_permission(self, request, obj=None):
        return False
