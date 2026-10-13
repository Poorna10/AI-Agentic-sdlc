"""Command line interface:  python -m orchestrator <command>"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audit import AuditLog
from .runner import resume_run, run_scenario
from .workflow import build_workflow


def _inject(items):
    out = []
    for s in items or []:
        stage, attempt, kind = s.split(":")
        out.append({"stage": stage, "attempt": int(attempt), "type": kind})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="orchestrator", description="Agentic SDLC orchestrator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a scenario file")
    r.add_argument("scenario")
    r.add_argument("--runs-dir", default="runs")
    r.add_argument("--interactive", action="store_true", help="prompt for approvals/clarifications on stdin")
    r.add_argument("--reject-all", action="store_true", help="human rejects every approval (safe-stop demo)")
    r.add_argument("--inject", action="append", metavar="STAGE:ATTEMPT:TYPE",
                   help="fault injection, TYPE in exception|policy_violation|corrupt_syntax")
    rs = sub.add_parser("resume", help="resume a safe-stopped/failed run (successful stages are kept)")
    rs.add_argument("run_dir")
    rs.add_argument("--interactive", action="store_true")
    m = sub.add_parser("metrics", help="aggregate reliability metrics across runs")
    m.add_argument("--runs-dir", default="runs")
    v = sub.add_parser("verify-audit", help="verify the audit hash chain of a run")
    v.add_argument("run_dir")
    sub.add_parser("graph", help="print the workflow DAG as Mermaid")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        mode = "interactive" if a.interactive else ("reject_all" if a.reject_all else None)
        res = run_scenario(a.scenario, a.runs_dir, mode, _inject(a.inject))
    elif a.cmd == "resume":
        res = resume_run(a.run_dir, "interactive" if a.interactive else None)
    elif a.cmd == "graph":
        print(build_workflow().to_mermaid())
        return 0
    elif a.cmd == "verify-audit":
        ok, n, msg = AuditLog.verify(Path(a.run_dir) / "audit.jsonl")
        print(f"{'OK' if ok else 'TAMPERED'}: {n} entries ({msg})")
        return 0 if ok else 1
    else:
        runs = [json.loads(p.read_text()) | {"run": p.parent.name} for p in sorted(Path(a.runs_dir).glob("*/metrics.json"))]
        if not runs:
            print("no runs found")
            return 0
        print(f"{'run':<44}{'succ':>6}{'1st-try':>9}{'retry':>6}{'rollb':>6}{'replan':>7}{'MTTR(s)':>9}{'e2e(s)':>8}")
        for x in runs:
            print(f"{x['run']:<44}{x['stage_success_rate']:>6.0%}{x['first_attempt_success_rate']:>9.0%}{x['retries']:>6}"
                  f"{x['rollbacks']:>6}{x['replans']:>7}{(x['mttr_s'] if x['mttr_s'] is not None else float('nan')):>9.2f}"
                  f"{x['end_to_end_latency_s']:>8.2f}")
        n = len(runs)
        print(f"\naggregate over {n} run(s): mean success {sum(x['stage_success_rate'] for x in runs) / n:.0%}, "
              f"retries {sum(x['retries'] for x in runs)}, rollbacks {sum(x['rollbacks'] for x in runs)}")
        return 0

    print(f"\n=== RESULT: {res.status.value}" + (f" ({res.stop_reason})" if res.stop_reason else ""))
    print(f"    summary : {res.run_dir / 'ENGINEERING_SUMMARY.md'}\n    workspace: {res.run_dir / 'workspace'}")
    return 0 if res.status.value == "COMPLETED" else 2


if __name__ == "__main__":
    sys.exit(main())
