from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, UserRole


class UserRoleInline(admin.TabularInline):
    model = UserRole
    extra = 0


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = [UserRoleInline]
    list_display = ("username", "email", "is_staff", "is_active")


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "created_at")
    list_filter = ("role",)
