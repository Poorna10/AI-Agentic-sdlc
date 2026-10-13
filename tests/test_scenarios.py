"""End-to-end: the three required scenarios plus chaos / human-governance paths."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator.audit import AuditLog
from orchestrator.engine import EngineConfig
from orchestrator.model import RunStatus
from orchestrator.runner import resume_run, run_scenario

ROOT = Path(__file__).resolve().parents[1]
CFG = EngineConfig(backoff_base_s=0.001, backoff_cap_s=0.01)


def run(name, tmp_path, **kw):
    return run_scenario(ROOT / "scenarios" / f"{name}.json", tmp_path, live=False, config=CFG, **kw)


def events(res, name):
    return [e for e in AuditLog.read(res.run_dir / "audit.jsonl") if e["event"] == name]


def pytest_in(res):
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-o", "addopts=", "-p", "no:cacheprovider"],
                       cwd=res.run_dir / "workspace", capture_output=True, text=True)
    return p.returncode, p.stdout


@pytest.fixture(scope="module")
def greenfield(tmp_path_factory):
    return run("greenfield", tmp_path_factory.mktemp("g"))


@pytest.fixture(scope="module")
def brownfield(tmp_path_factory):
    return run("brownfield", tmp_path_factory.mktemp("b"))


@pytest.fixture(scope="module")
def ambiguous(tmp_path_factory):
    return run("ambiguous", tmp_path_factory.mktemp("a"))


def test_greenfield_builds_a_working_service_from_nothing(greenfield):
    assert greenfield.status == RunStatus.COMPLETED
    ws = greenfield.run_dir / "workspace"
    assert (ws / "shortener" / "api.py").exists() and (ws / "tests" / "test_contract_generated.py").exists()
    rc, out = pytest_in(greenfield)                       # independently re-run the delivered suite
    assert rc == 0, out
    assert greenfield.metrics["stage_success_rate"] == 1.0
    approvals = {e["data"]["approval_id"] for e in events(greenfield, "approval_decision")}
    assert {"requirements_signoff", "design_signoff", "policy:CHG-002:implement", "release_approval"} <= approvals


def test_brownfield_is_additive_with_rollback_retry_and_fallback_paths_exercised(brownfield):
    assert brownfield.status == RunStatus.COMPLETED
    plan = json.loads((brownfield.run_dir / "state.json").read_text())["ctx"]["artifacts"]["plan"]
    assert plan["mode"] == "brownfield" and plan["todo_packs"] == ["expiry"]      # core was NOT regenerated
    m = brownfield.metrics
    assert m["rollbacks"] == 1 and m["retries"] == 2 and m["recovered_incidents"] == 2 and m["mttr_s"] is not None
    assert "expires_at" in (brownfield.run_dir / "workspace/shortener/store.py").read_text()
    patch = (brownfield.run_dir / "artifacts/patches/implement.patch").read_text()
    assert "ALTER TABLE links ADD COLUMN expires_at" in patch and "-" in patch     # reviewable diff of edits
    assert pytest_in(brownfield)[0] == 0
    assert any("legacy" in l for l in (brownfield.run_dir / "workspace/tests/test_expiry.py").read_text().splitlines())


def test_ambiguous_clarifies_assumes_replans_and_stays_consistent(ambiguous):
    assert ambiguous.status == RunStatus.COMPLETED
    state = json.loads((ambiguous.run_dir / "state.json").read_text())["ctx"]
    req = state["artifacts"]["requirements"]
    assert {c["id"] for c in req["clarifications"]} == {"AMB-PERF", "AMB-SEC", "AMB-PROD", "AMB-ABUSE"}
    assert {a["id"] for a in req["assumptions"]} == {"AMB-PROD", "AMB-ABUSE"}      # unanswered => flagged assumptions
    plan = state["artifacts"]["plan"]
    assert plan["todo_packs"] == ["ratelimit", "blocklist", "secheaders"]           # blocklist came from the change request
    assert ambiguous.metrics["replans"] >= 2 and ambiguous.metrics["rollbacks"] >= 2
    assert state["versions"]["requirements"][-1]["version"] == 2
    superseded = [d for d in state["decisions"] if d["status"] == "superseded"]
    assert superseded and {d["stage"] for d in superseded} >= {"requirements", "plan", "design"}
    cr = [d for d in state["decisions"] if d["kind"] == "change_request"]
    assert len(cr) == 1 and cr[0]["status"] == "active" and cr[0]["stage"] == "(external)"   # external input is not superseded
    release = state["artifacts"]["release_report"]
    assert release["ready"] and all(c["ok"] for c in release["checks"])
    ver = state["artifacts"]["verification"]
    assert ver["perf"]["p95_ms"] <= ver["perf"]["target_ms"]                        # clarified NFR actually gated
    assert pytest_in(ambiguous)[0] == 0


def test_every_run_has_a_verifiable_audit_trail_and_summary(greenfield, brownfield, ambiguous):
    for res in (greenfield, brownfield, ambiguous):
        ok, n, _ = AuditLog.verify(res.run_dir / "audit.jsonl")
        assert ok and n > 20
        text = (res.run_dir / "ENGINEERING_SUMMARY.md").read_text()
        for section in ("Requirement understanding", "Plan and rationale", "Decision lineage", "Risks, validation",
                        "Reliability metrics", "Assumptions and limitations", "Audit integrity"):
            assert section in text
        assert (res.run_dir / "lineage.json").exists() and (res.run_dir / "metrics.json").exists()


def test_repeated_policy_violations_exhaust_retries_then_fallback_recovers(tmp_path):
    faults = [{"stage": "implement", "attempt": i, "type": "policy_violation"} for i in (1, 2, 3)]
    res = run("greenfield", tmp_path, extra_faults=faults)
    assert res.status == RunStatus.COMPLETED
    assert res.metrics["policy_blocks"] == 3 and len(events(res, "fallback_engaged")) == 1
    assert not (res.run_dir / "workspace/shortener/debug_config.py").exists()       # the secret never landed


def test_unrecoverable_stage_fails_closed_and_blocks_downstream(tmp_path):
    faults = [{"stage": "implement", "attempt": i, "type": "policy_violation"} for i in (1, 2, 3, 4)]
    res = run("greenfield", tmp_path, extra_faults=faults)
    assert res.status == RunStatus.FAILED
    assert res.statuses["implement"] == "FAILED" and res.statuses["release"] == "BLOCKED"
    assert res.statuses["author_tests"] == "SUCCEEDED"                              # independent branch still completed
    assert not (res.run_dir / "workspace/shortener/api.py").exists()                # fail closed: no partial code


def test_human_rejection_safe_stops_and_resume_reuses_completed_work(tmp_path):
    res = run("greenfield", tmp_path, human_mode="reject_all")
    assert res.status == RunStatus.SAFE_STOPPED and "requirements" in res.stop_reason
    assert res.statuses["plan"] == "SKIPPED"
    done = resume_run(res.run_dir, live=False, config=CFG)                          # reviewer now approves
    assert done.status == RunStatus.COMPLETED
    started = [e["stage"] for e in events(done, "stage_started")]
    assert started.count("codebase_analysis") == 1                                  # not re-executed after resume
    assert started.count("requirements") == 2
    assert AuditLog.verify(done.run_dir / "audit.jsonl")[0]                          # one unbroken chain across resume


def test_cli_graph_and_metrics(tmp_path, greenfield):
    out = subprocess.run([sys.executable, "-m", "orchestrator", "graph"], cwd=ROOT, capture_output=True, text=True).stdout
    assert out.startswith("flowchart TD") and "design --> implement" in out and "docs --> release" in out
    m = subprocess.run([sys.executable, "-m", "orchestrator", "metrics", "--runs-dir", str(greenfield.run_dir.parent)],
                       cwd=ROOT, capture_output=True, text=True).stdout
    assert "greenfield" in m and "aggregate" in m
