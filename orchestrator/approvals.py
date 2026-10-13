"""Human-in-the-loop: approvals and clarification questions.

Modes: scripted (deterministic, for demos/CI), interactive (stdin), reject_all.
Every decision is returned with approver identity and comment so it can be audited.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class ApprovalRequest:
    approval_id: str
    title: str
    stage: str
    reason: str
    details: dict = field(default_factory=dict)


@dataclass
class Decision:
    approved: bool
    approver: str
    comment: str = ""
    ts: float = field(default_factory=time.time)


class Human:
    def __init__(self, mode: str = "scripted", approver: str = "human:reviewer",
                 approvals: dict | None = None, answers: dict | None = None,
                 default: str = "approve", input_fn=input, out=print) -> None:
        self.mode, self.approver = mode, approver
        self.approvals = approvals or {}
        self.answers = answers or {}
        self.default = "reject" if mode == "reject_all" else default
        self._in, self._out = input_fn, out
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, cfg: dict | None, override_mode: str | None = None, **kw) -> "Human":
        cfg = dict(cfg or {})
        if override_mode:
            cfg["mode"] = override_mode
        return cls(mode=cfg.get("mode", "scripted"), approver=cfg.get("approver", "human:reviewer"),
                   approvals=cfg.get("approvals"), answers=cfg.get("answers"),
                   default=cfg.get("default", "approve"), **kw)

    def decide(self, req: ApprovalRequest) -> Decision:
        with self._lock:     # serialise prompts coming from parallel stages
            if self.mode == "interactive":
                self._out(f"\n=== APPROVAL REQUIRED: {req.title} [{req.approval_id}] (stage {req.stage}) ===")
                self._out(f"Reason: {req.reason}")
                for k, v in req.details.items():
                    self._out(f"  {k}: {v}")
                ans = self._in("Approve? [y/N] (optionally 'n: reason'): ").strip()
                ok = ans.lower().startswith("y")
                return Decision(ok, self.approver, ans.partition(":")[2].strip())
            if self.mode == "reject_all":
                return Decision(False, self.approver, "reject_all mode: every approval is refused")
            spec = self._lookup(req.approval_id)
            if isinstance(spec, dict):
                return Decision(spec.get("decision", self.default) == "approve", self.approver, spec.get("comment", ""))
            return Decision(spec == "approve", self.approver,
                            "scripted decision" if req.approval_id in self.approvals else f"default policy: {self.default}")

    def _lookup(self, approval_id: str):
        if approval_id in self.approvals:
            return self.approvals[approval_id]
        parts = approval_id.split(":")            # policy:RULE:stage -> try policy:RULE, policy
        for i in range(len(parts) - 1, 0, -1):
            key = ":".join(parts[:i])
            if key in self.approvals:
                return self.approvals[key]
        return self.default

    def clarify(self, questions: list[dict]) -> dict[str, str]:
        """Return {question_id: answer}. Missing id => unanswered (agent falls back to an assumption)."""
        with self._lock:
            if self.mode == "interactive":
                out = {}
                for q in questions:
                    self._out(f"\n[CLARIFY {q['id']}] {q['question']}\n  (default if blank: {q['default']})")
                    a = self._in("> ").strip()
                    if a:
                        out[q["id"]] = a
                return out
            return {q["id"]: self.answers[q["id"]] for q in questions if q["id"] in self.answers}
