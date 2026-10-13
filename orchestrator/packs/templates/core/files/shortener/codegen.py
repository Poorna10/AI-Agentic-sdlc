"""Short-code generation and alias validation."""
from __future__ import annotations

import re
import secrets

from .errors import InvalidAlias

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
# Paths the API owns; an alias must never shadow them.
RESERVED = frozenset({"api", "healthz", "docs", "redoc", "openapi.json", "admin", "static"})


def generate_code(length: int = 7) -> str:
    """Cryptographically random code (unguessable; 62^7 ~ 3.5e12 combinations)."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def validate_alias(alias: str) -> str:
    if not ALIAS_RE.fullmatch(alias):
        raise InvalidAlias("alias must be 3-32 chars of letters, digits, '_' or '-'")
    if alias.lower() in RESERVED:
        raise InvalidAlias(f"alias '{alias}' is reserved")
    return alias
