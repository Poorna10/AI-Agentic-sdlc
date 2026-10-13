import pytest

from orchestrator.graph import GraphError, WorkflowGraph
from orchestrator.model import Stage, Status
from orchestrator.workflow import build_workflow


def S(id, deps=(), consumes=(), produces=()):
    return Stage(id, "a", id, depends_on=tuple(deps), consumes=tuple(consumes), produces=tuple(produces))


def test_cycle_is_rejected():
    with pytest.raises(GraphError, match="cycle"):
        WorkflowGraph([S("a", ["b"]), S("b", ["a"])])


def test_unknown_dependency_is_rejected():
    with pytest.raises(GraphError, match="unknown"):
        WorkflowGraph([S("a", ["ghost"])])


def test_dataflow_requires_an_ancestor_producer():
    with pytest.raises(GraphError, match="no ancestor produces"):
        WorkflowGraph([S("a", produces=["x"]), S("b", consumes=["x"])])      # b is not downstream of a
    WorkflowGraph([S("a", produces=["x"]), S("b", ["a"], consumes=["x"])])    # fine


def test_ready_requires_all_ancestors_and_blocked_propagates():
    g = WorkflowGraph([S("a"), S("b", ["a"]), S("c", ["b"])])
    st = {k: Status.PENDING for k in g.order}
    assert g.ready(st) == ["a"]
    st["a"] = Status.SUCCEEDED
    assert g.ready(st) == ["b"]
    st["a"] = Status.PENDING          # upstream reset by a re-plan: b must not run on stale input
    st["b"] = Status.PENDING
    assert g.ready(st) == ["a"]
    st["a"] = Status.FAILED
    assert g.propagate_blocked(st) == ["b", "c"] or set(g.propagate_blocked(st)) <= {"b", "c"}
    assert st["b"] == Status.BLOCKED and st["c"] == Status.BLOCKED


def test_sdlc_workflow_has_parallel_paths_and_joins():
    g = build_workflow()
    levels = g.levels()
    assert {"codebase_analysis", "requirements"} == set(levels[0])           # parallel roots, joined at plan
    assert {"api_spec", "implement"} <= set(sum(levels, [])) and any(
        {"api_spec", "implement"} == set(l) for l in levels)
    assert set(g.stages["release"].depends_on) == {"verify", "security_review", "docs"}   # synchronisation join
    assert g.stages["plan"].depends_on == ("requirements", "codebase_analysis")
    assert g.descendants(["design"]) >= {"implement", "verify", "release"}
