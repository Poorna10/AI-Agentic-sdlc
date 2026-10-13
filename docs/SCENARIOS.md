# The three scenarios

Run any of them with `python -m orchestrator run scenarios/<name>.json`. Numbers below come from real runs
(exact artifacts are in `docs/sample_runs/<name>/`; timings vary slightly per run).

All three share the same workflow graph. What differs is what the agents *derive* from the requirement and the
codebase, and which governance paths get exercised.

---

## 1. Greenfield - "build it from scratch" (well-defined requirement)

**Requirement**
> Build a URL shortener service. Users can create short links for long URLs, optionally with a custom alias.
> Visiting a short link redirects to the original URL. Users can view click analytics for a link: total clicks,
> clicks in the last 24 hours and top referrers. Provide a health check endpoint.

**Requirement understanding** - no ambiguity detected, so no questions. Five capabilities extracted with their evidence
(`create_link`, `redirect`, `custom_alias`, `analytics`, `health`), normalised into a problem statement with NFRs
(policy-clean changes, tests pass before release). Out-of-scope is explicit: multi-node, auth, UI.

**Decomposition** - the codebase analyst finds an empty workspace -> `mode: greenfield`; the planner maps all five
capabilities to the `core` pack and emits a dependency-ordered task graph:

```
T-ANALYZE -> T-DESIGN -> T-IMPL-core ----------------------+-> T-VERIFY --+
                  |                                         +-> T-SEC ------+-> T-RELEASE
                  +-> T-CONTRACT -> T-TEST-core ------------+-> T-DOCS -----+
```

**Orchestration highlights**
* Parallel roots (`requirements` ‖ `codebase_analysis`), join at `plan`.
* `design` is classed **high-impact** (new schema, new public API, new dependencies) -> `design_signoff`.
* `implement` proposes `CREATE TABLE` in `store.py` -> policy **CHG-002 REQUIRE_APPROVAL** -> human approves with a comment
  (recorded in the lineage). `author_tests` runs concurrently with `implement` (disjoint paths).
* `verify` ‖ `security_review` ‖ `docs`, then `release` with `release_approval`.

```
✋ approval_requested  requirements  requirements_signoff
👤 approval_decision   design        design_signoff -> APPROVED by human:tech-lead
⛔ policy_violation    implement     CHG-002 REQUIRE_APPROVAL - persistent schema change [shortener/store.py]
👤 approval_decision   implement     policy:CHG-002:implement -> APPROVED by human:tech-lead
✔ stage_succeeded     author_tests  ...                      (ran while implement was still applying)
✔ stage_succeeded     verify        ...
✋ approval_requested  release       release_approval
```

**Validation** - 45 tests pass in the delivered workspace (42 product tests + 3 generated from the API contract), including SSRF/URL
validation matrices, alias rules, analytics windows with an injected clock, and the full create -> redirect -> stats flow. Security review: 0 blocking
findings; advisories list the missing hardening (no rate limit / blocklist / headers) as **residual risk** - which is exactly what scenario 3 addresses.
Release readiness: 8/8 checks green. Stage success 100%, 4 human approvals, 0 retries.

---

## 2. Brownfield - "enhance what exists" (link expiry + click budgets)

Starting point: the greenfield result (`core` pack) installed as the existing codebase.

**Requirement**
> Links must be able to expire after a configurable TTL, and optionally stop working after a maximum number of clicks.
> Expired links must return HTTP 410. Existing links must keep working: no breaking API change and no data loss.

**Requirement understanding** - capabilities `expiry`, `click_limit`; the constraint *"existing links must keep working"* is
recognised and promoted to **NFR-COMPAT** (additive, data-preserving migration).

**Codebase reasoning** - the analyst parses the AST: 9 modules, 4 routes, tables `links`/`clicks`, the module import graph and 14
`# [ext:*]` extension anchors. The planner sees `core` already present and plans **only** `expiry` (it does not regenerate anything).
The architect previews the exact footprint (read-only) and computes impact:

* modified: `api.py`, `service.py`, `store.py`, `errors.py`; new: `lifecycle.py`; blast radius 7 modules
* data flow: `POST /api/v1/links -> api.py -> service.py -> store.py -> tables [links, clicks]`
* high-impact because of a schema change and an API behaviour change -> `design_signoff`
* risks with mitigation **and** validation (R-EXP-1 migration safety -> legacy-DB test; R-EXP-2 click-budget race -> atomic
  `BEGIN IMMEDIATE`; R-EXP-3 clock skew -> injected clock), a three-level rollback plan, and ADR-010/011 with rejected alternatives

**Orchestration highlights - faults are injected on purpose** (`faults` in `scenarios/brownfield.json`)

