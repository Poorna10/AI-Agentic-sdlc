"""Core data model: stages, results, changes, gates and the exception taxonomy."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class Status(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"    # an upstream dependency failed
    SKIPPED = "SKIPPED"    # run was safe-stopped before this stage executed


class RunStatus(str, enum.Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SAFE_STOPPED = "SAFE_STOPPED"


@dataclass
class Change:
    """A proposed workspace mutation. Agents *propose*; the engine governs and applies."""
    path: str
    kind: str                                   # "write" (create/overwrite) | "edit"
    content: str = ""
    edits: list[tuple[str, str]] = field(default_factory=list)   # (old, new), old must be unique
    source: str = ""

    def added_text(self) -> str:
        return self.content if self.kind == "write" else "\n".join(new for _, new in self.edits)


@dataclass
class GateResult:
    ok: bool
    reason: str = ""


PASS = GateResult(True)


def fail(reason: str) -> GateResult:
    return GateResult(False, reason)


@dataclass
class AgentResult:
    artifacts: dict[str, Any] = field(default_factory=dict)
    changes: list[Change] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    notes: str = ""


@dataclass
class ApprovalSpec:
    approval_id: str
    title: str
    when: Optional[Callable[[Any, Any], bool]] = None               # condition on (ctx, result)
    summary: Optional[Callable[[Any, AgentResult], dict]] = None    # what the human reviews


@dataclass
class Stage:
    id: str
    agent: str
    description: str
    depends_on: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    entry_gate: Optional[Callable[..., GateResult]] = None
    exit_gate: Optional[Callable[..., GateResult]] = None
    approval: Optional[ApprovalSpec] = None
    max_retries: int = 2
    fallback_agent: Optional[str] = None
    critical: bool = False        # failure of a critical stage triggers a safe-stop
    mutates: bool = False


class OrchestrationError(Exception):
    pass


class GateFailed(OrchestrationError):
    pass


class PolicyBlocked(OrchestrationError):
    def __init__(self, violations):
        super().__init__("; ".join(f"{v.rule}: {v.message} ({v.path})" for v in violations))
        self.violations = violations


class ChangeConflict(OrchestrationError):
    pass


class HumanRejected(OrchestrationError):
    pass


class TransientAgentError(OrchestrationError):
    pass


class BudgetExhausted(OrchestrationError):
    pass
