from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.register, name="account_register"),
    path("login/", LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("logout/", LogoutView.as_view(next_page="home"), name="logout"),
    path("profile/", views.dashboard, name="account_dashboard"),
    path("authors/<str:username>/", views.public_profile, name="public_profile"),
]
