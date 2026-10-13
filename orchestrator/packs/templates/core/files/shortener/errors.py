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


# [ext:errors]
