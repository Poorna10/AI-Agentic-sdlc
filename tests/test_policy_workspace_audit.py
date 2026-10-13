import json

import pytest

from orchestrator.audit import AuditLog
from orchestrator.model import Change, ChangeConflict
from orchestrator.policy import PolicyEngine
from orchestrator.workspace import Workspace

P = PolicyEngine()


def rules(changes):
    return {(v.rule, v.action) for v in P.evaluate_changes(changes)}


@pytest.mark.parametrize("code,rule", [
    ('key = "AKIAABCDEFGHIJKLMNOP"\n', "SEC-001"),
    ('API_TOKEN = "sk_live_0123456789"\n', "SEC-001"),
    ("-----BEGIN RSA PRIVATE KEY-----\n", "SEC-001"),
    ("eval(user_input)\n", "SEC-002"),
    ("import os\nos.system('rm -rf /')\n", "SEC-002"),
    ("subprocess.run(cmd, shell=True)\n", "SEC-002"),
    ('conn.execute(f"SELECT * FROM t WHERE id={x}")\n', "SEC-003"),
    ('conn.execute("SELECT * FROM t WHERE id=%s" % x)\n', "SEC-003"),
    ("requests.get(u, verify=False)\n", "SEC-004"),
    ("code = random.choice(ALPHABET)\n", "SEC-005"),
])
def test_blocking_rules(code, rule):
    assert (rule, "BLOCK") in rules([Change("shortener/x.py", "write", code)])


def test_safe_code_is_clean():
    code = 'conn.execute("SELECT * FROM t WHERE id = ?", (x,))\ncode = secrets.choice(A)\n'
    assert rules([Change("shortener/x.py", "write", code)]) == set()


def test_path_traversal_and_absolute_paths_blocked():
    assert ("CHG-001", "BLOCK") in rules([Change("../evil.py", "write", "x=1")])
    assert ("CHG-001", "BLOCK") in rules([Change("/etc/passwd", "write", "x")])


def test_protected_paths_and_unapproved_dependencies_need_approval():
    assert ("CHG-003", "REQUIRE_APPROVAL") in rules([Change(".github/workflows/ci.yml", "write", "on: push")])
    r = rules([Change("requirements.txt", "write", "fastapi>=1\nleftpad-evil==1.0\n")])
    assert ("CMP-002", "REQUIRE_APPROVAL") in r
    assert rules([Change("requirements.txt", "write", "fastapi>=1\nhttpx\n")]) == set()


def test_schema_and_pii_rules_apply_to_source_not_docs_or_tests():
    ddl = "CREATE TABLE t (id int)"
    assert ("CHG-002", "REQUIRE_APPROVAL") in rules([Change("shortener/store.py", "write", ddl)])
    assert rules([Change("docs/DESIGN.md", "write", ddl)]) == set()
    assert rules([Change("tests/test_x.py", "write", ddl)]) == set()
    pii = 'conn.execute("INSERT INTO c VALUES (?)", (request.client.host,))'
    assert ("CMP-001", "REQUIRE_APPROVAL") in rules([Change("shortener/store.py", "write", pii)])
    assert rules([Change("shortener/rl.py", "write", "key = request.client.host\n")]) == set()


def test_workspace_apply_is_atomic_and_revertible(tmp_path):
    ws = Workspace(tmp_path / "w")
    ws.apply([Change("a.py", "write", "x = 1\n# [anchor]\n")])
    receipt = ws.apply([Change("a.py", "edit", edits=[("# [anchor]", "y = 2\n# [anchor]")]),
                        Change("b.py", "write", "new")])
    assert "y = 2" in ws.read("a.py") and ws.exists("b.py")
    assert "y = 2" in ws.diff(receipt)
    ws.revert(receipt)
    assert ws.read("a.py") == "x = 1\n# [anchor]\n" and not ws.exists("b.py")


def test_failed_edit_leaves_nothing_behind(tmp_path):
    ws = Workspace(tmp_path / "w")
    ws.apply([Change("a.py", "write", "x = 1\n")])
    with pytest.raises(ChangeConflict, match="matched 0 times"):
        ws.apply([Change("new.py", "write", "n"), Change("a.py", "edit", edits=[("missing", "z")])])
    assert not ws.exists("new.py") and ws.read("a.py") == "x = 1\n"
    ws.apply([Change("d.py", "write", "t\nt\n")])
    with pytest.raises(ChangeConflict, match="matched 2 times"):       # ambiguous anchors are refused
        ws.apply([Change("d.py", "edit", edits=[("t", "u")])])


def test_workspace_rejects_escaping_paths(tmp_path):
    ws = Workspace(tmp_path / "w")
    for bad in ("../x", "/abs", "a/../../x"):
        with pytest.raises(ChangeConflict):
            ws.apply([Change(bad, "write", "x")])


def test_audit_chain_detects_tampering_and_resumes(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, "r1")
    for i in range(5):
        log.record("evt", "tester", f"s{i}", n=i)
    assert AuditLog.verify(path) == (True, 5, "ok")
    AuditLog(path, "r1").record("evt", "tester", "after-resume")      # chain continues across resume
    assert AuditLog.verify(path)[:2] == (True, 6)
    lines = path.read_text().splitlines()
    forged = json.loads(lines[2])
    forged["data"]["n"] = 999
    lines[2] = json.dumps(forged)
    path.write_text("\n".join(lines) + "\n")
    ok, n, msg = AuditLog.verify(path)
    assert not ok and "chain broken" in msg
