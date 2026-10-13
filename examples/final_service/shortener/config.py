"""Runtime settings (immutable)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = "shortener.db"
    base_url: str = "http://localhost:8000"
    code_length: int = 7
    max_url_length: int = 2048
    rate_limit_per_minute: int = 30
    blocked_domains: tuple[str, ...] = ("evil.example", "phishing.test")
    # [ext:settings]

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.getenv("SHORTENER_DB", cls.db_path),
            base_url=os.getenv("SHORTENER_BASE_URL", cls.base_url),
        )
