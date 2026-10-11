from urllib.parse import urlsplit

from django import forms
from django.forms import inlineformset_factory

from catalog.models import Product
from .models import Project, ProjectComponent, ProjectResource


class ProjectForm(forms.ModelForm):
    rights_confirmed = forms.BooleanField(
        required=True, label="Подтверждаю права на свои материалы и источники",
    )

    class Meta:
        model = Project
        fields = (
            "title", "summary", "description", "assembly_instructions",
            "license_notes", "related_products", "rights_confirmed",
        )
        labels = {
            "title": "Название проекта",
            "summary": "Краткое описание",
            "description": "Назначение и принцип работы",
            "assembly_instructions": "Инструкция по сборке и проверке",
            "license_notes": "Права и лицензии",
            "related_products": "Использованные товарные модели",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "assembly_instructions": forms.Textarea(attrs={"rows": 9}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["related_products"].queryset = Product.objects.filter(
            status=Product.Status.PUBLISHED,
        ).order_by("title")

    def clean_assembly_instructions(self):
        text = self.cleaned_data["assembly_instructions"].strip()
        if len(text) < 70:
            raise forms.ValidationError("Добавьте подробные шаги сборки (от 70 символов).")
        return text


class ComponentForm(forms.ModelForm):
    class Meta:
        model = ProjectComponent
        fields = ("name", "quantity", "unit", "product", "note")
        labels = {
            "name": "Компонент", "quantity": "Количество",
            "unit": "Ед. измерения", "product": "Модель из каталога",
            "note": "Примечание",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(
            status=Product.Status.PUBLISHED,
        ).order_by("title")


class ResourceForm(forms.ModelForm):
    class Meta:
        model = ProjectResource
        fields = ("kind", "title", "url", "rights_note")
        labels = {
            "kind": "Тип файла или ссылки", "title": "Название",
            "url": "Адрес HTTPS", "rights_note": "Источник / лицензия",
        }

    def clean_url(self):
        url = self.cleaned_data["url"]
        if urlsplit(url).scheme != "https":
            raise forms.ValidationError("Для ресурсов разрешены только HTTPS-ссылки.")
        return url


ComponentFormSet = inlineformset_factory(
    Project, ProjectComponent, form=ComponentForm,
    extra=2, can_delete=True, max_num=50, validate_max=True,
)
ResourceFormSet = inlineformset_factory(
    Project, ProjectResource, form=ResourceForm,
    extra=2, can_delete=True, max_num=30, validate_max=True,
)
