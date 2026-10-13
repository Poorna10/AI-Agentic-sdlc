"""HTTP API (FastAPI)."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .config import Settings
from .errors import ShortenerError
from .service import ShortenerService
from .store import Link, LinkStore
# [ext:imports]


class CreateLinkRequest(BaseModel):
    url: str = Field(..., max_length=4096)
    alias: str | None = None
    # [ext:request-fields]


class LinkResponse(BaseModel):
    code: str
    short_url: str
    url: str
    created_at: float
    # [ext:response-fields]


def create_app(settings: Settings | None = None, service: ShortenerService | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    service = service or ShortenerService(LinkStore(settings.db_path), settings)
    app = FastAPI(title="URL Shortener", version="1.0.0")
    # [ext:middleware]

    @app.exception_handler(ShortenerError)
    async def handle_domain_error(_: Request, exc: ShortenerError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "detail": str(exc)},
            headers=getattr(exc, "headers", None),
        )

    def to_response(link: Link) -> LinkResponse:
        return LinkResponse(
            code=link.code,
            short_url=f"{settings.base_url.rstrip('/')}/{link.code}",
            url=link.url,
            created_at=link.created_at,
            # [ext:response-values]
        )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/api/v1/links", status_code=201, response_model=LinkResponse)
    def create_link(body: CreateLinkRequest, request: Request) -> LinkResponse:
        # [ext:create-guards]
        link = service.create(body.url, body.alias)
        return to_response(link)

    @app.get("/api/v1/links/{code}/stats")
    def link_stats(code: str) -> dict:
        return service.stats(code)

    @app.get("/{code}")
    def redirect(code: str, request: Request) -> RedirectResponse:
        target = service.resolve(code, request.headers.get("referer"))
        return RedirectResponse(target, status_code=307, headers={"Cache-Control": "no-store"})

    return app
