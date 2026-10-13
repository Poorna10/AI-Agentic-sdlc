"""Link lifecycle rules: optional TTL and optional click budget."""
from __future__ import annotations

from .errors import InvalidLifetime

MAX_TTL_SECONDS = 365 * 86_400


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_lifetime(ttl_seconds: int | None, max_clicks: int | None) -> None:
    if ttl_seconds is not None and (not _is_int(ttl_seconds) or not 0 < ttl_seconds <= MAX_TTL_SECONDS):
        raise InvalidLifetime(f"ttl_seconds must be between 1 and {MAX_TTL_SECONDS}")
    if max_clicks is not None and (not _is_int(max_clicks) or max_clicks < 1):
        raise InvalidLifetime("max_clicks must be a positive integer")


def compute_expiry(created_at: float, ttl_seconds: int | None) -> float | None:
    return None if ttl_seconds is None else created_at + ttl_seconds


def is_expired(link, now: float) -> bool:
    return link.expires_at is not None and now >= link.expires_at
