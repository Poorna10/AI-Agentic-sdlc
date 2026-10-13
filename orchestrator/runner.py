"""Builds a run from a scenario file and executes / resumes it."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .agents import build_registry
from .approvals import Human
from .audit import AuditLog
from .context import Context
from .engine import EngineConfig, FaultInjector, Orchestrator, RunResult
from .metrics import Metrics
from .packs import TemplateGenerator
from .policy import PolicyEngine
from .workflow import build_workflow
from .workspace import Workspace

_SHOW = {"stage_started": "▶", "stage_succeeded": "✔", "attempt_failed": "✘", "policy_violation": "⛔",
         "approval_requested": "✋", "approval_decision": "👤", "rollback": "↩", "fallback_engaged": "⤵",
         "replan": "♻", "safe_stop": "🛑", "requirement_amended": "✎", "stage_blocked": "⊘", "run_resumed": "⏯"}


def _printer(t0: float, out=print):
    lock = threading.Lock()

    def sink(e: dict) -> None:
        sym = _SHOW.get(e["event"])
        if not sym:
            return
        d, stage = e["data"], (e["stage"] or "-")
        detail = {
            "stage_started": f"agent={d.get('agent')}",
            "stage_succeeded": f"attempt={d.get('attempt')} agent={d.get('agent')} ({d.get('duration_s')}s)",
            "attempt_failed": f"attempt={d.get('attempt')} {d.get('error_type')}: {str(d.get('error'))[:110]}",
            "policy_violation": f"{d.get('rule')} {d.get('action')} - {d.get('message')} [{d.get('path')}]",
            "approval_requested": f"{d.get('approval_id')}: {d.get('reason')}",
            "approval_decision": f"{d.get('approval_id')} -> {'APPROVED' if d.get('approved') else 'REJECTED'} by {e['actor']}",
            "rollback": f"{d.get('reason')}: {len(d.get('files', []))} file(s) reverted",
            "fallback_engaged": f"-> {d.get('fallback')}",
            "replan": f"stale={d.get('stale_stages')} changed={d.get('changed_artifacts')}",
            "safe_stop": d.get("reason"), "requirement_amended": d.get("text"),
            "stage_blocked": d.get("reason"), "run_resumed": f"kept={d.get('kept')}",
        }[e["event"]]
        with lock:
            out(f"[{e['ts'] - t0:6.2f}s] {sym} {e['event']:<19} {stage:<17} {detail}")
    return sink


def _assemble(scenario: dict, run_dir: Path, human_mode: str | None, extra_faults: list[dict] | None,
              live: bool, out=print, config: EngineConfig | None = None, input_fn=input) -> Orchestrator:
    t0 = time.time()
    run_dir.mkdir(parents=True, exist_ok=True)
    ws = Workspace(run_dir / "workspace")
    audit = AuditLog(run_dir / "audit.jsonl", run_dir.name, sink=_printer(t0, out) if live else None)
    human = Human.from_config(scenario.get("human"), human_mode, input_fn=input_fn, out=out)
    policy = PolicyEngine()
    ctx = Context(run_dir.name, run_dir, ws, scenario, human, policy)
    faults = FaultInjector((scenario.get("faults") or []) + (extra_faults or []))
    engine = Orchestrator(build_workflow(), build_registry(), ctx, audit, Metrics(), config, faults,
                          scenario.get("events"))
    return engine


def run_scenario(path: str | Path, runs_dir: str | Path = "runs", human_mode: str | None = None,
                 extra_faults: list[dict] | None = None, live: bool = True, out=print,
                 config: EngineConfig | None = None, scenario_override: dict | None = None,
                 input_fn=input) -> RunResult:
    scenario = scenario_override or json.loads(Path(path).read_text())
    run_id = f"{scenario['name']}-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}"
    run_dir = Path(runs_dir) / run_id
    engine = _assemble(scenario, run_dir, human_mode, extra_faults, live, out, config, input_fn)
    (run_dir / "scenario.json").write_text(json.dumps(scenario, indent=2))
    # pre-existing codebase for brownfield scenarios (not orchestrated: it is the starting point)
    gen = TemplateGenerator()
    for pack in scenario.get("baseline_packs", []):
        engine.ctx.workspace.apply(gen.propose(pack))
        engine.audit.record("baseline_installed", "setup", pack=pack)
    if live:
        out(f"\n=== {scenario['name']}: {scenario.get('description', '')}\n    run: {run_dir}\n")
    return engine.run()


def resume_run(run_dir: str | Path, human_mode: str | None = None, live: bool = True, out=print,
               config: EngineConfig | None = None, scenario_override: dict | None = None, input_fn=input) -> RunResult:
    run_dir = Path(run_dir)
    scenario = scenario_override or json.loads((run_dir / "scenario.json").read_text())
    engine = _assemble(scenario, run_dir, human_mode, None, live, out, config, input_fn)
    engine.load_state()
    return engine.run()
