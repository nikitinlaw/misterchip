from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from .security import inquiry_rate_limit


@override_settings(
    TRUST_PROXY_CLIENT_IP=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "market-rate-tests"}},
)
class InquiryRateLimitTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.view = inquiry_rate_limit(lambda request: HttpResponse("accepted"))

    def request(self, email, user=None, **headers):
        request = self.factory.post("/market/offers/1/inquiry/", {"email": email}, **headers)
        request.user = user or AnonymousUser()
        return request

    def test_recipient_limit_cannot_be_evaded_with_proxy_headers(self):
        for number in range(10):
            self.assertEqual(self.view(self.request("buyer@example.test", HTTP_X_FORWARDED_FOR=f"203.0.113.{number}")).status_code, 200)
        response = self.view(self.request("BUYER@EXAMPLE.TEST", HTTP_X_FORWARDED_FOR="198.51.100.1"))
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)

    def test_two_buyers_behind_same_proxy_have_separate_recipient_budgets(self):
        for number in range(10):
            self.assertEqual(self.view(self.request("one@example.test")).status_code, 200)
        self.assertEqual(self.view(self.request("two@example.test")).status_code, 200)

    def test_logged_in_buyer_cannot_change_throttle_identity_with_form_email(self):
        actor = SimpleNamespace(pk=4, email="verified@example.test", is_authenticated=True, is_active=True)
        for number in range(10):
            self.assertEqual(self.view(self.request(f"forged{number}@example.test", actor)).status_code, 200)
        self.assertEqual(self.view(self.request("another@example.test", actor)).status_code, 429)

    def test_cache_outage_fails_closed_before_view(self):
        with patch("market.security.cache.add", side_effect=ConnectionError):
            response = self.view(self.request("buyer@example.test"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "60")

    @override_settings(TRUST_PROXY_CLIENT_IP=True)
    def test_network_limit_does_not_ban_other_clients_through_same_proxy(self):
        for number in range(100):
            response = self.view(self.request(
                f"buyer{number}@example.test", REMOTE_ADDR="172.18.0.1", HTTP_X_FORWARDED_FOR="203.0.113.1",
            ))
            self.assertEqual(response.status_code, 200)
        blocked = self.view(self.request(
            "exhausted@example.test", REMOTE_ADDR="172.18.0.1", HTTP_X_FORWARDED_FOR="203.0.113.1",
        ))
        self.assertEqual(blocked.status_code, 429)
        unaffected = self.view(self.request(
            "fresh@example.test", REMOTE_ADDR="172.18.0.1", HTTP_X_FORWARDED_FOR="203.0.113.2",
        ))
        self.assertEqual(unaffected.status_code, 200)

    @override_settings(TRUST_PROXY_CLIENT_IP=True)
    def test_malformed_proxy_identity_cannot_consume_recipient_or_network_budget(self):
        with patch("market.security.cache.add") as add:
            for value in ("", "invalid", "203.0.113.1, 203.0.113.2", "203.0.113.1:80"):
                with self.subTest(value=value):
                    response = self.view(self.request(
                        "buyer@example.test", REMOTE_ADDR="172.18.0.1", HTTP_X_FORWARDED_FOR=value,
                    ))
                    self.assertEqual(response.status_code, 400)
        add.assert_not_called()

    def test_default_does_not_trust_proxy_header_for_network_budget(self):
        for number in range(100):
            response = self.view(self.request(
                f"buyer{number}@example.test", REMOTE_ADDR="172.18.0.1", HTTP_X_FORWARDED_FOR=f"203.0.113.{number + 1}",
            ))
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.view(self.request(
            "another@example.test", REMOTE_ADDR="172.18.0.1", HTTP_X_FORWARDED_FOR="198.51.100.1",
        )).status_code, 429)
