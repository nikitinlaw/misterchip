"""Security primitives for sign-up email verification and shared auth throttling."""
import logging
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.http import HttpResponse
from django.urls import reverse
from django.utils.crypto import salted_hmac

log = logging.getLogger(__name__)

CONFIRMATION_SALT = "misterchip.account.email-verification.v1"
VERIFICATION_MAX_AGE = 24 * 60 * 60


def confirmation_token(user):
    return signing.dumps(
        {"uid": user.pk, "email": user.email},
        salt=CONFIRMATION_SALT,
    )


def find_unverified_user(token):
    from .models import User
    try:
        claim = signing.loads(
            token, salt=CONFIRMATION_SALT, max_age=VERIFICATION_MAX_AGE,
        )
        if not isinstance(claim, dict) or not isinstance(claim.get("uid"), int):
            return None
        user = User.objects.filter(pk=claim["uid"], is_active=False).first()
        if user is None or user.email != claim.get("email"):
            return None
        return user
    except (signing.BadSignature, TypeError, ValueError, OverflowError):
        return None


def send_confirmation(request, user):
    link = request.build_absolute_uri(
        reverse("account_verify", args=[confirmation_token(user)]),
    )
    send_mail(
        "Подтвердите электронную почту — MISTERCHIP",
        (
            "Для подтверждения адреса электронной почты откройте ссылку ниже, "
            "затем нажмите кнопку подтверждения на странице:\n\n"
            f"{link}\n\nСсылка действительна 24 часа. "
            "Если вы не регистрировались, проигнорируйте письмо."
        ),
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )


def auth_rate_limit(scope, *, max_requests, period_seconds):
    """Shared Redis-based counters; fail closed when storage is unavailable.

    This uses REMOTE_ADDR only (not spoofable X-Forwarded-For).
    A trusted reverse proxy must expose a vetted client address.
    """
    def outer(view):
        @wraps(view)
        def inner(request, *args, **kwargs):
            if request.method != "POST":
                return view(request, *args, **kwargs)
            peer = request.META.get("REMOTE_ADDR") or "unknown"
            digest = salted_hmac(
                "misterchip.auth.limits", f"{scope}:{peer}",
            ).hexdigest()
            key = f"misterchip:auth:v1:{digest}"
            try:
                if cache.add(key, 1, timeout=period_seconds):
                    count = 1
                else:
                    count = cache.incr(key)
            except Exception:
                log.exception("Authentication rate limit storage is not reachable")
                response = HttpResponse(
                    "Временно недоступно. Повторите попытку позднее.",
                    status=503,
                )
                response["Retry-After"] = "60"
                return response
            if count > max_requests:
                response = HttpResponse(
                    "Слишком много попыток. Повторите позднее.",
                    status=429,
                )
                response["Retry-After"] = str(period_seconds)
                return response
            return view(request, *args, **kwargs)
        return inner
    return outer
