EDITS = [
    ("shortener/api.py", "# [ext:imports]", "from .headers import SECURITY_HEADERS\n# [ext:imports]"),
    ("shortener/api.py", "    # [ext:middleware]", '''    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    # [ext:middleware]'''),
]
