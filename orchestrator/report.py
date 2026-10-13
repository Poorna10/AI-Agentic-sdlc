"""Final engineering summary + decision lineage, generated from the run's own records."""
from __future__ import annotations

import json
from pathlib import Path

from .audit import AuditLog

LIMITATIONS = [
    "Agents are deterministic and template-backed so the prototype is reproducible offline; the `generator` "
    "interface is where an LLM plugs in. Every guardrail (policy, approvals, gates, rollback) applies to any generator.",
    "Single-process, thread-based scheduler with file-backed state; no distributed workers or durable queue.",
    "Policy scanning is regex-based (fast, explainable) and is not a substitute for SAST/DAST/SCA in CI.",
    "Rollback is path-scoped: concurrently running mutating stages must own disjoint file paths (true for this workflow).",
    "The latency benchmark is in-process (TestClient) - indicative, not a load test.",
    "Metrics are per run segment: a resumed run reports its own segment's retries/latency.",
    "Scripted human decisions stand in for reviewers in demos; interactive mode prompts on stdin.",
]


def _md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in r) + " |" for r in rows]
    return "\n".join(out)


def write_final_summary(engine, run_status, metrics: dict) -> Path:
    ctx, g = engine.ctx, engine.graph
    req, plan, design = ctx.get("requirements") or {}, ctx.get("plan") or {}, ctx.get("design") or {}
    ver, sec, rel = ctx.get("verification"), ctx.get("security_report"), ctx.get("release_report")
    audit_events = AuditLog.read(engine.audit.path)
    ok, n, msg = AuditLog.verify(engine.audit.path)
    L: list[str] = []
    add = L.append
    add(f"# Engineering summary - {ctx.scenario.get('name')} ({ctx.run_id})\n")
    add(f"**Run status:** `{run_status.value}`" + (f" - stopped: {engine.safe_stop_reason}" if engine.safe_stop_reason else ""))
    add(f"**Mode:** {plan.get('mode', 'n/a')}  |  **Scope delivered:** {plan.get('todo_packs', [])}  |  "
        f"**Version:** {(rel or {}).get('version', 'n/a')}\n")

    add("## 1. Requirement understanding")
    add(f"> {req.get('raw', ctx.get('raw_requirement', ''))}\n")
    add(f"**Normalised problem:** {req.get('problem_statement', 'n/a')}\n")
    if req.get("capabilities"):
        add(_md_table(["ID", "Capability", "Derived from", "Evidence"],
                      [(c["id"], c["title"], c["source"], c["evidence"]) for c in req["capabilities"]]))
    if req.get("clarifications"):
        add("\n**Ambiguities detected**\n")
        add(_md_table(["ID", "Question", "Resolution"], [
            (c["id"], c["question"], f"answered: {c['answer']}" if c["answer"] else f"ASSUMED: {c['assumed_default']}")
            for c in req["clarifications"]]))
    add("\n**Non-functional requirements:** " + "; ".join(n_["text"] for n_ in req.get("nfrs", [])) + "\n")

    add("## 2. Plan and rationale")
    add(f"Parallel structure of the workflow graph: `{g.levels()}`\n")
    if plan.get("tasks"):
        add(_md_table(["Task", "Stage", "Depends on", "Acceptance"],
                      [(t["id"], t["stage"], ", ".join(t["depends_on"]) or "-", "; ".join(t["acceptance"])) for t in plan["tasks"]]))
    if design:
        add(f"\n**Impact:** modified `{design['modified_modules']}`, new `{design['new_modules']}`, "
            f"blast radius {len(design['blast_radius'])} modules.")
        add(f"**High-impact:** {design['high_impact']} ({', '.join(design['high_impact_reasons']) or '-'})")

    add("\n## 3. Decision lineage (who decided what, on which inputs)")
    add(_md_table(["ID", "Stage", "Actor", "Kind", "Decision", "Inputs", "Status"],
                  [(d["id"], d["stage"], d["actor"], d["kind"], d["decision"],
                    ", ".join(f"{k}@v{v}" for k, v in d["inputs"].items()) or "-", d["status"]) for d in ctx.decisions]))
    trade = [d for d in ctx.decisions if d.get("tradeoff") and d["status"] == "active"]
    if trade:
        add("\n**Trade-offs accepted**\n")
        add(_md_table(["Decision", "Rationale", "Trade-off", "Alternatives rejected"],
                      [(d["decision"], d["rationale"], d["tradeoff"], "; ".join(d["alternatives"])) for d in trade]))

    add("\n## 4. Artifacts")
    add(_md_table(["Artifact", "Version", "Producer", "History"],
                  [(a, h[-1]["version"], h[-1]["producer"], f"{len(h)} version(s)") for a, h in sorted(ctx.versions.items())]))
    patches = sorted((ctx.artifact_dir / "patches").glob("*.patch")) if (ctx.artifact_dir / "patches").exists() else []
    add("\nPatches for review: " + (", ".join(f"`artifacts/patches/{p.name}`" for p in patches) or "none"))
    add(f"\nWorkspace files: {len(ctx.workspace.files())} (`workspace/`)")

    add("\n## 5. Risks, validation and guardrails")
    if design.get("risks"):
        add(_md_table(["Risk", "Scenario", "Mitigation", "Validation"],
                      [(r["id"], r["scenario"], r["mitigation"], r["validation"]) for r in design["risks"]]))
    if ver:
        add(f"\n**Tests:** {ver['tests']['passed']} passed, {ver['tests']['failed']} failed. "
            + (f"**Perf:** p95 {ver['perf'].get('p95_ms')} ms vs target {ver['perf']['target_ms']} ms." if ver.get("perf") else ""))
    if sec:
        add(f"**Security review:** {len(sec['blocking'])} blocking findings; advisories: {[a['message'] for a in sec['advisories']] or 'none'}")
    if rel:
        add("\n**Release readiness**\n")
        add(_md_table(["Check", "Result", "Detail"], [(c["name"], "PASS" if c["ok"] else "FAIL", c["detail"]) for c in rel["checks"]]))
    viol = [e for e in audit_events if e["event"] == "policy_violation"]
    add(f"\n**Policy events:** {len(viol)} - " + (", ".join(sorted({f"{e['data']['rule']}({e['data']['action']})@{e['stage']}" for e in viol})) or "none"))

    add("\n## 6. Execution record")
    rows = []
    for sid in g.order:
        m = metrics["per_stage"].get(sid, {})
        rows.append((sid, engine.status[sid].value, m.get("attempts", 0), m.get("retries", 0), m.get("rollbacks", 0),
                     m.get("duration_s", 0), engine.errors.get(sid, "")[:90]))
    add(_md_table(["Stage", "Status", "Attempts", "Retries", "Rollbacks", "Time (s)", "Last error"], rows))
    appr = [e for e in audit_events if e["event"] == "approval_decision"]
    add("\n**Human approvals**\n")
    add(_md_table(["Approval", "Stage", "Approver", "Decision", "Comment"],
                  [(e["data"]["approval_id"], e["stage"], e["actor"], "APPROVED" if e["data"]["approved"] else "REJECTED",
                    e["data"]["comment"]) for e in appr]) if appr else "none")
    for e in audit_events:
        if e["event"] == "replan":
            add(f"\n**Re-plan** (audit seq {e['seq']}): stale stages `{e['data']['stale_stages']}` because artifacts changed "
                f"`{e['data']['changed_artifacts']}`; unaffected and reused: `{e['data']['unaffected']}`")
        if e["event"] == "fallback_engaged":
            add(f"\n**Fallback** at `{e['stage']}` -> `{e['data']['fallback']}`")

    add("\n## 7. Reliability metrics")
    add(_md_table(["Metric", "Value"], [
        ("Stage success rate", f"{metrics['stage_success_rate']:.0%} ({metrics['stages_succeeded']}/{metrics['stages_total']})"),
        ("First-attempt success rate", f"{metrics['first_attempt_success_rate']:.0%}"),
        ("Retries / rollbacks / re-plans", f"{metrics['retries']} / {metrics['rollbacks']} / {metrics['replans']}"),
        ("Policy blocks", metrics["policy_blocks"]),
        ("MTTR", "n/a" if metrics["mttr_s"] is None else f"{metrics['mttr_s']} s over {metrics['recovered_incidents']} incident(s)"),
        ("Unrecovered incidents", metrics["unrecovered_incidents"]),
        ("Human approvals (wait)", f"{metrics['approvals']} ({metrics['approval_wait_s']} s)"),
        ("End-to-end latency", f"{metrics['end_to_end_latency_s']} s")]))

    add("\n## 8. Assumptions and limitations")
    for a in req.get("assumptions", []):
        add(f"- **Assumption {a['id']}:** {a['text']} (flagged for, and covered by, requirements sign-off)")
    add("- Out of scope: " + ", ".join(req.get("out_of_scope", [])))
    for l in LIMITATIONS:
        add(f"- {l}")
    for r in (rel or {}).get("residual_risks", []):
        add(f"- Residual risk: {r}")
    add(f"\n## 9. Audit integrity\nHash-chained audit log: {n} entries, verification **{'OK' if ok else 'FAILED'}** ({msg}).")

    path = ctx.run_dir / "ENGINEERING_SUMMARY.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    (ctx.run_dir / "lineage.json").write_text(json.dumps(
        {"versions": ctx.versions, "decisions": ctx.decisions}, indent=2, default=str))
    return path
