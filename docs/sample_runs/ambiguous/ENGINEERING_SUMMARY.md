# Engineering summary - ambiguous (ambiguous-20261013-092250-604)

**Run status:** `COMPLETED`
**Mode:** brownfield  |  **Scope delivered:** ['ratelimit', 'blocklist', 'secheaders']  |  **Version:** 1.4.0

## 1. Requirement understanding
> Make the URL shortener production ready. It should be fast and secure, and we are seeing abuse from bots. Also reject links whose destination is a known phishing domain (blocklist).

**Normalised problem:** Deliver the following capabilities on the URL shortener service: rate limiting, domain blocklist, security headers, health endpoint. Constraints: p95 redirect latency <= 50 ms (verified by in-process benchmark); All changes pass policy guardrails: no secrets, parameterised SQL, safe URL handling.

| ID | Capability | Derived from | Evidence |
|---|---|---|---|
| REQ-01 | Rate limiting | stated | abuse |
| REQ-02 | Domain blocklist | stated | phishing |
| REQ-03 | Security headers | clarified:AMB-SEC | security headers |
| REQ-04 | Health endpoint | assumed:AMB-PROD | health |

**Ambiguities detected**

| ID | Question | Resolution |
|---|---|---|
| AMB-PERF | What measurable latency target defines 'fast' (e.g. p95 redirect latency)? | answered: p95 redirect latency under 50 ms. |
| AMB-SEC | Which threats are in scope for 'secure': abuse/spam, malicious destinations, browser/transport hardening? | answered: Throttle abusive clients and add standard browser security headers. |
| AMB-PROD | What does 'production ready' include for this release (health, hardening, limits, docs)? | ASSUMED: health endpoint, security headers and request throttling |
| AMB-ABUSE | What request rate per client should be tolerated before throttling? | ASSUMED: 30 link creations per minute per client |

**Non-functional requirements:** p95 redirect latency <= 50 ms (verified by in-process benchmark); All changes pass policy guardrails: no secrets, parameterised SQL, safe URL handling; Unit and integration tests pass before release

## 2. Plan and rationale
Parallel structure of the workflow graph: `[['codebase_analysis', 'requirements'], ['plan'], ['design'], ['api_spec', 'implement'], ['author_tests', 'docs', 'security_review'], ['verify'], ['release']]`

| Task | Stage | Depends on | Acceptance |
|---|---|---|---|
| T-ANALYZE | codebase_analysis | - | codebase_map produced; no syntax errors |
| T-DESIGN | design | T-ANALYZE | every risk has mitigation + validation; each pack has an ADR |
| T-IMPL-ratelimit | implement | T-DESIGN | policy-clean change set; workspace compiles; marker shortener/ratelimit.py present |
| T-TEST-ratelimit | author_tests | T-DESIGN, T-CONTRACT | limitation recorded; bounded-keys test |
| T-IMPL-blocklist | implement | T-DESIGN | policy-clean change set; workspace compiles; marker shortener/blocklist.py present |
| T-TEST-blocklist | author_tests | T-DESIGN, T-CONTRACT | limitation recorded; notevil.example test |
| T-IMPL-secheaders | implement | T-DESIGN | policy-clean change set; workspace compiles; marker shortener/headers.py present |
| T-TEST-secheaders | author_tests | T-DESIGN, T-CONTRACT | docs |
| T-CONTRACT | api_spec | T-DESIGN | all public endpoints and request fields declared |
| T-VERIFY | verify | T-IMPL-ratelimit, T-IMPL-blocklist, T-IMPL-secheaders, T-TEST-ratelimit, T-TEST-blocklist, T-TEST-secheaders | all tests pass; NFR targets met |
| T-SEC | security_review | T-IMPL-ratelimit, T-IMPL-blocklist, T-IMPL-secheaders | no blocking findings |
| T-DOCS | docs | T-CONTRACT, T-IMPL-ratelimit, T-IMPL-blocklist, T-IMPL-secheaders | docs match contract |
| T-RELEASE | release | T-VERIFY, T-SEC, T-DOCS | all readiness checks green; assumptions approved |

**Impact:** modified `['shortener/api.py', 'shortener/config.py', 'shortener/errors.py', 'shortener/service.py']`, new `['shortener/blocklist.py', 'shortener/headers.py', 'shortener/ratelimit.py']`, blast radius 9 modules.
**High-impact:** True (public API contract/behaviour change, wide blast radius (9 modules))

