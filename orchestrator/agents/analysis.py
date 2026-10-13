"""Requirement understanding, codebase reasoning and task decomposition."""
from __future__ import annotations

import ast
import re
from collections import deque

from ..catalog import CAPABILITIES, CAPABILITY_TO_PACK, PACKS, pack_closure
from ..model import AgentResult, Stage
from . import Agent

AMBIGUITY_RULES = [
    {"id": "AMB-PERF", "pattern": r"\b(fast|quick(ly)?|performan\w+|low[- ]latency|snappy)\b",
     "question": "What measurable latency target defines 'fast' (e.g. p95 redirect latency)?",
     "default": "p95 redirect latency <= 50 ms"},
    {"id": "AMB-SEC", "pattern": r"\bsecur(e|ity)\b",
     "question": "Which threats are in scope for 'secure': abuse/spam, malicious destinations, browser/transport hardening?",
     "default": "abuse throttling and browser/transport security headers"},
    {"id": "AMB-PROD", "pattern": r"production[- ]ready|enterprise[- ]grade|\brobust\b",
     "question": "What does 'production ready' include for this release (health, hardening, limits, docs)?",
     "default": "health endpoint, security headers and request throttling"},
    {"id": "AMB-ABUSE", "pattern": r"\b(abus\w+|spam|bots?)\b",
     "question": "What request rate per client should be tolerated before throttling?",
     "default": "30 link creations per minute per client"},
    {"id": "AMB-TTL", "pattern": r"for a while|for some time|temporar\w+|short[- ]lived",
     "question": "What default and maximum lifetime should links have?",
     "default": "optional per-link TTL up to 365 days; no default expiry"},
]

