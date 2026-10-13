"""Documentation and release readiness."""
from __future__ import annotations

import datetime as dt

from ..catalog import PACKS
from ..model import AgentResult, Change, Stage
from . import Agent


def _installed(plan: dict) -> list[str]:
    return [p for p in PACKS if p in set(plan["present_packs"]) | set(plan["todo_packs"])]


class DocsAgent(Agent):
    name = "docs-writer"

    def run(self, ctx, stage: Stage) -> AgentResult:
        plan, design, contract = ctx.get("plan"), ctx.get("design"), ctx.get("api_contract")
        installed = _installed(plan)
        ws = ctx.workspace
        feats = "\n".join(f"- **{PACKS[p]['title']}** (v{PACKS[p]['version']})" for p in installed)
        readme = f"""# URL Shortener

A small, tested URL-shortening service (FastAPI + SQLite), delivered by the agentic SDLC orchestrator.

## Features
{feats}

## Run
```bash
pip install -r requirements.txt
uvicorn shortener.main:app --port 8000
```
Configuration: `SHORTENER_DB` (default `shortener.db`), `SHORTENER_BASE_URL` (default `http://localhost:8000`).

## Test
```bash
pytest
```

## API
See [docs/API.md](docs/API.md). Interactive docs are served at `/docs`.
Design rationale, risks and rollback: [docs/DESIGN.md](docs/DESIGN.md).
"""
        api = ["# API reference (generated from the API contract)", "", "| Method | Path | Documented responses |", "|---|---|---|"]
        api += [f"| {e['method']} | `{e['path']}` | {', '.join(map(str, sorted(e['responses'])))} |" for e in contract["endpoints"]]
        api += ["", f"`POST /api/v1/links` body fields: {', '.join(f'`{f}`' for f in contract['request_fields'])}", ""]
        api += ["Error bodies: `{\"error\": \"<code>\", \"detail\": \"...\"}`."]
        entries = "\n".join(f"- {PACKS[p]['title']}" for p in plan["todo_packs"]) or "- no functional change"
        prior = ws.read("CHANGELOG.md") or "# Changelog\n"
        version = max((PACKS[p]["version"] for p in installed), key=lambda v: tuple(map(int, v.split("."))))
        changelog = prior.replace("# Changelog\n", f"# Changelog\n\n## {version} - {dt.date.today().isoformat()}\n{entries}\n", 1)
        if not changelog.startswith("# Changelog"):
            changelog = "# Changelog\n\n" + changelog
        changes = [Change("README.md", "write", readme, source="docs-writer"),
                   Change("docs/API.md", "write", "\n".join(api) + "\n", source="docs-writer"),
                   Change("docs/DESIGN.md", "write", design["markdown"], source="docs-writer"),
                   Change("CHANGELOG.md", "write", changelog, source="docs-writer")]
        return AgentResult(artifacts={"docs_bundle": {"files": [c.path for c in changes], "version": version}},
                           changes=changes, notes=f"{len(changes)} documents")


class DocsMinimalAgent(Agent):
    """Fallback: README only, so a docs failure never blocks an otherwise-good release."""
    name = "docs-minimal"

    def run(self, ctx, stage: Stage) -> AgentResult:
        plan = ctx.get("plan")
        readme = "# URL Shortener\n\nRun: `uvicorn shortener.main:app`. Test: `pytest`.\n"
        return AgentResult(
            artifacts={"docs_bundle": {"files": ["README.md"], "version": "n/a", "degraded": True}},
            changes=[Change("README.md", "write", readme, source="docs-minimal"),
                     Change("docs/API.md", "write", "# API\nSee `/docs` (OpenAPI).\n", source="docs-minimal")],
            notes="degraded documentation (fallback)")


class ReleaseAgent(Agent):
    name = "release-manager"

    def run(self, ctx, stage: Stage) -> AgentResult:
        plan, ver, sec = ctx.get("plan"), ctx.get("verification"), ctx.get("security_report")
        impl, req, docs = ctx.get("implementation"), ctx.get("requirements"), ctx.get("docs_bundle")
        ws = ctx.workspace
        with ctx.lock:
            stale = [(sid, a) for sid, ins in ctx.stage_inputs.items() for a, v in ins.items() if ctx.version(a) != v]
            signed = any(d["ref"] == "requirements_signoff" and d["status"] == "active"
                         and d["decision"].startswith("APPROVED") for d in ctx.decisions)
        missing = [p for p in plan["todo_packs"] if p not in impl["deferred_packs"] and not ws.exists(PACKS[p]["marker"])]
        checks = [
            ("tests_pass", bool(ver["ok"]), f"{ver['tests']['passed']} passed"),
            ("nfr_targets_met", ver["perf"] is None or ver["perf"].get("p95_ms", 1e9) <= ver["perf"]["target_ms"],
             "no benchmark required" if ver["perf"] is None else f"p95 {ver['perf'].get('p95_ms')} ms vs {ver['perf']['target_ms']} ms"),
            ("security_clean", not sec["blocking"], f"{len(sec['blocking'])} blocking findings"),
            ("scope_complete", not impl["deferred_packs"] and not missing,
             f"deferred={impl['deferred_packs']} missing={missing}"),
            ("assumptions_approved", not req["assumptions"] or signed,
             f"{len(req['assumptions'])} assumptions; sign-off recorded={signed}"),
            ("rollback_plan_defined", bool(ctx.get("design")["rollback_plan"]) or not plan["todo_packs"], "design.rollback_plan"),
            ("docs_updated", bool(docs and "README.md" in docs["files"]), ", ".join(docs["files"]) if docs else "-"),
            ("no_stale_inputs", not stale, f"stale={stale}" if stale else "all stage inputs current"),
        ]
        report = {"ready": all(c[1] for c in checks), "version": docs["version"] if docs else None,
                  "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
                  "residual_risks": sec["residual_risks"]}
        return AgentResult(artifacts={"release_report": report}, notes=f"ready={report['ready']}")
