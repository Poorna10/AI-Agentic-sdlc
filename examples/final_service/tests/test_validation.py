import pytest

from shortener.errors import InvalidUrl
from shortener.validation import validate_url


@pytest.mark.parametrize("url", [
    "https://example.com", "http://example.com/a?b=c#d", "https://sub.example.co.uk:8443/x",
    "https://93.184.216.34/x",
])
def test_accepts_public_urls(url):
    assert validate_url(url) == url


@pytest.mark.parametrize("url", [
    "", "   ", "ftp://example.com", "javascript:alert(1)", "//example.com", "https://",
    "http://localhost/x", "http://foo.localhost", "http://127.0.0.1", "http://10.0.0.5",
    "http://192.168.1.1", "http://169.254.169.254/latest/meta-data", "http://[::1]/",
    "http://0.0.0.0", "https://user:pw@example.com", "https://svc.internal/x",
    "https://example.com/" + "a" * 3000,
])
def test_rejects_unsafe_urls(url):
    with pytest.raises(InvalidUrl):
        validate_url(url)
