import re
from datetime import timedelta
from smtplib import SMTPException
from unittest.mock import patch
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .security import (
    VERIFICATION_MAX_AGE, auth_rate_limit, confirmation_token, find_unverified_user,
)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def registration_data(self):
        return {
            "username": "securemaker", "email": "maker@example.test",
            "password1": "StrongPass987654!", "password2": "StrongPass987654!",
            "roles": ["author", "developer"],
        }

    def register_user(self):
        response = self.client.post(
            reverse("account_register"), self.registration_data(), secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("account_verification_sent"))
        user = get_user_model().objects.get(username="securemaker")
        self.assertFalse(user.is_active)
        return user

    def test_registration_requires_email_verification_and_token_is_single_use(self):
        user = self.register_user()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://testserver/account/verify/", mail.outbox[0].body)
        self.assertFalse(self.client.login(
            username=user.username, password="StrongPass987654!"
        ))
        token = confirmation_token(user)
        url = reverse("account_verify", args=[token])
        self.assertEqual(self.client.get(url, secure=True).status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_active)  # GET cannot activate
        response = self.client.post(url, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("account_verified"))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(self.client.post(url, secure=True).status_code, 400)
        self.assertTrue(self.client.login(
            username=user.username, password="StrongPass987654!"
        ))

    def test_expired_and_invalid_tokens(self):
        user = self.register_user()
        now = timezone.now().timestamp()
        with patch("django.core.signing.time.time", return_value=now):
            token = confirmation_token(user)
        with patch(
            "django.core.signing.time.time",
            return_value=now + VERIFICATION_MAX_AGE + 120,
        ):
            self.assertIsNone(find_unverified_user(token))
        self.assertEqual(self.client.get(reverse("account_verify", args=["invalid-token"]), secure=True).status_code, 400)

    def test_resend_is_generic_for_unknown_and_active_email(self):
        self.client.post(reverse("account_resend"), {
            "email": "nobody@example.test"
        }, secure=True)
        self.assertEqual(len(mail.outbox), 0)
        self.register_user()
        self.client.post(reverse("account_resend"), {
            "email": "maker@example.test"
        }, secure=True)
        self.assertEqual(len(mail.outbox), 2)
        user = get_user_model().objects.get(username="securemaker")
        user.is_active = True
        user.save(update_fields=["is_active"])
        self.client.post(reverse("account_resend"), {
            "email": user.email
        }, secure=True)
        self.assertEqual(len(mail.outbox), 2)

    def test_password_reset_for_active_only_and_generic_response(self):
        inactive = self.register_user()
        inactive_mail_count = len(mail.outbox)
        self.client.post(reverse("password_reset"), {
            "email": inactive.email
        }, secure=True)
        self.assertEqual(len(mail.outbox), inactive_mail_count)
        active = get_user_model().objects.create_user(
            username="active", email="active@example.test",
            password="StrongInitial987!",
        )
        response = self.client.post(reverse("password_reset"), {
            "email": active.email
        }, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), inactive_mail_count + 1)
        url = re.search(r"https?://[^\s]+", mail.outbox[-1].body).group()
        path = urlparse(url).path
        response = self.client.get(path, secure=True)
        self.assertEqual(response.status_code, 302)
        set_password_url = response["Location"]
        response = self.client.post(set_password_url, {
            "new_password1": "DifferentStrongPassword987!",
            "new_password2": "DifferentStrongPassword987!",
        }, secure=True)
        self.assertEqual(response.status_code, 302)
        active.refresh_from_db()
        self.assertTrue(active.check_password("DifferentStrongPassword987!"))
        self.client.post(reverse("password_reset"), {
            "email": "unknown@example.test"
        }, secure=True)
        self.assertEqual(len(mail.outbox), inactive_mail_count + 1)

    def test_redis_counter_blocks_after_limit_without_email_leak(self):
        from django.http import HttpResponse

        def handler(request):
            return HttpResponse("ok")

        limited = auth_rate_limit("unit-test-signup", max_requests=2, period_seconds=60)(handler)
        self.assertEqual(limited(self.factory.post("/test/", REMOTE_ADDR="192.0.2.1")).status_code, 200)
        self.assertEqual(limited(self.factory.post("/test/", REMOTE_ADDR="192.0.2.1")).status_code, 200)
        blocked = limited(self.factory.post("/test/", REMOTE_ADDR="192.0.2.1"))
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked["Retry-After"], "60")
        self.assertEqual(limited(self.factory.post("/test/", REMOTE_ADDR="192.0.2.2")).status_code, 200)

    def test_cache_outage_fails_closed(self):
        with patch("accounts.security.cache.add", side_effect=OSError("Redis down")):
            response = self.client.post(
                reverse("account_register"), self.registration_data(), secure=True,
            )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(get_user_model().objects.filter(username="securemaker").exists())

    def test_confirmation_mail_send_failure_rolls_back_registration(self):
        with patch("accounts.views.send_confirmation", side_effect=SMTPException("smtp down")):
            response = self.client.post(
                reverse("account_register"), self.registration_data(), secure=True,
            )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(get_user_model().objects.filter(username="securemaker").exists())