NFR_RULES = [
    ("NFR-COMPAT", r"existing .{0,60}(keep|continue|still) work|backward[- ]compat|no breaking|without breaking|no data loss",
     "Backward compatible: existing links and API clients keep working; migrations are additive and data-preserving"),
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


class RequirementsAgent(Agent):
    name = "requirements-analyst"

    def run(self, ctx, stage: Stage) -> AgentResult:
        raw = _norm(ctx.get("raw_requirement", ""))
        # 1. ambiguity detection -> targeted questions (deterministic ids so answers survive re-runs)
        detected = [r for r in AMBIGUITY_RULES if re.search(r["pattern"], raw, re.I)]
        decisions: list[dict] = []
        with ctx.lock:
            pending = [r for r in detected if r["id"] not in ctx.clarifications]
        if pending:
            answers = ctx.human.clarify([{"id": r["id"], "question": r["question"], "default": r["default"]}
                                         for r in pending])
            with ctx.lock:
                for r in pending:
                    ans = answers.get(r["id"])
                    ctx.clarifications[r["id"]] = {"question": r["question"], "answer": ans,
                                                   "assumed_default": None if ans else r["default"]}
                    decisions.append({
                        "kind": "clarification" if ans else "assumption", "ref": r["id"],
                        "decision": f"{r['id']}: {ans}" if ans else f"{r['id']}: ASSUMED '{r['default']}'",
                        "rationale": ("answered by requester" if ans else
                                      "no answer available; conservative default chosen and flagged for sign-off"),
                        "alternatives": [r["question"]]})
        clar = [{"id": r["id"], **ctx.clarifications[r["id"]]} for r in detected]
        assumptions = [{"id": c["id"], "text": c["assumed_default"], "question": c["question"]}
                       for c in clar if c["assumed_default"]]

        # 2. capability extraction from stated text + answers + assumptions (with provenance)
        sources = [("stated", raw)] + [(f"clarified:{c['id']}", c["answer"]) for c in clar if c["answer"]] + \
                  [(f"assumed:{c['id']}", c["assumed_default"]) for c in clar if c["assumed_default"]]
        caps: dict[str, dict] = {}
        for src, text in sources:
            for cap, meta in CAPABILITIES.items():
                m = re.search(meta["keywords"], text, re.I)
                if m and cap not in caps:
                    caps[cap] = {"capability": cap, "title": meta["title"], "source": src, "evidence": m.group(0)}
        capabilities = [{"id": f"REQ-{i:02d}", **c} for i, c in enumerate(caps.values(), 1)]

        # 3. non-functional requirements and parameters
        nfrs = [{"id": i, "text": t} for i, p, t in NFR_RULES if re.search(p, raw, re.I)]
        all_text = " ".join(t for _, t in sources)
        perf = None
        if any(c["id"] == "AMB-PERF" for c in clar) or re.search(r"p9\d", all_text):
            m = re.search(r"(\d+)\s*ms", all_text)
            perf = int(m.group(1)) if m else 50
            nfrs.append({"id": "NFR-PERF", "text": f"p95 redirect latency <= {perf} ms (verified by in-process benchmark)"})
        params = {}
        m = re.search(r"(\d+)\s*(?:\w+\s+){0,3}(?:per|/|a)\s*(?:min|minute)", all_text, re.I)
        if m and "rate_limit" in caps:
            params["rate_limit_per_minute"] = int(m.group(1))
        nfrs += [{"id": "NFR-SEC", "text": "All changes pass policy guardrails: no secrets, parameterised SQL, safe URL handling"},
                 {"id": "NFR-TEST", "text": "Unit and integration tests pass before release"}]

        titles = ", ".join(c["title"].lower() for c in capabilities) or "(none identified)"
        req = {
            "raw": raw,
            "problem_statement": (f"Deliver the following capabilities on the URL shortener service: {titles}. "
                                  f"Constraints: {'; '.join(n['text'] for n in nfrs if n['id'] != 'NFR-TEST')}."),
            "capabilities": capabilities, "nfrs": nfrs, "clarifications": clar, "assumptions": assumptions,
            "params": params, "perf_target_ms": perf,
            "out_of_scope": ["multi-node deployment", "authentication / per-user accounts", "UI"],
        }
        return AgentResult(artifacts={"requirements": req}, decisions=decisions,
                           notes=f"{len(capabilities)} capabilities, {len(clar)} ambiguities "
                                 f"({len(assumptions)} assumed, {len(clar) - len(assumptions)} answered)")


class CodebaseAnalyst(Agent):
    name = "codebase-analyst"
    ANCHOR = re.compile(r"# \[ext:([\w-]+)\]")

    def run(self, ctx, stage: Stage) -> AgentResult:
        ws = ctx.workspace
        modules, routes, edges, tables, tests, anchors, errors = {}, [], set(), set(), [], [], []
        for rel in ws.files(".py"):
            if rel.startswith("tests/"):
                tests.append(rel)
                continue
            src = ws.read(rel) or ""
            try:
                tree = ast.parse(src)
            except SyntaxError as exc:
                errors.append(f"{rel}: {exc.msg} (line {exc.lineno})")
                continue
            info = {"loc": len(src.splitlines()), "classes": [], "functions": [], "imports": []}
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    info["classes"].append(node.name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    info["functions"].append(node.name)
            pkg = rel.rsplit("/", 1)[0] if "/" in rel else ""
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    target = None
                    if node.level >= 1 and node.module:
                        target = f"{pkg}/{node.module}.py" if pkg else f"{node.module}.py"
                    elif node.module and node.module.startswith("shortener."):
                        target = node.module.replace(".", "/") + ".py"
                    if target and target != rel:
                        edges.add((rel, target))
                        info["imports"].append(target)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for dec in node.decorator_list:
                        if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                                and dec.func.attr in {"get", "post", "put", "delete", "patch"}
                                and dec.args and isinstance(dec.args[0], ast.Constant)):
                            routes.append({"method": dec.func.attr.upper(), "path": dec.args[0].value,
                                           "module": rel, "handler": node.name})
            tables.update(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", src))
            anchors += [f"{rel}:{a}" for a in self.ANCHOR.findall(src)]
            modules[rel] = info
        present = [p for p, meta in PACKS.items() if ws.exists(meta["marker"])]
        cmap = {"modules": modules, "routes": sorted(routes, key=lambda r: (r["path"], r["method"])),
                "edges": sorted(edges), "tables": sorted(tables), "tests": sorted(tests),
                "extension_anchors": sorted(anchors), "present_packs": present, "syntax_errors": errors,
                "empty": not modules}
        return AgentResult(artifacts={"codebase_map": cmap},
                           notes=f"{len(modules)} modules, {len(routes)} routes, present packs: {present or 'none'}")


def _toposort(tasks: list[dict]) -> list[str]:
    deps = {t["id"]: set(t["depends_on"]) for t in tasks}
    indeg = {k: len(v) for k, v in deps.items()}
    q, order = deque(sorted(k for k, n in indeg.items() if n == 0)), []
    while q:
        k = q.popleft()
        order.append(k)
        for other, d in deps.items():
            if k in d:
                indeg[other] -= 1
                if indeg[other] == 0:
                    q.append(other)
    return order


class PlannerAgent(Agent):
    name = "planner"

    def run(self, ctx, stage: Stage) -> AgentResult:
        req, cmap = ctx.get("requirements"), ctx.get("codebase_map")
        wanted_caps = [c["capability"] for c in req["capabilities"]]
        unmapped = [c for c in wanted_caps if c not in CAPABILITY_TO_PACK]
        wanted = pack_closure({CAPABILITY_TO_PACK[c] for c in wanted_caps if c in CAPABILITY_TO_PACK})
        present = cmap["present_packs"]
        todo = [p for p in wanted if p not in present]
        satisfied = [c for c in wanted_caps if CAPABILITY_TO_PACK.get(c) in present]
        mode = "greenfield" if cmap["empty"] else "brownfield"

        T = []
        def add(tid, title, stage_id, deps, acceptance, owner):
            T.append({"id": tid, "title": title, "stage": stage_id, "depends_on": deps,
                      "acceptance": list(dict.fromkeys(acceptance)), "owner": owner})
        add("T-ANALYZE", "Map existing modules, routes, data flows and extension points", "codebase_analysis", [],
            ["codebase_map produced", "no syntax errors"], "codebase-analyst")
        add("T-DESIGN", "Assess impact, record decisions, build risk register and rollback plan", "design",
            ["T-ANALYZE"], ["every risk has mitigation + validation", "each pack has an ADR"], "architect")
        impl, tests = [], []
        for p in todo:
            deps = ["T-DESIGN"] + [f"T-IMPL-{r}" for r in PACKS[p]["requires"] if r in todo]
            add(f"T-IMPL-{p}", f"Implement: {PACKS[p]['title']}", "implement", deps,
                ["policy-clean change set", "workspace compiles", f"marker {PACKS[p]['marker']} present"], "implementer")
            add(f"T-TEST-{p}", f"Author tests: {PACKS[p]['title']}", "author_tests", ["T-DESIGN", "T-CONTRACT"],
                [r["validation"] for r in PACKS[p]["risks"]], "test-author")
            impl.append(f"T-IMPL-{p}")
            tests.append(f"T-TEST-{p}")
        add("T-CONTRACT", "Define API contract (contract-first) and generate conformance tests", "api_spec",
            ["T-DESIGN"], ["all public endpoints and request fields declared"], "api-designer")
        add("T-VERIFY", "Run full test suite and NFR benchmarks", "verify", impl + tests,
            ["all tests pass", "NFR targets met"], "verifier")
        add("T-SEC", "Security review of the resulting workspace", "security_review", impl,
            ["no blocking findings"], "security-reviewer")
        add("T-DOCS", "Update README, API reference, design notes, changelog", "docs", ["T-CONTRACT"] + impl,
            ["docs match contract"], "docs-writer")
        add("T-RELEASE", "Release-readiness gate and human approval", "release", ["T-VERIFY", "T-SEC", "T-DOCS"],
            ["all readiness checks green", "assumptions approved"], "release-manager")
        order = _toposort(T)
        ids = {t["id"] for t in T}
        for t in T:
            t["depends_on"] = [d for d in t["depends_on"] if d in ids]
        order = _toposort(T)
        plan = {"mode": mode, "wanted_packs": wanted, "present_packs": present, "todo_packs": todo,
                "satisfied_capabilities": satisfied, "unmapped_capabilities": unmapped, "tasks": T,
                "order": order, "acyclic": len(order) == len(T), "params": req["params"],
                "perf_target_ms": req["perf_target_ms"]}
        rationale = (f"{mode}: requested capabilities map to packs {wanted}; already installed: {present or 'none'}; "
                     f"to implement: {todo or 'nothing'}")
        return AgentResult(artifacts={"plan": plan}, notes=rationale,
                           decisions=[{"kind": "plan", "decision": f"Scope = {todo or 'no change'} ({mode})",
                                       "rationale": rationale,
                                       "alternatives": ["implement everything from scratch", "defer optional capabilities"]}])
