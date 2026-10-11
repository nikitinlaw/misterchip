from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction

from .models import Profile, User, UserRole


SELF_SERVICE_ROLES = (
    (UserRole.Role.AUTHOR, "Автор статей"),
    (UserRole.Role.REVIEWER, "Обзорщик техники"),
    (UserRole.Role.DEVELOPER, "Разработчик устройств"),
)


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="Электронная почта", required=True)
    roles = forms.MultipleChoiceField(
        label="В каких качествах планируете участвовать",
        choices=SELF_SERVICE_ROLES, widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Указанный адрес уже используется.")
        return email

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            return super().save(commit=False)
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.is_active = False  # Must confirm email before authenticating.
        user.save()
        Profile.objects.create(user=user)
        UserRole.objects.get_or_create(user=user, role=UserRole.Role.BUYER)
        for role in self.cleaned_data.get("roles", []):
            UserRole.objects.get_or_create(user=user, role=role)
        return user


class ProfileForm(forms.Form):
    first_name = forms.CharField(label="Имя", max_length=150, required=False)
    last_name = forms.CharField(label="Фамилия", max_length=150, required=False)
    display_name = forms.CharField(label="Публичное имя", max_length=100, required=False)
    bio = forms.CharField(label="О себе", max_length=1200, widget=forms.Textarea(attrs={"rows": 5}), required=False)
    website = forms.URLField(label="Сайт или портфолио", required=False)
    roles = forms.MultipleChoiceField(
        label="Мои направления",
        choices=SELF_SERVICE_ROLES, widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    @classmethod
    def for_user(cls, user, data=None):
        profile = Profile.objects.filter(user=user).first()
        initial = {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": profile.display_name if profile else "",
            "bio": profile.bio if profile else "",
            "website": profile.website if profile else "",
            "roles": list(user.business_roles.filter(
                role__in=[role for role, _ in SELF_SERVICE_ROLES]
            ).values_list("role", flat=True)),
        }
        return cls(data, initial=initial)

    @transaction.atomic
    def save(self, user):
        if not self.is_valid():
            raise ValueError("Форма не прошла проверку.")
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.save(update_fields=["first_name", "last_name"])
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.display_name = self.cleaned_data["display_name"]
        profile.bio = self.cleaned_data["bio"]
        profile.website = self.cleaned_data["website"]
        profile.save()
        selected = set(self.cleaned_data["roles"])
        allowed = {role for role, _ in SELF_SERVICE_ROLES}
        user.business_roles.filter(role__in=allowed - selected).delete()
        for role in selected:
            UserRole.objects.get_or_create(user=user, role=role)
        return user
