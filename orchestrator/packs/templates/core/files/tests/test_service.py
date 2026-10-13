import pytest

from shortener.config import Settings
from shortener.errors import AliasTaken, LinkNotFound
from shortener.service import ShortenerService
from shortener.store import LinkStore


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def service(tmp_path, clock):
    settings = Settings(db_path=str(tmp_path / "s.db"))
    return ShortenerService(LinkStore(settings.db_path), settings, clock)


def test_create_and_resolve(service):
    link = service.create("https://example.com/a")
    assert service.resolve(link.code) == "https://example.com/a"


def test_alias_conflict(service):
    service.create("https://example.com/a", alias="mine")
    with pytest.raises(AliasTaken):
        service.create("https://example.com/b", alias="mine")


def test_unknown_code(service):
    with pytest.raises(LinkNotFound):
        service.resolve("nope")
    with pytest.raises(LinkNotFound):
        service.stats("nope")


def test_stats_windows_and_referrers(service, clock):
    link = service.create("https://example.com/a")
    service.resolve(link.code, "https://old.example")
    clock.now += 2 * 86_400
    service.resolve(link.code, "https://a.example")
    service.resolve(link.code, "https://a.example")
    service.resolve(link.code, None)
    stats = service.stats(link.code)
    assert stats["total_clicks"] == 4
    assert stats["clicks_last_24h"] == 3
    assert stats["top_referrers"][0] == {"referrer": "https://a.example", "clicks": 2}
