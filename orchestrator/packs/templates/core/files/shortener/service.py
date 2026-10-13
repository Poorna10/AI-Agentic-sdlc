"""Application service: validation, persistence and analytics orchestration."""
from __future__ import annotations

import time
from typing import Callable

from .codegen import generate_code, validate_alias
from .config import Settings
from .errors import AliasTaken, CodeGenerationFailed, LinkNotFound
from .store import Link, LinkStore
from .validation import validate_url
# [ext:service-imports]

MAX_COLLISION_RETRIES = 5
DAY_SECONDS = 86_400


class ShortenerService:
    def __init__(self, store: LinkStore, settings: Settings,
                 clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._settings = settings
        self._clock = clock

    def create(self, url: str, alias: str | None = None) -> Link:
        url = validate_url(url, self._settings.max_url_length)
        # [ext:create-validation]
        if alias is not None:
            validate_alias(alias)
            return self._insert(self._new_link(alias, url))
        for _ in range(MAX_COLLISION_RETRIES):
            link = self._new_link(generate_code(self._settings.code_length), url)
            try:
                return self._insert(link)
            except AliasTaken:
                continue
        raise CodeGenerationFailed("could not allocate a unique code")

    def resolve(self, code: str, referrer: str | None = None) -> str:
        link = self._store.get_link(code)
        if link is None:
            raise LinkNotFound(code)
        # [ext:resolve-checks]
        self._store.record_click(code, self._clock(), referrer)
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
            "total_clicks": self._store.count_clicks(code),
            "clicks_last_24h": self._store.count_clicks(code, since=now - DAY_SECONDS),
            "top_referrers": self._store.top_referrers(code),
        }

    def _new_link(self, code: str, url: str) -> Link:
        return Link(code=code, url=url, created_at=self._clock())

    def _insert(self, link: Link) -> Link:
        self._store.insert_link(link)
        return link
