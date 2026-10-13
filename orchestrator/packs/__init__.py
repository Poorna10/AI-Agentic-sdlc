"""Template-backed code generator: turns a feature pack into a reviewable change set."""
from __future__ import annotations

import runpy
from pathlib import Path

from ..catalog import PACKS
from ..model import Change

TEMPLATES = Path(__file__).parent / "templates"


def _render(text: str, params: dict) -> str:
    for key, value in params.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


class TemplateGenerator:
    """Deterministic stand-in for an LLM code generator.

    Any generator (including an LLM-backed one) only *proposes* Changes; the engine's
    policy layer, approval gates and exit gates apply identically to all of them.
    """

    name = "template-generator"

    def propose(self, pack: str, params: dict | None = None, include: str = "all") -> list[Change]:
        """include: 'src' | 'tests' | 'all'."""
        if pack not in PACKS:
            raise KeyError(f"unknown pack {pack!r}")
        params = {**PACKS[pack].get("params", {}), **(params or {})}
        base = TEMPLATES / pack
        changes: list[Change] = []
        files_dir = base / "files"
        for f in sorted(files_dir.rglob("*")):
            if not f.is_file() or "__pycache__" in f.parts:
                continue
            rel = f.relative_to(files_dir).as_posix()
            is_test = rel.startswith("tests/")
            if include == "src" and is_test or include == "tests" and not is_test:
                continue
            changes.append(Change(rel, "write", _render(f.read_text(encoding="utf-8"), params), source=pack))
        if include != "tests" and (base / "edits.py").exists():
            by_path: dict[str, list[tuple[str, str]]] = {}
            for path, old, new in runpy.run_path(str(base / "edits.py"))["EDITS"]:
                by_path.setdefault(path, []).append((_render(old, params), _render(new, params)))
            changes.extend(Change(p, "edit", edits=e, source=pack) for p, e in by_path.items())
        # edits must come after the files they patch within the same set
        changes.sort(key=lambda c: c.kind == "edit")
        return changes
