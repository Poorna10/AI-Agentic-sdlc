"""Application service: validation, persistence and analytics orchestration."""
from __future__ import annotations

import time
from typing import Callable

from .codegen import generate_code, validate_alias
from .config import Settings
from .errors import AliasTaken, CodeGenerationFailed, LinkNotFound
from .store import Link, LinkStore
from .validation import validate_url
from .errors import ClickLimitReached, LinkExpired
from .lifecycle import compute_expiry, is_expired, validate_lifetime
from urllib.parse import urlsplit

from .blocklist import is_blocked
from .errors import DomainBlocked
# [ext:service-imports]

MAX_COLLISION_RETRIES = 5
DAY_SECONDS = 86_400


class ShortenerService:
    def __init__(self, store: LinkStore, settings: Settings,
                 clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._settings = settings
        self._clock = clock

    def create(self, url: str, alias: str | None = None, ttl_seconds: int | None = None,
               max_clicks: int | None = None) -> Link:
        url = validate_url(url, self._settings.max_url_length)
        validate_lifetime(ttl_seconds, max_clicks)
        host = urlsplit(url).hostname or ""
        if is_blocked(host, self._settings.blocked_domains):
            raise DomainBlocked(f"destination domain '{host}' is blocked")
        # [ext:create-validation]
        if alias is not None:
            validate_alias(alias)
            return self._insert(self._new_link(alias, url, ttl_seconds, max_clicks))
        for _ in range(MAX_COLLISION_RETRIES):
            link = self._new_link(generate_code(self._settings.code_length), url, ttl_seconds, max_clicks)
            try:
                return self._insert(link)
            except AliasTaken:
                continue
        raise CodeGenerationFailed("could not allocate a unique code")

    def resolve(self, code: str, referrer: str | None = None) -> str:
        link = self._store.get_link(code)
        if link is None:
            raise LinkNotFound(code)
        now = self._clock()
        if is_expired(link, now):
            raise LinkExpired(code)
        # [ext:resolve-checks]
        if link.max_clicks is None:
            self._store.record_click(code, now, referrer)
        elif not self._store.record_click_limited(code, now, referrer, link.max_clicks):
            raise ClickLimitReached(code)
        return link.url

    def stats(self, code: str) -> dict:
        link = self._store.get_link(code)
        if link is None:
            raise LinkNotFound(code)
        now = self._clock()
        return {
            "code": link.code,
            "url": link.url,
            "created_at": link.created_at,
            "expires_at": link.expires_at,
            "max_clicks": link.max_clicks,
            "total_clicks": self._store.count_clicks(code),
            "clicks_last_24h": self._store.count_clicks(code, since=now - DAY_SECONDS),
            "top_referrers": self._store.top_referrers(code),
        }

    def _new_link(self, code: str, url: str, ttl_seconds: int | None = None,
                  max_clicks: int | None = None) -> Link:
        now = self._clock()
        return Link(code=code, url=url, created_at=now,
                    expires_at=compute_expiry(now, ttl_seconds), max_clicks=max_clicks)

    def _insert(self, link: Link) -> Link:
        self._store.insert_link(link)
        return link
