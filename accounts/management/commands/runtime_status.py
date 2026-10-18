"""Report configuration without exposing environment values or sending mail."""
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ops.runtime import REVISION_PATTERN, runtime_report


class Command(BaseCommand):
    help = "Show redacted runtime configuration; no database writes or email sends."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--expect-revision", help="Require this exact 40-character image SHA.")
        parser.add_argument("--check-mail", action="store_true", help="Accept configured SMTP or the existing file-mail pilot.")
        parser.add_argument("--require-smtp", action="store_true", help="Require complete encrypted SMTP configuration; does not test delivery.")

    def handle(self, *args, **options):
        expected = options["expect_revision"]
        if expected and not REVISION_PATTERN.fullmatch(expected):
            raise CommandError("Expected revision must be a 40-character lowercase SHA.")
        report = runtime_report(settings)
        failures = []
        if expected and report["revision"] != expected:
            failures.append("image_revision_mismatch")
        mail = report["mail"]
        if options["require_smtp"] and not mail["configuration_ready"]:
            failures.append("smtp_configuration_incomplete")
        elif options["check_mail"] and not (
            mail["mode"] == "file" or mail["configuration_ready"]
        ):
            failures.append("unsupported_or_incomplete_mail_configuration")
        if not report["public_site_url_valid"]:
            failures.append("invalid_public_site_url")
        report["checks_passed"] = not failures
        report["failed_checks"] = failures
        self.stdout.write(json.dumps(report, sort_keys=True))
        if failures:
            raise CommandError("Runtime configuration check failed; see redacted status.")
