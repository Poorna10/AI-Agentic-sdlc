import pytest


@pytest.mark.parametrize("path", ["/healthz", "/missing"])
def test_security_headers_present(client, path):
    h = client.get(path).headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"
    assert "max-age" in h["strict-transport-security"]


def test_redirects_also_carry_headers(client):
    code = client.post("/api/v1/links", json={"url": "https://example.com"}).json()["code"]
    r = client.get("/" + code)
    assert r.status_code == 307 and r.headers["x-frame-options"] == "DENY"
