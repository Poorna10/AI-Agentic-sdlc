"""Destination domain denylist (exact or subdomain match)."""
from __future__ import annotations


def is_blocked(host: str, blocked: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in (b.lower() for b in blocked))
