EDITS = [
    ("shortener/errors.py", "# [ext:errors]", '''class LinkExpired(ShortenerError):
    status_code = 410
    code = "link_expired"


class ClickLimitReached(ShortenerError):
    status_code = 410
    code = "click_limit_reached"


class InvalidLifetime(ShortenerError):
    status_code = 422
    code = "invalid_lifetime"


# [ext:errors]'''),
    ("shortener/store.py", "    # [ext:link-fields]",
     "    expires_at: float | None = None\n    max_clicks: int | None = None\n    # [ext:link-fields]"),
    ("shortener/store.py", '_INSERT_LINK = "INSERT INTO links (code, url, created_at) VALUES (?, ?, ?)"',
     '_INSERT_LINK = ("INSERT INTO links (code, url, created_at, expires_at, max_clicks) "\n                "VALUES (?, ?, ?, ?, ?)")'),
    ("shortener/store.py", '_SELECT_LINK = "SELECT code, url, created_at FROM links WHERE code = ?"',
     '_SELECT_LINK = ("SELECT code, url, created_at, expires_at, max_clicks "\n                "FROM links WHERE code = ?")'),
    ("shortener/store.py", "    return (link.code, link.url, link.created_at)",
     "    return (link.code, link.url, link.created_at, link.expires_at, link.max_clicks)"),
    ("shortener/store.py", '    return Link(code=row["code"], url=row["url"], created_at=row["created_at"])',
     '    return Link(code=row["code"], url=row["url"], created_at=row["created_at"],\n'
     '                expires_at=row["expires_at"], max_clicks=row["max_clicks"])'),
    ("shortener/store.py", "        # [ext:migrations]", '''        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(links)")}
        if "expires_at" not in cols:
            self._conn.execute("ALTER TABLE links ADD COLUMN expires_at REAL")
        if "max_clicks" not in cols:
            self._conn.execute("ALTER TABLE links ADD COLUMN max_clicks INTEGER")
        # [ext:migrations]'''),
    ("shortener/store.py", "    # [ext:store-methods]", '''    def record_click_limited(self, code: str, ts: float, referrer: str | None, max_clicks: int) -> bool:
        """Atomically record a click unless the budget is spent. False => limit reached."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                used = self._conn.execute("SELECT COUNT(*) FROM clicks WHERE code = ?", (code,)).fetchone()[0]
                if used >= max_clicks:
                    self._conn.execute("ROLLBACK")
                    return False
                self._conn.execute(
                    "INSERT INTO clicks (code, ts, referrer) VALUES (?, ?, ?)",
                    (code, ts, (referrer or None) and referrer[:512]),
                )
                self._conn.execute("COMMIT")
                return True
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    # [ext:store-methods]'''),
    ("shortener/service.py", "# [ext:service-imports]",
     "from .errors import ClickLimitReached, LinkExpired\nfrom .lifecycle import compute_expiry, is_expired, validate_lifetime\n# [ext:service-imports]"),
    ("shortener/service.py", "    def create(self, url: str, alias: str | None = None) -> Link:",
     "    def create(self, url: str, alias: str | None = None, ttl_seconds: int | None = None,\n"
     "               max_clicks: int | None = None) -> Link:"),
    ("shortener/service.py", "        # [ext:create-validation]",
     "        validate_lifetime(ttl_seconds, max_clicks)\n        # [ext:create-validation]"),
    ("shortener/service.py", "self._insert(self._new_link(alias, url))",
     "self._insert(self._new_link(alias, url, ttl_seconds, max_clicks))"),
    ("shortener/service.py", "self._new_link(generate_code(self._settings.code_length), url)",
     "self._new_link(generate_code(self._settings.code_length), url, ttl_seconds, max_clicks)"),
    ("shortener/service.py",
     "    def _new_link(self, code: str, url: str) -> Link:\n        return Link(code=code, url=url, created_at=self._clock())",
     "    def _new_link(self, code: str, url: str, ttl_seconds: int | None = None,\n"
     "                  max_clicks: int | None = None) -> Link:\n"
     "        now = self._clock()\n"
     "        return Link(code=code, url=url, created_at=now,\n"
     "                    expires_at=compute_expiry(now, ttl_seconds), max_clicks=max_clicks)"),
    ("shortener/service.py", "        # [ext:resolve-checks]",
     "        now = self._clock()\n        if is_expired(link, now):\n            raise LinkExpired(code)\n        # [ext:resolve-checks]"),
    ("shortener/service.py",
     "        self._store.record_click(code, self._clock(), referrer)\n        return link.url",
     "        if link.max_clicks is None:\n            self._store.record_click(code, now, referrer)\n"
     "        elif not self._store.record_click_limited(code, now, referrer, link.max_clicks):\n"
     "            raise ClickLimitReached(code)\n        return link.url"),
    ("shortener/service.py", '            "created_at": link.created_at,',
     '            "created_at": link.created_at,\n            "expires_at": link.expires_at,\n            "max_clicks": link.max_clicks,'),
    ("shortener/api.py", "    # [ext:request-fields]",
     "    ttl_seconds: int | None = Field(default=None, gt=0)\n    max_clicks: int | None = Field(default=None, gt=0)\n    # [ext:request-fields]"),
    ("shortener/api.py", "    # [ext:response-fields]",
     "    expires_at: float | None = None\n    max_clicks: int | None = None\n    # [ext:response-fields]"),
    ("shortener/api.py", "            # [ext:response-values]",
     "            expires_at=link.expires_at,\n            max_clicks=link.max_clicks,\n            # [ext:response-values]"),
    ("shortener/api.py", "link = service.create(body.url, body.alias)",
     "link = service.create(body.url, body.alias, body.ttl_seconds, body.max_clicks)"),
]
