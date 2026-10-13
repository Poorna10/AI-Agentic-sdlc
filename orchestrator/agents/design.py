"""Architecture / impact analysis, risk register, ADRs and rollback plan."""
from __future__ import annotations

from collections import defaultdict, deque

from ..catalog import API_META, PACKS
from ..model import AgentResult, Stage
from . import Agent

GENERIC_RISKS = [
    {"id": "R-GEN-1", "scenario": "Generated change violates security/compliance policy",
     "mitigation": "Engine-level policy guardrails block or escalate every change set before it is applied",
     "validation": "policy tests + security_review full scan"},
    {"id": "R-GEN-2", "scenario": "Upstream requirement changes after downstream work finished",
     "mitigation": "Versioned artifacts + hash-based stale detection; only affected stages re-run and are rolled back",
     "validation": "replan tests / ambiguous scenario"},
    {"id": "R-GEN-3", "scenario": "Partial application leaves workspace inconsistent",
     "mitigation": "Atomic apply with receipts; exit-gate failure reverts the stage's changes",
     "validation": "rollback tests (injected corrupt syntax)"},
]


class ArchitectAgent(Agent):
    name = "architect"

    def __init__(self, generator=None) -> None:
        from ..packs import TemplateGenerator
        self.gen = generator or TemplateGenerator()

    def run(self, ctx, stage: Stage) -> AgentResult:
        plan, cmap, req = ctx.get("plan"), ctx.get("codebase_map"), ctx.get("requirements")
        todo = plan["todo_packs"]
        existing = set(cmap["modules"])

        # exact footprint: preview each pack's proposed change set (read-only, nothing is applied)
        created_set, modified_set = set(), set()
        for p in todo:
            for ch in self.gen.propose(p, include="src"):
                (created_set if ch.kind == "write" else modified_set).add(ch.path)
        touched = created_set | modified_set
        modified = sorted(touched & existing)       # already in the codebase => modification
        created = sorted(touched - existing)        # not there yet => new file

        # blast radius: modules that (transitively) import something we modify
        rev = defaultdict(set)
        for a, b in cmap["edges"]:
            rev[b].add(a)
        blast, q = set(modified), deque(modified)
        while q:
            for importer in rev[q.popleft()]:
                if importer not in blast:
                    blast.add(importer)
                    q.append(importer)
        impacted_routes = [r for r in cmap["routes"] if r["module"] in blast]

        flows = []
        fwd = defaultdict(list)
        for a, b in cmap["edges"]:
            fwd[a].append(b)
        for r in cmap["routes"]:
            chain, seen, q = [r["module"]], {r["module"]}, deque([r["module"]])
            while q:
                for nxt in sorted(fwd[q.popleft()]):
                    if nxt not in seen and nxt.split("/")[-1] in ("service.py", "store.py"):
                        seen.add(nxt)
                        chain.append(nxt)
                        q.append(nxt)
            flows.append(f"{r['method']} {r['path']}  ->  " + "  ->  ".join(chain) +
                         (f"  ->  tables {cmap['tables']}" if chain[-1].endswith("store.py") else ""))

        schema_changes = []
        for p in todo:
            if p == "core":
                schema_changes.append(f"new tables: {PACKS[p]['schema']}")
            elif PACKS[p].get("schema_change"):
                schema_changes.append(PACKS[p]["schema_change"])
        deps = sorted({d for p in todo for d in PACKS[p]["dependencies"]})
        api_changes = [c for p in todo for c in API_META[p]["api_changes"]]

        reasons = []
        if schema_changes:
            reasons.append("persistent schema change")
        if api_changes:
            reasons.append("public API contract/behaviour change")
        if deps:
            reasons.append("new dependencies")
        if len(modified) >= 4:
            reasons.append(f"wide blast radius ({len(blast)} modules)")

        risks = [r for p in todo for r in PACKS[p]["risks"]] + (GENERIC_RISKS if todo else [])
        if req["perf_target_ms"]:
            risks.append({"id": "R-PERF-1", "scenario": f"Latency target {req['perf_target_ms']} ms regresses",
                          "mitigation": "Hot path stays one indexed read + one insert; checks live on create path",
                          "validation": "verify stage benchmark gates p95"})
        rollback = [
            "Stage-level: every applied change set has a receipt of pre-images; failures revert automatically",
            "Release-level: revert the unified patch(es) in artifacts/patches/ (or `git revert` the release commit)",
            "Data-level: schema changes are additive and nullable; previous code versions ignore new columns",
        ]
        adr_decisions = []
        for p in todo:
            for a in PACKS[p]["adrs"]:
                adr_decisions.append({"kind": "adr", "ref": a["id"], "decision": f"{a['id']}: {a['decision']}",
                                      "rationale": a["rationale"], "alternatives": a["alternatives"],
                                      "tradeoff": a["tradeoff"]})
        design = {
            "todo_packs": todo, "modified_modules": modified, "new_modules": created, "blast_radius": sorted(blast),
            "impacted_routes": impacted_routes, "data_flows": flows, "schema_changes": schema_changes,
            "api_changes": api_changes, "dependency_changes": deps, "risks": risks, "rollback_plan": rollback,
            "adrs": [a for p in todo for a in PACKS[p]["adrs"]],
            "high_impact": bool(reasons), "high_impact_reasons": reasons,
        }
        design["markdown"] = self._markdown(design, plan)
        ctx.write_report("design.md", design["markdown"])
        return AgentResult(artifacts={"design": design}, decisions=adr_decisions,
                           notes=f"high_impact={design['high_impact']} {reasons}; {len(risks)} risks; "
                                 f"{len(modified)} modified / {len(created)} new modules")

    @staticmethod
    def _markdown(d: dict, plan: dict) -> str:
        L = [f"# Design notes ({plan['mode']})", "", f"Scope: {', '.join(d['todo_packs']) or 'no change'}", ""]
        L += ["## Impact", f"- Modified modules: {', '.join(d['modified_modules']) or '-'}",
              f"- New modules: {', '.join(d['new_modules']) or '-'}",
              f"- Blast radius: {len(d['blast_radius'])} modules", "", "## Data flows"] + [f"- {f}" for f in d["data_flows"]]
        L += ["", "## Interface changes"] + ([f"- {c}" for c in d["api_changes"] + d["schema_changes"]] or ["- none"])
        L += ["", "## Decisions"] + [f"- **{a['id']}** {a['decision']} - {a['rationale']} _(trade-off: {a['tradeoff']})_"
                                     for a in d["adrs"]]
        L += ["", "## Risks", "| ID | Scenario | Mitigation | Validation |", "|---|---|---|---|"]
        L += [f"| {r['id']} | {r['scenario']} | {r['mitigation']} | {r['validation']} |" for r in d["risks"]]
        L += ["", "## Rollback"] + [f"- {s}" for s in d["rollback_plan"]]
        return "\n".join(L) + "\n"
