# Engineering summary - brownfield (brownfield-20261013-092249-407)

**Run status:** `COMPLETED`
**Mode:** brownfield  |  **Scope delivered:** ['expiry']  |  **Version:** 1.1.0

## 1. Requirement understanding
> Links must be able to expire after a configurable TTL, and optionally stop working after a maximum number of clicks. Expired links must return HTTP 410. Existing links must keep working: no breaking API change and no data loss.

**Normalised problem:** Deliver the following capabilities on the URL shortener service: link expiry (ttl), click budget. Constraints: Backward compatible: existing links and API clients keep working; migrations are additive and data-preserving; All changes pass policy guardrails: no secrets, parameterised SQL, safe URL handling.

| ID | Capability | Derived from | Evidence |
|---|---|---|---|
| REQ-01 | Link expiry (TTL) | stated | expire |
| REQ-02 | Click budget | stated | stop working after a maximum number of clicks |

**Non-functional requirements:** Backward compatible: existing links and API clients keep working; migrations are additive and data-preserving; All changes pass policy guardrails: no secrets, parameterised SQL, safe URL handling; Unit and integration tests pass before release

## 2. Plan and rationale
Parallel structure of the workflow graph: `[['codebase_analysis', 'requirements'], ['plan'], ['design'], ['api_spec', 'implement'], ['author_tests', 'docs', 'security_review'], ['verify'], ['release']]`

| Task | Stage | Depends on | Acceptance |
|---|---|---|---|
| T-ANALYZE | codebase_analysis | - | codebase_map produced; no syntax errors |
| T-DESIGN | design | T-ANALYZE | every risk has mitigation + validation; each pack has an ADR |
| T-IMPL-expiry | implement | T-DESIGN | policy-clean change set; workspace compiles; marker shortener/lifecycle.py present |
| T-TEST-expiry | author_tests | T-DESIGN, T-CONTRACT | legacy-database migration test; budget enforcement test; fake-clock tests |
| T-CONTRACT | api_spec | T-DESIGN | all public endpoints and request fields declared |
| T-VERIFY | verify | T-IMPL-expiry, T-TEST-expiry | all tests pass; NFR targets met |
| T-SEC | security_review | T-IMPL-expiry | no blocking findings |
| T-DOCS | docs | T-CONTRACT, T-IMPL-expiry | docs match contract |
| T-RELEASE | release | T-VERIFY, T-SEC, T-DOCS | all readiness checks green; assumptions approved |

**Impact:** modified `['shortener/api.py', 'shortener/errors.py', 'shortener/service.py', 'shortener/store.py']`, new `['shortener/lifecycle.py']`, blast radius 7 modules.
**High-impact:** True (persistent schema change, public API contract/behaviour change, wide blast radius (7 modules))

## 3. Decision lineage (who decided what, on which inputs)
| ID | Stage | Actor | Kind | Decision | Inputs | Status |
|---|---|---|---|---|---|---|
| D-001 | requirements | human:service-owner | approval | APPROVED: Requirements sign-off | raw_requirement@v1 | active |
| D-002 | plan | agent:planner | plan | Scope = ['expiry'] (brownfield) | requirements@v1, codebase_map@v1 | active |
| D-003 | design | human:service-owner | approval | APPROVED: Design sign-off (high-impact change) | plan@v1, codebase_map@v1, requirements@v1 | active |
| D-004 | design | agent:architect | adr | ADR-010: Additive nullable columns instead of a new table | plan@v1, codebase_map@v1, requirements@v1 | active |
| D-005 | design | agent:architect | adr | ADR-011: HTTP 410 Gone for expired and exhausted links | plan@v1, codebase_map@v1, requirements@v1 | active |
| D-006 | implement | human:service-owner | approval | APPROVED: High-impact change (CHG-002) | plan@v1, design@v1 | active |
| D-007 | implement | human:service-owner | approval | APPROVED: High-impact change (CHG-002) | plan@v1, design@v1 | active |
| D-008 | release | human:service-owner | approval | APPROVED: Release approval | verification@v1, security_report@v1, implementation@v1, requirements@v1, docs_bundle@v1, plan@v1, design@v1 | active |

**Trade-offs accepted**

| Decision | Rationale | Trade-off | Alternatives rejected |
|---|---|---|---|
| ADR-010: Additive nullable columns instead of a new table | Keeps existing rows valid with zero backfill; trivially reversible | Wider links table; revisit if more per-link policy accumulates | link_policies table; full migration framework |
| ADR-011: HTTP 410 Gone for expired and exhausted links | Distinguishes 'existed but is gone' from 404 for clients and crawlers | Reveals that a code once existed | 404; 403 |

## 4. Artifacts
| Artifact | Version | Producer | History |
|---|---|---|---|
| api_contract | 1 | api_spec:api-designer | 1 version(s) |
| codebase_map | 1 | codebase_analysis:codebase-analyst | 1 version(s) |
| design | 1 | design:architect | 1 version(s) |
| docs_bundle | 1 | docs:docs-writer | 1 version(s) |
| implementation | 1 | implement:implementer | 1 version(s) |
| plan | 1 | plan:planner | 1 version(s) |
| raw_requirement | 1 | human:requester | 1 version(s) |
| release_report | 1 | release:release-manager | 1 version(s) |
| requirements | 1 | requirements:requirements-analyst | 1 version(s) |
| security_report | 1 | security_review:security-reviewer | 1 version(s) |
| test_suite | 1 | author_tests:test-author | 1 version(s) |
| verification | 1 | verify:verifier | 1 version(s) |

