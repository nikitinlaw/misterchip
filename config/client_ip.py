"""Canonical client addresses for an explicitly trusted, single reverse proxy."""
from ipaddress import ip_address, ip_network

from django.conf import settings


_LOCAL_PROXY_NETWORKS = tuple(ip_network(value) for value in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "::1/128", "fc00::/7",
))


class InvalidClientAddress(ValueError):
    """No usable address; callers must reject without a shared fallback bucket."""


def _parse_address(value):
    # No chain, hostname, port, scoped IPv6 address or header control characters.
    if not isinstance(value, str) or len(value) > 64 or any(char in value for char in (",", "%", "\r", "\n")):
        raise InvalidClientAddress("invalid_client_address")
    try:
        address = ip_address(value.strip(" \t"))
    except ValueError:
        raise InvalidClientAddress("invalid_client_address") from None
    # Different spellings of the same peer must share the same rate limit.
    address = getattr(address, "ipv4_mapped", None) or address
    if address.is_unspecified or address.is_multicast:
        raise InvalidClientAddress("invalid_client_address")
    return address


def client_ip(request):
    """Return one validated IP; forwarded headers are ignored by default.

    TRUST_PROXY_CLIENT_IP is an explicit deployment assertion that only the
    trusted proxy can reach the private upstream and that it overwrites incoming
    X-Forwarded-For. Local address ranges are an additional topology check, not a
    reason to trust a peer automatically. A proxy chain requires a new contract.
    """
    peer = _parse_address(request.META.get("REMOTE_ADDR"))
    if not getattr(settings, "TRUST_PROXY_CLIENT_IP", False):
        return str(peer)
    if not any(peer.version == network.version and peer in network for network in _LOCAL_PROXY_NETWORKS):
        raise InvalidClientAddress("untrusted_proxy_peer")
    return str(_parse_address(request.META.get("HTTP_X_FORWARDED_FOR")))
