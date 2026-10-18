"""Explicit moderation actions; admin edit forms cannot bypass Market workflows."""
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError

from .models import Inquiry, MarketEvent, Notification, Offer, SellerProfile, Shop, ShopMembership
from .permissions import can_moderate
from .services import moderate_seller, set_offer_status, set_shop_status


def _apply(modeladmin, request, queryset, callback):
    if not can_moderate(request.user):
        raise PermissionDenied
    passed = skipped = 0
    for obj in queryset:
        try:
            callback(obj)
            passed += 1
        except ValidationError:
            skipped += 1
    level = messages.WARNING if skipped else messages.SUCCESS
    modeladmin.message_user(request, f"Обработано: {passed}. Не соответствует условиям перехода: {skipped}.", level)


@admin.action(description="Подтвердить проверенные сведения продавцов")
def verify_sellers(modeladmin, request, queryset):
    _apply(modeladmin, request, queryset, lambda obj: moderate_seller(actor=request.user, seller=obj, status=SellerProfile.Status.VERIFIED))


@admin.action(description="Вернуть сведения продавцов на доработку")
def reject_sellers(modeladmin, request, queryset):
    _apply(modeladmin, request, queryset, lambda obj: moderate_seller(actor=request.user, seller=obj, status=SellerProfile.Status.REJECTED, note="Уточните сведения продавца и отправьте их повторно."))


@admin.action(description="Приостановить продавцов и публичность их магазинов")
def suspend_sellers(modeladmin, request, queryset):
    _apply(modeladmin, request, queryset, lambda obj: moderate_seller(actor=request.user, seller=obj, status=SellerProfile.Status.SUSPENDED))


@admin.action(description="Опубликовать проверенные магазины")
def publish_shops(modeladmin, request, queryset):
    _apply(modeladmin, request, queryset, lambda obj: set_shop_status(actor=request.user, shop=obj, status=Shop.Status.PUBLISHED))


@admin.action(description="Вернуть магазины на доработку")
def reject_shops(modeladmin, request, queryset):
    _apply(modeladmin, request, queryset, lambda obj: set_shop_status(actor=request.user, shop=obj, status=Shop.Status.REJECTED, note="Уточните сведения магазина и отправьте на проверку."))


@admin.action(description="Приостановить публикацию магазинов")
def pause_shops(modeladmin, request, queryset):
    _apply(modeladmin, request, queryset, lambda obj: set_shop_status(actor=request.user, shop=obj, status=Shop.Status.PAUSED))


@admin.action(description="Опубликовать проверенные предложения")
def publish_offers(modeladmin, request, queryset):
    _apply(modeladmin, request, queryset, lambda obj: set_offer_status(actor=request.user, offer=obj, status=Offer.Status.PUBLISHED))


@admin.action(description="Вернуть предложения на доработку")
def reject_offers(modeladmin, request, queryset):
    _apply(modeladmin, request, queryset, lambda obj: set_offer_status(actor=request.user, offer=obj, status=Offer.Status.REJECTED, note="Уточните предложение и отправьте его на проверку."))


@admin.action(description="Приостановить публикацию предложений")
def pause_offers(modeladmin, request, queryset):
    _apply(modeladmin, request, queryset, lambda obj: set_offer_status(actor=request.user, offer=obj, status=Offer.Status.PAUSED))


class ModerationAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_module_permission(self, request):
        return can_moderate(request.user)

    def has_view_permission(self, request, obj=None):
        return can_moderate(request.user)

    def has_change_permission(self, request, obj=None):
        return can_moderate(request.user)

    def get_actions(self, request):
        return super().get_actions(request) if can_moderate(request.user) else {}

    def save_model(self, request, obj, form, change):
        # All data fields are read-only. State changes use the actions/services above.
        if form.changed_data:
            raise PermissionDenied("Используйте предусмотренные действия проверки.")


@admin.register(SellerProfile)
class SellerProfileAdmin(ModerationAdmin):
    list_display = ("legal_name", "legal_type", "inn", "status", "created_at")
    list_filter = ("status", "legal_type")
    search_fields = ("legal_name", "inn", "user__username")
    actions = (verify_sellers, reject_sellers, suspend_sellers)


@admin.register(Shop)
class ShopAdmin(ModerationAdmin):
    list_display = ("name", "seller", "city", "status", "updated_at")
    list_filter = ("status", "city")
    search_fields = ("name", "seller__legal_name", "slug")
    actions = (publish_shops, reject_shops, pause_shops)


@admin.register(Offer)
class OfferAdmin(ModerationAdmin):
    list_display = ("product", "shop", "price", "availability", "status", "valid_until")
    list_filter = ("status", "availability", "condition")
    search_fields = ("product__title", "shop__name", "seller_sku")
    actions = (publish_offers, reject_offers, pause_offers)


class PrivateReadOnlyAdmin(admin.ModelAdmin):
    actions = None

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def _allowed(self, request):
        user = request.user
        return bool(user.is_active and (user.is_superuser or user.has_perm(f"market.view_{self.model._meta.model_name}")))

    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ShopMembership)
class ShopMembershipAdmin(PrivateReadOnlyAdmin):
    list_display = ("shop", "user", "role", "is_active")
    list_filter = ("role", "is_active")


@admin.register(Inquiry)
class InquiryAdmin(PrivateReadOnlyAdmin):
    list_display = ("public_id", "shop", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("public_id",)


@admin.register(Notification)
class NotificationAdmin(PrivateReadOnlyAdmin):
    list_display = ("event_key", "kind", "status", "attempts", "error_code", "created_at")
    list_filter = ("status", "kind")
    search_fields = ("event_key",)


@admin.register(MarketEvent)
class MarketEventAdmin(PrivateReadOnlyAdmin):
    list_display = ("action", "actor", "shop", "created_at")
    list_filter = ("action",)
