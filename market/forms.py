"""Explicit forms for the Market's public and shop-member workflows."""
from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from catalog.models import Product

from .models import Inquiry, Offer, SellerProfile, Shop, ShopMembership
from .services import INQUIRY_CONSENT_TEXT


class SellerProfileForm(forms.ModelForm):
    class Meta:
        model = SellerProfile
        fields = ("legal_name", "legal_type", "inn", "description")
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}
        help_texts = {
            "legal_name": "Укажите полное наименование юридического лица или ФИО предпринимателя.",
            "inn": "Сведения проверит редакция до публикации магазинов.",
        }


class ShopForm(forms.ModelForm):
    class Meta:
        model = Shop
        fields = (
            "name", "city", "address", "description", "public_email",
            "public_phone", "website", "opening_hours",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}
        help_texts = {
            "public_email": "Этот адрес будет виден всем посетителям. Личный email вашей учётной записи не публикуется.",
            "public_phone": "Укажите телефон, который можно показать на странице магазина.",
        }


class OfferForm(forms.ModelForm):
    valid_until = forms.DateTimeField(
        label="Сведения актуальны до", required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="Время московское. Если срок не указан, покупателю предложат уточнить цену и наличие.",
    )

    class Meta:
        model = Offer
        fields = (
            "product", "price", "stock_quantity", "availability", "condition",
            "condition_description", "seller_sku", "fulfilment", "lead_time",
            "comment", "external_url", "valid_until",
        )
        labels = {
            "product": "Модель из каталога", "availability": "Наличие",
            "condition": "Состояние товара", "external_url": "Ссылка на предложение магазина",
        }
        widgets = {
            "condition_description": forms.Textarea(attrs={"rows": 3}),
            "comment": forms.Textarea(attrs={"rows": 4}),
            "price": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "stock_quantity": forms.NumberInput(attrs={"min": "0", "step": "1"}),
        }
        help_texts = {
            "stock_quantity": "Оставьте пустым, если точное количество неизвестно.",
            "fulfilment": "Например: самовывоз, доставка по России или получение в магазине.",
            "condition_description": "Для бывшего в употреблении и восстановленного товара описание обязательно.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(
            status=Product.Status.PUBLISHED,
        ).select_related("brand", "product_type").order_by("title", "pk")

    def clean_valid_until(self):
        value = self.cleaned_data.get("valid_until")
        if value is not None and value <= timezone.now():
            raise forms.ValidationError("Укажите будущую дату подтверждения или оставьте срок пустым.")
        return value


class OfferConfirmationForm(forms.Form):
    valid_until = forms.DateTimeField(
        label="Подтвердить цену и наличие до",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="Время московское. Подтверждайте только проверенные сведения.",
    )

    def clean_valid_until(self):
        value = self.cleaned_data["valid_until"]
        if value <= timezone.now():
            raise forms.ValidationError("Укажите будущую дату.")
        return value


class MembershipForm(forms.Form):
    username = forms.CharField(
        label="Логин сотрудника", max_length=150,
        help_text="Сотрудник должен заранее зарегистрироваться и подтвердить email. Введите его точный логин.",
    )
    role = forms.ChoiceField(label="Доступ к магазину", choices=ShopMembership.Role.choices)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        self.target_user = get_user_model().objects.filter(
            username=username, is_active=True,
        ).first()
        if self.target_user is None:
            raise forms.ValidationError("Не найден участник с таким подтверждённым логином.")
        return username


class MembershipUpdateForm(forms.ModelForm):
    class Meta:
        model = ShopMembership
        fields = ("role", "is_active")
        labels = {"role": "Доступ к магазину"}


class VisibilityForm(forms.Form):
    status = forms.ChoiceField(
        label="Действие",
        choices=(("paused", "Приостановить"), ("archived", "Перенести в архив")),
    )


class InquiryForm(forms.Form):
    name = forms.CharField(label="Как к вам обращаться", max_length=120, required=False)
    email = forms.EmailField(label="Email для ответа")
    phone = forms.CharField(label="Телефон", max_length=60, required=False)
    message = forms.CharField(
        label="Сообщение магазину", min_length=10, max_length=5000,
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    consent = forms.BooleanField(label=INQUIRY_CONSENT_TEXT, required=True)
    submission_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, actor=None, submission_key=None, **kwargs):
        initial = dict(kwargs.pop("initial", {}))
        if submission_key is not None:
            initial["submission_key"] = submission_key
        active_actor = actor if actor is not None and actor.is_authenticated and actor.is_active else None
        if active_actor:
            initial.setdefault("name", active_actor.get_full_name() or active_actor.username)
            initial["email"] = active_actor.email
        super().__init__(*args, initial=initial, **kwargs)
        if active_actor:
            self.fields["email"].disabled = True
            self.fields["email"].help_text = "Ответ придёт на подтверждённый адрес вашей учётной записи."
        else:
            self.fields["email"].help_text = "Магазин получит этот адрес, чтобы ответить на ваше обращение."
        self.fields["phone"].help_text = "Необязательно. Телефон будет доступен только сотрудникам этого магазина."

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class InquiryReplyForm(forms.Form):
    reply_text = forms.CharField(
        label="Ответ покупателю", max_length=5000,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Этот текст будет доступен покупателю и включён в уведомление об ответе.",
    )


class InquiryStatusForm(forms.Form):
    status = forms.ChoiceField(
        label="Статус обращения",
        choices=(
            (Inquiry.Status.VIEWED, Inquiry.Status.VIEWED.label),
            (Inquiry.Status.CLOSED, Inquiry.Status.CLOSED.label),
        ),
    )
