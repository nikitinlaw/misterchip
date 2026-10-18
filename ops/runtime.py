"""Read-only, redacted runtime checks shared by the management command and tests."""
from email.utils import parseaddr
from pathlib import Path
import re
from urllib.parse import urlsplit


REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
MAIL_MODES = {
    "django.core.mail.backends.smtp.EmailBackend": "smtp",
    "django.core.mail.backends.filebased.EmailBackend": "file",
    "django.core.mail.backends.locmem.EmailBackend": "memory",
    "django.core.mail.backends.console.EmailBackend": "console",
    "django.core.mail.backends.dummy.EmailBackend": "dummy",
}


def read_revision(base_dir):
    """Read the image's baked revision; environment variables cannot replace it."""
    try:
        revision = (Path(base_dir) / "RELEASE").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return "unknown"
    return revision if REVISION_PATTERN.fullmatch(revision) else "unknown"


def public_site_url_is_valid(value, *, allow_http=False):
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme in ({"https", "http"} if allow_http else {"https"})
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and (parsed.port is None or 1 <= parsed.port <= 65535)
        )
    except (ValueError, TypeError):
        return False


def _nonplaceholder_domain(value):
    value = str(value or "").strip().lower().rstrip(".")
    return bool(
        value
        and "." in value
        and value not in {"localhost", "127.0.0.1", "0.0.0.0"}
        and not value.endswith((".invalid", ".test", ".localhost", ".example"))
    )


def runtime_report(settings):
    mode = MAIL_MODES.get(settings.EMAIL_BACKEND, "unsupported")
    _, sender = parseaddr(str(settings.DEFAULT_FROM_EMAIL))
    sender_domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    try:
        port_valid = 1 <= int(settings.EMAIL_PORT) <= 65535
    except (ValueError, TypeError):
        port_valid = False
    mail = {
        "mode": mode,
        "host_configured": _nonplaceholder_domain(settings.EMAIL_HOST),
        "port_valid": port_valid,
        "username_configured": bool(settings.EMAIL_HOST_USER),
        "password_configured": bool(settings.EMAIL_HOST_PASSWORD),
        "sender_configured": bool(
            _nonplaceholder_domain(sender_domain)
            and "\n" not in str(settings.DEFAULT_FROM_EMAIL)
            and "\r" not in str(settings.DEFAULT_FROM_EMAIL)
        ),
        "starttls": bool(settings.EMAIL_USE_TLS),
        "implicit_tls": bool(getattr(settings, "EMAIL_USE_SSL", False)),
    }
    mail["configuration_ready"] = bool(
        mode == "smtp"
        and all(mail[key] for key in (
            "host_configured", "port_valid", "username_configured",
            "password_configured", "sender_configured",
        ))
        and mail["starttls"] != mail["implicit_tls"]
    )
    # This command never connects to an SMTP service or sends a message.
    mail["delivery_verified"] = False
    return {
        "schema_version": 1,
        "revision": settings.MISTERCHIP_REVISION,
        "trusted_client_ip": bool(getattr(settings, "TRUST_PROXY_CLIENT_IP", False)),
        "mail": mail,
        "public_site_url_valid": public_site_url_is_valid(
            settings.PUBLIC_SITE_URL,
            allow_http=settings.DEBUG or settings.STAGING_SSH_TUNNEL,
        ),
    }
