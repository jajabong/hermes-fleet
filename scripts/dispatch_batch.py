#!/usr/bin/env python3
"""Queen-mode programmatic dispatch to codex/pi/opencode.

Returns only stdout tail (≤3KB per task). Designed for hermes execute_code:
the script's stdout enters the parent as a tool result, not the conversation.
"""
import concurrent.futures as cf
import json
import subprocess
import sys

STDOUT_TAIL = 3000
STDERR_TAIL = 1000
TIMEOUT_S = 600


def _build_cmd(engine: str, prompt: str, task: dict) -> list:
    if engine == "codex":
        return [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "-C",
            task.get("workdir", "."),
            prompt,
        ]
    if engine == "pi":
        return [
            "pi-anchor",
            "-p",
            "--provider",
            "anchor",
            "--model",
            "anchor",
            "--mode",
            "json",
            "--no-session",
            prompt,
        ]
    if engine == "claude":
        # v2.3: parallel with codex read-only profile; Queen-direct shell equivalent.
        return [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--allowedTools",
            "Read,Grep,Glob,LS",
            prompt,
        ]
    if engine == "opencode":
        # v28.9.2: 默认 model 与 SOUL §舰队表 L143 对齐; SOUL 列 3 选 1, 本文件取限流最强 (`kilocode/kilo-auto/free`) 为兜底.
        # 备选: `opencode/laguna-s-2.1-free` / `opencode/nemotron-3-ultra-free` (plan.task.model 显式传覆盖).
        model = task.get("model", "kilocode/kilo-auto/free")
        return ["opencode", "run", "--model", model, "--share", prompt]
    raise ValueError(f"unknown engine: {engine}")


def _run(task: dict) -> dict:
    engine = task["engine"]
    goal = task["goal"]
    ctx = task.get("context", "")
    workdir = task.get("workdir", ".")
    prompt = f"{goal}\n\n{ctx}" if ctx else goal
    cmd = _build_cmd(engine, prompt, task)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            cwd=workdir,
        )
        return {
            "id": task.get("id"),
            "engine": engine,
            "exit": proc.returncode,
            "stdout_tail": proc.stdout[-STDOUT_TAIL:],
            "stderr_tail": proc.stderr[-STDERR_TAIL:],
        }
    except subprocess.TimeoutExpired:
        return {
            "id": task.get("id"),
            "engine": engine,
            "exit": 124,
            "error": "timeout",
            "timeout_seconds": TIMEOUT_S,
        }
    except Exception as e:
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
