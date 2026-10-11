from django import forms

from catalog.models import Product
from .models import Article


class ArticleForm(forms.ModelForm):
    rights_confirmed = forms.BooleanField(
        required=True, label="Подтверждаю права на публикуемые материалы"
    )

    class Meta:
        model = Article
        fields = (
            "title", "kind", "summary", "body", "video_url",
            "source_url", "related_products", "rights_confirmed",
        )
        widgets = {
            "body": forms.Textarea(attrs={"rows": 15}),
            "summary": forms.Textarea(attrs={"rows": 3}),
            "related_products": forms.SelectMultiple(attrs={"size": 6}),
        }
        labels = {
            "title": "Заголовок", "kind": "Тип материала",
            "summary": "Краткое описание", "body": "Текст публикации",
            "video_url": "Ссылка на видео", "source_url": "Ссылка на первоисточник",
            "related_products": "Связанные товары",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["related_products"].queryset = Product.objects.filter(
            status=Product.Status.PUBLISHED
        ).order_by("title")

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if len(body) < 80:
            raise forms.ValidationError("Добавьте содержательный текст (не менее 80 символов).")
        return body

    def clean_summary(self):
        summary = self.cleaned_data["summary"].strip()
        if not summary:
            raise forms.ValidationError("Укажите краткое описание.")
        return summary