## 3. Decision lineage (who decided what, on which inputs)
| ID | Stage | Actor | Kind | Decision | Inputs | Status |
|---|---|---|---|---|---|---|
| D-001 | requirements | human:product-owner | approval | APPROVED: Requirements sign-off | raw_requirement@v1 | superseded |
| D-002 | requirements | agent:requirements-analyst | clarification | AMB-PERF: p95 redirect latency under 50 ms. | raw_requirement@v1 | superseded |
| D-003 | requirements | agent:requirements-analyst | clarification | AMB-SEC: Throttle abusive clients and add standard browser security headers. | raw_requirement@v1 | superseded |
| D-004 | requirements | agent:requirements-analyst | assumption | AMB-PROD: ASSUMED 'health endpoint, security headers and request throttling' | raw_requirement@v1 | superseded |
| D-005 | requirements | agent:requirements-analyst | assumption | AMB-ABUSE: ASSUMED '30 link creations per minute per client' | raw_requirement@v1 | superseded |
| D-006 | plan | agent:planner | plan | Scope = ['ratelimit', 'secheaders'] (brownfield) | requirements@v1, codebase_map@v1 | superseded |
| D-007 | design | human:product-owner | approval | APPROVED: Design sign-off (high-impact change) | plan@v1, codebase_map@v1, requirements@v1 | superseded |
| D-008 | design | agent:architect | adr | ADR-020: In-process token bucket keyed by client address | plan@v1, codebase_map@v1, requirements@v1 | superseded |
| D-009 | design | agent:architect | adr | ADR-040: Add nosniff/DENY/no-referrer/HSTS but no Content-Security-Policy | plan@v1, codebase_map@v1, requirements@v1 | superseded |
| D-010 | (external) | human:security-lead | change_request | Change request: Also reject links whose destination is a known phishing domain (blocklist). | - | active |
| D-011 | requirements | human:product-owner | approval | APPROVED: Requirements sign-off | raw_requirement@v2 | active |
| D-012 | plan | agent:planner | plan | Scope = ['ratelimit', 'blocklist', 'secheaders'] (brownfield) | requirements@v2, codebase_map@v1 | active |
| D-013 | design | human:product-owner | approval | APPROVED: Design sign-off (high-impact change) | plan@v2, codebase_map@v1, requirements@v2 | active |
| D-014 | design | agent:architect | adr | ADR-020: In-process token bucket keyed by client address | plan@v2, codebase_map@v1, requirements@v2 | active |
| D-015 | design | agent:architect | adr | ADR-030: Enforce the denylist at creation time, not redirect time | plan@v2, codebase_map@v1, requirements@v2 | active |
| D-016 | design | agent:architect | adr | ADR-040: Add nosniff/DENY/no-referrer/HSTS but no Content-Security-Policy | plan@v2, codebase_map@v1, requirements@v2 | active |
| D-017 | release | human:product-owner | approval | APPROVED: Release approval | verification@v1, security_report@v1, implementation@v2, requirements@v2, docs_bundle@v1, plan@v2, design@v2 | active |

**Trade-offs accepted**

| Decision | Rationale | Trade-off | Alternatives rejected |
|---|---|---|---|
| ADR-020: In-process token bucket keyed by client address | No new infrastructure; O(1) per request; smooths bursts | Not shared across replicas; resets on restart | Redis sliding window; API gateway rate limiting |
| ADR-030: Enforce the denylist at creation time, not redirect time | Keeps the hot redirect path free of extra checks | Links created before a domain is listed keep redirecting; needs a periodic re-scan | Check on every redirect |
| ADR-040: Add nosniff/DENY/no-referrer/HSTS but no Content-Security-Policy | A strict CSP would break the bundled Swagger UI; API returns no HTML | Slightly weaker defence-in-depth | Strict CSP with docs disabled |

## 4. Artifacts
| Artifact | Version | Producer | History |
|---|---|---|---|
| api_contract | 2 | api_spec:api-designer | 2 version(s) |
| codebase_map | 1 | codebase_analysis:codebase-analyst | 1 version(s) |
| design | 2 | design:architect | 2 version(s) |
| docs_bundle | 1 | docs:docs-writer | 1 version(s) |
| implementation | 2 | implement:implementer | 2 version(s) |
| plan | 2 | plan:planner | 2 version(s) |
| raw_requirement | 2 | human:security-lead | 2 version(s) |
| release_report | 1 | release:release-manager | 1 version(s) |
| requirements | 2 | requirements:requirements-analyst | 2 version(s) |
| security_report | 1 | security_review:security-reviewer | 1 version(s) |
| test_suite | 2 | author_tests:test-author | 2 version(s) |
| verification | 1 | verify:verifier | 1 version(s) |

Patches for review: `artifacts/patches/author_tests.patch`, `artifacts/patches/docs.patch`, `artifacts/patches/implement.patch`

Workspace files: 29 (`workspace/`)

## 5. Risks, validation and guardrails
| Risk | Scenario | Mitigation | Validation |
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

**Tests:** 68 passed, 0 failed. **Perf:** p95 3.26 ms vs target 50 ms.
**Security review:** 0 blocking findings; advisories: none

**Release readiness**

