"""Toy-graph helpers so governance behaviour is tested independently of the SDLC agents."""
from __future__ import annotations

from pathlib import Path

from orchestrator.agents import Agent
from orchestrator.approvals import Human
from orchestrator.audit import AuditLog
from orchestrator.context import Context
from orchestrator.engine import EngineConfig, FaultInjector, Orchestrator
from orchestrator.graph import WorkflowGraph
from orchestrator.metrics import Metrics
from orchestrator.model import AgentResult
from orchestrator.policy import PolicyEngine
from orchestrator.workspace import Workspace


class FnAgent(Agent):
    def __init__(self, name, fn):
        self.name, self.fn, self.calls = name, fn, 0

    def run(self, ctx, stage):
        self.calls += 1
        return self.fn(ctx, stage, self.calls)


def ok(**artifacts):
    return AgentResult(artifacts=artifacts)


def make_engine(tmp_path: Path, stages, agents: list[FnAgent], human: Human | None = None, faults=None,
                config: EngineConfig | None = None, events=None):
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    scenario = {"name": "toy", "requirement": "x" * 40}
    ctx = Context("toy-run", run_dir, Workspace(run_dir / "workspace"), scenario,
                  human or Human(default="approve"), PolicyEngine())
    audit = AuditLog(run_dir / "audit.jsonl", "toy-run")
    cfg = config or EngineConfig(backoff_base_s=0.001, backoff_cap_s=0.005)
    return Orchestrator(WorkflowGraph(stages), {a.name: a for a in agents}, ctx, audit, Metrics(), cfg,
                        FaultInjector(faults), events)


def events_of(engine, name):
    return [e for e in AuditLog.read(engine.audit.path) if e["event"] == name]
