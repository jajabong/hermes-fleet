#!/usr/bin/env python3
"""Tests for the hermes engine routing in dispatcher."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, "/Users/henry/scratch/hermes-fleet/scripts")

from dispatcher import validate_plan, build_command


def _plan(tasks):
    return {
        "version": "1",
        "run_id": "hermes-" + uuid.uuid4().hex[:8],
        "project_root": "/tmp",
        "risk_level": "LOW",
        "sandbox": "fs:loose",
        "tasks": tasks,
    }


def test_validate_accepts_hermes_engine():
    plan = _plan([
        {"id": "t1", "engine": "hermes", "role": "general", "execution_mode": "write",
         "goal": "hi", "extra_args": []},
    ])
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    assert norm["tasks"][0]["engine"] == "hermes"


def test_build_command_hermes_plain():
    plan = _plan([
        {"id": "t1", "engine": "hermes", "role": "general", "execution_mode": "write",
         "goal": "reply ok", "extra_args": []},
    ])
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    cmd = build_command(norm["tasks"][0], Path("/tmp"), Path("/tmp/run/t1"))
    assert cmd[0] == "/opt/homebrew/bin/python3.14"
    assert cmd[1].endswith("scripts/hermes_subagent.py")
    assert "reply ok" in cmd[2]
    assert "--tools" not in cmd


def test_build_command_hermes_provider_model_tools():
    plan = _plan([
        {"id": "t1", "engine": "hermes", "role": "general", "execution_mode": "write",
         "goal": "analyze", "provider": "deepseek-official", "model": "deepseek-v4-flash",
         "use_tools": True, "extra_args": []},
    ])
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    cmd = build_command(norm["tasks"][0], Path("/tmp"), Path("/tmp/run/t1"))
    assert "--provider" in cmd and "deepseek-official" in cmd
    assert "--model" in cmd and "deepseek-v4-flash" in cmd
    assert "--tools" in cmd


def test_build_command_hermes_respects_extra_args():
    plan = _plan([
        {"id": "t1", "engine": "hermes", "role": "general", "execution_mode": "write",
         "goal": "hi", "extra_args": ["--timeout", "120"]},
    ])
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    cmd = build_command(norm["tasks"][0], Path("/tmp"), Path("/tmp/run/t1"))
    assert cmd[-2:] == ["--timeout", "120"]


def test_auto_without_argv_still_routes_to_dsh():
    plan = _plan([
        {"id": "t1", "engine": "auto", "role": "general", "execution_mode": "read_only",
         "goal": "ping", "extra_args": []},
    ])
    norm, _ = validate_plan(plan, Path.home() / ".hermes" / "artifacts" / "queen")
    assert norm["tasks"][0]["engine"] == "dsh"


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