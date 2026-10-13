# Design notes (brownfield)

Scope: expiry

## Impact
- Modified modules: shortener/api.py, shortener/errors.py, shortener/service.py, shortener/store.py
- New modules: shortener/lifecycle.py
- Blast radius: 7 modules

## Data flows
- POST /api/v1/links  ->  shortener/api.py  ->  shortener/service.py  ->  shortener/store.py  ->  tables ['clicks', 'links']
- GET /api/v1/links/{code}/stats  ->  shortener/api.py  ->  shortener/service.py  ->  shortener/store.py  ->  tables ['clicks', 'links']
- GET /healthz  ->  shortener/api.py  ->  shortener/service.py  ->  shortener/store.py  ->  tables ['clicks', 'links']
- GET /{code}  ->  shortener/api.py  ->  shortener/service.py  ->  shortener/store.py  ->  tables ['clicks', 'links']

## Interface changes
- POST /api/v1/links accepts optional ttl_seconds and max_clicks (additive)
- GET /{code} may return 410 (link_expired / click_limit_reached)
- ALTER TABLE links ADD COLUMN expires_at, max_clicks (nullable, additive)

## Decisions
- **ADR-010** Additive nullable columns instead of a new table - Keeps existing rows valid with zero backfill; trivially reversible _(trade-off: Wider links table; revisit if more per-link policy accumulates)_
- **ADR-011** HTTP 410 Gone for expired and exhausted links - Distinguishes 'existed but is gone' from 404 for clients and crawlers _(trade-off: Reveals that a code once existed)_

## Risks
| ID | Scenario | Mitigation | Validation |
|---|---|---|---|
| R-EXP-1 | Migration breaks or loses existing links | Additive nullable columns, idempotent PRAGMA-guarded migration; NULL = unlimited | legacy-database migration test |
| R-EXP-2 | Click budget overshoot under concurrent redirects | Count+insert inside BEGIN IMMEDIATE transaction | budget enforcement test |
| R-EXP-3 | Clock skew makes links expire early/late | Single injected clock; expiry stored as absolute epoch | fake-clock tests |
| R-GEN-1 | Generated change violates security/compliance policy | Engine-level policy guardrails block or escalate every change set before it is applied | policy tests + security_review full scan |
| R-GEN-2 | Upstream requirement changes after downstream work finished | Versioned artifacts + hash-based stale detection; only affected stages re-run and are rolled back | replan tests / ambiguous scenario |
| R-GEN-3 | Partial application leaves workspace inconsistent | Atomic apply with receipts; exit-gate failure reverts the stage's changes | rollback tests (injected corrupt syntax) |

## Rollback
- Stage-level: every applied change set has a receipt of pre-images; failures revert automatically
- Release-level: revert the unified patch(es) in artifacts/patches/ (or `git revert` the release commit)
- Data-level: schema changes are additive and nullable; previous code versions ignore new columns
