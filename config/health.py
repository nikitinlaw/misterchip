"""Minimal private health endpoint used by container readiness checks."""
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
        return HttpResponse("unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")
