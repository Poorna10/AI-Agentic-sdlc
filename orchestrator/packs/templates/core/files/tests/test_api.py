def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_create_redirect_stats_flow(client):
    r = client.post("/api/v1/links", json={"url": "https://example.com/page"})
    assert r.status_code == 201
    body = r.json()
    assert body["short_url"].endswith("/" + body["code"])
    hit = client.get("/" + body["code"], headers={"referer": "https://news.example"})
    assert hit.status_code == 307
    assert hit.headers["location"] == "https://example.com/page"
    assert hit.headers["cache-control"] == "no-store"
    stats = client.get(f"/api/v1/links/{body['code']}/stats").json()
    assert stats["total_clicks"] == 1
    assert stats["top_referrers"] == [{"referrer": "https://news.example", "clicks": 1}]


def test_custom_alias_and_conflict(client):
    assert client.post("/api/v1/links", json={"url": "https://example.com", "alias": "promo"}).status_code == 201
    dup = client.post("/api/v1/links", json={"url": "https://example.org", "alias": "promo"})
    assert dup.status_code == 409 and dup.json()["error"] == "alias_taken"


def test_validation_errors(client):
    assert client.post("/api/v1/links", json={"url": "http://127.0.0.1"}).json()["error"] == "invalid_url"
    assert client.post("/api/v1/links", json={"url": "https://e.com", "alias": "api"}).json()["error"] == "invalid_alias"
    assert client.post("/api/v1/links", json={}).status_code == 422


def test_unknown_code_404(client):
    assert client.get("/doesnotexist").status_code == 404
    assert client.get("/api/v1/links/doesnotexist/stats").status_code == 404
