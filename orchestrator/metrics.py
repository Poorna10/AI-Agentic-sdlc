"""Reliability metrics: success rate, retries, rollbacks, MTTR, end-to-end latency."""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from pathlib import Path

from .model import Status


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.t0 = time.time()
        self.stage: dict[str, dict] = defaultdict(lambda: {
            "attempts": 0, "failures": 0, "retries": 0, "rollbacks": 0, "duration_s": 0.0})
        self._incident_start: dict[str, float] = {}
        self.mttr_samples: list[float] = []
        self.counters: dict[str, int] = defaultdict(int)
        self.approval_wait_s: list[float] = []
        self.first_try_success: set[str] = set()

    def attempt_started(self, sid: str) -> float:
        with self._lock:
            self.stage[sid]["attempts"] += 1
        return time.time()

    def attempt_failed(self, sid: str) -> None:
        with self._lock:
            self.stage[sid]["failures"] += 1
            self._incident_start.setdefault(sid, time.time())

    def attempt_succeeded(self, sid: str, started: float) -> None:
        with self._lock:
            m = self.stage[sid]
            m["duration_s"] += time.time() - started
            if m["failures"] == 0:
                self.first_try_success.add(sid)
            if sid in self._incident_start:        # recovery => one MTTR sample
                self.mttr_samples.append(time.time() - self._incident_start.pop(sid))

    def count(self, name: str, n: int = 1) -> None:
        with self._lock:
            self.counters[name] += n

    def retry(self, sid: str) -> None:
        with self._lock:
            self.stage[sid]["retries"] += 1
            self.counters["retries"] += 1

    def rollback(self, sid: str) -> None:
        with self._lock:
            self.stage[sid]["rollbacks"] += 1
            self.counters["rollbacks"] += 1

    def summary(self, statuses: dict[str, Status]) -> dict:
        with self._lock:
            total = len(statuses)
            ok = sum(1 for s in statuses.values() if s == Status.SUCCEEDED)
            mttr = (sum(self.mttr_samples) / len(self.mttr_samples)) if self.mttr_samples else None
            return {
                "stages_total": total,
                "stages_succeeded": ok,
                "stage_success_rate": round(ok / total, 3) if total else 0.0,
                "first_attempt_success_rate": round(len(self.first_try_success) / ok, 3) if ok else 0.0,
                "retries": self.counters["retries"],
                "rollbacks": self.counters["rollbacks"],
                "policy_blocks": self.counters["policy_blocks"],
                "replans": self.counters["replans"],
                "approvals": len(self.approval_wait_s),
                "approval_wait_s": round(sum(self.approval_wait_s), 3),
                "mttr_s": None if mttr is None else round(mttr, 3),
                "recovered_incidents": len(self.mttr_samples),
                "unrecovered_incidents": len(self._incident_start),
                "end_to_end_latency_s": round(time.time() - self.t0, 3),
                "per_stage": {k: {**v, "duration_s": round(v["duration_s"], 3)} for k, v in self.stage.items()},
            }

    def save(self, path: Path, statuses: dict[str, Status]) -> dict:
        s = self.summary(statuses)
        Path(path).write_text(json.dumps(s, indent=2))
        return s