```
⛔ policy_violation  implement  CHG-002 REQUIRE_APPROVAL - persistent schema change [shortener/store.py]
👤 approval_decision implement  policy:CHG-002:implement -> APPROVED by human:service-owner   (ALTER TABLE is additive)
↩ rollback          implement  post-apply failure: 6 file(s) reverted
✘ attempt_failed    implement  attempt=1 GateFailed: exit gate failed: workspace does not compile: shortener/broken.py:1: invalid syntax
✔ stage_succeeded   implement  attempt=2
✘ attempt_failed    docs       attempt=1 TransientAgentError: injected transient failure (docs, attempt 1)
✔ stage_succeeded   docs       attempt=2
```

* Attempt 1 of `implement` emits a file that does not compile. The change set was applied, the **exit gate caught it, the receipt reverted
  all 6 touched files**, and the retry succeeded. The workspace was never left half-changed.
* `docs` hit a transient failure and recovered on retry.
* Metrics from the run: 2 retries, 1 rollback, 2 recovered incidents, MTTR ~0.03 s, first-attempt success 82% (9 of 11 stages).

**Validation** - 55 tests (the original 42 still pass = no regression, plus expiry/budget/migration tests and contract tests). The key one is
`test_existing_database_is_migrated_without_data_loss`: it builds a pre-upgrade SQLite file by hand, upgrades, and resolves an old link.
Review artifact: `artifacts/patches/implement.patch` shows the real diff against the existing files.

---

## 3. Ambiguous - "make it production ready"

Starting point: `core` + `expiry` installed.

**Requirement**
> Make the URL shortener production ready. It should be fast and secure, and we are seeing abuse from bots.

**Requirement understanding** - the analyst flags four ambiguities and asks targeted questions instead of guessing:

| ID | Question | Resolution |
|---|---|---|
| AMB-PERF | What measurable latency target defines "fast"? | answered: *p95 redirect latency under 50 ms* -> becomes **NFR-PERF**, enforced later by a benchmark gate |
| AMB-SEC | Which threats are in scope for "secure"? | answered: *throttle abusive clients, add standard browser security headers* |
| AMB-PROD | What does "production ready" include? | **no answer -> ASSUMED** *health endpoint, security headers, request throttling* |
| AMB-ABUSE | What request rate per client? | **no answer -> ASSUMED** *30 link creations per minute per client* (flows into the generated code as a parameter) |

Capabilities carry provenance (`stated`, `clarified:AMB-SEC`, `assumed:AMB-PROD`). The two assumptions are listed in the
`requirements_signoff` approval and tracked: the release gate checks `assumptions_approved` (a sign-off decision must exist and still be active).

**Mid-run change request** - after `implement` finishes, the security lead adds: *"Also reject links whose destination is a known phishing domain."*
The engine re-plans (full mechanism in `docs/ARCHITECTURE.md` section 5):

```
✎ requirement_amended  Also reject links whose destination is a known phishing domain (blocklist).
♻ replan  stale=['requirements']
♻ replan  stale=['plan', 'design']                         <- plan v2 now includes the blocklist pack
♻ replan  stale=['api_spec', 'implement', 'author_tests']
↩ rollback implement: replan: 5 file(s) reverted
↩ rollback author_tests: replan: 3 file(s) reverted
```

Plan before: `[ratelimit, secheaders]` -> after: `[ratelimit, blocklist, secheaders]`. `codebase_analysis` was reused. The earlier requirement/design
approvals appear in the lineage as `superseded` and were re-requested for the new versions; the change request itself is attributed to
`(external)` and stays active.

**Validation** - 68 tests pass; the **perf NFR is gated**: the verifier benchmarks 300 redirects and compares p95 (about 3 ms) against the clarified 50 ms target.
Security review: 0 blocking findings and **no residual advisories** (rate limit, blocklist, headers all present). Release readiness 8/8 including
`assumptions_approved` and `no_stale_inputs`. Metrics: 3 re-plans, 2 rollbacks, 5 approvals.

**Smoke test of the delivered service over HTTP** (done during development): alias + TTL link created; redirect returned 307 with
`X-Frame-Options`/HSTS headers; stats counted the referrer; `login.phishing.test` -> 422 `domain_blocked`; `169.254.169.254` -> 422 `invalid_url`; the 31st creation in a minute -> 429.

---

## Additional governance paths (covered by tests, runnable via CLI flags)

| Path | How to trigger | Expected |
|---|---|---|
| Repeated policy violations -> fallback | `--inject implement:1:policy_violation --inject implement:2:... --inject implement:3:...` | 3 blocks, fallback agent succeeds, secret never lands |
| Unrecoverable stage | inject on attempts 1-4 | `implement` FAILED, `release` BLOCKED, `author_tests` still SUCCEEDED, no partial code |
| Human rejection | `--reject-all` | SAFE_STOPPED, later stages SKIPPED; `resume` finishes without redoing completed stages |
| Kill-switch | `touch runs/<dir>/STOP` | SAFE_STOPPED |
