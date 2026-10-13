"""Domain errors. Each carries its HTTP status and a stable machine-readable code."""


class ShortenerError(Exception):
    status_code = 500
    code = "internal_error"


class InvalidUrl(ShortenerError):
    status_code = 422
    code = "invalid_url"


class InvalidAlias(ShortenerError):
    status_code = 422
    code = "invalid_alias"


class AliasTaken(ShortenerError):
    status_code = 409
    code = "alias_taken"


class LinkNotFound(ShortenerError):
    status_code = 404
    code = "link_not_found"


class CodeGenerationFailed(ShortenerError):
    status_code = 503
    code = "code_generation_failed"


class LinkExpired(ShortenerError):
    status_code = 410
    code = "link_expired"


class ClickLimitReached(ShortenerError):
    status_code = 410
    code = "click_limit_reached"


class InvalidLifetime(ShortenerError):
    status_code = 422
    code = "invalid_lifetime"


class RateLimited(ShortenerError):
    status_code = 429
    code = "rate_limited"
    headers = {"Retry-After": "60"}


class DomainBlocked(ShortenerError):
    status_code = 422
    code = "domain_blocked"


# [ext:errors]
