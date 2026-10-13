import pytest
from fastapi.testclient import TestClient

from shortener.api import create_app
from shortener.blocklist import is_blocked
from shortener.config import Settings


@pytest.mark.parametrize("host,expected", [
    ("evil.example", True), ("login.EVIL.example", True), ("evil.example.", True),
    ("notevil.example", False), ("example.com", False), ("", False),
])
def test_is_blocked(host, expected):
    assert is_blocked(host, ("evil.example",)) is expected


def test_api_rejects_blocked_domain(tmp_path):
    with TestClient(create_app(Settings(db_path=str(tmp_path / "b.db")))) as c:
        r = c.post("/api/v1/links", json={"url": "https://login.phishing.test/x"})
        assert r.status_code == 422 and r.json()["error"] == "domain_blocked"
        assert c.post("/api/v1/links", json={"url": "https://example.com"}).status_code == 201
