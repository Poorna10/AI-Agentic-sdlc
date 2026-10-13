"""Shared run context: versioned artifact store, decision lineage, persistence."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from .workspace import Receipt, Workspace


def content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


class Context:
    def __init__(self, run_id: str, run_dir: Path, workspace: Workspace, scenario: dict, human, policy) -> None:
        self.run_id, self.run_dir, self.workspace = run_id, Path(run_dir), workspace
        self.scenario, self.human, self.policy = scenario, human, policy
        self.lock = threading.RLock()
        self.artifacts: dict[str, Any] = {}
        self.versions: dict[str, list[dict]] = {}        # name -> [{version, hash, producer, ts}]
        self.decisions: list[dict] = []
        self.stage_inputs: dict[str, dict[str, int]] = {}   # stage -> {artifact: version consumed}
        self.receipts: dict[str, Receipt] = {}
        self.commit_order: list[str] = []
        self.clarifications: dict[str, dict] = {}
        self.events_fired: list[str] = []
        self.artifact_dir = self.run_dir / "artifacts"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    # ---- artifacts ----
    def put(self, name: str, value: Any, producer: str) -> int:
        """Store a new version only if content changed (drives change propagation)."""
        with self.lock:
            h = content_hash(value)
            hist = self.versions.setdefault(name, [])
            if hist and hist[-1]["hash"] == h:
                self.artifacts[name] = value
                return hist[-1]["version"]
            v = (hist[-1]["version"] + 1) if hist else 1
            hist.append({"version": v, "hash": h, "producer": producer, "ts": round(time.time(), 3)})
            self.artifacts[name] = value
            return v

    def get(self, name: str, default: Any = None) -> Any:
        with self.lock:
            return self.artifacts.get(name, default)

    def has(self, name: str) -> bool:
        return name in self.artifacts

    def version(self, name: str) -> int:
        with self.lock:
            hist = self.versions.get(name)
            return hist[-1]["version"] if hist else 0

    def snapshot_inputs(self, names) -> dict[str, int]:
        return {n: self.version(n) for n in names}

    # ---- decision lineage ----
    def add_decision(self, stage: str, actor: str, decision: str, rationale: str,
                     alternatives: list[str] | None = None, kind: str = "design", ref: str | None = None,
                     inputs: dict[str, int] | None = None, tradeoff: str = "") -> dict:
        with self.lock:
            d = {"id": f"D-{len(self.decisions) + 1:03d}", "stage": stage, "actor": actor, "kind": kind,
                 "ref": ref, "decision": decision, "rationale": rationale, "alternatives": alternatives or [],
                 "tradeoff": tradeoff, "inputs": dict(inputs or {}),
                 "status": "active", "ts": round(time.time(), 3)}
            self.decisions.append(d)
            return d

    def supersede(self, stage: str) -> None:
        with self.lock:
            for d in self.decisions:
                if d["stage"] == stage and d["status"] == "active":
                    d["status"] = "superseded"

    # ---- reports / persistence ----
    def write_report(self, name: str, text: str) -> Path:
        p = self.artifact_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def state_dict(self) -> dict:
        with self.lock:
            return {"artifacts": self.artifacts, "versions": self.versions, "decisions": self.decisions,
                    "stage_inputs": self.stage_inputs, "commit_order": self.commit_order,
                    "receipts": {k: v.to_json() for k, v in self.receipts.items()},
                    "clarifications": self.clarifications, "events_fired": self.events_fired}

    def load_state(self, s: dict) -> None:
        self.artifacts, self.versions, self.decisions = s["artifacts"], s["versions"], s["decisions"]
        self.stage_inputs, self.commit_order = s["stage_inputs"], s["commit_order"]
        self.receipts = {k: Receipt.from_json(v) for k, v in s["receipts"].items()}
        self.clarifications, self.events_fired = s["clarifications"], s["events_fired"]
