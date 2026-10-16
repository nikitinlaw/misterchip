from django.test import TestCase, override_settings
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_database_and_redis_health(self):
        response = self.client.get(reverse("healthz"), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")


class TunnelSecurityTests(TestCase):
    def test_staging_does_not_change_privileges(self):
        from django.conf import settings
        if settings.STAGING_SSH_TUNNEL:
            self.assertFalse(settings.DEBUG)
            self.assertFalse(settings.SESSION_COOKIE_SECURE)
            self.assertFalse(settings.SECURE_SSL_REDIRECT)
            self.assertTrue(set(settings.ALLOWED_HOSTS) <= {"localhost", "127.0.0.1", "[::1]"})
