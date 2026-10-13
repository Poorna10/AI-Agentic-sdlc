# Testing approach, limitations and trade-offs

## Testing approach

Three layers, because there are three things that can be wrong: the product, the governance, and the way they interact.

| Layer | Where | What it proves |
|---|---|---|
| **Product tests** (shipped *inside* each delivered workspace, 45-68 depending on scope) | `orchestrator/packs/templates/*/files/tests/` + generated contract tests | URL validation / SSRF matrix, alias rules, analytics windows (injected clock), 307/404/409/410/422/429 behaviour, legacy-DB migration, atomic click budget, bounded limiter memory, headers on every response, API contract conformance |
| **Governance tests** (52 tests in `tests/`) | `test_graph`, `test_policy_workspace_audit`, `test_engine`, `test_agents` | Each control tested in isolation on toy graphs with stub agents: cycle/dataflow rejection, `ready()` semantics, every policy rule, atomic apply/revert, ambiguous-anchor refusal, audit tamper detection, bounded retries, fallback, rollback on exit-gate failure, never-applied BLOCK changes, approval rejection -> safe-stop, critical-stage safe-stop, STOP file, run retry budget, parallel overlap + join, minimal-vs-cascading re-plan, rollback on re-plan, requirement analysis (including false-positive guards), planner dependency logic, safe-mode deferral, interactive approvals |
| **End-to-end scenario tests** | `tests/test_scenarios.py` | The three scenarios complete and their delivered workspaces pass their own suites when re-run independently; chaos paths (fallback after repeated violations, fail-closed total failure, reject -> safe-stop -> resume with unbroken audit chain); every run has a verifiable audit chain and a complete summary |

Run everything with `pytest` (about 10 s). Testing the *controls* separately from the *agents* means a governance regression cannot hide behind a lucky scenario.

**Things the tests caught while building this** (kept as regression tests): a secret regex that missed `API_TOKEN = "..."` (word-boundary bug - which also meant
my own fault injector would not have triggered); keyword false positives in requirement extraction (`ttl` inside "throttle", `redirect` inside "redirect latency");
`--reject-all` being overridden by scripted approvals; a change request being marked superseded because it was filed under a stage; docs/tests mentioning `ALTER TABLE` triggering the schema rule.

## Validation and risk control built into the run itself

* Pre-apply: policy BLOCK/APPROVE on every change set; path confinement; anchor must match exactly once or the edit fails closed.
* Post-apply: workspace compiles, pack markers exist, declared outputs present; then full test suite, NFR benchmark, full-workspace security scan; then release checklist (8 checks).
* Residual risk is *reported*, not hidden: the security report lists unmitigated posture gaps and standing limitations, and they flow into the engineering summary.

## Limitations (honest list)

1. **Agents are deterministic and template-backed.** This makes runs reproducible and testable offline, but code "generation" is selection and parameterisation of vetted packs, not open-ended synthesis. The LLM seam exists (`generator.propose`) and inherits every guardrail, but no LLM is wired in. Requirement understanding is rule-based (regex lexicon), so unfamiliar phrasing will be missed.
2. **Single process.** Thread pool + local files; no distributed workers, durable queue or leader election. State is persisted after each stage and runs are resumable, but a crash *during* a stage re-runs that stage.
3. **Rollback is path-scoped.** Safe because parallel mutating stages write disjoint paths; two parallel stages touching the same file would break the invariant (not enforced by the engine today).
4. **Regex policy engine.** Explainable and fast, but coarse (misses obfuscation, flags some benign strings). It is a guardrail, not a SAST/SCA/DAST replacement.
5. **Product limits:** rate limiter is per-process (N replicas = N x limit) and keyed by socket address (NAT/proxy users share a bucket; no trusted-proxy header handling); blocklist is static config and enforced at creation, so links created before a domain is listed keep redirecting; SSRF protection screens literal IPs and internal suffixes but does not resolve DNS (rebinding out of scope); SQLite is single-writer.
6. **Benchmark is in-process** (TestClient) - useful as a regression gate, not a capacity claim.
7. **Metrics are per run segment**; a resumed run reports its own segment.
8. **Scripted humans.** Demos use scripted approvals; `--interactive` prompts on stdin. There is no identity verification of approvers (the approver string is recorded, not authenticated).
9. **Audit chain is local**: tamper-*evident*, not tamper-*proof* - an attacker with write access could rewrite the whole file consistently; production should stream entries to an external append-only store.

## Trade-offs worth defending

* **Governance in the engine, not in prompts.** More code, but controls are testable, uniform across agents and cannot be talked around.
* **Incremental re-execution via content hashes** instead of re-running everything after a change: cheaper and more informative (the audit log shows exactly *why* each stage re-ran), at the price of requiring deterministic stages.
* **Fail closed.** A stage that cannot be delivered safely fails (or, in safe mode, is deferred and flagged) rather than shipping partial or unreviewed output. This lowers throughput on purpose.
* **Approvals after an outcome exists.** Reviewers judge a concrete diff/design, at the cost of a discarded attempt when they refuse.
* **Fallback = degrade, not mask.** Safe-mode delivery completes the stage but sets `deferred_packs`, which the release gate turns into a failed `scope_complete` check - the degradation cannot be released by accident.

## Path to production

LLM-backed generator behind the existing interface; swap threads for a durable workflow engine (Temporal) keeping the graph/gate/policy code; ship the audit log to an
append-only store; enforce path ownership per stage; add SAST/SCA (e.g. Semgrep, pip-audit) as additional gates; authenticated approvers (SSO) and four-eyes rules for release;
shared rate-limit store (Redis) and Postgres for the product; wire `metrics.json` into dashboards with SLOs on first-attempt success and MTTR.
