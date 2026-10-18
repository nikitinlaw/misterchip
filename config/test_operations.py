from io import StringIO
import json
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from ops.runtime import public_site_url_is_valid, read_revision


@override_settings(
    PUBLIC_SITE_URL="https://misterchip.ru", STAGING_SSH_TUNNEL=False,
    MISTERCHIP_REVISION="a" * 40, EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST="smtp.mailprovider.example.org", EMAIL_PORT=587,
    EMAIL_HOST_USER="private-smtp-user", EMAIL_HOST_PASSWORD="private-smtp-password",
    DEFAULT_FROM_EMAIL="Misterchip <noreply@misterchip.ru>",
    EMAIL_USE_TLS=True, EMAIL_USE_SSL=False,
)
class RuntimeStatusTests(SimpleTestCase):
    def test_smtp_configuration_is_reported_without_credentials_or_addresses(self):
        output = StringIO()
        call_command("runtime_status", require_smtp=True, stdout=output)
        text = output.getvalue()
        report = json.loads(text)
        self.assertTrue(report["mail"]["configuration_ready"])
        self.assertFalse(report["mail"]["delivery_verified"])
        for secret in ("private-smtp-user", "private-smtp-password", "smtp.mailprovider.example.org", "noreply@misterchip.ru"):
            self.assertNotIn(secret, text)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend")
    def test_file_pilot_is_accepted_but_never_reported_as_real_email(self):
        output = StringIO()
        call_command("runtime_status", check_mail=True, stdout=output)
        self.assertFalse(json.loads(output.getvalue())["mail"]["configuration_ready"])
        with self.assertRaises(CommandError):
            call_command("runtime_status", require_smtp=True, stdout=StringIO())

    @override_settings(EMAIL_HOST_PASSWORD="")
    def test_incomplete_smtp_is_a_deployment_check_failure(self):
        with self.assertRaises(CommandError):
            call_command("runtime_status", check_mail=True, stdout=StringIO())

    @override_settings(EMAIL_USE_SSL=True)
    def test_dual_tls_modes_are_not_reported_as_ready(self):
        with self.assertRaises(CommandError):
            call_command("runtime_status", require_smtp=True, stdout=StringIO())

    def test_deployment_cannot_accept_the_wrong_image_revision(self):
        with self.assertRaises(CommandError):
            call_command("runtime_status", expect_revision="b" * 40, stdout=StringIO())

    def test_baked_revision_rejects_untrusted_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "RELEASE"
            path.write_text("a" * 40)
            self.assertEqual(read_revision(directory), "a" * 40)
            path.write_text("secret\r\ninjected-header")
            self.assertEqual(read_revision(directory), "unknown")

    def test_email_origin_cannot_contain_credentials_paths_or_query_parameters(self):
        self.assertTrue(public_site_url_is_valid("https://misterchip.ru"))
        for url in (
            "http://misterchip.ru", "https://user:password@misterchip.ru",
            "https://misterchip.ru/account/", "https://misterchip.ru/?redirect=other",
            "https://misterchip.ru/#fragment",
        ):
            with self.subTest(url=url):
                self.assertFalse(public_site_url_is_valid(url))
