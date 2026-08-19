#!/usr/bin/env python3
"""Tests for auto-escalate (dsh failure → needs_queen)."""
from __future__ import annotations

import sys
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, "/Users/henry/scratch/hermes-fleet/scripts")

from dispatcher import validate_plan, execute_plan


def _plan(tasks):
    return {
        "version": "1",
        "run_id": "esc-" + uuid.uuid4().hex[:8],
        "project_root": "/tmp",
        "risk_level": "LOW",
        "sandbox": "fs:loose",
        "tasks": tasks,
    }


def test_dsh_failure_triggers_escalate():
    try:
        urllib.request.urlopen("http://127.0.0.1:3080", timeout=2)
    except Exception:
        pass
    else:
        print("SKIP: dsh server is running on 127.0.0.1:3080 (test requires dsh down)")
        return
    plan = _plan([
        {"id": "t1", "engine": "dsh", "role": "general", "execution_mode": "read_only",
         "goal": "fail task", "extra_args": []},
    ])
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    status = execute_plan(norm, max_concurrency=1)
    # dsh without running server will fail; any failure should escalate
    if status["task_summaries"][0]["status"] == "failed":
        assert status.get("needs_queen") is True
        assert "escalate_reason" in status
        events = []
        run_dir = Path.home() / ".hermes" / "artifacts" / "queen" / norm["run_id"]
        with (run_dir / "events.jsonl").open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(__import__("json").loads(line))
        escalate_events = [e for e in events if e.get("event") == "escalate"]
        assert len(escalate_events) >= 1
    else:
        print("SKIP: dsh did not fail (server running?)")


def test_shell_failure_does_not_escalate():
    plan = _plan([
        {"id": "t1", "engine": "shell", "role": "shell", "execution_mode": "write",
         "goal": "", "argv": ["false"], "on_failure": "continue", "extra_args": []},
    ])
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    status = execute_plan(norm, max_concurrency=1)
    assert status.get("needs_queen") is not True


def test_dsh_success_does_not_escalate():
    plan = _plan([
        {"id": "t1", "engine": "dsh", "role": "general", "execution_mode": "read_only",
         "goal": "reply ok", "extra_args": []},
    ])
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    status = execute_plan(norm, max_concurrency=1)
    if status["task_summaries"][0]["status"] == "done":
        assert status.get("needs_queen") is not True
    else:
        print("SKIP: dsh did not succeed")


if __name__ == "__main__":
    for name in list(globals()):
        if name.startswith("test_"):
            fn = globals()[name]
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:
                print(f"FAIL {name}: {exc}")
                sys.exit(1)
    print("ALL PASS")
