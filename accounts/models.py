from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Created before initial migrations; supports multiple independent roles."""
    email = models.EmailField("Email", unique=True)

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self):
        return self.username


class UserRole(models.Model):
    class Role(models.TextChoices):
        BUYER = "buyer", "Покупатель"
        AUTHOR = "author", "Автор"
        REVIEWER = "reviewer", "Обзорщик"
        DEVELOPER = "developer", "Разработчик"
        SELLER = "seller", "Продавец"
        MANUFACTURER = "manufacturer", "Представитель производителя"
        EDITOR = "editor", "Редактор"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="business_roles")
    role = models.CharField(max_length=32, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Роль пользователя"
        verbose_name_plural = "Роли пользователей"
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="uniq_user_business_role"),
        ]

    def __str__(self):
        return f"{self.user}: {self.get_role_display()}"


class Profile(models.Model):
    """Public-facing details, separate from login/email and privileged access."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(max_length=1200, blank=True)
    website = models.URLField(blank=True)

    class Meta:
        verbose_name = "Профиль участника"
        verbose_name_plural = "Профили участников"

    def __str__(self):
        return self.display_name or self.user.username
