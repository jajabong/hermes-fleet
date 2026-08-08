#!/usr/bin/env python3
"""v29.8 Phase 2: auto_run.py -- high-frequency simple tasks, 0 LLM tokens.

Designed for cron / CI / direct invocation. LLM Queen does not participate.
Subcommands:
  insights   --days N [--source X]     hermes insights summary + write to /tmp/auto_run-insights-{ts}.log
  smoke                                5-engine fleet smoke (shell/codex/pi/opencode/claude) + Kanban claim/complete
  monitor                              hermes monitoring status summary
  kanban-list    [--status S]          hermes kanban list (default board)
  kanban-create  --title T [--body B]  create Kanban task, return task_id
  kanban-show    --task-id ID          show Kanban task details
  kanban-complete --task-id ID --summary S  mark Kanban task done

vs dispatch_batch.py: Queen dispatches + LLM reasoning.
vs auto_run.py: direct execution + 0 LLM (cron friendly).

Isolation: auto_run.py calls hermes CLI, does not depend on LLM, does not modify hermes-agent upstream.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime


def _log(msg: str) -> None:
    sys.stderr.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")
    sys.stderr.flush()


def _run_hermes(args: list[str], timeout: int = 60) -> dict:
    """Run `hermes <args>` and return exit/stdout/stderr dict (best-effort)."""
    try:
        proc = subprocess.run(
            ["hermes"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {"exit": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired:
        return {"exit": 124, "stdout": "", "stderr": "timeout"}
    except FileNotFoundError:
        return {"exit": 127, "stdout": "", "stderr": "hermes CLI not found in PATH"}
    except Exception as e:
        return {"exit": 1, "stdout": "", "stderr": repr(e)}


def _write_output(task: str, content: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = f"/tmp/auto_run-{task}-{ts}.log"
    try:
        with open(path, "w") as f:
            f.write(content)
    except Exception as e:
        _log(f"write_output failed: {e!r}")
        return ""
    return path


def _summarize_insights(stdout: str) -> dict:
    summary = {}
    m = re.search(r"Sessions?:\s*(\d+)", stdout)
    if m:
        summary["sessions"] = int(m.group(1))
    m = re.search(r"([\d,]+)\s*tokens", stdout, re.IGNORECASE)
    if m:
        summary["total_tokens"] = int(m.group(1).replace(",", ""))
    return summary


def cmd_insights(days: int = 1, source: str | None = None) -> dict:
    args = ["insights", "--days", str(days)]
    if source:
        args.extend(["--source", source])
    result = _run_hermes(args, timeout=120)
    summary = _summarize_insights(result["stdout"]) if result["exit"] == 0 else {}
    return {
        "task": "insights",
        "days": days,
        "source": source,
        "exit": result["exit"],
        "summary": summary,
        "output_path": _write_output("insights", result["stdout"]) if result["stdout"] else "",
    }


def cmd_monitor() -> dict:
    result = _run_hermes(["monitoring", "status"], timeout=30)
    return {
        "task": "monitor",
        "exit": result["exit"],
        "summary": _summarize_monitoring(result["stdout"]),
        "output_path": _write_output("monitor", result["stdout"]) if result["stdout"] else "",
    }


def _summarize_monitoring(stdout: str) -> dict:
    summary = {"raw_excerpt": stdout[:200]}
    if "enabled" in stdout.lower():
        summary["enabled"] = True
    return summary


def cmd_smoke() -> dict:
    """5-engine fleet smoke with Kanban audit trail."""
    # Create Kanban task for audit
    kanban = _run_hermes(["kanban", "create", f"auto-smoke-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                          "--body", "auto_run.py fleet smoke"], timeout=15)
    kanban_id = None
    m = re.search(r"t_[a-f0-9]+", kanban["stdout"])
    if m:
        kanban_id = m.group(0)
    if not kanban_id:
        return {"task": "smoke", "exit": 1, "error": f"kanban create failed: {kanban['stderr'][:200]}"}

    # Lazy import dispatch_batch
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dispatch_batch",
            os.path.join(os.path.dirname(__file__), "dispatch_batch.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        return {"task": "smoke", "exit": 1, "error": f"import dispatch_batch: {e!r}"}

    tasks = [
        {"id": "smoke-shell", "engine": "shell", "argv": ["echo", "V298P2_SHELL_OK"], "kanban_task_id": kanban_id},
        {"id": "smoke-codex", "engine": "codex", "goal": "Respond with exactly: V298P2_CODEX_OK",
         "workdir": "/Users/henry/anchor", "kanban_task_id": kanban_id},
        {"id": "smoke-pi", "engine": "pi", "goal": "Respond with exactly: V298P2_PI_OK",
         "workdir": "/Users/henry/anchor", "kanban_task_id": kanban_id},
        {"id": "smoke-opencode", "engine": "opencode", "goal": "Respond with exactly: V298P2_OPENCODE_OK",
         "model": "kilocode/kilo-auto/free", "kanban_task_id": kanban_id},
        {"id": "smoke-claude", "engine": "claude", "goal": "Respond with exactly: V298P2_CLAUDE_OK",
         "kanban_task_id": kanban_id},
    ]
    results = mod.dispatch_batch(tasks)
    return {
        "task": "smoke",
        "kanban_task_id": kanban_id,
        "results": [{"id": r["id"], "engine": r["engine"], "exit": r["exit"]} for r in results],
        "all_pass": all(r["exit"] == 0 for r in results),
        "output_path": _write_output("smoke", json.dumps(results, indent=2)),
    }


def cmd_kanban_list(status: str | None = None) -> dict:
    args = ["kanban", "list"]
    if status:
        args.extend(["--status", status])
    result = _run_hermes(args, timeout=30)
    return {"task": "kanban-list", "status": status, "exit": result["exit"],
            "summary": _summarize_kanban_list(result["stdout"])}


def _summarize_kanban_list(stdout: str) -> dict:
    lines = [l for l in stdout.split("\n") if l.strip().startswith("✓") or l.strip().startswith("•")]
    return {"task_count": len(lines)}


def cmd_kanban_create(title: str, body: str | None = None) -> dict:
    args = ["kanban", "create", title]
    if body:
        args.extend(["--body", body])
    result = _run_hermes(args, timeout=15)
    task_id = None
    m = re.search(r"t_[a-f0-9]+", result["stdout"])
    if m:
        task_id = m.group(0)
    return {"task": "kanban-create", "title": title, "exit": result["exit"],
            "task_id": task_id, "stdout": result["stdout"][:200]}


def cmd_kanban_show(task_id: str) -> dict:
    result = _run_hermes(["kanban", "show", task_id], timeout=15)
    return {"task": "kanban-show", "task_id": task_id, "exit": result["exit"],
            "stdout": result["stdout"][:500]}


def cmd_kanban_complete(task_id: str, summary: str) -> dict:
    result = _run_hermes(["kanban", "complete", task_id, "--summary", summary[:500]], timeout=15)
    return {"task": "kanban-complete", "task_id": task_id, "exit": result["exit"],
            "stdout": result["stdout"][:200]}


def cmd_search_files(pattern: str, path: str = ".", file_glob: str | None = None,
                     limit: int = 50, output_mode: str = "files_only") -> dict:
    """hermes skill-equivalent search_files. Wraps ripgrep via subprocess."""
    args = ["rg", "--no-heading", "--line-number"]
    if output_mode == "files_only":
        args.append("--files-with-matches")
    if file_glob:
        args.extend(["--glob", file_glob])
    if limit:
        args.extend(["--max-count", str(limit)])
    args.extend(["--", pattern, path])
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
        matches = proc.stdout.strip().split("\n") if proc.stdout.strip() else []
        return {"task": "search-files", "pattern": pattern, "path": path,
                "exit": proc.returncode, "match_count": len(matches),
                "matches": matches[:limit]}
    except subprocess.TimeoutExpired:
        return {"task": "search-files", "pattern": pattern, "exit": 124, "error": "timeout"}
    except FileNotFoundError:
        return {"task": "search-files", "pattern": pattern, "exit": 127, "error": "rg not found"}
    except Exception as e:
        return {"task": "search-files", "pattern": pattern, "exit": 1, "error": repr(e)}


def cmd_read_file(path: str, offset: int = 1, limit: int = 500) -> dict:
    """hermes skill-equivalent read_file. Pure file read, paginated."""
    try:
        with open(path) as f:
            lines = f.readlines()
        total = len(lines)
        start = max(1, offset)
        end = min(total, start + limit - 1)
        content = "".join(lines[start - 1:end])
        return {"task": "read-file", "path": path, "offset": start, "limit": limit,
                "total_lines": total, "exit": 0, "content": content}
    except FileNotFoundError:
        return {"task": "read-file", "path": path, "exit": 1, "error": "file not found"}
    except Exception as e:
        return {"task": "read-file", "path": path, "exit": 1, "error": repr(e)}


def cmd_kanban_update_status(task_id: str, status: str) -> dict:
    """hermes kanban edit <id> --result <status> wrapper (edit has no --status flag)."""
    result = _run_hermes(["kanban", "edit", task_id, "--result", status], timeout=15)
    return {"task": "kanban-update-status", "task_id": task_id, "status": status,
            "exit": result["exit"], "stdout": result["stdout"][:200]}


def cmd_memory_save(label: str, content: str) -> dict:
    """Built-in memory is MEMORY.md/USER.md; no CLI save. Write to ~/.hermes/memories/ instead."""
    import os
    mem_dir = os.path.expanduser("~/.hermes/memories")
    os.makedirs(mem_dir, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", label)
    path = os.path.join(mem_dir, f"{safe}.md")
    try:
        with open(path, "a") as f:
            f.write(f"## {label}\n{content}\n\n")
        return {"task": "memory-save", "label": label, "exit": 0, "path": path}
    except Exception as e:
        return {"task": "memory-save", "label": label, "exit": 1, "error": repr(e)}


# v29.8 git-push 2-tier fallback retry pattern.
# Tier 1 (unset proxy) fails with any of these stderr signals → try Tier 2 (force proxy).
_PUSH_RETRY_PATTERN = re.compile(
    r"SSL_ERROR_SYSCALL|Failed to connect.*github.*443|Couldn't connect to server|connection.*reset|connect.*timed out",
    re.IGNORECASE,
)


def _try_push(repo_dir: str, env: dict, proxy_args: list[str],
              remote: str, branch: str, timeout: int = 120) -> dict:
    """Single git push attempt. Returns dict with exit/stdout/stderr."""
    cmd = ["git"] + proxy_args + ["push", remote, branch]
    proc = subprocess.run(
        cmd,
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "exit": proc.returncode,
        "stdout": proc.stdout[-500:] if proc.stdout else "",
        "stderr": proc.stderr[-500:] if proc.stderr else "",
        "cmd": " ".join(cmd),
    }


def cmd_git_push(repo_dir: str, remote: str = "origin", branch: str = "main") -> dict:
    """v29.8 git-push helper (2-tier fallback): bypass mihomo proxy for SSL_ERROR_SYSCALL.

    Root cause (Queen 架构问题 P1 #9): mihomo (127.0.0.1:7897) caches TLS sessions
    for some GitHub repos but not others. Behavior is non-deterministic across repos:
      - hermes-fleet: Tier 1 (unset proxy + -c http.proxy="") succeeds.
      - hermes-wiki:   Tier 1 fails with SSL_ERROR_SYSCALL on first attempt.
    Fix: 2-tier fallback.
      Tier 1: unset all 8 proxy env vars + git -c http.proxy= -c https.proxy=
              (override ~/.gitconfig [http] proxy).
      Tier 2: if Tier 1 exits non-zero AND stderr matches the retry pattern
              (SSL_ERROR_SYSCALL | "Failed to connect.*github.*443" |
               "Couldn't connect to server" | "connection.*reset" |
               "connect.*timed out"),
              retry with -c http.proxy=http://127.0.0.1:7897 + per-URL override
              -c http.https://github.com.proxy=http://127.0.0.1:7897.
              (mihomo proxy must be active — verified manually 2026-08-08.)
    See commit f02871a (Tier 1) and session log 2026-08-08 (Tier 2 evolved).

    Usage: auto_run.py git-push --repo-dir ~/hermes-wiki
    Return: includes tier_used (1|2) and retried (bool) fields.
    """
    env = os.environ.copy()
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "no_proxy", "NO_PROXY"):
        env.pop(k, None)
    repo_dir = os.path.expanduser(repo_dir)
    if not os.path.isdir(repo_dir):
        return {"task": "git-push", "repo_dir": repo_dir, "exit": 1,
                "error": f"not a directory: {repo_dir}"}
    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        return {"task": "git-push", "repo_dir": repo_dir, "exit": 1,
                "error": f"not a git repo: {repo_dir}"}
    try:
        # Tier 1: unset proxy + git -c http.proxy=
        tier1_args = ["-c", "http.proxy=", "-c", "https.proxy="]
        first = _try_push(repo_dir, env, tier1_args, remote, branch)
        if first["exit"] == 0:
            return {
                "task": "git-push",
                "repo_dir": repo_dir,
                "remote": remote,
                "branch": branch,
                "exit": 0,
                "tier_used": 1,
                "retried": False,
                "stdout": first["stdout"],
                "stderr": first["stderr"],
            }
        # Check if stderr matches retry pattern → Tier 2
        if _PUSH_RETRY_PATTERN.search(first["stderr"] or ""):
            # Tier 2: force mihomo proxy on http + per-URL for github.com
            tier2_args = [
                "-c", "http.proxy=http://127.0.0.1:7897",
                "-c", "http.https://github.com.proxy=http://127.0.0.1:7897",
            ]
            second = _try_push(repo_dir, env, tier2_args, remote, branch)
            return {
                "task": "git-push",
                "repo_dir": repo_dir,
                "remote": remote,
                "branch": branch,
                "exit": second["exit"],
                "tier_used": 2 if second["exit"] == 0 else None,
                "retried": True,
                "tier1_stderr": first["stderr"],
                "stdout": second["stdout"],
                "stderr": second["stderr"],
            }
        # Tier 1 failed for non-network reason — don't retry, surface as-is.
        return {
            "task": "git-push",
            "repo_dir": repo_dir,
            "remote": remote,
            "branch": branch,
            "exit": first["exit"],
            "tier_used": 1,
            "retried": False,
            "stdout": first["stdout"],
            "stderr": first["stderr"],
        }
    except subprocess.TimeoutExpired:
        return {"task": "git-push", "repo_dir": repo_dir, "exit": 124,
                "error": "timeout"}
    except Exception as e:
        return {"task": "git-push", "repo_dir": repo_dir, "exit": 1,
                "error": repr(e)}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="auto_run",
        description="v29.8 Phase 2: high-frequency simple tasks, 0 LLM tokens.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_insights = sub.add_parser("insights", help="hermes insights summary")
    p_insights.add_argument("--days", type=int, default=1)
    p_insights.add_argument("--source", default=None)

    sub.add_parser("smoke", help="5-engine fleet smoke + Kanban audit")

    sub.add_parser("monitor", help="hermes monitoring status")

    p_list = sub.add_parser("kanban-list", help="list Kanban tasks")
    p_list.add_argument("--status", default=None)

    p_create = sub.add_parser("kanban-create", help="create Kanban task")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--body", default=None)

    p_show = sub.add_parser("kanban-show", help="show Kanban task")
    p_show.add_argument("--task-id", required=True)

    p_complete = sub.add_parser("kanban-complete", help="complete Kanban task")
    p_complete.add_argument("--task-id", required=True)
    p_complete.add_argument("--summary", required=True)

    p_search = sub.add_parser("search-files", help="search files (rg wrapper)")
    p_search.add_argument("--pattern", required=True)
    p_search.add_argument("--path", default=".")
    p_search.add_argument("--file-glob", default=None)
    p_search.add_argument("--limit", type=int, default=50)
    p_search.add_argument("--output-mode", default="files_only",
                          choices=["files_only", "content"])

    p_read = sub.add_parser("read-file", help="read file (paginated)")
    p_read.add_argument("--path", required=True)
    p_read.add_argument("--offset", type=int, default=1)
    p_read.add_argument("--limit", type=int, default=500)

    p_update = sub.add_parser("kanban-update-status", help="update Kanban task status")
    p_update.add_argument("--task-id", required=True)
    p_update.add_argument("--status", required=True)

    p_mem = sub.add_parser("memory-save", help="save memory entry")
    p_mem.add_argument("--label", required=True)
    p_mem.add_argument("--content", required=True)

    # v29.8 git-push helper: bypass mihomo proxy for github.com SSL_ERROR_SYSCALL
    p_push = sub.add_parser("git-push", help="git push with proxy unset (mihomo workaround)")
    p_push.add_argument("--repo-dir", required=True, help="git repo path")
    p_push.add_argument("--remote", default="origin")
    p_push.add_argument("--branch", default="main")

    args = parser.parse_args()
    cmd = args.cmd

    if cmd == "insights":
        result = cmd_insights(args.days, args.source)
    elif cmd == "smoke":
        result = cmd_smoke()
    elif cmd == "monitor":
        result = cmd_monitor()
    elif cmd == "kanban-list":
        result = cmd_kanban_list(args.status)
    elif cmd == "kanban-create":
        result = cmd_kanban_create(args.title, args.body)
    elif cmd == "kanban-show":
        result = cmd_kanban_show(args.task_id)
    elif cmd == "kanban-complete":
        result = cmd_kanban_complete(args.task_id, args.summary)
    elif cmd == "search-files":
        result = cmd_search_files(args.pattern, args.path, args.file_glob,
                                  args.limit, args.output_mode)
    elif cmd == "read-file":
        result = cmd_read_file(args.path, args.offset, args.limit)
    elif cmd == "kanban-update-status":
        result = cmd_kanban_update_status(args.task_id, args.status)
    elif cmd == "memory-save":
        result = cmd_memory_save(args.label, args.content)
    elif cmd == "git-push":
        result = cmd_git_push(args.repo_dir, args.remote, args.branch)
    else:
        parser.error(f"unknown command: {cmd}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("exit", 1) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