| Check | Result | Detail |
|---|---|---|
| tests_pass | PASS | 68 passed |
| nfr_targets_met | PASS | p95 3.26 ms vs 50 ms |
| security_clean | PASS | 0 blocking findings |
| scope_complete | PASS | deferred=[] missing=[] |
| assumptions_approved | PASS | 2 assumptions; sign-off recorded=True |
| rollback_plan_defined | PASS | design.rollback_plan |
| docs_updated | PASS | README.md, docs/API.md, docs/DESIGN.md, CHANGELOG.md |
| no_stale_inputs | PASS | all stage inputs current |

**Policy events:** 0 - none

## 6. Execution record
| Stage | Status | Attempts | Retries | Rollbacks | Time (s) | Last error |
|---|---|---|---|---|---|---|
| codebase_analysis | SUCCEEDED | 1 | 0 | 0 | 0.021 |  |
| requirements | SUCCEEDED | 2 | 0 | 0 | 0.014 |  |
| plan | SUCCEEDED | 2 | 0 | 0 | 0.001 |  |
| design | SUCCEEDED | 2 | 0 | 0 | 0.004 |  |
| api_spec | SUCCEEDED | 2 | 0 | 0 | 0.004 |  |
| implement | SUCCEEDED | 2 | 0 | 1 | 0.046 |  |
| author_tests | SUCCEEDED | 2 | 0 | 1 | 0.015 |  |
| docs | SUCCEEDED | 1 | 0 | 0 | 0.01 |  |
| security_review | SUCCEEDED | 1 | 0 | 0 | 0.045 |  |
| verify | SUCCEEDED | 1 | 0 | 0 | 2.228 |  |
| release | SUCCEEDED | 1 | 0 | 0 | 0.001 |  |

**Human approvals**

| Approval | Stage | Approver | Decision | Comment |
|---|---|---|---|---|
| requirements_signoff | requirements | human:product-owner | APPROVED | Assumptions AMB-PROD and AMB-ABUSE accepted (30 creates/min/client). |
| design_signoff | design | human:product-owner | APPROVED | New 429 / 422 failure modes are acceptable to API clients. |
| requirements_signoff | requirements | human:product-owner | APPROVED | Assumptions AMB-PROD and AMB-ABUSE accepted (30 creates/min/client). |
| design_signoff | design | human:product-owner | APPROVED | New 429 / 422 failure modes are acceptable to API clients. |
| release_approval | release | human:product-owner | APPROVED | Ship. |

**Re-plan** (audit seq 48): stale stages `['requirements']` because artifacts changed `{'requirements': ['raw_requirement']}`; unaffected and reused: `['codebase_analysis', 'plan', 'design', 'api_spec', 'implement', 'author_tests']`

**Re-plan** (audit seq 57): stale stages `['plan', 'design']` because artifacts changed `{'plan': ['requirements'], 'design': ['requirements']}`; unaffected and reused: `['codebase_analysis', 'requirements', 'api_spec', 'implement', 'author_tests']`

**Re-plan** (audit seq 63): stale stages `['api_spec', 'implement', 'author_tests']` because artifacts changed `{'api_spec': ['plan'], 'implement': ['plan'], 'author_tests': ['plan']}`; unaffected and reused: `['codebase_analysis', 'requirements', 'plan']`

## 7. Reliability metrics
| Metric | Value |
|---|---|
| Stage success rate | 100% (11/11) |
| First-attempt success rate | 100% |
| Retries / rollbacks / re-plans | 0 / 2 / 3 |
| Policy blocks | 0 |
| MTTR | n/a |
| Unrecovered incidents | 0 |
| Human approvals (wait) | 5 (0.0 s) |
| End-to-end latency | 2.335 s |

## 8. Assumptions and limitations
- **Assumption AMB-PROD:** health endpoint, security headers and request throttling (flagged for, and covered by, requirements sign-off)
- **Assumption AMB-ABUSE:** 30 link creations per minute per client (flagged for, and covered by, requirements sign-off)
- Out of scope: multi-node deployment, authentication / per-user accounts, UI
- Agents are deterministic and template-backed so the prototype is reproducible offline; the `generator` interface is where an LLM plugs in. Every guardrail (policy, approvals, gates, rollback) applies to any generator.
- Single-process, thread-based scheduler with file-backed state; no distributed workers or durable queue.
- Policy scanning is regex-based (fast, explainable) and is not a substitute for SAST/DAST/SCA in CI.
- Rollback is path-scoped: concurrently running mutating stages must own disjoint file paths (true for this workflow).
- The latency benchmark is in-process (TestClient) - indicative, not a load test.
- Metrics are per run segment: a resumed run reports its own segment's retries/latency.
- Scripted human decisions stand in for reviewers in demos; interactive mode prompts on stdin.
- Residual risk: Static (regex) policy scan; not a substitute for SAST/DAST in CI
- Residual risk: DNS-rebinding SSRF is out of scope: only literal IPs and internal suffixes are screened

## 9. Audit integrity
Hash-chained audit log: 114 entries, verification **OK** (ok).
