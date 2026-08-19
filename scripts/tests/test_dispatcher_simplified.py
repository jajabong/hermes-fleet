#!/usr/bin/env python3
"""Tests for the simplified dispatcher (shell + dsh only)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, "/Users/henry/scratch/hermes-fleet/scripts")

from dispatcher import validate_plan, build_command, execute_plan, ENGINES, ON_FAILURE


def test_engines_are_shell_and_dsh_only():
    assert ENGINES == {"shell", "dsh", "hermes", "auto"}, f"unexpected engines: {ENGINES}"


def test_validate_rejects_unknown_engines():
    plan = {
        "version": "1",
        "run_id": "x",
        "project_root": "/tmp",
        "risk_level": "LOW",
        "sandbox": "fs:loose",
        "tasks": [
            {"id": "t1", "engine": "codex", "role": "general", "execution_mode": "write", "goal": "hi"},
            {"id": "t2", "engine": "unknown", "role": "general", "execution_mode": "write", "goal": "hi"},
        ],
    }
    try:
        validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    except ValueError as exc:
        msg = str(exc)
        assert "engine must be one of" in msg
        assert "'dsh'" in msg
        assert "'shell'" in msg
        assert "codex" not in msg
        assert "unknown" not in msg
        return
    raise AssertionError("expected ValueError for unknown engines")


def test_build_command_shell():
    task = {
        "id": "t1", "engine": "shell", "role": "shell", "execution_mode": "write",
        "goal": "", "context": "", "argv": ["echo", "hello"], "extra_args": [],
    }
    cmd = build_command(task, Path("/tmp"), Path("/tmp/run/t1"))
    assert cmd == ["echo", "hello"]


def test_build_command_dsh_with_routing():
    task = {
        "id": "t1", "engine": "dsh", "role": "general", "execution_mode": "read_only",
        "goal": "hi", "context": "", "preset": "excel", "provider": "minimax", "model": "MiniMax-M3", "extra_args": [],
    }
    cmd = build_command(task, Path("/tmp"), Path("/tmp/run/t1"))
    assert cmd[0].endswith("python3.14")
    assert cmd[1].endswith("hermes_dsh_bridge.py")
    assert cmd[2] == "hi"
    assert "--preset" in cmd
    assert "excel" in cmd
    assert "--provider" in cmd
    assert "minimax" in cmd
    assert "--model" in cmd
    assert "MiniMax-M3" in cmd


def test_dry_run_outputs_plan():
    with tempfile.TemporaryDirectory() as td:
        artifact_root = Path.home() / ".hermes" / "artifacts" / f"queen-test-{uuid.uuid4().hex[:8]}"
        plan = {
            "version": "1",
            "run_id": "dry-" + uuid.uuid4().hex[:8],
            "project_root": "/tmp",
            "risk_level": "LOW",
            "sandbox": "fs:loose",
            "tasks": [
            {"id": "a", "engine": "shell", "role": "shell", "execution_mode": "write",
             "goal": "", "context": "", "argv": ["echo", "a"], "extra_args": []},
                {"id": "b", "engine": "dsh", "role": "general", "execution_mode": "read_only",
                 "goal": "hi", "extra_args": []},
            ],
        }
        norm, by_id = validate_plan(plan, artifact_root)
        status = execute_plan(norm, max_concurrency=2, dry_run=True)
        assert status["run_status"] == "dry_run"
        assert len(status["task_summaries"]) == 2
        assert status["task_summaries"][0]["id"] == "a"
        assert status["task_summaries"][1]["id"] == "b"


def test_dag_block_on_failure():
    with tempfile.TemporaryDirectory() as td:
        artifact_root = Path.home() / ".hermes" / "artifacts" / f"queen-test-{uuid.uuid4().hex[:8]}"
        plan = {
            "version": "1",
            "run_id": "block-" + uuid.uuid4().hex[:8],
            "project_root": "/tmp",
            "risk_level": "LOW",
            "sandbox": "fs:loose",
            "tasks": [
                {"id": "fail", "engine": "shell", "role": "shell", "execution_mode": "write",
                 "goal": "", "context": "", "argv": ["false"], "verification_command": "false", "on_failure": "block", "extra_args": []},
                {"id": "child", "engine": "shell", "role": "shell", "execution_mode": "write",
                 "goal": "", "context": "", "depends_on": ["fail"], "argv": ["echo", "x"], "extra_args": []},
            ],
        }
        norm, _ = validate_plan(plan, artifact_root)
        status = execute_plan(norm, max_concurrency=2)
        summaries = {s["id"]: s for s in status["task_summaries"]}
        assert summaries["fail"]["status"] == "failed"
        assert summaries["child"]["status"] == "blocked"
        assert status["run_status"] == "failed"


def test_on_failure_continue_allows_sibling():
    with tempfile.TemporaryDirectory() as td:
        artifact_root = Path.home() / ".hermes" / "artifacts" / f"queen-test-{uuid.uuid4().hex[:8]}"
        plan = {
            "version": "1",
            "run_id": "continue-" + uuid.uuid4().hex[:8],
            "project_root": "/tmp",
            "risk_level": "LOW",
            "sandbox": "fs:loose",
            "tasks": [
                {"id": "fail", "engine": "shell", "role": "shell", "execution_mode": "write",
                 "goal": "", "context": "", "argv": ["false"], "on_failure": "continue", "extra_args": []},
                {"id": "ok", "engine": "shell", "role": "shell", "execution_mode": "write",
                 "goal": "", "context": "", "argv": ["echo", "ok"], "extra_args": []},
            ],
        }
        norm, _ = validate_plan(plan, artifact_root)
        status = execute_plan(norm, max_concurrency=2)
        summaries = {s["id"]: s for s in status["task_summaries"]}
        assert summaries["fail"]["status"] == "failed"
        assert summaries["ok"]["status"] == "done"


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
