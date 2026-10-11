from django.contrib.auth.views import (
    LogoutView, PasswordResetCompleteView, PasswordResetConfirmView,
    PasswordResetDoneView,
)
from django.urls import path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path("register/", views.register, name="account_register"),
    path(
        "register/sent/",
        TemplateView.as_view(template_name="accounts/verification_sent.html"),
        name="account_verification_sent",
    ),
    path("verify/<str:token>/", views.verify_email, name="account_verify"),
    path(
        "verified/",
        TemplateView.as_view(template_name="accounts/verified.html"),
        name="account_verified",
    ),
    path("resend-verification/", views.resend_verification, name="account_resend"),
    path("login/", views.LimitedLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(next_page="home"), name="logout"),
    path(
        "password-reset/", views.LimitedPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/sent/",
        PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html",
        ), name="password_reset_done",
    ),
    path(
        "password-reset/confirm/<uidb64>/<token>/",
        PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url="/account/password-reset/complete/",
        ), name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html",
        ), name="password_reset_complete",
    ),
    path("profile/", views.dashboard, name="account_dashboard"),
    path("authors/<str:username>/", views.public_profile, name="public_profile"),
]
