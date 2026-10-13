EDITS = [
    ("shortener/errors.py", "# [ext:errors]", '''class RateLimited(ShortenerError):
    status_code = 429
    code = "rate_limited"
    headers = {"Retry-After": "60"}


# [ext:errors]'''),
    ("shortener/config.py", "    # [ext:settings]",
     "    rate_limit_per_minute: int = {{rate_limit_per_minute}}\n    # [ext:settings]"),
    ("shortener/api.py", "# [ext:imports]",
     "from .errors import RateLimited\nfrom .ratelimit import TokenBucketLimiter, client_key\n# [ext:imports]"),
    ("shortener/api.py", "    # [ext:middleware]",
     "    limiter = TokenBucketLimiter(settings.rate_limit_per_minute)\n    # [ext:middleware]"),
    ("shortener/api.py", "        # [ext:create-guards]",
     "        if not limiter.allow(client_key(request)):\n"
     "            raise RateLimited(\"too many link creations; retry later\")\n        # [ext:create-guards]"),
]
