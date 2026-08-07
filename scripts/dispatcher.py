#!/usr/bin/env python3
"""Queen-mode dispatcher.

Reads a plan.json, validates it, executes a Kahn-ordered DAG of tasks,
and writes structured artifacts to disk. Stdlib only. No LLM in the loop.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import fcntl
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

PLAN_VERSION = "1"
FINDING_FINGERPRINT_VERSION = "1"
CHECKPOINT_INTERVAL_SECONDS = 3600
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
ENGINES = {"codex", "pi", "opencode", "shell"}
ROLES = {"implement", "research", "review", "general", "shell"}
MODES = {"read_only", "write"}
ON_FAILURE = {"block", "continue"}
TIMEOUT_MIN, TIMEOUT_MAX = 30, 3600
DEFAULT_ARTIFACT_ROOT = Path.home() / ".hermes" / "artifacts" / "queen"
ARTIFACT_FLOOR = Path.home() / ".hermes" / "artifacts"
FORBIDDEN_CODEX_FLAGS = (
    "--dangerously-bypass-approvals-and-sandbox",
    "--dangerously-bypass-hook-trust",
)
READONLY_TOOLS = "read,grep,find,ls"
QUEEN_RISK_TEAM = {
    "LOW": ["codex:write", "opencode:read"],
    "MEDIUM": ["codex:write", "opencode:read"],
    "HIGH": ["codex:write", "opencode:read", "pi:read"],
}


def fail(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Patterns stripped from each stderr line before fingerprinting so that the
# same root-cause failure hashes the same across runs (timestamps, pids, and
# incidental random tokens are noise; the underlying error text is the signal).
_FP_LINE_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"),
    re.compile(r"\bpid=\d+\b"),
    re.compile(r"\btid=\d+\b"),
    re.compile(r"\buid=\d+\b"),
    re.compile(r"\bpid\s+\d+\b"),
    re.compile(r"\b0x[0-9a-fA-F]{6,}\b"),         # memory addresses
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),  # uuids
    re.compile(r"\b[a-f0-9]{16,}\b"),             # long hex blobs (sha, random ids)
    re.compile(r"\b\d{10,}\b"),                   # epoch timestamps / long numerics
)


def finding_fingerprint(task_id: str, stderr_text: str) -> str:
    """Return a short stable hash that groups identical root-cause failures.

    Normalizes each stderr line by stripping leading noise (timestamps, pids,
    uuids, random hex), then hashes the joined canonical text. Returns the
    first 8 hex chars of sha256 — enough to distinguish distinct findings
    while staying compact in status.json.
    """
    if not stderr_text:
        canonical = ""
    else:
        cleaned_lines = []
        for raw_line in stderr_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            for pat in _FP_LINE_PATTERNS:
                line = pat.sub("", line)
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                cleaned_lines.append(line)
        canonical = "\n".join(cleaned_lines)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:8]


def emit_replan_event(run_dir: Path, events_path: Path, reason: str) -> None:
    """Append a replan event to events.jsonl.

    Used at run-end when the run did not achieve full success, to signal
    that the orchestrator should consider re-planning.
    """
    record = {"ts": now(), "event": "replan", "reason": reason}
    append_jsonl(events_path, record)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def append_notify(run_dir: Path, level: str, **fields) -> None:
    """Append a row to <run_dir>/notify.jsonl. Queen tail-reads this on next turn.

    level: info | warn | block | l3_finding
    """
    path = run_dir / "notify.jsonl"
    detail = fields.pop("error", None) or fields.pop("reason", None) or fields.get("run_status", "")
    if "detail" not in fields:
        fields["detail"] = detail
    row = {"ts": now(), "level": level, **fields}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_previous_status(run_dir: Path) -> dict:
    """Load existing status.json from a previous run. Returns {} if absent."""
    path = run_dir / "status.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"resume: cannot parse {path}: {exc}", 3)
    if not isinstance(data, dict) or "task_summaries" not in data:
        fail(f"resume: {path} missing task_summaries", 3)
    return data


class RunLock:
    """fcntl-exclusive lock at <run_dir>/.lock. Released on close() or process exit."""

    def __init__(self, run_dir: Path, force_release: bool = False):
        self.run_dir = run_dir
        self.lock_path = run_dir / ".lock"
        self.fd = None
        if force_release and self.lock_path.exists():
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            try:
                self.fd.close()
            except Exception:
                pass
            self.fd = None
            print(
                f"run {run_dir.name} already running (lock held): {exc}",
                file=sys.stderr,
            )
            sys.exit(5)
        self.fd.write(f"pid={os.getpid()} started_at={now()}\n")
        self.fd.flush()

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self.fd.close()
        except Exception:
            pass
        self.fd = None

    def __enter__(self) -> "RunLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_plan(plan: dict, artifact_root: Path) -> tuple[dict, dict]:
    errors = []
    if plan.get("version") != PLAN_VERSION:
        errors.append(f"plan.version must be {PLAN_VERSION!r}; got {plan.get('version')!r}")

    # Feature 5: optional top-level sandbox. Default "fs:loose" because we do NOT
    # yet enforce it (codex build_command maps mode→-s, not plan.sandbox). The
    # field is recorded for future enforcement via codex `-s` wiring.
    sandbox = plan.get("sandbox", "fs:loose")
    if not isinstance(sandbox, str) or not sandbox:
        errors.append(f"plan.sandbox must be a non-empty string; got {sandbox!r}")

    run_id = plan.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        errors.append(f"plan.run_id must match {RUN_ID_RE.pattern}; got {run_id!r}")

    project_root_str = plan.get("project_root")
    if not project_root_str or not Path(project_root_str).is_absolute():
        errors.append(f"plan.project_root must be an absolute path; got {project_root_str!r}")
    elif not Path(project_root_str).exists():
        errors.append(f"plan.project_root does not exist: {project_root_str}")
    project_root = Path(project_root_str).resolve() if project_root_str else None

    if not _is_under(artifact_root, ARTIFACT_FLOOR):
        errors.append(f"--artifact-root must be under {ARTIFACT_FLOOR}; got {artifact_root}")

    risk_level = plan.get("risk_level")
    if risk_level not in RISK_LEVELS:
        errors.append(f"plan.risk_level must be one of {sorted(RISK_LEVELS)}; got {risk_level!r}")

    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append("plan.tasks must be a non-empty list")

    by_id: dict = {}
    normalized_tasks = []
    if isinstance(tasks, list):
        for i, raw in enumerate(tasks):
            if not isinstance(raw, dict):
                errors.append(f"tasks[{i}] must be an object")
                continue
            tid = raw.get("id")
            if not isinstance(tid, str) or not tid:
                errors.append(f"tasks[{i}].id must be a non-empty string")
                continue
            if tid in by_id:
                errors.append(f"duplicate task id: {tid}")
                continue
            by_id[tid] = raw

            engine = raw.get("engine")
            role = raw.get("role")
            mode = raw.get("execution_mode")
            if engine not in ENGINES:
                errors.append(f"task {tid}: engine must be one of {sorted(ENGINES)}")
            if role not in ROLES:
                errors.append(f"task {tid}: role must be one of {sorted(ROLES)}")
            if mode not in MODES:
                errors.append(f"task {tid}: execution_mode must be one of {sorted(MODES)}")

            requested_mode = mode
            if role == "review" or engine == "opencode":
                mode = "read_only"

            deps = raw.get("depends_on", [])
            if not isinstance(deps, list) or not all(isinstance(x, str) for x in deps):
                errors.append(f"task {tid}: depends_on must be an array of task ids")
                deps = []

            timeout = raw.get("timeout_seconds", 600)
            if not isinstance(timeout, int) or not TIMEOUT_MIN <= timeout <= TIMEOUT_MAX:
                errors.append(f"task {tid}: timeout_seconds must be {TIMEOUT_MIN}–{TIMEOUT_MAX}")

            on_failure = raw.get("on_failure", "block")
            if on_failure not in ON_FAILURE:
                errors.append(f"task {tid}: on_failure must be block or continue")

            output_file = raw.get("output_file")
            if output_file is not None:
                op = Path(output_file)
                if op.is_absolute():
                    errors.append(f"task {tid}: output_file must be relative to project_root")
                elif project_root and not _is_under(project_root / op, project_root):
                    errors.append(f"task {tid}: output_file escapes project_root: {output_file}")

            shell_argv = raw.get("argv")
            if engine == "shell":
                if not isinstance(shell_argv, list) or not shell_argv or not all(isinstance(x, str) for x in shell_argv):
                    errors.append(f"task {tid}: shell engine requires non-empty argv string array")

            extra_args = raw.get("extra_args", [])
            if extra_args and (not isinstance(extra_args, list) or not all(isinstance(x, str) for x in extra_args)):
                errors.append(f"task {tid}: extra_args must be a string array")
                extra_args = []
            if engine == "codex" and any(x in FORBIDDEN_CODEX_FLAGS for x in extra_args):
                errors.append(f"task {tid}: forbidden codex bypass flag")
            if engine == "codex" and any(x == "danger-full-access" for x in extra_args):
                errors.append(f"task {tid}: danger-full-access is forbidden")

            # Feature 5: optional rollback_on_fail flag (default false).
            rollback_on_fail = raw.get("rollback_on_fail", False)
            if not isinstance(rollback_on_fail, bool):
                errors.append(f"task {tid}: rollback_on_fail must be a boolean")
                rollback_on_fail = False

            normalized_tasks.append({
                "id": tid,
                "engine": engine,
                "role": role,
                "execution_mode": mode,
                "requested_execution_mode": requested_mode,
                "goal": str(raw.get("goal", "")),
                "context": str(raw.get("context", "")),
                "depends_on": deps,
                "timeout_seconds": timeout,
                "on_failure": on_failure,
                "output_file": output_file,
                "argv": shell_argv,
                "extra_args": extra_args,
                "rollback_on_fail": rollback_on_fail,
            })

    ids = {t["id"] for t in normalized_tasks}
    for t in normalized_tasks:
        for dep in t["depends_on"]:
            if dep not in ids:
                errors.append(f"task {t['id']}: unknown dependency {dep}")
            if dep == t["id"]:
                errors.append(f"task {t['id']}: self-dependency is not allowed")

    if not errors:
        cycle = find_cycle(normalized_tasks)
        if cycle:
            errors.append("dependency cycle detected: " + " -> ".join(cycle))

    if errors:
        raise ValueError("\n".join(errors))

    normalized = dict(plan)
    normalized["version"] = PLAN_VERSION
    normalized["project_root"] = str(project_root)
    normalized["artifact_root"] = str(artifact_root.resolve())
    normalized["risk_team"] = QUEEN_RISK_TEAM[risk_level]
    normalized["sandbox"] = sandbox
    # Print a one-liner so operators see sandbox is recorded but not enforced.
    # codex build_command uses execution_mode→-s; plan.sandbox will be wired in
    # a future v24+. Queen should NOT trust plan.sandbox as an isolation gate.
    print(f"[dispatcher] sandbox={sandbox} (recorded; not enforced — see runtime contract)")
    normalized["tasks"] = normalized_tasks
    return normalized, {t["id"]: t for t in normalized_tasks}


def find_cycle(tasks: list[dict]) -> list[str]:
    indegree = {t["id"]: len(t["depends_on"]) for t in tasks}
    children = {t["id"]: [] for t in tasks}
    for t in tasks:
        for dep in t["depends_on"]:
            children.setdefault(dep, []).append(t["id"])
    q = deque(k for k, v in indegree.items() if v == 0)
    seen = []
    while q:
        n = q.popleft()
        seen.append(n)
        for c in children.get(n, []):
            indegree[c] -= 1
            if indegree[c] == 0:
                q.append(c)
    if len(seen) == len(tasks):
        return []
    return [k for k, v in indegree.items() if v > 0]



def build_prompt(task: dict) -> str:
    goal = task["goal"].strip()
    context = task["context"].strip()
    return goal + ("\n\n" + context if context else "")


def build_command(task: dict, project_root: Path, task_dir: Path) -> list[str]:
    prompt = build_prompt(task)
    engine = task["engine"]
    mode = task["execution_mode"]
    output_file = task.get("output_file")

    if engine == "shell":
        return list(task["argv"])
    if engine == "codex":
        sandbox = "workspace-write" if mode == "write" else "read-only"
        last_message = project_root / output_file if output_file else task_dir / "agent-last-message.txt"
        return [
            "codex", "exec", "-C", str(project_root), "-s", sandbox,
            "--skip-git-repo-check", "--ephemeral", "--json",
            "-o", str(last_message), *task.get("extra_args", []), prompt,
        ]
    if engine == "pi":
        command = [
            "pi-anchor", "-p", "--provider", "anchor", "--model", "anchor",
            "--mode", "json", "--no-session",
        ]
        if mode == "read_only":
            command.extend(["--tools", READONLY_TOOLS])
        else:
            command.extend(["--tools", "read,grep,find,ls,bash,edit,write"])
        command.extend(task.get("extra_args", []))
        command.append(prompt)
        return command
    if engine == "opencode":
        return [
            "opencode", "run", "--format", "json", "--dir", str(project_root),
            *task.get("extra_args", []), prompt,
        ]
    raise ValueError(f"unsupported engine: {engine}")


def event(events_path: Path, event_name: str, task_id: str | None = None, **extra) -> None:
    record = {"ts": now(), "event": event_name}
    if task_id is not None:
        record["task_id"] = task_id
    record.update(extra)
    append_jsonl(events_path, record)


def prepare_task_artifacts(task: dict, task_dir: Path, command: list[str]) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "prompt.md").write_text(build_prompt(task), encoding="utf-8")
    for name in ("stdout.log", "stderr.log"):
        (task_dir / name).touch()
    write_json(task_dir / "command.json", {
        "argv": command,
        "cwd": task.get("project_root"),
        "started_at": None,
        "ended_at": None,
        "exit": None,
    })


def run_task(task: dict, project_root: Path, run_dir: Path, events_path: Path) -> dict:
    task_id = task["id"]
    task_dir = run_dir / "tasks" / task_id
    command = build_command(task, project_root, task_dir)
    prepare_task_artifacts(task, task_dir, command)
    started_at = now()
    start_mono = time.monotonic()
    event(events_path, "start", task_id, engine=task["engine"])
    exit_code = 1
    error = None

    command_record = {
        "argv": command,
        "cwd": str(project_root),
        "started_at": started_at,
        "ended_at": None,
        "exit": None,
    }
    write_json(task_dir / "command.json", command_record)

    try:
        with (task_dir / "stdout.log").open("wb") as stdout, (task_dir / "stderr.log").open("wb") as stderr:
            proc = subprocess.Popen(
                command,
                cwd=str(project_root),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                start_new_session=True,
            )
            try:
                exit_code = proc.wait(timeout=task["timeout_seconds"])
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, 15)
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        os.killpg(proc.pid, 9)
                    except Exception:
                        proc.kill()
                exit_code = 124
                error = f"timeout after {task['timeout_seconds']}s"
    except FileNotFoundError as exc:
        exit_code = 127
        error = str(exc)
    except Exception as exc:
        exit_code = 1
        error = f"{type(exc).__name__}: {exc}"

    ended_at = now()
    duration_ms = int((time.monotonic() - start_mono) * 1000)

    # Feature 2: derive a fingerprint from stderr on failure so identical
    # root-cause errors are grouped under one finding key across retries.
    # Read stderr.log back (it's already flushed+closed by Popen).
    stderr_text = ""
    try:
        stderr_text = (task_dir / "stderr.log").read_text(encoding="utf-8", errors="replace")
    except Exception:
        stderr_text = ""
    fingerprint = finding_fingerprint(task_id, stderr_text) if exit_code != 0 else ""
    finding_key = f"{task_id}:{fingerprint}" if fingerprint else ""

    result = {
        "exit": exit_code,
        "duration_ms": duration_ms,
        "started_at": started_at,
        "ended_at": ended_at,
        "mode": task["execution_mode"],
    }
    if error:
        result["error"] = error
    if fingerprint:
        result["finding_key"] = finding_key
        result["finding_fingerprint"] = fingerprint
    write_json(task_dir / "result.json", result)
    command_record.update({"ended_at": ended_at, "exit": exit_code})
    write_json(task_dir / "command.json", command_record)
    summary_lines = [
        f"task: {task_id}",
        f"engine: {task['engine']}",
        f"exit: {exit_code}",
    ]
    if fingerprint:
        summary_lines.append(f"finding_key: {finding_key}")
    # Feature 5: rollback hint — only on failure, only when the task opted in.
    # Hint is written to summary.md as a planning aid; we do NOT execute git.
    if exit_code != 0 and task.get("rollback_on_fail"):
        summary_lines.append(f"rollback: git checkout -- {project_root}")
    (task_dir / "summary.md").write_text(
        "\n".join(summary_lines) + "\n",
        encoding="utf-8",
    )
    event(events_path, "done" if exit_code == 0 else "fail", task_id,
          exit=exit_code, duration_ms=duration_ms)
    level = "info" if exit_code == 0 else "warn"
    append_notify(
        run_dir, level, task_id=task_id,
        detail=f"exit={exit_code} duration_ms={duration_ms}",
    )
    return {
        "id": task_id,
        "engine": task["engine"],
        "role": task["role"],
        "mode": task["execution_mode"],
        "status": "done" if exit_code == 0 else "failed",
        "exit": exit_code,
        "duration_ms": duration_ms,
        "summary_path": str(task_dir / "summary.md"),
        "finding_key": finding_key,
    }


def mark_blocked(task: dict, project_root: Path, run_dir: Path, events_path: Path,
                 reason: str) -> dict:
    task_dir = run_dir / "tasks" / task["id"]
    command = build_command(task, project_root, task_dir)
    prepare_task_artifacts(task, task_dir, command)
    ts = now()
    result = {
        "exit": None,
        "duration_ms": 0,
        "started_at": None,
        "ended_at": ts,
        "mode": task["execution_mode"],
        "blocked_reason": reason,
    }
    write_json(task_dir / "result.json", result)
    (task_dir / "summary.md").write_text(
        f"task: {task['id']}\nengine: {task['engine']}\nexit: blocked\n",
        encoding="utf-8",
    )
    event(events_path, "block", task["id"], reason=reason)
    append_notify(run_dir, "block", task_id=task["id"], reason=reason)
    return {
        "id": task["id"],
        "engine": task["engine"],
        "role": task["role"],
        "mode": task["execution_mode"],
        "status": "blocked",
        "exit": None,
        "duration_ms": 0,
        "blocked_reason": reason,
        "summary_path": str(task_dir / "summary.md"),
    }



def _flush_status(run_dir: Path, normalized: dict, started_at: str,
                   status_map: dict, run_status_hint: str = "partial",
                   counters: dict | None = None,
                   last_checkpoint_at: str | None = None,
                   last_checkpoint_mono: float | None = None) -> None:
    """Write status.json incrementally so a mid-run kill leaves recoverable state.

    counters (Feature 1), last_checkpoint_at (Feature 3), and
    last_checkpoint_mono (Feature 3 anchor) are optional so older callers
    (and tests) can flush without them; they default to None and only
    appear in the JSON if explicitly provided.
    """
    tasks = normalized["tasks"]
    summaries = [status_map[t["id"]] for t in tasks if t["id"] in status_map]
    payload = {
        "run_id": normalized["run_id"],
        "run_status": "running",
        "started_at": started_at,
        "completed_at": None,
        "risk_level": normalized.get("risk_level"),
        "risk_team": normalized.get("risk_team"),
        "task_summaries": summaries,
        "run_status_hint": run_status_hint,
    }
    if counters is not None:
        payload["counters"] = counters
    if last_checkpoint_at is not None:
        payload["last_checkpoint_at"] = last_checkpoint_at
    if last_checkpoint_mono is not None:
        payload["last_checkpoint_mono"] = last_checkpoint_mono
    write_json(run_dir / "status.json", payload)


def execute_plan(normalized: dict, max_concurrency: int, dry_run: bool = False,
                  resume: bool = False, force_release: bool = False) -> dict:
    project_root = Path(normalized["project_root"])
    run_dir = Path(normalized["artifact_root"]) / normalized["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path = run_dir / "events.jsonl"

    status_path = run_dir / "status.json"
    prior_status: dict = {}
    if status_path.exists():
        if not resume:
            fail(
                f"run {normalized['run_id']} already has status.json; "
                "use --resume to continue or --no-resume to fail",
                2,
            )
        prior_status = load_previous_status(run_dir)
    prior_summaries = {s["id"]: s for s in prior_status.get("task_summaries", [])}
    started_at = prior_status.get("started_at") or now()

    # Feature 1: counters — preserve across --resume by reloading from the prior
    # status.json if present; otherwise start fresh.
    # total_retries counts failed task occurrences (incl. first failure);
    # retry_count counts tasks that previously failed and are being re-executed —
    # this is what SOUL's "≤8 轮 per run" maps to.
    prior_counters = prior_status.get("counters") or {}
    counters = {
        "total_retries": int(prior_counters.get("total_retries", 0)),
        "retry_count": int(prior_counters.get("retry_count", 0)),
        "findings": dict(prior_counters.get("findings", {})),
    }
    # Feature 3: last_checkpoint_at + monotonic anchor carried across resumes.
    last_checkpoint_at = prior_status.get("last_checkpoint_at")
    _last_checkpoint_mono = prior_status.get("last_checkpoint_mono")  # may be None on first run

    lock = RunLock(run_dir, force_release=force_release)
    try:
        if not resume and events_path.exists():
            events_path.unlink()
        event(
            events_path,
            "run_resume" if resume else "run_start",
            run_id=normalized["run_id"],
            dry_run=dry_run,
            prior_run_status=prior_status.get("run_status"),
        )

        tasks = normalized["tasks"]
        by_id = {t["id"]: t for t in tasks}
        children = {t["id"]: [] for t in tasks}
        remaining_deps = {t["id"]: set(t["depends_on"]) for t in tasks}
        for t in tasks:
            for dep in t["depends_on"]:
                children[dep].append(t["id"])

        status_map: dict[str, dict] = {}

        if resume:
            for tid, summary in prior_summaries.items():
                if tid not in by_id:
                    continue
                status = summary.get("status")
                if status == "done":
                    status_map[tid] = summary
                    for child in children[tid]:
                        remaining_deps[child].discard(tid)
                elif status == "blocked":
                    status_map[tid] = summary
                elif status == "running":
                    event(
                        events_path,
                        "stale_running",
                        tid,
                        prior_started_at=summary.get("started_at"),
                    )
                elif status == "failed":
                    # conservative: keep failed summary, do not auto-retry
                    status_map[tid] = summary
                    if by_id[tid].get("on_failure") == "block":
                        queue = deque(children[tid])
                        while queue:
                            blocked_id = queue.popleft()
                            if blocked_id in status_map or blocked_id not in by_id:
                                continue
                            remaining_deps[blocked_id] = set()
                            status_map[blocked_id] = mark_blocked(
                                by_id[blocked_id],
                                project_root,
                                run_dir,
                                events_path,
                                reason=f"blocked by failed dependency {tid}",
                            )
                            queue.extend(children[blocked_id])

        ready = deque(
            tid
            for tid, deps in remaining_deps.items()
            if not deps and tid not in status_map
        )

        if dry_run:
            dry_rows = []
            for task in tasks:
                command = build_command(
                    task, project_root, run_dir / "tasks" / task["id"]
                )
                dry_rows.append(
                    {
                        "id": task["id"],
                        "engine": task["engine"],
                        "role": task["role"],
                        "execution_mode": task["execution_mode"],
                        "depends_on": task["depends_on"],
                        "argv": command,
                    }
                )
                event(events_path, "dry_run", task["id"], argv=command)
            write_json(run_dir / "normalized-plan.json", normalized)
            write_json(
                run_dir / "status.json",
                {
                    "run_id": normalized["run_id"],
                    "run_status": "dry_run",
                    "started_at": started_at,
                    "completed_at": now(),
                    "task_summaries": dry_rows,
                    "risk_level": normalized.get("risk_level"),
                    "risk_team": normalized.get("risk_team"),
                },
            )
            print(
                json.dumps(
                    {
                        "run_id": normalized["run_id"],
                        "run_status": "dry_run",
                        "tasks": dry_rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return {"run_status": "dry_run", "task_summaries": dry_rows}

        write_json(run_dir / "normalized-plan.json", normalized)
        futures: dict = {}

        def launch(task_id: str) -> None:
            task = by_id[task_id]
            futures[task_id] = executor.submit(
                run_task, task, project_root, run_dir, events_path
            )

        with cf.ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            while ready or futures:
                while ready and len(futures) < max_concurrency:
                    launch(ready.popleft())
                if not futures:
                    break
                done, _ = cf.wait(futures.values(), return_when=cf.FIRST_COMPLETED)
                finished_ids = [
                    tid for tid, fut in list(futures.items()) if fut in done
                ]
                for tid in finished_ids:
                    fut = futures.pop(tid)
                    try:
                        summary = fut.result()
                    except Exception as exc:
                        summary = {
                            "id": tid,
                            "engine": by_id[tid]["engine"],
                            "role": by_id[tid]["role"],
                            "mode": by_id[tid]["execution_mode"],
                            "status": "failed",
                            "exit": 1,
                            "duration_ms": 0,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                        event(events_path, "fail", tid, error=summary["error"])
                        append_notify(
                            run_dir, "warn", task_id=tid,
                            detail=f"crash: {summary['error']}",
                        )
                    status_map[tid] = summary

                    # Feature 1: count failures. total_retries = failed-task
                    # occurrences (incl. first failure). retry_count = tasks
                    # that previously failed and are now being re-executed —
                    # this is what SOUL "≤8 轮 per run" maps to. We detect
                    # retry via prior_status (carried across --resume).
                    if summary.get("status") == "failed":
                        counters["total_retries"] += 1
                        if tid in prior_summaries and prior_summaries[tid].get("status") == "failed":
                            counters["retry_count"] += 1
                        fkey = summary.get("finding_key") or ""
                        if fkey:
                            counters["findings"][fkey] = (
                                int(counters["findings"].get(fkey, 0)) + 1
                            )

                    # Feature 3: emit a checkpoint.tick event when more than
                    # CHECKPOINT_INTERVAL_SECONDS have elapsed since the last
                    # checkpoint. _last_checkpoint_mono is carried across
                    # --resume via status.json#last_checkpoint_mono; on the
                    # very first task we anchor the clock without emitting
                    # (avoids spurious checkpoints on short runs).
                    now_ts = now()
                    now_mono = time.monotonic()
                    last_mono = (
                        execute_plan._last_checkpoint_mono  # type: ignore[attr-defined]
                        if hasattr(execute_plan, "_last_checkpoint_mono")
                        else _last_checkpoint_mono
                    )
                    if last_mono is None:
                        execute_plan._last_checkpoint_mono = now_mono  # type: ignore[attr-defined]
                        _last_checkpoint_mono = now_mono
                    elif (now_mono - last_mono) >= CHECKPOINT_INTERVAL_SECONDS:
                        completed_tasks = sum(
                            1 for s in status_map.values() if s.get("status") == "done"
                        )
                        event(
                            events_path,
                            "checkpoint.tick",
                            run_id=normalized["run_id"],
                            completed_tasks=completed_tasks,
                        )
                        last_checkpoint_at = now_ts
                        execute_plan._last_checkpoint_mono = now_mono  # type: ignore[attr-defined]
                        _last_checkpoint_mono = now_mono

                    _flush_status(
                        run_dir, normalized, started_at, status_map,
                        run_status_hint="partial",
                        counters=counters,
                        last_checkpoint_at=last_checkpoint_at,
                        last_checkpoint_mono=_last_checkpoint_mono,
                    )
                    if summary["status"] == "done":
                        for child in children[tid]:
                            remaining_deps[child].discard(tid)
                            if (
                                not remaining_deps[child]
                                and child not in status_map
                                and child not in futures
                                and child not in ready
                            ):
                                ready.append(child)
                    else:
                        if by_id[tid]["on_failure"] == "block":
                            queue = deque(children[tid])
                            while queue:
                                blocked_id = queue.popleft()
                                if blocked_id in status_map or blocked_id in futures:
                                    continue
                                if blocked_id in ready:
                                    ready = deque(
                                        x for x in ready if x != blocked_id
                                    )
                                status_map[blocked_id] = mark_blocked(
                                    by_id[blocked_id],
                                    project_root,
                                    run_dir,
                                    events_path,
                                    reason=f"blocked by failed dependency {tid}",
                                )
                                queue.extend(children[blocked_id])
                        else:
                            for child in children[tid]:
                                remaining_deps[child].discard(tid)
                                if (
                                    not remaining_deps[child]
                                    and child not in status_map
                                    and child not in futures
                                    and child not in ready
                                ):
                                    ready.append(child)

        for tid in by_id:
            if tid not in status_map:
                status_map[tid] = mark_blocked(
                    by_id[tid],
                    project_root,
                    run_dir,
                    events_path,
                    reason="unresolved dependency or not scheduled",
                )

        summaries = [status_map[t["id"]] for t in tasks]
        statuses = {s["status"] for s in summaries}
        if statuses == {"done"}:
            run_status = "success"
        elif "done" in statuses:
            run_status = "partial_success"
        else:
            run_status = "failed"

        completed_at = now()
        status = {
            "run_id": normalized["run_id"],
            "run_status": run_status,
            "started_at": started_at,
            "completed_at": completed_at,
            "risk_level": normalized.get("risk_level"),
            "risk_team": normalized.get("risk_team"),
            "task_summaries": summaries,
            "counters": counters,
        }
        if last_checkpoint_at is not None:
            status["last_checkpoint_at"] = last_checkpoint_at
        if _last_checkpoint_mono is not None:
            status["last_checkpoint_mono"] = _last_checkpoint_mono
        write_json(run_dir / "status.json", status)
        (run_dir / "summary.md").write_text(
            "\n".join(
                [
                    f"# Queen run {normalized['run_id']}",
                    f"status: {run_status}",
                    f"risk: {normalized.get('risk_level')}",
                    "",
                    "## tasks",
                    *[
                        f"- {s['id']}: {s['status']} (exit={s.get('exit')})"
                        for s in summaries
                    ],
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        event(events_path, "run_end", run_status=run_status)
        # Feature 4: if the run did not fully succeed, signal the orchestrator
        # to consider re-planning. Emitted AFTER run_end so consumers see the
        # final outcome first, then the follow-up suggestion.
        if run_status in {"partial_success", "failed"}:
            emit_replan_event(run_dir, events_path, reason=f"run_status={run_status}")
        level = "info" if run_status == "success" else "warn"
        append_notify(
            run_dir, level, run_status=run_status,
            task_ids=[s["id"] for s in summaries],
            summary_path=str(run_dir / "summary.md"),
        )
        print(
            json.dumps(
                {
                    "run_id": normalized["run_id"],
                    "run_status": run_status,
                    "summary_path": str(run_dir / "summary.md"),
                },
                ensure_ascii=False,
            )
        )
        return status
    finally:
        lock.release()



def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Queen-mode pure-Python DAG dispatcher")
    p.add_argument("--plan", required=True, help="Path to plan.json")
    p.add_argument("--dry-run", action="store_true", help="Validate and print argv only")
    p.add_argument("--max-concurrency", type=int, default=None,
                   help="Max concurrent tasks (default min(3, len(tasks)))")
    p.add_argument("--artifact-root", default=str(DEFAULT_ARTIFACT_ROOT),
                   help="Artifact root under ~/.hermes/artifacts/")
    p.add_argument("--resume", dest="resume", action="store_true", default=None,
                   help="Resume from existing status.json: skip done, reset stale running to pending, keep blocked, keep failed (no auto-retry; use new --plan or clear status to force a retry)")
    p.add_argument("--no-resume", dest="resume", action="store_false",
                   help="Fail if run directory already has status.json (default)")
    p.add_argument("--force-release", dest="force_release", action="store_true",
                   help="Remove stale .lock before starting (post-kill recovery); does NOT touch status.json")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    plan_path = Path(args.plan).expanduser().resolve()
    if not plan_path.exists():
        fail(f"plan not found: {plan_path}", 2)
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid plan JSON: {exc}", 2)

    artifact_root = Path(args.artifact_root).expanduser()
    try:
        normalized, _ = validate_plan(plan, artifact_root)
    except ValueError as exc:
        fail(str(exc), 2)

    max_concurrency = args.max_concurrency
    if max_concurrency is None:
        max_concurrency = min(3, len(normalized["tasks"]))
    if max_concurrency < 1:
        fail("--max-concurrency must be >= 1", 2)

    try:
        status = execute_plan(
            normalized,
            max_concurrency=max_concurrency,
            dry_run=args.dry_run,
            resume=bool(args.resume),
            force_release=bool(args.force_release),
        )
    except Exception as exc:
        print(f"runtime error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        return 0
    if status["run_status"] in {"success", "partial_success"}:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
