#!/usr/bin/env python3
"""Queen-mode programmatic dispatch to codex/pi/opencode.

Returns only stdout tail (≤3KB per task). Designed for hermes execute_code:
the script's stdout enters the parent as a tool result, not the conversation.
"""
import concurrent.futures as cf
import json
import os
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
        #
        # v29.6 fix: codex CLI 0.146.0 + macOS mihomo/Clash proxy at 127.0.0.1:7897
        # requires NO_PROXY=127.0.0.1,localhost to bypass proxy for loopback. Without
        # this, codex routes /v1/responses through mihomo which returns 502 Bad Gateway
        # (mihomo doesn't know how to proxy loopback). We pass NO_PROXY explicitly so
        # dispatch_batch.py works on any host regardless of system proxy config.
        # See commit v29.6 fleet-smoke-5of5 for live verification.
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


def _kanban_claim(task_id: str, ttl: int = 600) -> None:
    """Best-effort Kanban claim (v29.8). Silent on failure.

    Uses 'hermes kanban claim <id> --ttl <ttl>'. If the binary is missing,
    the network is down, or the task_id was never created, we just log to
    stderr and move on — Kanban is observability, not a hard dependency.
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
    for failure semantics — Kanban is observability, not a hard dependency.
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
    # v29.6: codex needs NO_PROXY=127.0.0.1,localhost to bypass macOS mihomo/Clash
    # proxy (127.0.0.1:7897). Without this, codex routes /v1/responses through
    # mihomo which returns 502 Bad Gateway. NO_PROXY is harmless on hosts
    # without a proxy.
    # pi-anchor requires ANCHOR_API_KEYS env var (the wrapper script uses set -u).
    # Set a dummy value if not already in env.
    env = dict(os.environ)
    env.setdefault("ANCHOR_API_KEYS", "dummy,test")
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    # shell task uses argv, not goal; default goal="" so _build_cmd gets empty prompt.
    goal = task.get("goal", "")
    ctx = task.get("context", "")
    workdir = task.get("workdir", ".")
    prompt = f"{goal}\n\n{ctx}" if ctx and goal else goal
    cmd = _build_cmd(engine, prompt, task)
    # v29.8 Phase 1: auto Kanban claim (if task has kanban_task_id or 'id').
    # Kanban is observability, not a hard dependency — failures are silent.
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
