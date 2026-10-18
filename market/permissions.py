from django.db.models import Q

from .models import Inquiry, Shop, ShopMembership


def _active(user):
    return bool(user and user.is_authenticated and user.is_active)


def can_moderate(user):
    return _active(user) and (user.is_superuser or user.has_perm("market.moderate_market"))


def _shop_permission(user, shop, roles):
    if not _active(user):
        return False
    if user.is_superuser or shop.owner_id == user.pk:
        return True
    return ShopMembership.objects.filter(
        shop=shop, user=user, is_active=True, role__in=roles,
    ).exists()


def can_manage_shop(user, shop):
    return _shop_permission(user, shop, [ShopMembership.Role.MANAGER])


def can_manage_offers(user, shop):
    return _shop_permission(user, shop, [ShopMembership.Role.MANAGER, ShopMembership.Role.OFFERS])


def can_manage_inquiries(user, shop):
    return _shop_permission(user, shop, [ShopMembership.Role.MANAGER, ShopMembership.Role.INQUIRIES])


def can_manage_memberships(user, shop):
    return _active(user) and (user.is_superuser or shop.owner_id == user.pk)


def shops_for_user(user, capability=None):
    qs = Shop.objects.select_related("seller__user")
    if not _active(user):
        return qs.none()
    roles_by_capability = {
        None: ShopMembership.Role.values,
        "shop": [ShopMembership.Role.MANAGER],
        "offers": [ShopMembership.Role.MANAGER, ShopMembership.Role.OFFERS],
        "inquiries": [ShopMembership.Role.MANAGER, ShopMembership.Role.INQUIRIES],
        "memberships": [],
    }
    if capability not in roles_by_capability:
        raise ValueError("Unknown shop capability")
    if user.is_superuser:
        return qs
    return qs.filter(
        Q(seller__user=user) | Q(
            memberships__user=user, memberships__is_active=True,
            memberships__role__in=roles_by_capability[capability],
        )
    ).distinct()


def inquiries_for_user(user):
    qs = Inquiry.objects.select_related("shop__seller__user", "offer__product", "buyer")
    if not _active(user):
        return qs.none()
    if user.is_superuser:
        return qs
    allowed_shops = shops_for_user(user, "inquiries").values("pk")
    return qs.filter(Q(buyer=user) | Q(shop_id__in=allowed_shops)).distinct()


def can_view_inquiry(user, inquiry):
    return _active(user) and (inquiry.buyer_id == user.pk or can_manage_inquiries(user, inquiry.shop))
