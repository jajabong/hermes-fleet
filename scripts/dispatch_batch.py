#!/usr/bin/env python3
"""Queen-mode programmatic dispatch to shell/dsh/hermes.

Returns only stdout tail (<=3KB per task). Designed for hermes execute_code:
the script's stdout enters the parent as a tool result, not the conversation.

Mirrors scripts/dispatcher.py (the DAG orchestrator) for ad-hoc single-task
dispatch -- use this when you don't need DAG scheduling or artifact persistence.

Public API:
  dispatch_batch(tasks) -> list[dict]
    tasks: [{"id", "engine", "prompt", "argv?", "preset?", "provider?",
             "model?", "extra_args?", "kanban_task_id?", "workdir?"}]
    returns: [{"id", "engine", "exit", "stdout_tail", "stderr_tail"}]
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys
from pathlib import Path

STDOUT_TAIL = 3000
STDERR_TAIL = 1000
TIMEOUT_S = 600


def _build_cmd(engine: str, prompt: str, task: dict) -> list:
    if engine == "shell":
        return list(task.get("argv", []))
    if engine == "dsh":
        bridge = Path.home() / "hermes-fleet" / "dsh-bridge" / "hermes_dsh_bridge.py"
        cmd = [os.environ.get("HERMES_PYTHON", "/opt/homebrew/bin/python3.14"), str(bridge), prompt]
        for flag, key in (("--preset", "preset"), ("--provider", "provider"), ("--model", "model")):
            if task.get(key):
                cmd.extend([flag, str(task[key])])
        return cmd
    if engine == "hermes":
        subagent = Path.home() / "hermes-fleet" / "scripts" / "hermes_subagent.py"
        cmd = [os.environ.get("HERMES_PYTHON", "/opt/homebrew/bin/python3.14"), str(subagent), prompt]
        for flag, key in (("--provider", "provider"), ("--model", "model")):
            if task.get(key):
                cmd.extend([flag, str(task[key])])
        return cmd
    raise ValueError(f"engine {engine!r} was removed in v29.12; use 'shell' or 'dsh'")


def _kanban_claim(task_id: str, ttl: int = 600) -> None:
    """Best-effort Kanban claim (v29.8). Silent on failure.

    Uses 'hermes kanban claim <id> --ttl <ttl>'. If the binary is missing,
    the network is down, or the task_id was never created, we just log to
    stderr and move on -- Kanban is observability, not a hard dependency.
    """
    try:
        subprocess.run(
            ["hermes", "kanban", "claim", task_id, "--ttl", str(ttl)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        sys.stderr.write(f"kanban claim {task_id} failed: {e!r}\n")


def _kanban_complete(task_id: str, summary: str) -> None:
    """Best-effort Kanban complete (v29.8). Silent on failure.

    Uses 'hermes kanban complete <id> --summary <text>'. See _kanban_claim
    for failure semantics -- Kanban is observability, not a hard dependency.
    """
    try:
        subprocess.run(
            ["hermes", "kanban", "complete", task_id, "--summary", summary[:500]],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        sys.stderr.write(f"kanban complete {task_id} failed: {e!r}\n")


def _run(task: dict) -> dict:
    engine = task["engine"]
    env = dict(os.environ)
    goal = task.get("goal", "")
    ctx = task.get("context", "")
    workdir = task.get("workdir", ".")
    prompt = f"{goal}\n\n{ctx}" if ctx and goal else goal
    cmd = _build_cmd(engine, prompt, task)
    # v29.8 Phase 1: auto Kanban claim (if task has kanban_task_id or 'id').
    # Kanban is observability, not a hard dependency -- failures are silent.
    kanban_task_id = task.get("kanban_task_id") or task.get("id")
    if kanban_task_id:
        _kanban_claim(str(kanban_task_id))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            cwd=workdir,
            env=env,
        )
        result = {
            "id": task.get("id"),
            "engine": engine,
            "exit": proc.returncode,
            "stdout_tail": proc.stdout[-STDOUT_TAIL:],
            "stderr_tail": proc.stderr[-STDERR_TAIL:],
        }
        # v29.8 Phase 1: auto Kanban complete (best-effort, silent on failure).
        if kanban_task_id:
            summary = f"engine={engine} exit={proc.returncode}"
            _kanban_complete(str(kanban_task_id), summary)
        return result
    except subprocess.TimeoutExpired:
        if kanban_task_id:
            _kanban_complete(str(kanban_task_id), f"engine={engine} exit=124 timeout")
        return {
            "id": task.get("id"),
            "engine": engine,
            "exit": 124,
            "error": "timeout",
            "timeout_seconds": TIMEOUT_S,
        }
    except Exception as e:
        if kanban_task_id:
            _kanban_complete(str(kanban_task_id), f"engine={engine} exit=1 {e!r}")
        return {
            "id": task.get("id"),
            "engine": engine,
            "exit": 1,
            "error": repr(e),
        }


def dispatch_batch(tasks):
    if not tasks:
        return []
    max_workers = min(len(tasks), 3)
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(_run, tasks))


if __name__ == "__main__":
    tasks = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []
    print(json.dumps(dispatch_batch(tasks), ensure_ascii=False, indent=2))
