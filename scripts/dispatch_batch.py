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
    if engine == "shell":
        return list(task.get("argv", []))
    if engine == "codex":
        # v29.4 (reverted): tried -m 'anchor high' to bypass anchor-auto router /v1/responses
        # streaming 502, but 'anchor high' is NOT a valid anchor model (gateway returns 400
        # 'Unknown model'). Reverted to default behavior — codex reads model from
        # config.toml ([model_providers.anchor] base_url=http://127.0.0.1:8088/v1).
        # The /v1/responses streaming 502 is an anchor gateway bug (server.py:73217
        # _v1_responses_stream_gen in-flight JSONResponse handling), NOT a hermes-fleet
        # issue. Fix lives in anchor repo, not hermes-fleet. dispatch_batch.py codex
        # branch stays minimal — let config.toml decide.
        codex_args = ["codex", "exec", "--skip-git-repo-check"]
        if "model" in task:
            codex_args.extend(["-m", task["model"]])
        codex_args.extend(["-C", task.get("workdir", "."), prompt])
        return codex_args
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
            # Order matters: `claude -p "PROMPT" --flags` — prompt must come RIGHT AFTER -p,
            # BEFORE --output-format / --allowedTools, otherwise claude CLI rejects with
            # "Input must be provided either through stdin or as a prompt argument".
            return [
                "claude",
                "-p",
                prompt,
                "--output-format",
                "json",
                "--allowedTools",
                "Read,Grep,Glob,LS",
            ]
    if engine == "opencode":
        # v28.9.2: 默认 model 与 SOUL §舰队表 L143 对齐; SOUL 列 3 选 1, 本文件取限流最强 (`kilocode/kilo-auto/free`) 为兜底.
        # 备选: `opencode/laguna-s-2.1-free` / `opencode/nemotron-3-ultra-free` (plan.task.model 显式传覆盖).
        model = task.get("model", "kilocode/kilo-auto/free")
        return ["opencode", "run", "--model", model, "--share", prompt]
    raise ValueError(f"unknown engine: {engine}")


def _run(task: dict) -> dict:
    engine = task["engine"]
    # shell task uses argv, not goal; default goal="" so _build_cmd gets empty prompt.
    goal = task.get("goal", "")
    ctx = task.get("context", "")
    workdir = task.get("workdir", ".")
    prompt = f"{goal}\n\n{ctx}" if ctx and goal else goal
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
