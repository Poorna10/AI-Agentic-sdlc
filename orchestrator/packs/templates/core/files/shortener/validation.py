"""Destination URL validation (open-redirect / SSRF hygiene)."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from .errors import InvalidUrl

_BLOCKED_SUFFIXES = (".localhost", ".internal", ".local")


def validate_url(raw: str, max_length: int = 2048) -> str:
    url = (raw or "").strip()
    if not url or len(url) > max_length:
        raise InvalidUrl(f"url must be 1-{max_length} characters")
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError as exc:
        raise InvalidUrl("malformed url") from exc
    if parts.scheme not in ("http", "https"):
        raise InvalidUrl("only http and https urls are allowed")
    if not host:
        raise InvalidUrl("url must include a host")
    if parts.username or parts.password:
        raise InvalidUrl("credentials in urls are not allowed")
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(_BLOCKED_SUFFIXES):
        raise InvalidUrl("destination host is not allowed")
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return url  # a DNS name; resolution-time checks are out of scope (see docs)
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        raise InvalidUrl("destination address is not allowed")
    return url
