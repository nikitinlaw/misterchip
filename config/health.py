"""Readiness endpoint; the body stays compatible with existing container checks."""
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        cache.set("misterchip:healthcheck", "ok", timeout=10)
        if cache.get("misterchip:healthcheck") != "ok":
            raise RuntimeError("Cache unavailable")
    except Exception:
        response = HttpResponse("unavailable", status=503, content_type="text/plain")
    else:
        response = HttpResponse("ok", content_type="text/plain")
    response["X-Misterchip-Revision"] = settings.MISTERCHIP_REVISION
    response["Cache-Control"] = "no-store"
    return response
