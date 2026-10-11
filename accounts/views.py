from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import ProfileForm, RegistrationForm
from .models import Profile


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("account_dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("account_dashboard")
    return render(request, "accounts/register.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def dashboard(request):
    form = ProfileForm.for_user(
        request.user, request.POST if request.method == "POST" else None
    )
    if request.method == "POST" and form.is_valid():
        form.save(request.user)
        return redirect("account_dashboard")
    return render(request, "accounts/dashboard.html", {
        "form": form,
        "roles": request.user.business_roles.order_by("role"),
    })


def public_profile(request, username):
    person = get_object_or_404(get_user_model(), username=username, is_active=True)
    profile = Profile.objects.filter(user=person).first()
    publications = person.publications.filter(status="published").order_by("-published_at", "-pk")
    return render(request, "accounts/public_profile.html", {
        "person": person, "profile": profile, "publications": publications,
    })
