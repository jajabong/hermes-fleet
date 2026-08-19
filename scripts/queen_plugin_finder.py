#!/usr/bin/env python3
"""Queen plugin finder: when dispatcher escalates, search npm/GitHub for plugins.

Reads a failed run's status.json, extracts the escalate reason, searches npm
for candidate plugins, and prints an installation report. Does NOT auto-install;
Queen (human or LLM) decides whether to install.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ARTIFACT_ROOT = Path.home() / ".hermes" / "artifacts" / "queen"


def _latest_escalated_run() -> tuple[Path, dict] | None:
    """Find the most recent run with needs_queen=true."""
    if not ARTIFACT_ROOT.exists():
        return None
    candidates = []
    for d in sorted(ARTIFACT_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        status_path = d / "status.json"
        if not status_path.exists():
            continue
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("needs_queen"):
            candidates.append((d, data))
    return candidates[0] if candidates else None


def _search_npm(query: str, limit: int = 5) -> list[dict]:
    """Search npm for dsh plugins matching query."""
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    try:
        proc = subprocess.run(
            ["npm", "search", query, "--long", "--json"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if proc.returncode != 0:
            return []
        results = json.loads(proc.stdout) if proc.stdout.strip() else []
        hits = []
        for pkg in results:
            name = pkg.get("name", "")
            if "dsh" in name or "deepseek" in name.lower():
                hits.append({
                    "name": name,
                    "version": pkg.get("version", ""),
                    "description": pkg.get("description", "")[:120],
                    "npm": f"https://npm.im/{name}",
                })
            if len(hits) >= limit:
                break
        return hits
    except Exception:
        return []


def find_plugins_for_run(run_id: str | None = None) -> dict:
    """Find candidate plugins for an escalated run."""
    if run_id:
        run_dir = ARTIFACT_ROOT / run_id
        status_path = run_dir / "status.json"
        if not status_path.exists():
            return {"error": f"no status.json for run {run_id}"}
        data = json.loads(status_path.read_text(encoding="utf-8"))
    else:
        found = _latest_escalated_run()
        if not found:
            return {"error": "no escalated run found"}
        run_dir, data = found

    if not data.get("needs_queen"):
        return {"error": "run does not have needs_queen=true"}

    reason = data.get("escalate_reason", "unknown")
    task_id = reason.split(":")[0] if ":" in reason else reason

    # Search npm using task_id and finding fingerprint as query hints
    queries = [f"dsh-{task_id}", "deepseek-harness plugin"]
    seen = set()
    candidates = []
    for q in queries:
        hits = _search_npm(q, limit=5)
        for h in hits:
            key = h["name"]
            if key not in seen:
                seen.add(key)
                candidates.append(h)

    return {
        "run_id": data.get("run_id"),
        "task_id": task_id,
        "escalate_reason": reason,
        "candidates": candidates,
        "install_suggestion": "\n".join(
            f"dsh plugin install {c['name']} --profile web" for c in candidates
        ),
    }


def _install_plugin(name: str, profile: str = "web") -> dict:
    """Install a dsh plugin and return result."""
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    try:
        proc = subprocess.run(
            [os.environ.get("HERMES_NODE", "/opt/homebrew/opt/node@22/bin/node"),
             os.environ.get("HERMES_DSH", "/opt/homebrew/bin/dsh"),
             "plugin", "install", name, "--profile", profile],
            capture_output=True, text=True, timeout=120, env=env,
        )
        ok = proc.returncode == 0 or "Packages:" in proc.stdout
        return {
            "name": name,
            "ok": ok,
            "stdout": proc.stdout[-500:],
            "stderr": proc.stderr[-500:],
        }
    except Exception as exc:
        return {"name": name, "ok": False, "error": str(exc)}


def main() -> int:
    run_id = None
    auto_install = False
    dry_run = False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--auto-install":
            auto_install = True
        elif args[i] == "--dry-run":
            dry_run = True
        else:
            run_id = args[i]
        i += 1

    report = find_plugins_for_run(run_id)
    if not report.get("candidates"):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if dry_run:
        report["dry_run"] = True
        report["install_commands"] = [
            f"dsh plugin install {c['name']} --profile web" for c in report["candidates"]
        ]
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if auto_install:
        results = []
        for c in report["candidates"]:
            print(f"[finder] installing {c['name']} ...", file=sys.stderr)
            res = _install_plugin(c["name"])
            results.append(res)
            print(f"[finder] {'OK' if res['ok'] else 'FAIL'} {c['name']}", file=sys.stderr)
        report["install_results"] = results
        report["installed"] = [r["name"] for r in results if r.get("ok")]

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
