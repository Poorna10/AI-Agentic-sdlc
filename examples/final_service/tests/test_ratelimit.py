from fastapi.testclient import TestClient

from shortener.api import create_app
from shortener.config import Settings
from shortener.ratelimit import TokenBucketLimiter


def test_bucket_allows_burst_then_refills():
    now = [0.0]
    limiter = TokenBucketLimiter(per_minute=60, burst=3, clock=lambda: now[0])
    assert [limiter.allow("a") for _ in range(4)] == [True, True, True, False]
    now[0] += 2.0
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")


def test_buckets_are_per_key_and_bounded():
    limiter = TokenBucketLimiter(per_minute=1, burst=1, max_keys=10)
    assert limiter.allow("a") and not limiter.allow("a") and limiter.allow("b")
    for i in range(200):
        limiter.allow(f"k{i}")
    assert len(limiter._buckets) <= 11


def test_api_returns_429_with_retry_after(tmp_path):
    settings = Settings(db_path=str(tmp_path / "r.db"), rate_limit_per_minute=2)
    with TestClient(create_app(settings), follow_redirects=False) as c:
        codes = [c.post("/api/v1/links", json={"url": "https://example.com"}).status_code for _ in range(3)]
        assert codes == [201, 201, 429]
        limited = c.post("/api/v1/links", json={"url": "https://example.com"})
        assert limited.json()["error"] == "rate_limited" and limited.headers["retry-after"] == "60"
        assert c.get("/healthz").status_code == 200  # only creation is throttled
