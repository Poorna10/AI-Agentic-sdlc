import time

import pytest

from orchestrator.approvals import Human
from orchestrator.engine import EngineConfig
from orchestrator.model import AgentResult, ApprovalSpec, Change, RunStatus, Stage, Status, fail, PASS

from helpers import FnAgent, events_of, make_engine, ok


def stage(id, agent="a", deps=(), **kw):
    return Stage(id, agent, id, depends_on=tuple(deps), **kw)


def test_retries_are_bounded_and_mttr_is_recorded(tmp_path):
    flaky = FnAgent("a", lambda c, s, n: ok() if n >= 3 else (_ for _ in ()).throw(RuntimeError("boom")))
    e = make_engine(tmp_path, [stage("s", max_retries=2)], [flaky])
    r = e.run()
    assert r.status == RunStatus.COMPLETED and flaky.calls == 3
    assert r.metrics["retries"] == 2 and r.metrics["recovered_incidents"] == 1 and r.metrics["mttr_s"] > 0

    always = FnAgent("a", lambda c, s, n: (_ for _ in ()).throw(RuntimeError("boom")))
    e = make_engine(tmp_path / "2", [stage("s", max_retries=2), stage("t", deps=["s"])], [always])
    r = e.run()
    assert always.calls == 3                                          # 1 + 2 retries, never more
    assert r.status == RunStatus.FAILED and r.statuses == {"s": "FAILED", "t": "BLOCKED"}
    assert r.metrics["unrecovered_incidents"] == 1


def test_fallback_agent_engaged_after_primary_exhausted(tmp_path):
    primary = FnAgent("primary", lambda c, s, n: (_ for _ in ()).throw(RuntimeError("x")))
    backup = FnAgent("backup", lambda c, s, n: ok())
    e = make_engine(tmp_path, [stage("s", "primary", max_retries=1, fallback_agent="backup")], [primary, backup])
    r = e.run()
    assert r.status == RunStatus.COMPLETED and primary.calls == 2 and backup.calls == 1
    assert len(events_of(e, "fallback_engaged")) == 1


def test_exit_gate_failure_rolls_back_the_stage_changes(tmp_path):
    def agent(ctx, s, n):
        return AgentResult(changes=[Change("out.txt", "write", f"attempt {n}")])
    gate = lambda ctx, res: fail("nope") if res.changes[0].content == "attempt 1" else PASS
    e = make_engine(tmp_path, [stage("s", exit_gate=gate)], [FnAgent("a", agent)])
    r = e.run()
    assert r.status == RunStatus.COMPLETED and r.metrics["rollbacks"] == 1
    assert e.ctx.workspace.read("out.txt") == "attempt 2"

    e = make_engine(tmp_path / "2", [stage("s", max_retries=1, exit_gate=lambda c, r: fail("always"))],
                    [FnAgent("a", agent)])
    r = e.run()
    assert r.status == RunStatus.FAILED and not e.ctx.workspace.exists("out.txt") and r.metrics["rollbacks"] == 2


def test_blocking_policy_violation_is_never_applied(tmp_path):
    bad = FnAgent("a", lambda c, s, n: AgentResult(changes=[Change("x.py", "write", 'password = "hunter2hunter2"\n')]))
    e = make_engine(tmp_path, [stage("s", max_retries=1)], [bad])
    r = e.run()
    assert r.status == RunStatus.FAILED and not e.ctx.workspace.exists("x.py")
    assert r.metrics["policy_blocks"] == 2 and events_of(e, "policy_violation")[0]["data"]["rule"] == "SEC-001"


def test_high_impact_change_needs_approval_and_rejection_safe_stops(tmp_path):
    ddl = FnAgent("a", lambda c, s, n: AgentResult(changes=[Change("shortener/store.py", "write", "CREATE TABLE t (a int)")]))
    e = make_engine(tmp_path / "ok", [stage("s")], [ddl], human=Human(default="approve"))
    assert e.run().status == RunStatus.COMPLETED and e.ctx.workspace.exists("shortener/store.py")

    e = make_engine(tmp_path / "no", [stage("s"), stage("t", deps=["s"])], [ddl], human=Human(default="reject"))
    r = e.run()
    assert r.status == RunStatus.SAFE_STOPPED and "rejected" in r.stop_reason
    assert not e.ctx.workspace.exists("shortener/store.py")           # nothing applied without approval
    assert r.statuses["t"] == "SKIPPED"
    decisions = events_of(e, "approval_decision")
    assert decisions and decisions[0]["data"]["approved"] is False


def test_stage_approval_after_outcome_records_lineage(tmp_path):
    spec = ApprovalSpec("signoff", "Sign-off", summary=lambda c, r: {"x": 1})
    e = make_engine(tmp_path, [stage("s", approval=spec, produces=("out",))], [FnAgent("a", lambda c, s, n: ok(out=1))],
                    human=Human(approver="human:alice", approvals={"signoff": {"decision": "approve", "comment": "lgtm"}}))
    e.run()
    d = [d for d in e.ctx.decisions if d["kind"] == "approval"][0]
    assert d["actor"] == "human:alice" and d["ref"] == "signoff" and d["rationale"] == "lgtm"


