"""Validation: test execution, NFR benchmark and security review."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

from ..catalog import PACKS
from ..model import AgentResult, Stage
from . import Agent

BENCH = r'''
import json, os, tempfile, time
from fastapi.testclient import TestClient
from shortener.api import create_app
from shortener.config import Settings
d = tempfile.mkdtemp()
with TestClient(create_app(Settings(db_path=os.path.join(d, "b.db"))), follow_redirects=False) as c:
    code = c.post("/api/v1/links", json={"url": "https://example.com"}).json()["code"]
    lat = []
    for _ in range(300):
        t = time.perf_counter(); r = c.get("/" + code); lat.append((time.perf_counter() - t) * 1000)
        assert r.status_code == 307
lat.sort()
print(json.dumps({"n": len(lat), "p50_ms": round(lat[len(lat)//2], 2), "p95_ms": round(lat[int(len(lat)*.95)], 2)}))
'''


def _run(ctx, args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ctx.workspace.root), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, *args], cwd=ctx.workspace.root, env=env, capture_output=True,
                          text=True, timeout=timeout)


class VerifierAgent(Agent):
    name = "verifier"

    def run(self, ctx, stage: Stage) -> AgentResult:
        proc = _run(ctx, ["-m", "pytest", "-o", "addopts=", "-q", "-p", "no:cacheprovider", "tests"])
        out = proc.stdout + proc.stderr
        passed = int(next(iter(re.findall(r"(\d+) passed", out)), 0))
        failed = int(next(iter(re.findall(r"(\d+) failed", out)), 0)) + int(next(iter(re.findall(r"(\d+) error", out)), 0))
        tests = {"returncode": proc.returncode, "passed": passed, "failed": failed, "tail": out.strip()[-1200:]}
        perf, perf_ok = None, True
        target = ctx.get("requirements", {}).get("perf_target_ms")
        if target and proc.returncode == 0:
            b = _run(ctx, ["-c", BENCH], timeout=120)
            if b.returncode == 0:
                perf = {**json.loads(b.stdout.strip().splitlines()[-1]), "target_ms": target}
                perf_ok = perf["p95_ms"] <= target
            else:
                perf, perf_ok = {"error": b.stderr[-400:], "target_ms": target}, False
        ok = proc.returncode == 0 and passed > 0 and perf_ok
        return AgentResult(artifacts={"verification": {"ok": ok, "tests": tests, "perf": perf}},
                           notes=f"{passed} passed, {failed} failed" + (f", p95={perf['p95_ms']}ms" if perf and "p95_ms" in perf else ""))


class SecurityReviewAgent(Agent):
    name = "security-reviewer"

    def run(self, ctx, stage: Stage) -> AgentResult:
        ws = ctx.workspace
        findings = [dict(v.to_dict(), severity="BLOCK") for v in ctx.policy.scan_workspace(ws)]
        req = ws.read("requirements.txt") or ""
        for line in req.splitlines():
            name = re.split(r"[<>=!~\[ ;#]", line.strip(), maxsplit=1)[0].lower()
            if name and name not in ctx.policy.dep_allowlist:
                findings.append({"rule": "CMP-002", "severity": "BLOCK", "message": f"unapproved dependency {name}",
                                 "path": "requirements.txt", "action": "BLOCK", "line": None})
        if "is_private" not in (ws.read("shortener/validation.py") or ""):
            findings.append({"rule": "SEC-SSRF", "severity": "BLOCK", "path": "shortener/validation.py", "line": None,
                             "action": "BLOCK", "message": "destination URL validation lacks private-address checks"})
        advisories = []
        for pack, why in (("ratelimit", "No rate limiting: link creation can be abused"),
                          ("blocklist", "No destination blocklist: malicious domains can be shortened"),
                          ("secheaders", "No security response headers")):
            if not ws.exists(PACKS[pack]["marker"]):
                advisories.append({"rule": f"POSTURE-{pack}", "severity": "WARN", "message": why})
        blocking = [f for f in findings if f["severity"] == "BLOCK"]
        report = {"blocking": blocking, "advisories": advisories, "files_scanned": len(ws.files()),
                  "residual_risks": [a["message"] for a in advisories]
                  + ["Static (regex) policy scan; not a substitute for SAST/DAST in CI",
                     "DNS-rebinding SSRF is out of scope: only literal IPs and internal suffixes are screened"]}
        return AgentResult(artifacts={"security_report": report},
                           notes=f"{len(blocking)} blocking, {len(advisories)} advisories, {report['files_scanned']} files")
