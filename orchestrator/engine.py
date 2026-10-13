"""The orchestration engine.

Design in one paragraph: agents *propose* (artifacts, decisions, workspace changes); the engine
*disposes*. For every stage it enforces entry gate -> agent attempt (bounded retries, then a
fallback agent) -> policy evaluation -> human approval for high-impact items -> atomic apply
(with receipts) -> exit gate -> optional outcome approval -> commit. Failures roll back the
stage's own changes. Stages run in parallel as soon as their dependencies succeed. When an
artifact changes after consumers have already run, the engine quiesces, resets only the stale
stages (reverting their changes) and lets hash-based change propagation decide how far the
re-execution has to go.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .approvals import ApprovalRequest
from .audit import AuditLog
from .context import Context
from .graph import WorkflowGraph
from .metrics import Metrics
from .model import (AgentResult, BudgetExhausted, Change, GateFailed, HumanRejected, PolicyBlocked, RunStatus,
                    Stage, Status, TransientAgentError)


@dataclass
class EngineConfig:
    max_workers: int = 4
    backoff_base_s: float = 0.02
    backoff_cap_s: float = 0.5
    max_total_retries: int = 10       # run-level retry budget; exceeding it safe-stops the run


class FaultInjector:
    """Chaos hooks used by scenarios and tests to exercise retry / rollback / fallback paths."""

    def __init__(self, faults: list[dict] | None = None) -> None:
        self.faults = faults or []

    def _match(self, stage: str, attempt: int, kind: str) -> bool:
        return any(f["stage"] == stage and f.get("attempt", 1) == attempt and f["type"] == kind for f in self.faults)

    def before(self, stage: str, attempt: int) -> None:
        if self._match(stage, attempt, "exception"):
            raise TransientAgentError(f"injected transient failure ({stage}, attempt {attempt})")

    def after(self, stage: str, attempt: int, result: AgentResult) -> AgentResult:
        if self._match(stage, attempt, "policy_violation"):
            result.changes.append(Change("shortener/debug_config.py", "write",
                                         'API_TOKEN = "sk_live_0123456789abcdef"\n', source="fault-injector"))
        if self._match(stage, attempt, "corrupt_syntax"):
            result.changes.append(Change("shortener/broken.py", "write", "def broken(:\n    pass\n", source="fault-injector"))
        return result


@dataclass
class RunResult:
    run_id: str
    status: RunStatus
    stop_reason: Optional[str]
    statuses: dict
    metrics: dict
    run_dir: Path


class Orchestrator:
    def __init__(self, graph: WorkflowGraph, agents: dict, ctx: Context, audit: AuditLog, metrics: Metrics,
                 config: EngineConfig | None = None, faults: FaultInjector | None = None,
                 events: list[dict] | None = None) -> None:
        self.graph, self.agents, self.ctx = graph, agents, ctx
        self.audit, self.metrics = audit, metrics
        self.cfg = config or EngineConfig()
        self.faults = faults or FaultInjector()
        self.events = events or []
        self.status: dict[str, Status] = {sid: Status.PENDING for sid in graph.order}
        self.errors: dict[str, str] = {}
        self.attempts: dict[str, int] = defaultdict(int)
        self.total_retries = 0
        self.safe_stop_reason: Optional[str] = None

    # ------------------------------------------------------------------ run loop
    def run(self) -> RunResult:
        ctx = self.ctx
        if not ctx.has("raw_requirement"):
            ctx.put("raw_requirement", ctx.scenario["requirement"], "human:requester")
        self.audit.record("run_started", "orchestrator", scenario=ctx.scenario.get("name"),
                          stages=len(self.graph.order), parallel_levels=self.graph.levels())
        pool = ThreadPoolExecutor(max_workers=self.cfg.max_workers)
        running: dict[Future, str] = {}
        replan_pending = False
        try:
            while True:
                if not self.safe_stop_reason and (ctx.run_dir / "STOP").exists():
                    self._safe_stop("operator kill-switch: STOP file present")
                if not self.safe_stop_reason and not replan_pending:
                    for sid in self.graph.propagate_blocked(self.status):
                        self.audit.record("stage_blocked", "orchestrator", sid, reason="upstream failure")
                    for sid in self.graph.ready(self.status):
                        self.status[sid] = Status.RUNNING
                        running[pool.submit(self._execute_stage, sid)] = sid
                if not running:
                    if replan_pending and not self.safe_stop_reason:
                        self._replan()
                        replan_pending = False
                        continue
                    break
                done, _ = wait(running, timeout=0.25, return_when=FIRST_COMPLETED)
                for fut in done:
                    sid = running.pop(fut)
                    status, error, escalate = fut.result()
                    self.status[sid] = status
                    if error:
                        self.errors[sid] = error
                    else:
                        self.errors.pop(sid, None)
                    if escalate and not self.safe_stop_reason:
                        self._safe_stop(escalate)
                    if status == Status.FAILED and self.graph.stages[sid].critical and not self.safe_stop_reason:
                        self._safe_stop(f"critical stage '{sid}' failed")
                    self._save_state()
                    if status == Status.SUCCEEDED:
                        self._process_events(sid)
                        if self._stale_stages():
                            replan_pending = True
        finally:
            pool.shutdown(wait=True)
        if self.safe_stop_reason:
            for sid, st in self.status.items():
                if st in (Status.PENDING, Status.BLOCKED):
                    self.status[sid] = Status.SKIPPED
        return self._finish()

    def _safe_stop(self, reason: str) -> None:
        self.safe_stop_reason = reason
        self.audit.record("safe_stop", "orchestrator", reason=reason)

    def _finish(self) -> RunResult:
        failed = any(s in (Status.FAILED, Status.BLOCKED) for s in self.status.values())
        if self.safe_stop_reason:
            rs = RunStatus.SAFE_STOPPED
        elif failed or any(s != Status.SUCCEEDED for s in self.status.values()):
            rs = RunStatus.FAILED
        else:
            rs = RunStatus.COMPLETED
        summary = self.metrics.save(self.ctx.run_dir / "metrics.json", self.status)
        self.audit.record("run_finished", "orchestrator", status=rs.value, reason=self.safe_stop_reason,
                          statuses={k: v.value for k, v in self.status.items()})
        self._save_state(final=rs.value)
        from .report import write_final_summary          # local import: report depends on the engine's outputs
        write_final_summary(self, rs, summary)
        return RunResult(self.ctx.run_id, rs, self.safe_stop_reason,
                         {k: v.value for k, v in self.status.items()}, summary, self.ctx.run_dir)

    # ------------------------------------------------------------------ one stage
    def _execute_stage(self, sid: str):
        stage = self.graph.stages[sid]
        self.audit.record("stage_started", "orchestrator", sid, agent=stage.agent, depends_on=list(stage.depends_on))
        try:
            if stage.entry_gate:
                g = stage.entry_gate(self.ctx)
                self.audit.record("entry_gate", "gate", sid, ok=g.ok, reason=g.reason)
                if not g.ok:
                    raise GateFailed(f"entry gate failed: {g.reason}")
            chain = [(stage.agent, 1 + stage.max_retries)]
            if stage.fallback_agent:
                chain.append((stage.fallback_agent, 1))
            last: Exception | None = None
            for ci, (agent_name, tries) in enumerate(chain):
                if ci > 0:
                    self.audit.record("fallback_engaged", "orchestrator", sid, fallback=agent_name,
                                      after_error=str(last)[:300])
                for i in range(tries):
                    with self.ctx.lock:
                        self.attempts[sid] += 1
                        n = self.attempts[sid]
                    started = self.metrics.attempt_started(sid)
                    self.audit.record("attempt_started", f"agent:{agent_name}", sid, attempt=n)
                    try:
                        self._attempt(stage, agent_name, n)
                        self.metrics.attempt_succeeded(sid, started)
                        self.audit.record("stage_succeeded", "orchestrator", sid, agent=agent_name, attempt=n,
                                          duration_s=round(time.time() - started, 3))
                        return Status.SUCCEEDED, None, None
                    except HumanRejected:
                        raise
                    except Exception as exc:                      # noqa: BLE001 - boundary: classify everything
                        last = exc
                        self.metrics.attempt_failed(sid)
                        self.audit.record("attempt_failed", f"agent:{agent_name}", sid, attempt=n,
                                          error_type=type(exc).__name__, error=str(exc)[:500])
                        if i < tries - 1 or ci < len(chain) - 1:
                            self.metrics.retry(sid)
                            with self.ctx.lock:
                                self.total_retries += 1
                                over = self.total_retries > self.cfg.max_total_retries
                            if over:
                                raise BudgetExhausted(f"run retry budget ({self.cfg.max_total_retries}) exhausted")
                            time.sleep(min(self.cfg.backoff_cap_s, self.cfg.backoff_base_s * 2 ** i))
            assert last is not None
            raise last
        except HumanRejected as exc:
            self.audit.record("stage_failed", "orchestrator", sid, error=str(exc), reason="human_rejected")
            return Status.FAILED, str(exc), f"human rejected at stage '{sid}': {exc}"
        except BudgetExhausted as exc:
            self.audit.record("stage_failed", "orchestrator", sid, error=str(exc), reason="budget")
            return Status.FAILED, str(exc), str(exc)
        except Exception as exc:                                    # noqa: BLE001
            self.audit.record("stage_failed", "orchestrator", sid, error=str(exc)[:500], error_type=type(exc).__name__)
            return Status.FAILED, f"{type(exc).__name__}: {exc}", None

    def _attempt(self, stage: Stage, agent_name: str, n: int) -> None:
        ctx = self.ctx
        sid = stage.id
        inputs = ctx.snapshot_inputs(stage.consumes)
        self.faults.before(sid, n)
        result: AgentResult = self.agents[agent_name].run(ctx, stage)
        result = self.faults.after(sid, n, result)

        # --- policy guardrails (security / compliance / change control)
        violations = ctx.policy.evaluate_changes(result.changes)
        for v in violations:
            self.audit.record("policy_violation", "policy", sid, **v.to_dict())
        blocks = [v for v in violations if v.action == "BLOCK"]
        if blocks:
            self.metrics.count("policy_blocks", len(blocks))
            raise PolicyBlocked(blocks)
        by_rule: dict[str, list] = defaultdict(list)
        for v in violations:
            if v.action == "REQUIRE_APPROVAL":
                by_rule[v.rule].append(v)
        for rule, vs in by_rule.items():
            d = self._ask(f"policy:{rule}:{sid}", f"High-impact change ({rule})", sid, vs[0].message,
                          {"files": sorted({v.path for v in vs}), "proposed_by": agent_name}, inputs)
            if not d.approved:
                raise HumanRejected(f"policy approval {rule} rejected by {d.approver}: {d.comment}")

        # --- apply atomically, then exit gate; roll back on any failure after this point
        receipt = None
        if result.changes:
            receipt = ctx.workspace.apply(result.changes)
            self.audit.record("changes_applied", f"agent:{agent_name}", sid, files=sorted(receipt.pre_images))
        try:
            missing = [a for a in stage.produces if a not in result.artifacts]
            if missing:
                raise GateFailed(f"agent did not produce declared artifacts: {missing}")
            if stage.exit_gate:
                g = stage.exit_gate(ctx, result)
                self.audit.record("exit_gate", "gate", sid, ok=g.ok, reason=g.reason)
                if not g.ok:
                    raise GateFailed(f"exit gate failed: {g.reason}")
            ap = stage.approval
            if ap and (ap.when is None or ap.when(ctx, result)):
                details = ap.summary(ctx, result) if ap.summary else {}
                d = self._ask(ap.approval_id, ap.title, sid, "stage outcome requires human sign-off", details, inputs)
                if not d.approved:
                    raise HumanRejected(f"{ap.approval_id} rejected by {d.approver}: {d.comment}")
        except Exception:
            if receipt is not None:
                ctx.workspace.revert(receipt)
                self.metrics.rollback(sid)
                self.audit.record("rollback", "orchestrator", sid, files=sorted(receipt.pre_images), reason="post-apply failure")
            raise

        # --- commit
        with ctx.lock:
            for name, value in result.artifacts.items():
                ctx.put(name, value, f"{sid}:{agent_name}")
            ctx.stage_inputs[sid] = inputs
            if receipt is not None:
                ctx.receipts[sid] = receipt
                ctx.write_report(f"patches/{sid}.patch", ctx.workspace.diff(receipt))
            if sid in ctx.commit_order:
                ctx.commit_order.remove(sid)
            ctx.commit_order.append(sid)
            for d in result.decisions:
                ctx.add_decision(sid, f"agent:{agent_name}", inputs=inputs, **d)
        self.audit.record("artifacts_committed", f"agent:{agent_name}", sid,
                          artifacts={a: ctx.version(a) for a in result.artifacts}, notes=result.notes[:300])

    def _ask(self, approval_id: str, title: str, stage: str, reason: str, details: dict, inputs: dict | None = None):
        ctx = self.ctx
        details = {**details, "reviewed_versions": {n: ctx.version(n) for n in ctx.artifacts}}
        self.audit.record("approval_requested", "orchestrator", stage, approval_id=approval_id, title=title,
                          reason=reason, details=details)
        t = time.time()
        d = ctx.human.decide(ApprovalRequest(approval_id, title, stage, reason, details))
        self.metrics.approval_wait_s.append(time.time() - t)
        self.audit.record("approval_decision", d.approver, stage, approval_id=approval_id,
                          approved=d.approved, comment=d.comment)
        ctx.add_decision(stage, d.approver, f"{'APPROVED' if d.approved else 'REJECTED'}: {title}",
                         d.comment or reason, kind="approval", ref=approval_id, inputs=inputs)
        return d

    # ------------------------------------------------------------------ change propagation
    def _process_events(self, sid: str) -> None:
        ctx = self.ctx
        for ev in self.events:
            if ev["after_stage"] != sid or ev["id"] in ctx.events_fired:
                continue
            ctx.events_fired.append(ev["id"])
            if ev["type"] == "amend_requirement":
                new = ctx.get("raw_requirement", "").rstrip() + "\n" + ev["text"]
                v = ctx.put("raw_requirement", new, f"human:{ev.get('by', 'stakeholder')}")
                self.audit.record("requirement_amended", f"human:{ev.get('by', 'stakeholder')}", sid,
                                  change_request=ev["id"], text=ev["text"], new_version=v)
                ctx.add_decision("(external)", f"human:{ev.get('by', 'stakeholder')}", f"Change request: {ev['text']}",
                                 ev.get("reason", "mid-run requirement change"), kind="change_request", ref=ev["id"])

    def _stale_stages(self) -> list[str]:
        out = []
        for sid in self.graph.order:
            if self.status[sid] == Status.SUCCEEDED and any(
                    self.ctx.version(a) != v for a, v in self.ctx.stage_inputs.get(sid, {}).items()):
                out.append(sid)
        return out

    def _replan(self) -> None:
        stale = self._stale_stages()
        if not stale:
            return
        ctx = self.ctx
        changed = {sid: [a for a, v in ctx.stage_inputs[sid].items() if ctx.version(a) != v] for sid in stale}
        self.metrics.count("replans")
        self.audit.record("replan", "orchestrator", stale_stages=stale, changed_artifacts=changed,
                          unaffected=[s for s in self.graph.order if self.status[s] == Status.SUCCEEDED and s not in stale])
        for sid in [s for s in reversed(ctx.commit_order) if s in stale]:
            receipt = ctx.receipts.pop(sid, None)
            if receipt is not None:
                ctx.workspace.revert(receipt)
                self.metrics.rollback(sid)
                self.audit.record("rollback", "orchestrator", sid, files=sorted(receipt.pre_images), reason="replan")
        for sid in stale:
            ctx.stage_inputs.pop(sid, None)
            if sid in ctx.commit_order:
                ctx.commit_order.remove(sid)
            ctx.supersede(sid)
            self.status[sid] = Status.PENDING
        self._save_state()

    # ------------------------------------------------------------------ persistence / resume
    def _save_state(self, final: str | None = None) -> None:
        state = {"statuses": {k: v.value for k, v in self.status.items()}, "errors": self.errors,
                 "attempts": dict(self.attempts), "total_retries": self.total_retries,
                 "safe_stop_reason": self.safe_stop_reason, "final": final, "ctx": self.ctx.state_dict()}
        tmp = self.ctx.run_dir / "state.json.tmp"
        tmp.write_text(json.dumps(state, default=str))
        tmp.replace(self.ctx.run_dir / "state.json")

    def load_state(self) -> None:
        """Resume: keep SUCCEEDED stages, retry everything else."""
        s = json.loads((self.ctx.run_dir / "state.json").read_text())
        self.ctx.load_state(s["ctx"])
        for sid, st in s["statuses"].items():
            self.status[sid] = Status.SUCCEEDED if st == "SUCCEEDED" else Status.PENDING
        self.attempts.update(s["attempts"])
        self.audit.record("run_resumed", "orchestrator", kept=[k for k, v in self.status.items() if v == Status.SUCCEEDED])
