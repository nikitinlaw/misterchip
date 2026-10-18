"""Shared inquiry counters using the explicit proxy identity contract."""
from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse
from django.utils.crypto import salted_hmac

from config.client_ip import InvalidClientAddress, client_ip


def inquiry_rate_limit(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method != "POST":
            return view(request, *args, **kwargs)
        actor = request.user if request.user.is_authenticated and request.user.is_active else None
        try:
            peer = client_ip(request)
        except InvalidClientAddress:
            return HttpResponse("Некорректный запрос. Обновите страницу и повторите попытку.", status=400)
        email = actor.email if actor else request.POST.get("email", "")
        email = email.strip().lower()[:254]
        # Network, authenticated actor and recipient limits remain independent.
        limits = [("network", peer, 100, 10 * 60)]
        if actor:
            limits.append(("buyer", str(actor.pk), 20, 60 * 60))
        if email:
            limits.append(("recipient", email, 10, 60 * 60))
        try:
            for scope, identity, maximum, seconds in limits:
                digest = salted_hmac("misterchip.market.inquiry.v1", f"{scope}:{identity}").hexdigest()
                key = f"misterchip:market:inquiry:{digest}"
                count = 1 if cache.add(key, 1, timeout=seconds) else cache.incr(key)
                if count > maximum:
                    response = HttpResponse("Слишком много обращений. Повторите отправку позднее.", status=429)
                    response["Retry-After"] = str(seconds)
                    return response
        except Exception:
            response = HttpResponse("Отправка временно недоступна. Повторите попытку позднее.", status=503)
            response["Retry-After"] = "60"
            return response
        return view(request, *args, **kwargs)
    return wrapped
