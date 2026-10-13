# Agentic SDLC Orchestrator - URL Shortener

A runnable prototype that turns a plain-English requirement into a **reviewable, governed engineering
outcome**: requirements -> plan -> design -> implementation -> tests -> docs -> release gate, executed by
agents inside an orchestration layer that owns the controls (dependency graph, gates, policy, approvals,
retries/rollback/safe-stop, re-planning, audit, metrics).

The system under construction is a URL shortener (create / redirect / analytics, then expiry, rate limiting,
blocklist, security headers). The *orchestrator* is the deliverable that matters; the shortener is the
workload it builds, extends and hardens in three scenarios.

> **Principle:** agents *propose* (artifacts, decisions, workspace changes); the engine *disposes*
> (policy-checks, asks humans, applies atomically, verifies, rolls back). Humans own approvals and final quality.

## Quick start

Requires Python 3.10+ (developed on 3.12). The orchestrator itself is standard-library only; the generated
service and tests need FastAPI.

```bash
pip install -r requirements.txt

pytest                                                    # 52 tests: governance, agents, 3 scenarios, chaos paths

python -m orchestrator run scenarios/greenfield.json      # build from scratch
python -m orchestrator run scenarios/brownfield.json      # enhance existing code (+ injected faults)
python -m orchestrator run scenarios/ambiguous.json       # vague ask -> clarification -> mid-run re-plan
```

Each run prints a live event trace and writes everything to `runs/<scenario>-<timestamp>/`:

| Path | Contents |
|---|---|
| `workspace/` | the delivered code (a real, runnable service with its tests) |
| `ENGINEERING_SUMMARY.md` | plan/rationale, artifacts, risks/trade-offs/validation, assumptions, limitations, metrics |
| `audit.jsonl` | hash-chained, append-only audit log of every action and decision |
| `lineage.json` | artifact versions and decision lineage (who decided what, on which input versions) |
| `metrics.json` | success rate, retries, rollbacks, MTTR, end-to-end latency, per-stage detail |
| `artifacts/` | `design.md` and per-stage unified patches (`patches/implement.patch`, ...) for review |
| `state.json` | resumable run state |

Run the delivered service:

```bash
cd runs/ambiguous-*/workspace && uvicorn shortener.main:app --port 8000
curl -X POST localhost:8000/api/v1/links -H 'content-type: application/json' \
     -d '{"url":"https://example.com/docs","alias":"demo","ttl_seconds":3600}'
curl -i localhost:8000/demo
curl localhost:8000/api/v1/links/demo/stats
```

### Other commands

```bash
python -m orchestrator run scenarios/greenfield.json --interactive    # you are the approver / clarifier (stdin)
python -m orchestrator run scenarios/greenfield.json --reject-all     # every approval refused -> safe-stop
python -m orchestrator resume runs/<run-dir>                          # keeps SUCCEEDED stages, retries the rest
python -m orchestrator run scenarios/greenfield.json \
       --inject implement:1:policy_violation --inject implement:2:policy_violation   # chaos: STAGE:ATTEMPT:TYPE
python -m orchestrator metrics                                        # reliability metrics across runs
python -m orchestrator verify-audit runs/<run-dir>                    # check the audit hash chain
python -m orchestrator graph                                          # workflow DAG as Mermaid
touch runs/<run-dir>/STOP                                             # operator kill-switch (safe-stop)
```

Fault types: `exception` (transient agent failure), `policy_violation` (agent emits a hard-coded secret),
`corrupt_syntax` (agent emits code that does not compile).

## Where things are

| Deliverable | Location |
|---|---|
| Working prototype | `orchestrator/` (engine + agents), `orchestrator/packs/templates/` (the shortener, as feature packs) |
| Architecture overview | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Three scenarios (decomposition, orchestration, validation) | [`docs/SCENARIOS.md`](docs/SCENARIOS.md) + `scenarios/*.json` |
| Testing approach, limitations, trade-offs | [`docs/TESTING_AND_TRADEOFFS.md`](docs/TESTING_AND_TRADEOFFS.md) |
| Final engineering summary | [`docs/FINAL_ENGINEERING_SUMMARY.md`](docs/FINAL_ENGINEERING_SUMMARY.md); per-run: `docs/sample_runs/*/ENGINEERING_SUMMARY.md` |
| Real outputs without running anything | `docs/sample_runs/` (summaries, audit logs, patches) and `examples/final_service/` (the final delivered service) |

## Repository layout

```
orchestrator/
  engine.py        scheduler, stage lifecycle, retries/fallback/rollback/safe-stop, re-plan
  workflow.py      the SDLC DAG, entry/exit gates, approval checkpoints
  graph.py         explicit dependency graph (cycle + data-flow validation, parallel levels)
  context.py       versioned artifact store + decision lineage
  policy.py        security / compliance / change-control guardrails
  approvals.py     human-in-the-loop (scripted | interactive | reject_all)
  workspace.py     sandbox with atomic apply, receipts and path-scoped rollback
  audit.py         tamper-evident hash-chained audit log
  metrics.py       reliability metrics
  report.py        final engineering summary + lineage
  catalog.py       capability -> feature-pack knowledge (risks, ADRs, endpoints)
  agents/          requirements, codebase, planner, architect, api-designer, implementer(+safe mode),
                   test-author, verifier, security-reviewer, docs-writer(+minimal), release-manager
  packs/           template-backed code generator + the shortener as 5 feature packs
scenarios/         greenfield.json, brownfield.json, ambiguous.json
tests/             52 tests
docs/              architecture, scenarios, testing & trade-offs, summaries, sample runs
```