Patches for review: `artifacts/patches/author_tests.patch`, `artifacts/patches/docs.patch`, `artifacts/patches/implement.patch`

Workspace files: 23 (`workspace/`)

## 5. Risks, validation and guardrails
| Risk | Scenario | Mitigation | Validation |
|---|---|---|---|
| R-EXP-1 | Migration breaks or loses existing links | Additive nullable columns, idempotent PRAGMA-guarded migration; NULL = unlimited | legacy-database migration test |
| R-EXP-2 | Click budget overshoot under concurrent redirects | Count+insert inside BEGIN IMMEDIATE transaction | budget enforcement test |
| R-EXP-3 | Clock skew makes links expire early/late | Single injected clock; expiry stored as absolute epoch | fake-clock tests |
| R-GEN-1 | Generated change violates security/compliance policy | Engine-level policy guardrails block or escalate every change set before it is applied | policy tests + security_review full scan |
| R-GEN-2 | Upstream requirement changes after downstream work finished | Versioned artifacts + hash-based stale detection; only affected stages re-run and are rolled back | replan tests / ambiguous scenario |
| R-GEN-3 | Partial application leaves workspace inconsistent | Atomic apply with receipts; exit-gate failure reverts the stage's changes | rollback tests (injected corrupt syntax) |

**Tests:** 55 passed, 0 failed. 
**Security review:** 0 blocking findings; advisories: ['No rate limiting: link creation can be abused', 'No destination blocklist: malicious domains can be shortened', 'No security response headers']

**Release readiness**

| Check | Result | Detail |
|---|---|---|
| tests_pass | PASS | 55 passed |
| nfr_targets_met | PASS | no benchmark required |
| security_clean | PASS | 0 blocking findings |
| scope_complete | PASS | deferred=[] missing=[] |
| assumptions_approved | PASS | 0 assumptions; sign-off recorded=True |
| rollback_plan_defined | PASS | design.rollback_plan |
| docs_updated | PASS | README.md, docs/API.md, docs/DESIGN.md, CHANGELOG.md |
| no_stale_inputs | PASS | all stage inputs current |

**Policy events:** 2 - CHG-002(REQUIRE_APPROVAL)@implement

## 6. Execution record
| Stage | Status | Attempts | Retries | Rollbacks | Time (s) | Last error |
|---|---|---|---|---|---|---|
| codebase_analysis | SUCCEEDED | 1 | 0 | 0 | 0.01 |  |
| requirements | SUCCEEDED | 1 | 0 | 0 | 0.003 |  |
| plan | SUCCEEDED | 1 | 0 | 0 | 0.0 |  |
| design | SUCCEEDED | 1 | 0 | 0 | 0.002 |  |
| api_spec | SUCCEEDED | 1 | 0 | 0 | 0.0 |  |
| implement | SUCCEEDED | 2 | 1 | 1 | 0.018 |  |
| author_tests | SUCCEEDED | 1 | 0 | 0 | 0.005 |  |
| docs | SUCCEEDED | 2 | 1 | 0 | 0.003 |  |
| security_review | SUCCEEDED | 1 | 0 | 0 | 0.033 |  |
| verify | SUCCEEDED | 1 | 0 | 0 | 1.032 |  |
| release | SUCCEEDED | 1 | 0 | 0 | 0.001 |  |

**Human approvals**

| Approval | Stage | Approver | Decision | Comment |
|---|---|---|---|---|
| requirements_signoff | requirements | human:service-owner | APPROVED | Backward-compat constraint captured. |
| design_signoff | design | human:service-owner | APPROVED | Additive nullable columns agreed; rollback plan reviewed. |
| policy:CHG-002:implement | implement | human:service-owner | APPROVED | ALTER TABLE is additive and idempotent. |
| policy:CHG-002:implement | implement | human:service-owner | APPROVED | ALTER TABLE is additive and idempotent. |
| release_approval | release | human:service-owner | APPROVED | Legacy-DB migration test is green. |

## 7. Reliability metrics
| Metric | Value |
|---|---|
| Stage success rate | 100% (11/11) |
| First-attempt success rate | 82% |
| Retries / rollbacks / re-plans | 2 / 1 / 0 |
| Policy blocks | 0 |
| MTTR | 0.032 s over 2 incident(s) |
| Unrecovered incidents | 0 |
| Human approvals (wait) | 5 (0.0 s) |
| End-to-end latency | 1.112 s |

## 8. Assumptions and limitations
- Out of scope: multi-node deployment, authentication / per-user accounts, UI
- Agents are deterministic and template-backed so the prototype is reproducible offline; the `generator` interface is where an LLM plugs in. Every guardrail (policy, approvals, gates, rollback) applies to any generator.
- Single-process, thread-based scheduler with file-backed state; no distributed workers or durable queue.
- Policy scanning is regex-based (fast, explainable) and is not a substitute for SAST/DAST/SCA in CI.
- Rollback is path-scoped: concurrently running mutating stages must own disjoint file paths (true for this workflow).
- The latency benchmark is in-process (TestClient) - indicative, not a load test.
- Metrics are per run segment: a resumed run reports its own segment's retries/latency.
- Scripted human decisions stand in for reviewers in demos; interactive mode prompts on stdin.
- Residual risk: No rate limiting: link creation can be abused
- Residual risk: No destination blocklist: malicious domains can be shortened
- Residual risk: No security response headers
- Residual risk: Static (regex) policy scan; not a substitute for SAST/DAST in CI
- Residual risk: DNS-rebinding SSRF is out of scope: only literal IPs and internal suffixes are screened

## 9. Audit integrity
Hash-chained audit log: 82 entries, verification **OK** (ok).
