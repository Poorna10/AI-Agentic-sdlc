"""The SDLC workflow definition: stages, dependency graph, entry/exit gates, approvals.

          requirements --+                                   +--> verify ---------+
                         +--> plan --> design --+--> implement --+--> security ----+--> release
          codebase ------+                      +--> api_spec --> author_tests ----+
                                                          +--------> docs ---------+
"""
from __future__ import annotations

from .catalog import PACKS
from .graph import WorkflowGraph
from .model import ApprovalSpec, PASS, Stage, fail


def _compiles(ctx) -> str | None:
    for rel in ctx.workspace.files(".py"):
        try:
            compile(ctx.workspace.read(rel) or "", rel, "exec")
        except SyntaxError as exc:
            return f"{rel}:{exc.lineno}: {exc.msg}"
    return None


# ---- entry gates ---------------------------------------------------------------------------
def entry_requirements(ctx):
    raw = ctx.get("raw_requirement", "")
    return PASS if len(raw.strip()) >= 20 else fail("requirement text missing or too short")


def entry_design(ctx):
    plan = ctx.get("plan")
    return PASS if plan and plan.get("acyclic") else fail("no valid plan")


# ---- exit gates ----------------------------------------------------------------------------
def exit_requirements(ctx, res):
    r = res.artifacts["requirements"]
    if not r["capabilities"]:
        return fail("no capabilities could be derived from the requirement")
    unresolved = [c["id"] for c in r["clarifications"] if not c["answer"] and not c["assumed_default"]]
    return fail(f"unresolved ambiguities: {unresolved}") if unresolved else PASS


def exit_codebase(ctx, res):
    errs = res.artifacts["codebase_map"]["syntax_errors"]
    return fail(f"existing code does not parse: {errs}") if errs else PASS


def exit_plan(ctx, res):
    p = res.artifacts["plan"]
    if not p["acyclic"]:
        return fail("task graph has a cycle")
    return fail(f"unmapped capabilities: {p['unmapped_capabilities']}") if p["unmapped_capabilities"] else PASS


def exit_design(ctx, res):
    d, plan = res.artifacts["design"], ctx.get("plan")
    if plan["todo_packs"] and not d["risks"]:
        return fail("empty risk register")
    bad = [r["id"] for r in d["risks"] if not r.get("mitigation") or not r.get("validation")]
    if bad:
        return fail(f"risks without mitigation/validation: {bad}")
    if plan["todo_packs"] and not d["rollback_plan"]:
        return fail("no rollback plan")
    return PASS


def exit_implement(ctx, res):
    err = _compiles(ctx)
    if err:
        return fail(f"workspace does not compile: {err}")
    impl = res.artifacts["implementation"]
    missing = [p for p in impl["packs_applied"] if not ctx.workspace.exists(PACKS[p]["marker"])]
    return fail(f"pack markers missing after apply: {missing}") if missing else PASS


def exit_api_spec(ctx, res):
    c, plan = res.artifacts["api_contract"], ctx.get("plan")
    declared = {(e["method"], e["path"]) for e in c["endpoints"]}
    need = {(m, p) for pk in set(plan["present_packs"]) | set(plan["todo_packs"]) for m, p, _ in PACKS[pk]["endpoints"]}
    return fail(f"contract missing endpoints: {sorted(need - declared)}") if need - declared else PASS


def exit_author_tests(ctx, res):
    missing = [f for f in res.artifacts["test_suite"]["files"] if not ctx.workspace.exists(f)]
    return fail(f"test files missing: {missing}") if missing else PASS


def exit_verify(ctx, res):
    v = res.artifacts["verification"]
    return PASS if v["ok"] else fail(f"verification failed: {v['tests']['passed']} passed, {v['tests']['failed']} failed; "
                                     f"perf={v['perf']}; pytest tail: {v['tests']['tail'][-300:]!r}")


def exit_security(ctx, res):
    b = res.artifacts["security_report"]["blocking"]
    return fail(f"{len(b)} blocking security findings, e.g. {b[0]['rule']} in {b[0]['path']}") if b else PASS


def exit_docs(ctx, res):
    need = ["README.md"]
    missing = [f for f in need if not ctx.workspace.exists(f)]
    return fail(f"docs missing: {missing}") if missing else PASS


