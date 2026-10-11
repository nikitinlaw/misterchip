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

from .forms import ComponentFormSet, ProjectForm, ResourceFormSet
from .models import Project


def may_develop(user):
    return user.is_authenticated and user.is_active and user.business_roles.filter(
        role__in=(UserRole.Role.AUTHOR, UserRole.Role.DEVELOPER),
    ).exists()


def unique_project_slug(title):
    base = slugify(title, allow_unicode=True)[:180].strip("-") or "device-project"
    slug, i = base, 2
    while Project.objects.filter(slug=slug).exists():
        slug = f"{base[:170]}-{i}"
        i += 1
    return slug


def project_list(request):
    projects = Project.objects.filter(
        status=Project.Status.PUBLISHED,
    ).select_related("author")
    return render(request, "projects/list.html", {
        "page": Paginator(projects, 12).get_page(request.GET.get("page")),
    })


def project_detail(request, slug):
    project = get_object_or_404(
        Project.objects.select_related("author"),
        status=Project.Status.PUBLISHED, slug=slug,
    )
    components = project.components.select_related("product").all()
    products = project.related_products.filter(
        status=Product.Status.PUBLISHED,
    ).select_related("brand", "product_type")
    resources = project.resources.all()
    return render(request, "projects/detail.html", {
        "project": project, "components": components,
        "resources": resources, "products": products,
    })


@login_required
def my_projects(request):
    return render(request, "projects/mine.html", {
        "projects": Project.objects.filter(author=request.user).order_by("-created_at"),
        "may_develop": may_develop(request.user),
    })


@login_required
@require_http_methods(["GET", "POST"])
def project_create(request):
    if not may_develop(request.user):
        raise PermissionDenied("Требуется роль автора или разработчика.")
    return _edit_project(request, Project(author=request.user), created=True)


@login_required
@require_http_methods(["GET", "POST"])
def project_edit(request, pk):
    project = get_object_or_404(Project, pk=pk, author=request.user)
    if not may_develop(request.user):
        raise PermissionDenied
    if project.status not in (Project.Status.DRAFT, Project.Status.REJECTED):
        raise PermissionDenied("Отправленный или опубликованный проект закрыт для правок.")
    return _edit_project(request, project, created=False)


def _edit_project(request, project, *, created):
    payload = request.POST if request.method == "POST" else None
    form = ProjectForm(payload, instance=project)
    parts = ComponentFormSet(payload, instance=project, prefix="parts")
    resources = ResourceFormSet(payload, instance=project, prefix="resources")
    if request.method == "POST" and form.is_valid() and parts.is_valid() and resources.is_valid():
        with transaction.atomic():
            record = form.save(commit=False)
            record.author = request.user
            record.status = Project.Status.DRAFT
            record.reviewed_at = None
            record.reviewed_by = None
            record.submitted_at = None
            if created:
                record.slug = unique_project_slug(record.title)
            record.save()
            form.save_m2m()
            parts.instance = record
            resources.instance = record
            parts.save()
            resources.save()
        messages.success(request, "Черновик DIY-проекта сохранён.")
        return redirect("my_projects")
    return render(request, "projects/form.html", {
        "form": form, "parts": parts, "resources": resources,
        "created": created,
    })


@login_required
@require_POST
def project_submit(request, pk):
    project = get_object_or_404(Project, pk=pk, author=request.user)
    if not may_develop(request.user):
        raise PermissionDenied
    if project.status not in (Project.Status.DRAFT, Project.Status.REJECTED):
        raise PermissionDenied
    if not project.rights_confirmed or len(project.assembly_instructions.strip()) < 70:
        messages.error(request, "Проверьте права и инструкцию перед отправкой.")
        return redirect("project_edit", pk=project.pk)
    project.status = Project.Status.SUBMITTED
    project.submitted_at = timezone.now()
    project.save(update_fields=["status", "submitted_at", "updated_at"])
    messages.success(request, "DIY-проект передан на редакционную проверку.")
    return redirect("my_projects")
