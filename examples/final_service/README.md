# URL Shortener

A small, tested URL-shortening service (FastAPI + SQLite), delivered by the agentic SDLC orchestrator.

## Features
- **Core shortener** (v1.0.0)
- **Link expiry and click budgets** (v1.1.0)
- **Per-client rate limiting on link creation** (v1.2.0)
- **Malicious destination blocklist** (v1.3.0)
- **Security response headers** (v1.4.0)

## Run
```bash
pip install -r requirements.txt
uvicorn shortener.main:app --port 8000
```
Configuration: `SHORTENER_DB` (default `shortener.db`), `SHORTENER_BASE_URL` (default `http://localhost:8000`).

## Test
```bash
pytest
```

## API
See [docs/API.md](docs/API.md). Interactive docs are served at `/docs`.
Design rationale, risks and rollback: [docs/DESIGN.md](docs/DESIGN.md).
