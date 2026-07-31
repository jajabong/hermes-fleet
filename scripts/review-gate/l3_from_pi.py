#!/usr/bin/env python3
"""Normalize Pi JSONL output into a review-gate L3 report."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REVIEW_ROOT = Path.home() / ".hermes" / "artifacts" / "review"
RG = Path.home() / ".hermes" / "skills" / "software-development" / "review-gate" / "scripts" / "review_gate.py"
VERDICTS = ("PASS_WITH_NOTES", "CHANGES_REQUIRED", "BLOCKED", "PASS")


def extract_strings(value) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, list):
        for item in value:
            found.extend(extract_strings(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "content", "message", "output", "result", "response", "final"}:
                found.extend(extract_strings(item))
            elif isinstance(item, (dict, list)):
                found.extend(extract_strings(item))
    return found


def parse_stream(path: Path) -> tuple[str, bool, list[str]]:
    texts: list[str] = []
    errors: list[str] = []
    terminal_stop = False
    raw = path.read_text(encoding="utf-8", errors="replace")
    for line in raw.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        typ = obj.get("type")
        if typ == "message_update":
            event = obj.get("assistantMessageEvent") or {}
            if event.get("type") == "text_end" and event.get("content"):
                texts.append(event["content"].strip())
        if typ == "turn_end":
            msg = obj.get("message") or {}
            if msg.get("role") == "assistant":
                for block in (msg.get("content") or []):
                    if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                        texts.append(block["text"].strip())
            terminal_stop = True
        if typ == "agent_end":
            terminal_stop = True
        if typ == "tool_use":
            state = obj.get("part", {}).get("state") or {}
            if state.get("status") == "error":
                errors.append(str(state.get("error") or "tool error"))
    return "\n\n".join(t for t in texts if t).strip(), terminal_stop, errors


def explicit_verdict(text: str) -> str | None:
    patterns = [
        r"(?im)^\s*\*{0,2}\s*(?:VERDICT|RECOMMENDATION|FINAL(?:_RECOMMENDATION)?)\s*\*{0,2}\s*[:=-]\s*\*{0,2}(PASS_WITH_NOTES|CHANGES_REQUIRED|BLOCKED|PASS)\*{0,2}\b",
        r"(?im)^\s*\*{0,2}\s*(PASS_WITH_NOTES|CHANGES_REQUIRED|BLOCKED|PASS)\s*\*{0,2}\s*$",
    ]
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(re.findall(pattern, text))
    return matches[-1].upper() if matches else None


def load_l2(run_dir: Path) -> dict:
    p = run_dir / "l2-review.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def findings_from_text(text: str, l2: dict, incomplete: bool, errors: list[str]) -> tuple[list[dict], list[dict], list[dict]]:
    evidence = list(dict.fromkeys(re.findall(r"[A-Za-z0-9_./~-]+\.[A-Za-z0-9]+:\d+(?:-\d+)?", text)))
    l2_findings = l2.get("findings", [])
    confirmed: list[dict] = []
    rejected: list[dict] = []
    new: list[dict] = []
    for f in l2_findings:
        if f.get("severity") in {"critical", "high"}:
            confirmed.append(f)
        else:
            rejected.append(f)
    if incomplete:
        new.append({
            "severity": "high",
            "category": "tooling",
            "title": "L3 review did not reach a terminal verdict",
            "evidence": evidence[:3] or ["l3-review.md:1"],
            "impact": "L3 evidence is incomplete",
            "recommendation": "rerun L3 with all review inputs inside project_root or inline",
            "confidence": 0.95,
        })
    if errors:
        new.append({
            "severity": "high",
            "category": "tooling",
            "title": f"L3 tool errors: {errors[0][:120]}",
            "evidence": evidence[:3] or ["l3-review.md:1"],
            "impact": "L3 could not read all review inputs",
            "recommendation": "ensure review artifacts are inside project_root",
            "confidence": 0.9,
        })
    return confirmed, rejected, new


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--stdout", required=True)
    ap.add_argument("--verdict", choices=VERDICTS, default=None)
    args = ap.parse_args()

    run_dir = REVIEW_ROOT / args.run_id
    stdout_path = Path(args.stdout)
    if not run_dir.exists() or not stdout_path.exists():
        print("missing run dir or pi stdout", file=sys.stderr)
        return 2

    text, terminal_stop, errors = parse_stream(stdout_path)
    l2 = load_l2(run_dir)
    parsed = args.verdict or explicit_verdict(text)
    incomplete = not terminal_stop or not parsed
    final = parsed if not incomplete else "BLOCKED"
    confirmed, rejected, new = findings_from_text(text, l2, incomplete, errors)

    report = {
        "verdict": final,
        "reviewed_l2_findings": l2.get("findings", []),
        "confirmed_findings": confirmed,
        "rejected_findings": rejected,
        "new_findings": new,
        "critical_invariants": [
            "implementation matches acceptance criteria",
            "L1 deterministic checks pass",
            "read-only L3 does not modify project files",
        ],
        "final_recommendation": final,
        "tests_missing": l2.get("tests_missing", []),
        "escalation_required": incomplete or final in {"CHANGES_REQUIRED", "BLOCKED"},
        "escalation_reasons": (["incomplete L3 output"] if incomplete else []) + (["non-pass verdict"] if final in {"CHANGES_REQUIRED", "BLOCKED"} else []),
        "raw_text_path": "l3-review.md",
        "stream_complete": terminal_stop,
        "tool_errors": errors,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "l3-review.md").write_text((text or "No final reviewer text emitted.") + "\n", encoding="utf-8")
    (run_dir / "l3-review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "decision.md").write_text(f"# decision\n\n{final}\n\nL1 + L2 + Pi L3 completed.\n", encoding="utf-8")

    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "completed" if terminal_stop else "review_incomplete"
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest["l3_verdict"] = final
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    validation = subprocess.run([sys.executable, str(RG), "validate", "--kind", "l3", "--file", str(run_dir / "l3-review.json")])
    if validation.returncode != 0:
        return validation.returncode
    print(json.dumps({"run_id": args.run_id, "verdict": final, "complete": terminal_stop, "l3": str(run_dir / "l3-review.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
