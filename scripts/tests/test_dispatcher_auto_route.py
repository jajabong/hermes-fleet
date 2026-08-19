#!/usr/bin/env python3
"""Tests for auto-route engine resolution."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/Users/henry/scratch/hermes-fleet/scripts")

from dispatcher import validate_plan, build_command, execute_plan
from conftest import make_plan


def test_auto_with_argv_routes_to_shell():
    plan = make_plan([
        {"id": "t1", "engine": "auto", "role": "shell", "execution_mode": "write",
         "goal": "", "argv": ["echo", "hi"], "extra_args": []},
    ], "auto")
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    assert norm["tasks"][0]["engine"] == "shell"
    cmd = build_command(norm["tasks"][0], Path("/tmp"), Path("/tmp/run/t1"))
    assert cmd == ["echo", "hi"]


def test_auto_without_argv_routes_to_dsh():
    plan = make_plan([
        {"id": "t1", "engine": "auto", "role": "general", "execution_mode": "read_only",
         "goal": "analyze xlsx data", "extra_args": []},
    ], "auto")
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    assert norm["tasks"][0]["engine"] == "dsh"
    cmd = build_command(norm["tasks"][0], Path("/tmp"), Path("/tmp/run/t1"))
    assert "hermes_dsh_bridge.py" in cmd[1]


def test_auto_without_argv_pure_dialogue_routes_to_hermes():
    plan = make_plan([
        {"id": "t1", "engine": "auto", "role": "general", "execution_mode": "read_only",
         "goal": "hi, what model are you?", "extra_args": []},
    ], "auto")
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    assert norm["tasks"][0]["engine"] == "hermes"
    cmd = build_command(norm["tasks"][0], Path("/tmp"), Path("/tmp/run/t1"))
    assert "hermes_subagent.py" in cmd[1]


def test_missing_engine_with_argv_routes_to_shell():
    plan = make_plan([
        {"id": "t1", "role": "shell", "execution_mode": "write",
         "goal": "", "argv": ["true"], "extra_args": []},
    ], "auto")
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    assert norm["tasks"][0]["engine"] == "shell"


def test_missing_engine_without_argv_routes_to_dsh():
    plan = make_plan([
        {"id": "t1", "role": "general", "execution_mode": "read_only",
         "goal": "analyze xlsx data", "extra_args": []},
    ], "auto")
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    assert norm["tasks"][0]["engine"] == "dsh"


def test_explicit_dsh_stays_dsh():
    plan = make_plan([
        {"id": "t1", "engine": "dsh", "role": "general", "execution_mode": "read_only",
         "goal": "hi", "extra_args": []},
    ], "auto")
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    assert norm["tasks"][0]["engine"] == "dsh"


def test_explicit_shell_stays_shell():
    plan = make_plan([
        {"id": "t1", "engine": "shell", "role": "shell", "execution_mode": "write",
         "goal": "", "argv": ["true"], "extra_args": []},
    ], "auto")
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    assert norm["tasks"][0]["engine"] == "shell"


def test_auto_dag_runs_correctly():
    try:
        import deepseek_harness  # noqa: F401
    except ImportError:
        print("SKIP test_auto_dag_runs_correctly (no deepseek_harness)")
        return
    plan = make_plan([
        {"id": "a", "engine": "auto", "role": "shell", "execution_mode": "write",
         "goal": "", "argv": ["echo", "a"], "extra_args": []},
        {"id": "b", "engine": "auto", "role": "general", "execution_mode": "read_only",
         "goal": "analyze xlsx report", "depends_on": ["a"], "extra_args": []},
    ], "auto")
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    assert norm["tasks"][0]["engine"] == "shell"
    assert norm["tasks"][1]["engine"] == "dsh"
    status = execute_plan(norm, max_concurrency=2)
    assert status["run_status"] == "success"
    summaries = {s["id"]: s for s in status["task_summaries"]}
    assert summaries["a"]["status"] == "done"
    assert summaries["b"]["status"] == "done"


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
