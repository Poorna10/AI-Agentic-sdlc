# Design notes (brownfield)

Scope: ratelimit, blocklist, secheaders

## Impact
- Modified modules: shortener/api.py, shortener/config.py, shortener/errors.py, shortener/service.py
- New modules: shortener/blocklist.py, shortener/headers.py, shortener/ratelimit.py
- Blast radius: 9 modules

## Data flows
- POST /api/v1/links  ->  shortener/api.py  ->  shortener/service.py  ->  shortener/store.py  ->  tables ['clicks', 'links']
- GET /api/v1/links/{code}/stats  ->  shortener/api.py  ->  shortener/service.py  ->  shortener/store.py  ->  tables ['clicks', 'links']
- GET /healthz  ->  shortener/api.py  ->  shortener/service.py  ->  shortener/store.py  ->  tables ['clicks', 'links']
- GET /{code}  ->  shortener/api.py  ->  shortener/service.py  ->  shortener/store.py  ->  tables ['clicks', 'links']

## Interface changes
- POST /api/v1/links may return 429 with Retry-After (new failure mode)
- POST /api/v1/links may return 422 domain_blocked (new failure mode)

## Decisions
- **ADR-020** In-process token bucket keyed by client address - No new infrastructure; O(1) per request; smooths bursts _(trade-off: Not shared across replicas; resets on restart)_
- **ADR-030** Enforce the denylist at creation time, not redirect time - Keeps the hot redirect path free of extra checks _(trade-off: Links created before a domain is listed keep redirecting; needs a periodic re-scan)_
- **ADR-040** Add nosniff/DENY/no-referrer/HSTS but no Content-Security-Policy - A strict CSP would break the bundled Swagger UI; API returns no HTML _(trade-off: Slightly weaker defence-in-depth)_

## Risks
| ID | Scenario | Mitigation | Validation |
|---|---|---|---|
| R-RL-1 | Limiter state is per-process: N replicas allow N x the limit | Documented; move to a shared store (Redis) when scaling out | limitation recorded |
| R-RL-2 | Key-churn attack exhausts limiter memory | Bounded bucket table with oldest-half eviction | bounded-keys test |
| R-RL-3 | Clients behind one NAT/proxy share a bucket | Generous burst = per-minute rate; trusted-proxy header handling is future work | limitation recorded |
| R-BL-1 | Static denylist goes stale and misses new phishing domains | Config-driven list; threat-feed integration recorded as follow-up | limitation recorded |
| R-BL-2 | Suffix matching blocks innocent look-alike domains | Match exact host or '.'-delimited subdomain only | notevil.example test |
| R-SH-1 | HSTS on a non-HTTPS deployment is ignored or confusing | Header is only honoured over TLS; document TLS termination requirement | docs |
| R-GEN-1 | Generated change violates security/compliance policy | Engine-level policy guardrails block or escalate every change set before it is applied | policy tests + security_review full scan |
| R-GEN-2 | Upstream requirement changes after downstream work finished | Versioned artifacts + hash-based stale detection; only affected stages re-run and are rolled back | replan tests / ambiguous scenario |
| R-GEN-3 | Partial application leaves workspace inconsistent | Atomic apply with receipts; exit-gate failure reverts the stage's changes | rollback tests (injected corrupt syntax) |
| R-PERF-1 | Latency target 50 ms regresses | Hot path stays one indexed read + one insert; checks live on create path | verify stage benchmark gates p95 |

## Rollback
- Stage-level: every applied change set has a receipt of pre-images; failures revert automatically
- Release-level: revert the unified patch(es) in artifacts/patches/ (or `git revert` the release commit)
- Data-level: schema changes are additive and nullable; previous code versions ignore new columns