def exit_release(ctx, res):
    r = res.artifacts["release_report"]
    bad = [c["name"] for c in r["checks"] if not c["ok"]]
    return PASS if r["ready"] else fail(f"release readiness checks failed: {bad}")


# ---- approval summaries ---------------------------------------------------------------------
def _req_summary(ctx, res):
    r = res.artifacts["requirements"]
    return {"capabilities": [f"{c['title']} ({c['source']})" for c in r["capabilities"]],
            "assumptions_to_confirm": [f"{a['id']}: {a['text']}" for a in r["assumptions"]] or "none",
            "nfrs": [n["text"] for n in r["nfrs"]]}


def _design_summary(ctx, res):
    d = res.artifacts["design"]
    return {"why_high_impact": d["high_impact_reasons"], "schema_changes": d["schema_changes"],
            "api_changes": d["api_changes"], "new_dependencies": d["dependency_changes"],
            "risks": len(d["risks"]), "rollback": d["rollback_plan"][0]}


def _release_summary(ctx, res):
    r = res.artifacts["release_report"]
    return {"version": r["version"], "checks": {c["name"]: ("PASS" if c["ok"] else "FAIL") for c in r["checks"]},
            "residual_risks": r["residual_risks"]}


def build_workflow() -> WorkflowGraph:
    S = Stage
    return WorkflowGraph([
        S("requirements", "requirements-analyst", "Normalise the requirement, detect ambiguity, clarify, sign off",
          consumes=("raw_requirement",), produces=("requirements",), entry_gate=entry_requirements,
          exit_gate=exit_requirements,
          approval=ApprovalSpec("requirements_signoff", "Requirements sign-off", summary=_req_summary)),
        S("codebase_analysis", "codebase-analyst", "Map modules, routes, data flows, extension points",
          produces=("codebase_map",), exit_gate=exit_codebase),
        S("plan", "planner", "Decompose into dependency-ordered tasks", depends_on=("requirements", "codebase_analysis"),
          consumes=("requirements", "codebase_map"), produces=("plan",), exit_gate=exit_plan),
        S("design", "architect", "Impact analysis, ADRs, risk register, rollback plan", depends_on=("plan",),
          consumes=("plan", "codebase_map", "requirements"), produces=("design",), entry_gate=entry_design,
          exit_gate=exit_design,
          approval=ApprovalSpec("design_signoff", "Design sign-off (high-impact change)",
                                when=lambda ctx, res: res.artifacts["design"]["high_impact"], summary=_design_summary)),
        S("implement", "implementer", "Apply policy-checked feature packs to the workspace", depends_on=("design",),
          consumes=("plan", "design"), produces=("implementation",), exit_gate=exit_implement, mutates=True,
          fallback_agent="implementer-safe-mode"),
        S("api_spec", "api-designer", "Contract-first API definition", depends_on=("design",),
          consumes=("plan", "design"), produces=("api_contract",), exit_gate=exit_api_spec),
        S("author_tests", "test-author", "Author tests and generate contract conformance tests",
          depends_on=("api_spec",), consumes=("plan", "api_contract"), produces=("test_suite",),
          exit_gate=exit_author_tests, mutates=True),
        S("verify", "verifier", "Run the suite and NFR benchmarks", depends_on=("implement", "author_tests"),
          consumes=("implementation", "test_suite", "requirements"), produces=("verification",),
          exit_gate=exit_verify, max_retries=1),
        S("security_review", "security-reviewer", "Policy scan and posture review of the result",
          depends_on=("implement",), consumes=("implementation",), produces=("security_report",),
          exit_gate=exit_security),
        S("docs", "docs-writer", "README, API reference, design notes, changelog", depends_on=("api_spec", "implement"),
          consumes=("plan", "design", "api_contract", "implementation"), produces=("docs_bundle",),
          exit_gate=exit_docs, mutates=True, fallback_agent="docs-minimal"),
        S("release", "release-manager", "Release-readiness gate and approval", depends_on=("verify", "security_review", "docs"),
          consumes=("verification", "security_report", "implementation", "requirements", "docs_bundle", "plan", "design"),
          produces=("release_report",), exit_gate=exit_release, critical=True,
          approval=ApprovalSpec("release_approval", "Release approval", summary=_release_summary)),
    ])
