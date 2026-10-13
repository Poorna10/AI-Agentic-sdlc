from orchestrator.agents.analysis import CodebaseAnalyst, PlannerAgent, RequirementsAgent
from orchestrator.agents.build import ImplementerSafeMode
from orchestrator.approvals import Human
from orchestrator.model import Change
from orchestrator.packs import TemplateGenerator

from helpers import make_engine


def ctx_for(tmp_path, text, answers=None, packs=()):
    e = make_engine(tmp_path, [], [], human=Human(answers=answers or {}))
    ctx = e.ctx
    ctx.put("raw_requirement", text, "test")
    for p in packs:
        ctx.workspace.apply(TemplateGenerator().propose(p))
    return ctx


def req(ctx):
    return RequirementsAgent().run(ctx, None).artifacts["requirements"]


def caps(r):
    return {c["capability"] for c in r["capabilities"]}


def test_no_false_positive_capabilities_from_substrings(tmp_path):
    r = req(ctx_for(tmp_path, "Make the URL shortener production ready. We see abuse; throttle clients. "
                              "p95 redirect latency must be low. It should be fast.", {"AMB-PERF": "p95 under 40 ms"}))
    assert "expiry" not in caps(r) and "redirect" not in caps(r) and "create_link" not in caps(r)   # ttl in 'throttle' etc.
    assert "rate_limit" in caps(r)


def test_ambiguity_questions_answers_and_assumptions(tmp_path):
    r = req(ctx_for(tmp_path, "Make it fast and secure.", {"AMB-PERF": "p95 under 40 ms"}))
    by = {c["id"]: c for c in r["clarifications"]}
    assert by["AMB-PERF"]["answer"] and by["AMB-SEC"]["answer"] is None
    assert [a["id"] for a in r["assumptions"]] == ["AMB-SEC"]
    assert r["perf_target_ms"] == 40
    assert "rate_limit" in caps(r) and "security_headers" in caps(r)               # derived from the assumed default


def test_numeric_parameters_flow_from_answers_to_generated_code(tmp_path):
    ctx = ctx_for(tmp_path, "We have abuse from bots.", {"AMB-ABUSE": "allow 120 link creations per minute"})
    r = req(ctx)
    assert r["params"] == {"rate_limit_per_minute": 120}
    changes = TemplateGenerator().propose("ratelimit", r["params"], include="src")
    assert any("rate_limit_per_minute: int = 120" in c.added_text() for c in changes)


def test_well_defined_requirement_has_no_questions(tmp_path):
    r = req(ctx_for(tmp_path, "Provide a health check endpoint. Users can create short links with a custom alias."))
    assert r["clarifications"] == [] and caps(r) == {"health", "create_link", "custom_alias"}


def test_codebase_analyst_finds_routes_flows_and_installed_packs(tmp_path):
    ctx = ctx_for(tmp_path, "x" * 30, packs=("core", "expiry"))
    cmap = CodebaseAnalyst().run(ctx, None).artifacts["codebase_map"]
    assert cmap["present_packs"] == ["core", "expiry"] and not cmap["empty"]
    assert ("POST", "/api/v1/links") in {(r["method"], r["path"]) for r in cmap["routes"]}
    assert ["shortener/service.py", "shortener/store.py"] in [list(e) for e in cmap["edges"]]
    assert {"links", "clicks"} == set(cmap["tables"]) and "shortener/api.py:middleware" in cmap["extension_anchors"]


def test_planner_only_plans_missing_packs_and_respects_dependencies(tmp_path):
    ctx = ctx_for(tmp_path / "g", "Provide health check. Links expire after a TTL.")
    ctx.put("codebase_map", CodebaseAnalyst().run(ctx, None).artifacts["codebase_map"], "t")
    ctx.put("requirements", req(ctx), "t")
    plan = PlannerAgent().run(ctx, None).artifacts["plan"]
    assert plan["mode"] == "greenfield" and plan["todo_packs"] == ["core", "expiry"]   # 'expiry' pulls in 'core'
    deps = {t["id"]: t["depends_on"] for t in plan["tasks"]}
    assert "T-IMPL-core" in deps["T-IMPL-expiry"] and plan["acyclic"]
    assert deps["T-RELEASE"] == ["T-VERIFY", "T-SEC", "T-DOCS"]

    ctx2 = ctx_for(tmp_path / "b", "Links expire after a TTL.", packs=("core",))
    ctx2.put("codebase_map", CodebaseAnalyst().run(ctx2, None).artifacts["codebase_map"], "t")
    ctx2.put("requirements", req(ctx2), "t")
    assert PlannerAgent().run(ctx2, None).artifacts["plan"]["todo_packs"] == ["expiry"]


def test_safe_mode_defers_a_pack_that_cannot_be_delivered_safely(tmp_path):
    class Poisoned(TemplateGenerator):
        def propose(self, pack, params=None, include="all"):
            out = super().propose(pack, params, include)
            if pack == "ratelimit":
                out.append(Change("shortener/leak.py", "write", 'SECRET_KEY = "super-secret-value"\n'))
            return out
    ctx = ctx_for(tmp_path, "x" * 30, packs=("core",))
    ctx.put("plan", {"todo_packs": ["expiry", "ratelimit", "secheaders"], "params": {}}, "t")
    res = ImplementerSafeMode(Poisoned()).run(ctx, None)
    impl = res.artifacts["implementation"]
    assert impl["deferred_packs"] == ["ratelimit"] and impl["packs_applied"] == ["expiry", "secheaders"]
    assert not any(c.path == "shortener/leak.py" for c in res.changes)


def test_interactive_human_prompts_and_records_identity(tmp_path):
    from orchestrator.approvals import ApprovalRequest
    outputs, replies = [], iter(["n: touches PII", "y", "use p95 30ms", ""])
    h = Human(mode="interactive", approver="human:me", input_fn=lambda _p: next(replies), out=outputs.append)
    d = h.decide(ApprovalRequest("x", "Title", "stage", "why", {"k": "v"}))
    assert (d.approved, d.comment, d.approver) == (False, "touches PII", "human:me")
    assert h.decide(ApprovalRequest("y", "T", "s", "r")).approved is True
    answers = h.clarify([{"id": "Q1", "question": "?", "default": "d"}, {"id": "Q2", "question": "?", "default": "d"}])
    assert answers == {"Q1": "use p95 30ms"}                       # blank => unanswered => assumption
    assert any("APPROVAL REQUIRED" in o for o in outputs)
