"""Explicit workflow DAG: validation, scheduling queries, data-flow checks."""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable

from .model import Stage, Status

EXTERNAL_INPUTS = frozenset({"raw_requirement"})   # artifacts injected by the orchestrator


class GraphError(ValueError):
    pass


class WorkflowGraph:
    def __init__(self, stages: Iterable[Stage]) -> None:
        self.stages: dict[str, Stage] = {}
        for s in stages:
            if s.id in self.stages:
                raise GraphError(f"duplicate stage {s.id}")
            self.stages[s.id] = s
        self.children: dict[str, set[str]] = defaultdict(set)
        for s in self.stages.values():
            for d in s.depends_on:
                if d not in self.stages:
                    raise GraphError(f"{s.id} depends on unknown stage {d}")
                self.children[d].add(s.id)
        self._order = self._toposort()
        self._check_dataflow()
        self._anc = {sid: self.ancestors(sid) for sid in self.stages}

    def _toposort(self) -> list[str]:
        indeg = {sid: len(s.depends_on) for sid, s in self.stages.items()}
        queue = deque(sorted(sid for sid, n in indeg.items() if n == 0))
        order = []
        while queue:
            sid = queue.popleft()
            order.append(sid)
            for c in sorted(self.children[sid]):
                indeg[c] -= 1
                if indeg[c] == 0:
                    queue.append(c)
        if len(order) != len(self.stages):
            raise GraphError("workflow contains a cycle")
        return order

    def _check_dataflow(self) -> None:
        """Every consumed artifact must be produced by an ancestor (or be an external input)."""
        for s in self.stages.values():
            anc = self.ancestors(s.id)
            produced = {a for sid in anc for a in self.stages[sid].produces}
            for art in s.consumes:
                if art not in produced and art not in EXTERNAL_INPUTS:
                    raise GraphError(f"{s.id} consumes '{art}' which no ancestor produces")

    @property
    def order(self) -> list[str]:
        return list(self._order)

    def ancestors(self, sid: str) -> set[str]:
        seen: set[str] = set()
        stack = list(self.stages[sid].depends_on)
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.add(n)
                stack.extend(self.stages[n].depends_on)
        return seen

    def descendants(self, ids: Iterable[str]) -> set[str]:
        seen: set[str] = set()
        stack = list(ids)
        while stack:
            for c in self.children[stack.pop()]:
                if c not in seen:
                    seen.add(c)
                    stack.append(c)
        return seen

    def ready(self, status: dict[str, Status]) -> list[str]:
        return [sid for sid in self._order
                if status[sid] == Status.PENDING
                and all(status[a] == Status.SUCCEEDED for a in self._anc[sid])]

    def propagate_blocked(self, status: dict[str, Status]) -> list[str]:
        newly = []
        for sid in self._order:
            if status[sid] == Status.PENDING and any(
                    status[d] in (Status.FAILED, Status.BLOCKED, Status.SKIPPED) for d in self.stages[sid].depends_on):
                status[sid] = Status.BLOCKED
                newly.append(sid)
        return newly

    def levels(self) -> list[list[str]]:
        """Parallel 'waves' (longest-path layering) - the theoretical concurrency profile."""
        depth: dict[str, int] = {}
        for sid in self._order:
            deps = self.stages[sid].depends_on
            depth[sid] = 1 + max((depth[d] for d in deps), default=-1)
        out: dict[int, list[str]] = defaultdict(list)
        for sid, d in depth.items():
            out[d].append(sid)
        return [sorted(out[k]) for k in sorted(out)]

    def to_mermaid(self) -> str:
        lines = ["flowchart TD"]
        for s in self.stages.values():
            marks = ("  [approval]" if s.approval else "") + ("  [mutates]" if s.mutates else "")
            lines.append(f'    {s.id}["{s.id}<br/><i>{s.agent}</i>{marks}"]')
        for s in self.stages.values():
            for d in s.depends_on:
                lines.append(f"    {d} --> {s.id}")
        return "\n".join(lines)
