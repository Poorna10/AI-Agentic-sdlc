import sqlite3

import pytest
from fastapi.testclient import TestClient

from shortener.api import create_app
from shortener.config import Settings
from shortener.errors import ClickLimitReached, InvalidLifetime, LinkExpired
from shortener.service import ShortenerService
from shortener.store import LinkStore


class Clock:
    now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def service(tmp_path, clock):
    settings = Settings(db_path=str(tmp_path / "e.db"))
    return ShortenerService(LinkStore(settings.db_path), settings, clock)


def test_link_expires_after_ttl(service, clock):
    link = service.create("https://example.com", ttl_seconds=60)
    assert service.resolve(link.code) == "https://example.com"
    clock.now += 60
    with pytest.raises(LinkExpired):
        service.resolve(link.code)


def test_click_budget_is_enforced_atomically(service):
    link = service.create("https://example.com", max_clicks=2)
    service.resolve(link.code)
    service.resolve(link.code)
    with pytest.raises(ClickLimitReached):
        service.resolve(link.code)
    assert service.stats(link.code)["total_clicks"] == 2


@pytest.mark.parametrize("ttl,clicks", [(0, None), (-5, None), (10**9, None), (None, 0), (True, None)])
def test_invalid_lifetimes(service, ttl, clicks):
    with pytest.raises(InvalidLifetime):
        service.create("https://example.com", ttl_seconds=ttl, max_clicks=clicks)


def test_links_without_lifetime_never_expire(service, clock):
    link = service.create("https://example.com")
    clock.now += 10 * 365 * 86_400
    assert service.resolve(link.code) == "https://example.com"


def test_api_returns_410_for_expired_and_exhausted(tmp_path):
    clock = Clock()
    settings = Settings(db_path=str(tmp_path / "api.db"))
    app = create_app(settings, ShortenerService(LinkStore(settings.db_path), settings, clock))
    with TestClient(app, follow_redirects=False) as c:
        a = c.post("/api/v1/links", json={"url": "https://example.com", "ttl_seconds": 30}).json()
        assert a["expires_at"] == clock.now + 30
        b = c.post("/api/v1/links", json={"url": "https://example.com", "max_clicks": 1}).json()
        assert c.get("/" + b["code"]).status_code == 307
        gone = c.get("/" + b["code"])
        assert gone.status_code == 410 and gone.json()["error"] == "click_limit_reached"
        clock.now += 31
        assert c.get("/" + a["code"]).json()["error"] == "link_expired"
        assert c.post("/api/v1/links", json={"url": "https://example.com", "ttl_seconds": 0}).status_code == 422


def test_existing_database_is_migrated_without_data_loss(tmp_path):
    """Backward compatibility: a pre-expiry database keeps working after upgrade."""
    path = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(path)
    raw.executescript(
        "CREATE TABLE links (code TEXT PRIMARY KEY, url TEXT NOT NULL, created_at REAL NOT NULL);"
        "CREATE TABLE clicks (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, ts REAL NOT NULL, referrer TEXT);"
        "INSERT INTO links VALUES ('legacy1', 'https://example.com/old', 1.0);"
    )
    raw.commit()
    raw.close()
    settings = Settings(db_path=path)
    svc = ShortenerService(LinkStore(path), settings, Clock())
    assert svc.resolve("legacy1") == "https://example.com/old"
    LinkStore(path)  # idempotent second migration
