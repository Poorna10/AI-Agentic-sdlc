"""Policy guardrails: security, compliance and change-control rules.

Actions:  BLOCK (never applied) | REQUIRE_APPROVAL (needs a human decision) | WARN (recorded).
The engine evaluates *every* proposed change set, whichever agent or generator produced it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Change


@dataclass(frozen=True)
class Violation:
    rule: str
    action: str
    message: str
    path: str
    line: int | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass(frozen=True)
class ContentRule:
    id: str
    pattern: re.Pattern
    action: str
    message: str
    category: str
    workspace_scan: bool = True        # also applied by the security-review full scan
    needs_all: tuple[re.Pattern, ...] = ()   # additional patterns that must match the same line
    src_only: bool = False                   # only application source (.py outside tests/)


def _r(p: str) -> re.Pattern:
    return re.compile(p)


CONTENT_RULES = [
    ContentRule("SEC-001", _r(r"AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
                "BLOCK", "hard-coded credential or private key", "security"),
    ContentRule("SEC-001", _r(r"(?i)[\w-]*(password|passwd|secret|api[_-]?key|token)[\w-]*\s*=\s*[\"'][^\"']{6,}[\"']"),
                "BLOCK", "hard-coded secret assignment", "security"),
    ContentRule("SEC-002", _r(r"\beval\(|\bexec\(|os\.system\(|shell\s*=\s*True|pickle\.loads?\("),
                "BLOCK", "dangerous call (code/command execution or unsafe deserialisation)", "security"),
    ContentRule("SEC-003", _r(r"execute(script|many)?\(\s*f[\"']|execute\(\s*[\"'][^\"']*[\"']\s*(%|\+|\.format)"),
                "BLOCK", "SQL built by string interpolation (injection risk)", "security"),
    ContentRule("SEC-004", _r(r"verify\s*=\s*False"), "BLOCK", "TLS verification disabled", "security"),
    ContentRule("SEC-005", _r(r"\brandom\.(choice|choices|randint|random|randrange)\("),
                "BLOCK", "non-cryptographic randomness (use `secrets` for identifiers)", "security"),
    ContentRule("CMP-001", _r(r"client\.host|remote_addr|[Xx]-[Ff]orwarded-[Ff]or"),
                "REQUIRE_APPROVAL", "client address may be persisted/logged (PII, data minimisation)",
                "compliance", workspace_scan=False, src_only=True,
                needs_all=(_r(r"INSERT|execute|logger|logging|print\("),)),
    ContentRule("CHG-002", _r(r"(?i)\b(ALTER|DROP|CREATE)\s+TABLE\b"),
                "REQUIRE_APPROVAL", "persistent schema change", "change-control", workspace_scan=False,
                src_only=True),
]

DEFAULT_PROTECTED = (".github/", "Dockerfile", "deploy/", "infra/")
DEFAULT_DEP_ALLOWLIST = frozenset({"fastapi", "uvicorn", "httpx", "pytest", "pydantic", "starlette"})


class PolicyEngine:
    def __init__(self, protected: tuple[str, ...] = DEFAULT_PROTECTED,
                 dep_allowlist: frozenset[str] = DEFAULT_DEP_ALLOWLIST) -> None:
        self.protected = protected
        self.dep_allowlist = dep_allowlist

    def scan_text(self, path: str, text: str, workspace_scan_only: bool = False) -> list[Violation]:
        out: list[Violation] = []
        if not path.endswith((".py", ".sh", ".txt", ".ini", ".cfg", ".toml", ".yml", ".yaml", ".md", ".json")):
            return out
        for n, line in enumerate(text.splitlines(), 1):
            for rule in CONTENT_RULES:
                if workspace_scan_only and not rule.workspace_scan:
                    continue
                if rule.src_only and (path.startswith("tests/") or not path.endswith(".py")):
                    continue
                if rule.pattern.search(line) and all(p.search(line) for p in rule.needs_all):
                    out.append(Violation(rule.id, rule.action, rule.message, path, n))
        return out

    def evaluate_changes(self, changes: list[Change]) -> list[Violation]:
        out: list[Violation] = []
        for ch in changes:
            norm = ch.path.replace("\\", "/")
            if norm.startswith("/") or ".." in norm.split("/") or not norm:
                out.append(Violation("CHG-001", "BLOCK", "path escapes the workspace", ch.path))
                continue
            if any(norm.startswith(p) or norm == p.rstrip("/") for p in self.protected):
                out.append(Violation("CHG-003", "REQUIRE_APPROVAL", "protected path (CI/CD or infra)", ch.path))
            if norm == "requirements.txt":
                for line in ch.added_text().splitlines():
                    name = re.split(r"[<>=!~\[ ;#]", line.strip(), maxsplit=1)[0].lower()
                    if name and name not in self.dep_allowlist:
                        out.append(Violation("CMP-002", "REQUIRE_APPROVAL",
                                             f"dependency '{name}' is not on the approved allowlist", ch.path))
            out.extend(self.scan_text(norm, ch.added_text()))
        seen, uniq = set(), []                      # one approval per (rule, path)
        for v in out:
            key = (v.rule, v.path, v.action) if v.action == "REQUIRE_APPROVAL" else (v.rule, v.path, v.line, v.action)
            if key not in seen:
                seen.add(key)
                uniq.append(v)
        return uniq

    def scan_workspace(self, ws) -> list[Violation]:
        out: list[Violation] = []
        for rel in ws.files():
            out.extend(self.scan_text(rel, ws.read(rel) or "", workspace_scan_only=True))
        return out
