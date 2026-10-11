from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import UserRole
from catalog.models import Product
from .forms import ArticleForm
from .models import Article


def can_author(user):
    return user.is_authenticated and user.is_active and user.business_roles.filter(
        role=UserRole.Role.AUTHOR
    ).exists()


def unique_article_slug(title):
    base = slugify(title, allow_unicode=True)[:190].strip("-") or "article"
    slug, serial = base, 2
    while Article.objects.filter(slug=slug).exists():
        slug = f"{base[:185]}-{serial}"
        serial += 1
    return slug


def article_list(request):
    publications = Article.objects.filter(
        status=Article.Status.PUBLISHED,
    ).select_related("author")
    page = Paginator(publications, 12).get_page(request.GET.get("page"))
    return render(request, "editorial/list.html", {"page": page})


def article_detail(request, slug):
    article = get_object_or_404(
        Article.objects.select_related("author"), slug=slug,
        status=Article.Status.PUBLISHED,
    )
    products = article.related_products.filter(
        status=Product.Status.PUBLISHED
    ).select_related("product_type", "brand")
    return render(request, "editorial/detail.html", {
        "article": article, "products": products,
    })


@login_required
def my_articles(request):
    return render(request, "editorial/mine.html", {
        "articles": Article.objects.filter(author=request.user).order_by("-created_at"),
        "can_author": can_author(request.user),
    })


@login_required
@require_http_methods(["GET", "POST"])
def article_create(request):
    if not can_author(request.user):
        raise PermissionDenied("Для создания публикаций включите роль автора в профиле.")
    form = ArticleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            article = form.save(commit=False)
            article.author = request.user
            article.slug = unique_article_slug(article.title)
            article.status = Article.Status.DRAFT
            article.save()
            form.save_m2m()
        messages.success(request, "Черновик сохранён. Отправьте его редактору после проверки.")
        return redirect("my_articles")
    return render(request, "editorial/form.html", {"form": form, "editing": False})


@login_required
@require_http_methods(["GET", "POST"])
def article_edit(request, pk):
    article = get_object_or_404(Article, pk=pk, author=request.user)
    if not can_author(request.user):
        raise PermissionDenied
    if article.status not in (Article.Status.DRAFT, Article.Status.REJECTED):
        raise PermissionDenied("Отправленные и опубликованные тексты изменяет редактор.")
    form = ArticleForm(request.POST or None, instance=article)
    if request.method == "POST" and form.is_valid():
        edited = form.save(commit=False)
        edited.status = Article.Status.DRAFT
        edited.reviewed_at = None
        edited.reviewed_by = None
        edited.save()
        form.save_m2m()
        messages.success(request, "Изменения сохранены как черновик.")
        return redirect("my_articles")
    return render(request, "editorial/form.html", {
        "form": form, "editing": True, "article": article,
    })


@login_required
@require_POST
def article_submit(request, pk):
    article = get_object_or_404(Article, pk=pk, author=request.user)
    if not can_author(request.user):
        raise PermissionDenied
    if article.status not in (Article.Status.DRAFT, Article.Status.REJECTED):
        raise PermissionDenied("Текст уже направлен редактору или опубликован.")
    if not article.rights_confirmed or len(article.body.strip()) < 80:
        messages.error(request, "Прежде чем отправить материал, подтвердите права и проверьте текст.")
        return redirect("article_edit", pk=article.pk)
    article.status = Article.Status.SUBMITTED
    article.submitted_at = timezone.now()
    article.save(update_fields=["status", "submitted_at", "updated_at"])
    messages.success(request, "Публикация отправлена редактору.")
    return redirect("my_articles")
