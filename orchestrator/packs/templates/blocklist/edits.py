EDITS = [
    ("shortener/errors.py", "# [ext:errors]", '''class DomainBlocked(ShortenerError):
    status_code = 422
    code = "domain_blocked"


# [ext:errors]'''),
    ("shortener/config.py", "    # [ext:settings]",
     '    blocked_domains: tuple[str, ...] = ("evil.example", "phishing.test")\n    # [ext:settings]'),
    ("shortener/service.py", "# [ext:service-imports]",
     "from urllib.parse import urlsplit\n\nfrom .blocklist import is_blocked\nfrom .errors import DomainBlocked\n# [ext:service-imports]"),
    ("shortener/service.py", "        # [ext:create-validation]",
     "        host = urlsplit(url).hostname or \"\"\n"
     "        if is_blocked(host, self._settings.blocked_domains):\n"
     "            raise DomainBlocked(f\"destination domain '{host}' is blocked\")\n"
     "        # [ext:create-validation]"),
]
