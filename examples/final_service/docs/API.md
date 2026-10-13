# API reference (generated from the API contract)

| Method | Path | Documented responses |
|---|---|---|
| POST | `/api/v1/links` | 201, 409, 422, 429 |
| GET | `/api/v1/links/{code}/stats` | 200, 404 |
| GET | `/healthz` | 200 |
| GET | `/{code}` | 307, 404, 410 |

`POST /api/v1/links` body fields: `alias`, `max_clicks`, `ttl_seconds`, `url`

Error bodies: `{"error": "<code>", "detail": "..."}`.
