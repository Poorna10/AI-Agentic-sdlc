"""Append-only, hash-chained audit log (tamper-evident)."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

GENESIS = "0" * 64


def _digest(entry: dict) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, default=str).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: Path, run_id: str, sink: Optional[Callable[[dict], None]] = None) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self._sink = sink
        self._lock = threading.Lock()
        self._seq = 0
        self._prev = GENESIS
        if self.path.exists():                      # resume: continue the chain
            for line in self.path.read_text().splitlines():
                if line.strip():
                    e = json.loads(line)
                    self._seq, self._prev = e["seq"], e["hash"]

    def record(self, event: str, actor: str, stage: str | None = None, **data) -> dict:
        with self._lock:
            self._seq += 1
            entry = {"seq": self._seq, "ts": round(time.time(), 6), "run_id": self.run_id,
                     "event": event, "actor": actor, "stage": stage, "data": data, "prev": self._prev}
            entry["hash"] = _digest(entry)
            self._prev = entry["hash"]
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        if self._sink:
            self._sink(entry)
        return entry

    @staticmethod
    def read(path: Path) -> list[dict]:
        return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]

    @staticmethod
    def verify(path: Path) -> tuple[bool, int, str]:
        prev, n = GENESIS, 0
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            claimed = e.pop("hash")
            if e["prev"] != prev or _digest(e) != claimed or e["seq"] != n + 1:
                return False, n, f"chain broken at seq {e.get('seq')}"
            prev, n = claimed, n + 1
        return True, n, "ok"
