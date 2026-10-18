from django.urls import path

from . import views


urlpatterns = [
    path("", views.shop_list, name="market_shop_list"),
    path("shops/<str:slug>/", views.shop_detail, name="market_shop_detail"),
    path("seller/", views.seller_dashboard, name="market_seller_dashboard"),
    path("seller/profile/", views.seller_profile, name="market_seller_profile"),
    path("seller/shops/new/", views.shop_create, name="market_shop_create"),
    path("seller/shops/<int:shop_id>/", views.shop_dashboard, name="market_shop_dashboard"),
    path("seller/shops/<int:shop_id>/edit/", views.shop_edit, name="market_shop_edit"),
    path("seller/shops/<int:shop_id>/submit/", views.shop_submit, name="market_shop_submit"),
    path("seller/shops/<int:shop_id>/visibility/", views.shop_visibility, name="market_shop_visibility"),
    path("seller/shops/<int:shop_id>/members/", views.shop_members, name="market_shop_members"),
    path("seller/shops/<int:shop_id>/members/<int:member_id>/", views.membership_update, name="market_membership_update"),
    path("seller/shops/<int:shop_id>/offers/new/", views.offer_create, name="market_offer_create"),
    path("seller/offers/<int:offer_id>/edit/", views.offer_edit, name="market_offer_edit"),
    path("seller/offers/<int:offer_id>/submit/", views.offer_submit, name="market_offer_submit"),
    path("seller/offers/<int:offer_id>/visibility/", views.offer_visibility, name="market_offer_visibility"),
    path("seller/offers/<int:offer_id>/confirm/", views.offer_confirm, name="market_offer_confirm"),
    path("offers/<int:offer_id>/inquiry/", views.inquiry_create, name="market_inquiry_create"),
    path("inquiries/received/<uuid:public_id>/", views.inquiry_received, name="market_inquiry_received"),
    path("inquiries/", views.my_inquiries, name="market_my_inquiries"),
    path("inquiries/<uuid:public_id>/", views.inquiry_detail, name="market_inquiry_detail"),
    path("inquiries/<uuid:public_id>/cancel/", views.inquiry_cancel, name="market_inquiry_cancel"),
    path("seller/inquiries/<uuid:public_id>/", views.seller_inquiry_detail, name="market_seller_inquiry_detail"),
]
