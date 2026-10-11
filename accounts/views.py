"""Public registration, verified activation and account profile workflows."""
from smtplib import SMTPException

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordResetView
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods

from .forms import ProfileForm, RegistrationForm
from .models import Profile
from .security import auth_rate_limit, find_unverified_user, send_confirmation


@method_decorator(
    auth_rate_limit("login", max_requests=20, period_seconds=15 * 60),
    name="dispatch",
)
class LimitedLoginView(LoginView):
    template_name = "accounts/login.html"


@method_decorator(
    auth_rate_limit("password_reset", max_requests=6, period_seconds=60 * 60),
    name="dispatch",
)
class LimitedPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = "/account/password-reset/sent/"


@require_http_methods(["GET", "POST"])
@auth_rate_limit("register", max_requests=8, period_seconds=60 * 60)
def register(request):
    if request.user.is_authenticated:
        return redirect("account_dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
                send_confirmation(request, user)
        except (SMTPException, OSError):
            return HttpResponse(
                "Письмо пока не удалось отправить. Попробуйте позднее.",
                status=503,
            )
        return redirect("account_verification_sent")
    return render(request, "accounts/register.html", {"form": form})


@require_http_methods(["GET", "POST"])
@auth_rate_limit("verify_email", max_requests=20, period_seconds=15 * 60)
def verify_email(request, token):
    user = find_unverified_user(token)
    if user is None:
        return render(request, "accounts/verify_invalid.html", status=400)
    if request.method == "POST":
        updated = get_user_model().objects.filter(
            pk=user.pk, is_active=False, email=user.email,
        ).update(is_active=True)
        if updated != 1:
            return render(request, "accounts/verify_invalid.html", status=400)
        return redirect("account_verified")
    return render(request, "accounts/verify_email.html")


@require_http_methods(["GET", "POST"])
@auth_rate_limit("resend_email", max_requests=6, period_seconds=60 * 60)
def resend_verification(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        if len(email) <= 254:
            user = get_user_model().objects.filter(
                email__iexact=email, is_active=False,
            ).first()
            if user is not None:
                try:
                    send_confirmation(request, user)
                except (SMTPException, OSError):
                    return HttpResponse(
                        "Временно недоступно. Попробуйте позднее.", status=503,
                    )
        return redirect("account_verification_sent")
    return render(request, "accounts/resend_verification.html")


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
    person = get_object_or_404(
        get_user_model(), username=username, is_active=True
    )
    profile = Profile.objects.filter(user=person).first()
    publications = person.publications.filter(
        status="published",
    ).order_by("-published_at", "-pk")
    return render(request, "accounts/public_profile.html", {
        "person": person, "profile": profile, "publications": publications,
    })