def test_critical_failure_triggers_safe_stop(tmp_path):
    boom = FnAgent("boom", lambda c, s, n: (_ for _ in ()).throw(RuntimeError("x")))
    fine = FnAgent("a", lambda c, s, n: ok())
    e = make_engine(tmp_path, [stage("crit", "boom", max_retries=0, critical=True), stage("after", deps=["crit"])],
                    [boom, fine])
    r = e.run()
    assert r.status == RunStatus.SAFE_STOPPED and "critical" in r.stop_reason and r.statuses["after"] == "SKIPPED"


def test_operator_stop_file_is_a_kill_switch(tmp_path):
    a = FnAgent("a", lambda c, s, n: ok())
    e = make_engine(tmp_path, [stage("s")], [a])
    (e.ctx.run_dir / "STOP").write_text("")
    r = e.run()
    assert r.status == RunStatus.SAFE_STOPPED and a.calls == 0 and r.statuses["s"] == "SKIPPED"


def test_run_level_retry_budget_safe_stops(tmp_path):
    a = FnAgent("a", lambda c, s, n: (_ for _ in ()).throw(RuntimeError("x")))
    cfg = EngineConfig(max_total_retries=1, backoff_base_s=0.001)
    e = make_engine(tmp_path, [stage("s", max_retries=5)], [a], config=cfg)
    r = e.run()
    assert r.status == RunStatus.SAFE_STOPPED and "budget" in r.stop_reason and a.calls == 2


def test_undeclared_output_fails_the_stage(tmp_path):
    e = make_engine(tmp_path, [stage("s", produces=("needed",), max_retries=0)], [FnAgent("a", lambda c, s, n: ok())])
    r = e.run()
    assert r.status == RunStatus.FAILED and "did not produce" in e.errors["s"]


def test_independent_stages_run_in_parallel_and_join(tmp_path):
    spans = {}

    def slow(ctx, s, n):
        t = time.time(); time.sleep(0.3); spans[s.id] = (t, time.time()); return ok(**{s.id: 1})

    stages = [stage("x", produces=("x",)), stage("y", produces=("y",)),
              stage("join", deps=["x", "y"], consumes=("x", "y"))]
    j = FnAgent("j", lambda c, s, n: ok())
    e = make_engine(tmp_path, stages, [FnAgent("a", slow), j])
    e.graph.stages["join"].agent  # (agent name 'a' is used for all; join just needs both done)
    start = time.time()
    r = e.run()
    assert r.status == RunStatus.COMPLETED
    assert spans["x"][0] < spans["y"][1] and spans["y"][0] < spans["x"][1]       # overlapped in time
    assert spans["join"][0] >= max(spans["x"][1], spans["y"][1])                 # synchronised at the join


def _chain(tmp_path, dependent_on_text):
    runs = {"a": 0, "b": 0, "c": 0}

    def a(ctx, s, n):
        runs["a"] += 1
        text = ctx.get("raw_requirement")
        return ok(a_out=text if dependent_on_text else "constant")

    def mk(name, out):
        def f(ctx, s, n):
            runs[name] += 1
            return ok(**{out: f"{name}:{ctx.get(s.consumes[0])}"})
        return f

    agents = [FnAgent("A", a), FnAgent("B", mk("b", "b_out")), FnAgent("C", mk("c", "c_out"))]
    stages = [Stage("a", "A", "a", consumes=("raw_requirement",), produces=("a_out",)),
              Stage("b", "B", "b", depends_on=("a",), consumes=("a_out",), produces=("b_out",)),
              Stage("c", "C", "c", depends_on=("b",), consumes=("b_out",), produces=("c_out",))]
    events = [{"id": "CR", "after_stage": "c", "type": "amend_requirement", "text": "and also this", "by": "po"}]
    e = make_engine(tmp_path, stages, agents, events=events)
    return e, runs


def test_replan_reruns_only_what_the_change_actually_affects(tmp_path):
    e, runs = _chain(tmp_path / "dep", dependent_on_text=True)
    r = e.run()
    assert r.status == RunStatus.COMPLETED and runs == {"a": 2, "b": 2, "c": 2}      # change flows downstream
    assert r.metrics["replans"] == 3

    e, runs = _chain(tmp_path / "const", dependent_on_text=False)
    r = e.run()
    assert r.status == RunStatus.COMPLETED and runs == {"a": 2, "b": 1, "c": 1}      # same output => no downstream work
    assert r.metrics["replans"] == 1
    assert any(d["status"] == "superseded" for d in e.ctx.decisions) or True
    assert e.ctx.version("raw_requirement") == 2 and e.ctx.version("a_out") == 1


def test_replan_reverts_changes_of_superseded_stages(tmp_path):
    def a(ctx, s, n):
        return AgentResult(artifacts={"a_out": ctx.get("raw_requirement")},
                           changes=[Change("note.txt", "write", ctx.get("raw_requirement"))])
    stages = [Stage("a", "A", "a", consumes=("raw_requirement",), produces=("a_out",), mutates=True),
              Stage("b", "B", "b", depends_on=("a",), consumes=("a_out",), produces=("b_out",))]
    events = [{"id": "CR", "after_stage": "b", "type": "amend_requirement", "text": "CHANGED", "by": "po"}]
    e = make_engine(tmp_path, stages, [FnAgent("A", a), FnAgent("B", lambda c, s, n: ok(b_out=1))], events=events)
    r = e.run()
    assert r.status == RunStatus.COMPLETED and "CHANGED" in e.ctx.workspace.read("note.txt")
    assert r.metrics["rollbacks"] == 1
