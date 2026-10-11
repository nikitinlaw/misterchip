from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Created before initial migrations; supports multiple independent roles."""
    email = models.EmailField("Email", unique=True)

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
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="uniq_user_business_role"),
        ]

    def __str__(self):
        return f"{self.user}: {self.get_role_display()}"
