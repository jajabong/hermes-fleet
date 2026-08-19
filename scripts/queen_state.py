#!/usr/bin/env python3
"""Queen B 状态决策脚本 (v28): 给 Queen 自己读 events.jsonl + 决定下一步.

Read-only. 不写 dispatcher / kanban. 不动 hermes state.

能力:
1) list-runs: 列最近 N 个 run 的状态 + 计数摘要
2) tail: 拉取某 run 的新事件 (from event-hub _event-log.jsonl)
3) decide: 给定当前 finding, 给出"应不该再派 / 换引擎 / 报用户"建议

用法:
  python3 queen_state.py list-runs [--limit N]
  python3 queen_state.py tail --run-id <id> [--limit N]
  python3 queen_state.py decide --run-id <id> --finding-key "<task_id>:<fp8>"

参见: SOUL.md §长程执行 + §汇报唯一出口
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

HERMES_ROOT = Path.home() / ".hermes"
ARTIFACT_ROOT = HERMES_ROOT / "artifacts" / "queen"
KANBAN_DB = HERMES_ROOT / "kanban.db"
EVENT_LOG = ARTIFACT_ROOT / "_event-log.jsonl"

WHEEL_LIMITS = {
    "same_finding_retries": 2,
    "run_total_redispatches": 8,
    "task_timeout_default_s": 600,
    "task_timeout_hard_s": 3600,
}


def _latest_status(run_dir: Path) -> dict | None:
    p = run_dir / "status.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cmd_list_runs(args) -> int:
    if not ARTIFACT_ROOT.exists():
        print("no runs yet")
        return 0
    runs = []
    for d in sorted(ARTIFACT_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        st = _latest_status(d)
        ctrs = (st or {}).get("counters", {})
        runs.append({
            "run_id": d.name,
            "run_status": (st or {}).get("run_status", "unknown"),
            "total_recent": ctrs.get("total_retries", 0),
            "re_recent": ctrs.get("retry_count", 0),
            "findings": len(ctrs.get("findings", {})),
            "last_ts": (st or {}).get("last_checkpoint_at"),
        })
    runs = runs[:args.limit]
    print(f"runs: {len(runs)} (showing top {args.limit})")
    for r in runs:
        print(f"  {r['run_id']:<40} status={r['run_status']:<18} "
              f"retries={r['total_recent']} retry={r['re_recent']} "
              f"findings={r['findings']} last_ts={r['last_ts']}")
    return 0


def cmd_tail(args) -> int:
    if not EVENT_LOG.exists():
        print("no events yet (run event-hub ingest first)")
        return 0
    events = []
    with EVENT_LOG.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ev = json.loads(line)
                if ev.get("run_id") == args.run_id:
                    events.append(ev)
    events.sort(key=lambda e: e.get("ts", ""))
    events = events[-args.limit:]
    print(f"tail run={args.run_id} ({len(events)} events)")
    for ev in events:
        print(f"  {ev['ts']}  {ev['type']:<12} {ev['source']:<10} "
              f"task={ev['task_id']} sev={ev['severity']}")
    return 0


def cmd_decide(args) -> int:
    """Decide whether to redispatch / switch engine / surface to user.

    Reads status.json#counters.findings[fp]; compares to WHEEL_LIMITS.
    """
    run_dir = ARTIFACT_ROOT / args.run_id
    st = _latest_status(run_dir)
    if not st:
        print(f"no status.json for run={args.run_id}")
        return 2
    ctrs = st.get("counters", {})
    findings = ctrs.get("findings", {})
    fp_count = findings.get(args.finding_key, 0)
    total_recent = ctrs.get("retry_count", 0)
    run_status = st.get("run_status", "unknown")
    parts = []
    if fp_count >= WHEEL_LIMITS["same_finding_retries"]:
        parts.append(f"[!] same_finding {fp_count}>={WHEEL_LIMITS['same_finding_retries']} → 报用户")
    else:
        parts.append(f"ok redispatch (same_finding={fp_count} <{WHEEL_LIMITS['same_finding_retries']})")
    if total_recent >= WHEEL_LIMITS["run_total_redispatches"]:
        parts.append(f"[!] run_total {total_recent}>={WHEEL_LIMITS['run_total_redispatches']} → 报用户, 不再自修")
    if run_status == "partial_success":
        parts.append("run=partial_success → 可触发 replan")
    elif run_status == "failed":
        parts.append("run=failed → 强制报用户")
    print(f"decide run={args.run_id} finding={args.finding_key}")
    for p in parts:
        print(f"  {p}")
    return 0




def cmd_kanban_tail(args) -> int:
    """Show tail of a kanban task: status + session_id + last events."""
    db = Path.home() / ".hermes" / "kanban.db"
    if not db.exists():
        print("no kanban.db yet (run `hermes kanban init`)")
        return 0
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, title, status, assignee, session_id, workspace_path, "
            "created_at, started_at, completed_at FROM tasks WHERE id = ?",
            (args.task_id,)).fetchone()
        if not row:
            print(f"no task {args.task_id}")
            return 2
        for k in ("id", "title", "status", "assignee", "session_id",
                  "workspace_path", "created_at", "started_at", "completed_at"):
            print(f"  {k:<16} {row[k]}")
        events = conn.execute(
            "SELECT kind, created_at, payload FROM task_events "
            "WHERE task_id = ? ORDER BY id DESC LIMIT ?",
            (args.task_id, args.limit)).fetchall()
        if events:
            print(f"--- last {len(events)} events ---")
            for e in events:
                print(f"  {e['created_at']}  {e['kind']:<20}")
    finally:
        conn.close()
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Queen B 状态决策 (v28)")
    sub = p.add_subparsers(dest="cmd", required=True)
    pk = sub.add_parser("kanban-tail")
    pk.add_argument("--task-id", required=True)
    pk.add_argument("--limit", type=int, default=10)
    pk.set_defaults(func=cmd_kanban_tail)
    pl = sub.add_parser("list-runs")
    pl.add_argument("--limit", type=int, default=10)
    pl.set_defaults(func=cmd_list_runs)
    pt = sub.add_parser("tail")
    pt.add_argument("--run-id", required=True)
    pt.add_argument("--limit", type=int, default=20)
    pt.set_defaults(func=cmd_tail)
    pd = sub.add_parser("decide")
    pd.add_argument("--run-id", required=True)
    pd.add_argument("--finding-key", required=True,
                   help="<task_id>:<fp8>")
    pd.set_defaults(func=cmd_decide)
    pk = sub.add_parser("kanban")
    pk.add_argument("--task-id", required=True)
    pk.add_argument("--limit", type=int, default=10)
    pk.set_defaults(func=cmd_kanban_tail)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())