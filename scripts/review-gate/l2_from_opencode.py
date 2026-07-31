#!/usr/bin/env python3
"""Normalize OpenCode JSONL output into a review-gate L2 report."""
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


def parse_stream(path: Path) -> tuple[str, bool, list[str]]:
    texts: list[str] = []
    errors: list[str] = []
    terminal_stop = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        typ = obj.get("type")
        part = obj.get("part") or {}
        if typ == "text" and part.get("type") == "text" and part.get("text"):
            texts.append(part["text"].strip())
        if typ == "tool_use":
            state = part.get("state") or {}
            if state.get("status") == "error":
                errors.append(str(state.get("error") or "tool error"))
        if typ == "step_finish" and part.get("reason") == "stop":
            terminal_stop = True
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


def findings_from_text(text: str, incomplete: bool, errors: list[str]) -> list[dict]:
    evidence = list(dict.fromkeys(re.findall(r"[A-Za-z0-9_./~-]+\.[A-Za-z0-9]+:\d+(?:-\d+)?", text)))
    findings: list[dict] = []
    severity_patterns = [
        ("high", r"(?im)^\s*(?:[-*]|\d+[.)])?\s*\**(?:critical|high)\**\s*[-—:]\s*(.+)$"),
        ("medium", r"(?im)^\s*(?:[-*]|\d+[.)])?\s*\**medium\**\s*[-—:]\s*(.+)$"),
        ("low", r"(?im)^\s*(?:[-*]|\d+[.)])?\s*\**low\**\s*[-—:]\s*(.+)$"),
    ]
    for severity, pattern in severity_patterns:
        for title in re.findall(pattern, text):
            findings.append({
                "severity": severity,
                "category": "correctness",
                "title": re.sub(r"\s+", " ", title).strip()[:240],
                "evidence": evidence[:3] or ["l2-review.md:1"],
                "impact": "see reviewer narrative",
                "recommendation": "resolve or explicitly accept before delivery",
                "confidence": 0.75,
            })
    if incomplete:
        findings.append({
            "severity": "high",
            "category": "testing",
            "title": "L2 review did not reach a terminal verdict",
            "evidence": ["l2-review.md:1"],
            "impact": "independent review evidence is incomplete",
            "recommendation": "rerun L2 with all review inputs inside project_root or inline in context",
            "confidence": 0.95,
        })
    elif not findings:
        findings.append({
            "severity": "info",
            "category": "correctness",
            "title": "No blocking finding extracted",
            "evidence": evidence[:3] or ["l2-review.md:1"],
            "impact": "none identified",
            "recommendation": "retain raw reviewer narrative",
            "confidence": 0.7,
        })
    if errors:
        findings[0]["tool_errors"] = errors[:5]
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--stdout", required=True)
    ap.add_argument("--verdict", choices=VERDICTS, default=None)
    ap.add_argument("--l1-commands", default="")
    args = ap.parse_args()

    run_dir = REVIEW_ROOT / args.run_id
    stdout_path = Path(args.stdout)
    if not run_dir.exists() or not stdout_path.exists():
        print("missing review run dir or opencode stdout", file=sys.stderr)
        return 2

    text, terminal_stop, errors = parse_stream(stdout_path)
    parsed = args.verdict or explicit_verdict(text)
    incomplete = not terminal_stop or not parsed
    verdict = parsed if not incomplete else "BLOCKED"
    findings = findings_from_text(text, incomplete, errors)
    l1_commands = [c for c in args.l1_commands.split("||") if c]
    high = any(f["severity"] in {"critical", "high"} for f in findings)

    report = {
        "verdict": verdict,
        "findings": findings,
        "commands_reviewed": l1_commands,
        "tests_missing": [],
        "escalation_required": incomplete or high or verdict in {"CHANGES_REQUIRED", "BLOCKED"},
        "escalation_reasons": (["incomplete L2 output"] if incomplete else []) + (["high finding or non-pass verdict"] if high or verdict in {"CHANGES_REQUIRED", "BLOCKED"} else []),
        "raw_text_path": "l2-review.md",
        "stream_complete": terminal_stop,
        "tool_errors": errors,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "l2-review.md").write_text((text or "No final reviewer text emitted.") + "\n", encoding="utf-8")
    (run_dir / "l2-review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "decision.md").write_text(f"# decision\n\n{verdict}\n\nSee l2-review.md and l1.json.\n", encoding="utf-8")

    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "completed" if terminal_stop else "review_incomplete"
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest["l2_verdict"] = verdict
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    validation = subprocess.run([sys.executable, str(RG), "validate", "--kind", "l2", "--file", str(run_dir / "l2-review.json")])
    if validation.returncode != 0:
        return validation.returncode
    print(json.dumps({"run_id": args.run_id, "verdict": verdict, "complete": terminal_stop, "l2": str(run_dir / "l2-review.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
