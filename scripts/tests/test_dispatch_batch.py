#!/usr/bin/env python3
"""Tests for scripts/dispatch_batch.py (queen-mode programmatic dispatch)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import ARTIFACT_ROOT

sys.path.insert(0, "/Users/henry/scratch/hermes-fleet/scripts")

import dispatch_batch


def _fake_script(path: Path, stdout: str = "FAKE_OK", exit_code: int = 0) -> Path:
    """Write a tiny shell script that prints stdout and exits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho '{stdout}'\nexit {exit_code}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_dispatch_batch_empty():
    assert dispatch_batch.dispatch_batch([]) == []


def test_dispatch_batch_shell_succeeds(tmp_path):
    fake = _fake_script(tmp_path / "fake.sh", stdout="shell_hello", exit_code=0)
    tasks = [{
        "id": "t1",
        "engine": "shell",
        "argv": [str(fake)],
    }]
    results = dispatch_batch.dispatch_batch(tasks)
    assert len(results) == 1
    r = results[0]
    assert r["id"] == "t1"
    assert r["engine"] == "shell"
    assert r["exit"] == 0
    assert "shell_hello" in r["stdout_tail"]


def test_dispatch_batch_shell_failure(tmp_path):
    fake = _fake_script(tmp_path / "fake.sh", stdout="", exit_code=1)
    tasks = [{
        "id": "t1",
        "engine": "shell",
        "argv": [str(fake)],
    }]
    results = dispatch_batch.dispatch_batch(tasks)
    assert results[0]["exit"] == 1


def test_dispatch_batch_strips_prompt_to_argv():
    """Verify _build_cmd for shell returns task['argv'] verbatim."""
    cmd = dispatch_batch._build_cmd("shell", "ignored-prompt", {"argv": ["echo", "hi"]})
    assert cmd == ["echo", "hi"]


def test_dispatch_batch_dsh_includes_prompt():
    """Verify _build_cmd for dsh includes prompt as 3rd arg."""
    cmd = dispatch_batch._build_cmd("dsh", "my-task-text", {})
    assert cmd[2] == "my-task-text"
    assert "hermes_dsh_bridge.py" in cmd[1]


def test_dispatch_batch_hermes_includes_prompt():
    """Verify _build_cmd for hermes includes prompt as 3rd arg."""
    cmd = dispatch_batch._build_cmd("hermes", "my-hermes-task", {})
    assert cmd[2] == "my-hermes-task"
    assert "hermes_subagent.py" in cmd[1]


def test_dispatch_batch_dsh_passes_provider_model():
    cmd = dispatch_batch._build_cmd("dsh", "p", {"provider": "minimax", "model": "MiniMax-M3"})
    assert "--provider" in cmd and "minimax" in cmd
    assert "--model" in cmd and "MiniMax-M3" in cmd


def test_dispatch_batch_hermes_passes_provider_model():
    cmd = dispatch_batch._build_cmd("hermes", "p", {"provider": "deepseek-official"})
    assert "--provider" in cmd and "deepseek-official" in cmd


def test_dispatch_batch_unknown_engine_raises():
    try:
        dispatch_batch._build_cmd("codex", "p", {})
    except ValueError as exc:
        assert "codex" in str(exc)
        return
    raise AssertionError("expected ValueError for unknown engine")


def test_dispatch_batch_parallel_runs(tmp_path):
    """Verify dispatch_batch runs N tasks in parallel."""
    base = tmp_path / "fake-bin"
    base.mkdir(exist_ok=True)
    fakes = [_fake_script(base / f"fake_{i}.sh", stdout=f"task_{i}", exit_code=0)
             for i in range(3)]
    tasks = [{"id": f"t{i}", "engine": "shell", "argv": [str(fakes[i])]}
             for i in range(3)]
    results = dispatch_batch.dispatch_batch(tasks)
    assert len(results) == 3
    for i, r in enumerate(results):
        assert r["exit"] == 0
        assert f"task_{i}" in r["stdout_tail"]


if __name__ == "__main__":
    import tempfile
    for name in list(globals()):
        if name.startswith("test_"):
            fn = globals()[name]
            try:
                if "tmp_path" in fn.__code__.co_varnames:
                    with tempfile.TemporaryDirectory() as td:
                        fn(Path(td))
                else:
                    fn()
                print(f"PASS {name}")
            except Exception as exc:
                print(f"FAIL {name}: {exc}")
                sys.exit(1)
    print("ALL PASS")