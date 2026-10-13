# Final engineering summary

## Plan and rationale

The assignment's differentiator is orchestration, so the work was sequenced to make the orchestrator the product:

1. **Workload first, deliberately small and real** - a URL shortener split into five feature packs (`core`, `expiry`, `ratelimit`, `blocklist`, `secheaders`) with their own tests,
   so scenarios have genuine greenfield, brownfield (edits to existing files) and hardening work to do. Packs were verified to apply in any order and pass together (65 product tests) before any orchestration existed.
2. **Governance primitives next** - explicit DAG with data-flow validation, versioned artifact store with decision lineage, policy engine, atomic workspace with receipts, hash-chained audit, metrics.
3. **Engine** - one stage lifecycle that every stage goes through (entry gate -> bounded attempts -> policy -> approval -> atomic apply -> exit gate -> outcome approval -> commit), a parallel scheduler with joins,
   fallback, rollback, safe-stop, and change-propagation re-planning.
4. **Agents** - small, single-purpose, propose-only.
5. **Scenarios, then tests, then docs** - tests were written against behaviours (and found real defects, listed in `docs/TESTING_AND_TRADEOFFS.md`).

Why this shape: it gives each requirement in section 4 of the brief a concrete, testable mechanism (traceability table below), and keeps humans as owners of approvals and quality.

## Artifacts delivered

* **Prototype:** `orchestrator/` (~2.6k lines, standard library only) + `orchestrator/packs/templates/` (the shortener, ~0.9k lines) + 52 tests.
* **Per-run outputs:** delivered workspace, `ENGINEERING_SUMMARY.md`, `audit.jsonl`, `lineage.json`, `metrics.json`, `design.md`, unified patches, resumable `state.json`.
* **Docs:** architecture, three scenarios, testing/limitations/trade-offs, setup (README), sample runs and the final service under `examples/final_service/`.

## Traceability to the brief

| Requirement | Mechanism | Evidence |
|---|---|---|
| Requirement understanding | Ambiguity lexicon -> targeted questions -> answers or **flagged assumptions**; capability extraction with provenance; NFR promotion | ambiguous scenario; `test_agents.py` |
| Task decomposition with dependencies | Planner builds a dependency-ordered task graph from capabilities minus what the codebase already has | task tables in each summary |
| Codebase reasoning | AST analysis: modules, routes, import graph, tables, extension anchors; footprint preview; blast radius; data-flow chains | brownfield scenario |
| **Explicit dependency graph + entry/exit gates** | `WorkflowGraph` (cycle + data-flow validation), per-stage gates, implicit declared-output gate | `test_graph.py`, `workflow.py` |
| Sequential + parallel with synchronisation | Event-driven scheduler; joins at plan / verify / release; run-only-when-all-ancestors-done | `test_engine.py::parallel`, traces |
| Cross-stage context + decision lineage | Hash-versioned artifacts; each stage records consumed versions; decisions with actor/rationale/alternatives/inputs/superseded | `lineage.json`, summary section 3 |
| Human approval checkpoints | Stage sign-offs + policy `REQUIRE_APPROVAL` for schema/PII/protected path/new dependency | audit `approval_*` events |
| Bounded retries, fallback, rollback, safe-stop | Per-stage retry bound + run budget; safe-mode implementer / minimal docs; receipts; kill-switch, rejection, critical failure | chaos tests, brownfield scenario |
| Policy guardrails (security / compliance / change control) | 10 rules, evaluated on every change set; plus full-workspace re-scan | `test_policy_workspace_audit.py` |
| Audit-grade observability | Hash-chained audit, `verify-audit`, per-run summary | tamper test |
| Reliability metrics | success rate, first-attempt rate, retries, rollbacks, MTTR, latency, approval wait | `metrics.json`, `orchestrator metrics` |
| Dynamic re-plan under governance | Quiesce -> stale detection by consumed versions -> rollback -> minimal re-execution; approvals re-requested | ambiguous scenario, replan tests |
| Production-quality outputs | Layered service, parameterised SQL, secure codes, SSRF checks, atomic budget, generated API contract tests, docs, changelog | delivered workspaces |
| Validation and risk control | Risk register with mitigation **and** validation per risk; NFR benchmark gate; release checklist | summary section 5 |
| Final engineering summary | `report.py` generates it from the run's own records | `docs/sample_runs/*/ENGINEERING_SUMMARY.md` |

## Risks, trade-offs and validation

Detailed in `docs/TESTING_AND_TRADEOFFS.md`. In one line each: deterministic agents trade open-endedness for reproducibility (LLM seam provided, guardrails inherited);
single-process threads trade scale for simplicity; regex policy trades depth for explainability; path-scoped rollback requires disjoint stage ownership; the audit chain is tamper-evident, not tamper-proof.

## Assumptions

* "Agentic" is demonstrated by autonomy *boundaries and controls*, so agents are deterministic and template-backed rather than model-backed; the brief evaluates orchestration, governance and engineering judgement over raw generation.
* A single-node SQLite service is an acceptable v1 for the workload; scale-out is documented, not built.
* Scripted approvals stand in for reviewers in demos; interactive mode exists for real use.
* Stakeholder change requests and clarification answers arrive as scenario data (events/answers) so runs are reproducible.

## Limitations

See section "Limitations" in `docs/TESTING_AND_TRADEOFFS.md` (nine items); the three most important: no LLM wired in, single-process execution, and regex-based policy scanning.
