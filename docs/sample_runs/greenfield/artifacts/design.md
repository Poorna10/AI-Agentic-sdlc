# Design notes (greenfield)

Scope: core

## Impact
- Modified modules: -
- New modules: pytest.ini, requirements.txt, shortener/__init__.py, shortener/api.py, shortener/codegen.py, shortener/config.py, shortener/errors.py, shortener/main.py, shortener/service.py, shortener/store.py, shortener/validation.py
- Blast radius: 0 modules

## Data flows

## Interface changes
- POST /api/v1/links, GET /{code}, GET /api/v1/links/{code}/stats, GET /healthz (new)
- new tables: ['links', 'clicks']

## Decisions
- **ADR-001** SQLite with a single locked connection - Zero-ops, transactional, adequate for the prototype's single node _(trade-off: Single-writer; horizontal scaling needs a store swap behind LinkStore)_
- **ADR-002** Redirect with 307 + Cache-Control: no-store - 301/308 are cached by browsers and would hide clicks from analytics _(trade-off: Extra hop on every visit)_
- **ADR-003** Layered api -> service -> store with `# [ext:*]` extension anchors - Features land as small reviewable patches instead of rewrites _(trade-off: Anchors are a convention that must be preserved)_

## Risks
| ID | Scenario | Mitigation | Validation |
|---|---|---|---|
| R-CORE-1 | Short-code collision under load | Unique PK + bounded retry (5) then 503 | service tests: alias conflict |
| R-CORE-2 | SSRF / open redirect to internal hosts | http(s) only; private, loopback and link-local IPs and internal suffixes rejected | parametrised URL validation tests |
| R-CORE-3 | Guessable codes allow enumeration | secrets-based 62^7 codes | uniqueness test + policy bans `random` |
| R-GEN-1 | Generated change violates security/compliance policy | Engine-level policy guardrails block or escalate every change set before it is applied | policy tests + security_review full scan |
| R-GEN-2 | Upstream requirement changes after downstream work finished | Versioned artifacts + hash-based stale detection; only affected stages re-run and are rolled back | replan tests / ambiguous scenario |
| R-GEN-3 | Partial application leaves workspace inconsistent | Atomic apply with receipts; exit-gate failure reverts the stage's changes | rollback tests (injected corrupt syntax) |

## Rollback
- Stage-level: every applied change set has a receipt of pre-images; failures revert automatically
- Release-level: revert the unified patch(es) in artifacts/patches/ (or `git revert` the release commit)
- Data-level: schema changes are additive and nullable; previous code versions ignore new columns
