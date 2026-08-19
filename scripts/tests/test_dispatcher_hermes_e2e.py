#!/usr/bin/env python3
"""End-to-end test for hermes engine via execute_plan + fake subagent."""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

from conftest import ARTIFACT_ROOT
from dispatcher import validate_plan, execute_plan


PYTHON = "/opt/homebrew/bin/python3.14"


def _write_fake_subagent(fake_dir):
    sub = fake_dir / "scripts"
    sub.mkdir(parents=True, exist_ok=True)
    script = sub / "hermes_subagent.py"
    lines = [
        "#!/usr/bin/env python3",
        "import argparse, sys",
        "from pathlib import Path",
        "ap = argparse.ArgumentParser()",
        "ap.add_argument(\"task\")",
        "ap.add_argument(\"--provider\", default=\"deepseek-official\")",
        "ap.add_argument(\"--model\", default=None)",
        "ap.add_argument(\"--system\", default=None)",
        "ap.add_argument(\"--timeout\", type=int, default=60)",
        "ap.add_argument(\"--tools\", action=\"store_true\")",
        "ap.add_argument(\"--json\", action=\"store_true\")",
        "ap.add_argument(\"--out\", default=None)",
        "args = ap.parse_args()",
        "out = \"P3_E2E_OK\"",
        "if args.out:",
        "    Path(args.out).parent.mkdir(parents=True, exist_ok=True)",
        "    Path(args.out).write_text(out, encoding='utf-8')",
        "print(\"[Hermes] tokens=prompt:1 completion:1\", file=sys.stderr)",
        "print(out)",
        "sys.exit(0)",
        "",
    ]
    script.write_text("\n".join(lines), encoding="utf-8")
    script.chmod(0o755)
    return script


def _plan(task_id, run_id, engine, goal, output_file=None):
    return {
        "version": "1",
        "run_id": run_id,
        "project_root": "/tmp",
        "risk_level": "LOW",
        "sandbox": "fs:loose",
        "tasks": [{
            "id": task_id,
            "engine": engine,
            "role": "general",
            "execution_mode": "write",
            "goal": goal,
            "output_file": output_file,
            "extra_args": [],
        }],
    }


def test_hermes_e2e_explicit_engine_writes_output_file(tmp_path, monkeypatch):
    fake_root = tmp_path / "fake-fleet"
    _write_fake_subagent(fake_root)
    monkeypatch.setenv("HERMES_FLEET_ROOT", str(fake_root))
    artifact_root = ARTIFACT_ROOT
    artifact_root.mkdir(parents=True, exist_ok=True)
    plan = _plan(
        task_id="t1",
        run_id="e2e-explicit-" + uuid.uuid4().hex[:8],
        engine="hermes",
        goal="Reply P3_E2E_OK",
        output_file="out/e2e.txt",
    )
    norm, _ = validate_plan(plan, artifact_root)
    status = execute_plan(norm, max_concurrency=1)
    assert status["run_status"] == "success"
    summary = status["task_summaries"][0]
    assert summary["status"] == "done"
    assert summary["exit"] == 0
    out_file = Path("/tmp/out/e2e.txt")
    assert out_file.exists(), f"output file not written: {out_file}"
    assert out_file.read_text() == "P3_E2E_OK"


def test_hermes_e2e_auto_routes_pure_dialogue(tmp_path, monkeypatch):
    fake_root = tmp_path / "fake-fleet"
    _write_fake_subagent(fake_root)
    monkeypatch.setenv("HERMES_FLEET_ROOT", str(fake_root))
    artifact_root = Path.home() / ".hermes" / "artifacts" / "queen"
    artifact_root.mkdir(parents=True, exist_ok=True)
    plan = _plan(
        task_id="t1",
        run_id="e2e-auto-" + uuid.uuid4().hex[:8],
        engine="auto",
        goal="hi, what model are you?",
    )
    norm, _ = validate_plan(plan, artifact_root)
    assert norm["tasks"][0]["engine"] == "hermes"
    status = execute_plan(norm, max_concurrency=1)
    assert status["run_status"] == "success"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
