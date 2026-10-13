"""Sandboxed workspace with atomic apply and receipt-based (path-scoped) rollback."""
from __future__ import annotations

import difflib
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .model import Change, ChangeConflict

_IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".git", ".venv"}
_IGNORED_SUFFIXES = (".pyc", ".db", ".db-journal")


@dataclass
class Receipt:
    """Pre-images of every path a change set touched (None => file did not exist)."""
    pre_images: dict[str, str | None] = field(default_factory=dict)

    def to_json(self) -> dict:
        return dict(self.pre_images)

    @classmethod
    def from_json(cls, data: dict) -> "Receipt":
        return cls(dict(data))


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def resolve(self, rel: str) -> Path:
        p = PurePosixPath(rel)
        if p.is_absolute() or ".." in p.parts or not rel:
            raise ChangeConflict(f"path escapes workspace: {rel!r}")
        full = (self.root / rel).resolve()
        if self.root not in full.parents and full != self.root:
            raise ChangeConflict(f"path escapes workspace: {rel!r}")
        return full

    def read(self, rel: str) -> str | None:
        path = self.resolve(rel)
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def exists(self, rel: str) -> bool:
        return self.resolve(rel).is_file()

    def files(self, suffix: str | None = None) -> list[str]:
        out = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file() or _IGNORED_PARTS & set(p.relative_to(self.root).parts):
                continue
            if p.name.endswith(_IGNORED_SUFFIXES):
                continue
            if suffix is None or p.name.endswith(suffix):
                out.append(p.relative_to(self.root).as_posix())
        return out

    def compute(self, changes: list[Change]) -> dict[str, str]:
        """Resolve a change set against current content (overlay) without touching disk."""
        overlay: dict[str, str] = {}
        for ch in changes:
            self.resolve(ch.path)
            if ch.kind == "write":
                overlay[ch.path] = ch.content
                continue
            current = overlay[ch.path] if ch.path in overlay else self.read(ch.path)
            if current is None:
                raise ChangeConflict(f"edit target does not exist: {ch.path}")
            for old, new in ch.edits:
                if current.count(old) != 1:
                    raise ChangeConflict(
                        f"edit anchor in {ch.path} matched {current.count(old)} times "
                        f"(expected exactly 1): {old.strip()[:60]!r}")
                current = current.replace(old, new)
            overlay[ch.path] = current
        return overlay

    def apply(self, changes: list[Change]) -> Receipt:
        """All-or-nothing: compute everything first, then write; revert on any I/O error."""
        with self._lock:
            overlay = self.compute(changes)
            receipt = Receipt({p: self.read(p) for p in overlay})
            try:
                for rel, text in overlay.items():
                    full = self.resolve(rel)
                    full.parent.mkdir(parents=True, exist_ok=True)
                    full.write_text(text, encoding="utf-8")
            except Exception:
                self.revert(receipt)
                raise
            return receipt

    def revert(self, receipt: Receipt) -> None:
        with self._lock:
            for rel, old in receipt.pre_images.items():
                full = self.resolve(rel)
                if old is None:
                    full.unlink(missing_ok=True)
                else:
                    full.parent.mkdir(parents=True, exist_ok=True)
                    full.write_text(old, encoding="utf-8")

    def diff(self, receipt: Receipt) -> str:
        chunks = []
        for rel, old in receipt.pre_images.items():
            new = self.read(rel)
            if old == new:
                continue
            a = (old or "").splitlines(keepends=True)
            b = (new or "").splitlines(keepends=True)
            chunks.append("".join(difflib.unified_diff(
                a, b, fromfile="/dev/null" if old is None else f"a/{rel}",
                tofile="/dev/null" if new is None else f"b/{rel}")))
        return "\n".join(chunks)
