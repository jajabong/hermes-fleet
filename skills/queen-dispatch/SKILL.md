---
name: queen-dispatch
description: Queen-mode programmatic dispatch to codex/pi/opencode in one execute_code call.
tags: [orchestration, queen, dispatch, codex, pi, opencode]
---

# Queen Dispatch — Programmatic Multi-Agent Orchestration

Hermes-as-Queen 把多个独立任务一次性派给外部 CLI agents，结果只回
final summary，不污染主对话。这是真正的 token 节省机制。

## When to use
- ≥2 个独立任务（互不依赖）
- 多视角 review（3 reviewers 并行）
- 重活拆给 codex / pi / opencode，避免自己写大段代码

## How (canonical pattern)

用 `execute_code` 在一次 LLM call 内批量派单 + 收集：

```python
from hermes_skills.queen_dispatch import dispatch_batch

results = dispatch_batch(tasks=[
    {"id": "impl",  "engine": "codex",    "goal": "...", "context": "...", "workdir": "..."},
    {"id": "review","engine": "opencode", "goal": "...", "context": "...", "workdir": "..."},
    {"id": "explore","engine": "pi",     "goal": "...", "context": "..."},
])
```

每条 task 的 context 用 path:line 引用，不要 paste 完整文件内容。

## Engines (与 SOUL.md 舰队一致)
- codex → `codex exec --skip-git-repo-check -C <workdir> "<goal>+context"`
- pi → `pi-anchor -p --provider anchor --model anchor --mode json --no-session "<goal>+context"` (Hermes-flavored wrapper)
- opencode → `opencode run --format json --dir <workdir> "<goal>+context"`（默认 model=`kilocode/kilo-auto/free`; 备选 `opencode/laguna-s-2.1-free` / `opencode/nemotron-3-ultra-free`; 不传 --auto）

## 不要
- 不要 paste 完整文件到 context（用 path:line）
- 不要在主对话里旁观子 agent 输出
- 默认不混用 claude-code；但若 SOUL 升级触发器命中，按舰队表 L98-L104 启用


## plan.json schema

```json
{
  "version": "1",
  "run_id": "feature-demo-001",
  "project_root": "/abs/path",
  "risk_level": "LOW|MEDIUM|HIGH",
  "goal": "...",
  "acceptance_criteria": ["..."],
  "max_concurrency": 2,
  "sandbox": "fs:loose",
  "tasks": [
    {
      "id": "unique-id",
      "engine": "codex|pi|opencode|shell",
      "role": "implement|research|review|general|shell",
      "execution_mode": "read_only|write",
      "goal": "goal + acceptance + no-overreach",
      "context": "path:line refs only",
      "depends_on": ["other-id"],
      "timeout_seconds": 600,
      "on_failure": "block|continue",
      "output_file": "relative/path.txt",
      "argv": ["python3", "-V"],
      "verification_command": "pytest -x -q",
      "rollback_on_fail": false
    }
  ]
}
```

Notes:
- `shell` tasks require `argv` (string array). Never use shell=True.
- `review` and `opencode` are forced to `read_only`.
- `codex` write uses `-s workspace-write`; danger/bypass flags are rejected.

## Risk → team mapping（Queen 决策表）

| 风险 | 实现 | L2 review | L3 review | 备注 |
|---|---|---|---|---|
| LOW | codex（write） | opencode（read） | - | 单 reviewer |
| MEDIUM | codex（write） | opencode（read） | - | 单 reviewer；显式写验收条件 |
| HIGH | codex（write） | opencode（read） | pi（read） | 验证 L2 finding + 关键不变量 |

Claude Code 仅在 SOUL.md 升级触发器命中时启用（必升级：上下文>50k / 前一轮 pi 失败；建议升级：链式判断≥3 / 架构权衡 / 失败调试 / 多步博弈）。默认走 pi/Anchor。

## Blind review rule（防止同源偏见）

review task 的 context 不出现实现 agent 的 prompt，只给：
- 原始目标 + 验收条件
- project_root
- diff 范围或受改文件清单
- 已执行的 L1 命令与结果摘要

## Deterministic scheduler（不变量）

调度循环里不放 LLM。Hermes 只在两个时刻调 LLM：
1. 出 plan.json
2. 综合 status.json + summary.md 写最终回复

## Canonical invocation

```bash
~/.hermes/skills/queen-dispatch/scripts/dispatcher.py \
    --plan <plan.json> \
    --artifact-root ~/.hermes/artifacts/queen
```

dry-run：

```bash
~/.hermes/skills/queen-dispatch/scripts/dispatcher.py \
    --plan <plan.json> --dry-run
```

## Resume / lock / force-release

Dispatcher 用 `fcntl.flock` 在 `<run_dir>/.lock` 上拿排他锁，防止同一 `run_id` 并发。
进程退出自动释放；mid-run kill 后锁文件可能残留。

| flag | 行为 |
|---|---|
| (default) | 若 `status.json` 已存在 → exit 2，提示用 `--resume` |
| `--resume` | 读 `status.json`：skip `done` / keep `blocked` / 记 `stale_running` / 不自动重试 `failed`（`on_failure=block` 会继续 block 下游） |
| `--no-resume` | 显式拒绝已有 status（与 default 同） |
| `--force-release` | 启动前 unlink 残留 `.lock`（进程已死时的恢复路径） |

锁冲突（另一进程仍持有）→ exit 5 + stderr `already running (lock held)`。

### 典型恢复

```bash
DISP=~/.hermes/skills/queen-dispatch/scripts/dispatcher.py
PLAN=examples/event-hub-ingest-plan.json

# mid-run kill 后：清锁 + 从 status.json 续跑
python3 $DISP --plan $PLAN --force-release --resume

# 全新 run（换 run_id，或先手动 rm -rf artifacts/queen/<run_id>）
python3 $DISP --plan $PLAN
```

### 证据

- `RunLock`：`scripts/dispatcher.py:96-140`（fcntl + force_release unlink）
- resume 状态机：`scripts/dispatcher.py:557-592`（done/blocked/running/failed）
- CLI：`scripts/dispatcher.py:802-807`（`--resume` / `--no-resume` / `--force-release`）
- 已知成功样例：`examples/event-hub-ingest-plan.json`（`--force-release --resume` 从 dry_run 续到 success）
- Event Hub 消费：`event-hub/scripts/hub.py ingest --source dispatcher --path <run>/events.jsonl`
- Queen B 状态决策：`scripts/queen_state.py list-runs|tail|decide|kanban`（读 status.json#counters + _event-log.jsonl + kanban.db，只读）

### 不变量

- resume 不重跑 `done` 任务
- resume 不自动重试 `failed`（保守；要重试就改 plan 或清 status）
- `--force-release` 只清锁文件，不改 status/events
- 并发第二实例拿不到锁 → exit 5，不覆盖

## Artifact layout

```text
~/.hermes/artifacts/queen/<run_id>/
  .lock
  normalized-plan.json
  status.json
  events.jsonl
  notify.jsonl
  summary.md
  status.json#counters          total_retries + retry_count + findings: {<task_id>:<fp8>: count}
  status.json#last_checkpoint_at   ISO8601 (when ≥ CHECKPOINT_INTERVAL_SECONDS elapsed)
  status.json#last_checkpoint_mono float (monotonic anchor, carried across --resume)
  tasks/<id>/{prompt.md,command.json,stdout.log,stderr.log,result.json,summary.md,gitlab_artifact}
```

Parent-facing stdout is one JSON line only:
`{"run_id":..., "run_status":..., "summary_path":...}`

## Out-of-scope（不要做）

- 不引入第三方 orchestrator
- 不给每个 agent 单独写 skill
- 不在 dispatcher 里调 LLM
- 不回灌 worker stdout 到主对话
- 保留 `scripts/dispatch_batch.py` 兼容旧接口

## 内置 subagent vs 外部 dispatcher（计数桥接）

- **内置 subagent**（`delegate_task`）不进 dispatcher `status.json#counters`；Queen 在 §轮速查表计数时自维护最小集 (task_id + fingerprint + retry_count)。
- **外部引擎**（codex/pi/opencode/shell/claude）走 dispatcher，`counters` 由 `status.json` 跟踪。
- **二选一**：同一 finding 的派单要么全走内置，要么全走外部，不混用（避免计数口径分裂）。
- 5 类 subagent vs 6 行 §舰队表：codex / pi / opencode / shell / claude-code 5 行外部 + hermes-agent 自身 1 行内置 = 6 行派单路径（per SOUL §舰队表 L139-150）。
- 若需把内置派单也纳入 counters，用 `dispatch_batch → delegate_task` 自动桥接（TODO: v29 实现）。


## Review-gate via dispatcher (L1 + L2)

After implementation, prefer a plan that ends with review-gate tasks:

| step | engine | role | purpose |
|---|---|---|---|
| implement | codex | implement | write code |
| l1-collect | shell | shell | pytest/lint/typecheck → review artifacts |
| l2-review | opencode | review | independent read-only review |
| l2-collect | shell | shell | write l2-review.json + decision.md |

Example: `examples/review-gate-l1-l2-plan.json`

Do not put L3 in the default MEDIUM plan. For HIGH, add a pi read_only task after L2.

## HIGH review-gate plan (Pi L3)

For `risk_level=HIGH`, append after L2:

| step | engine | role | mode |
|---|---|---|---|
| l3-pi-review | pi | review | read_only |
| l3-collect | shell | shell | write artifacts only |

Dispatcher forces Pi read-only tools to `read,grep,find,ls`; no bash/edit/write.
Example: `examples/review-gate-high-l3-plan.json`.

## HIGH L3 example plans

- Reusable template: `examples/review-gate-high-l3-plan.json`
- Known-good E2E sample: `examples/review-gate-high-l3-e2e-success.json`

Always dry-run first. Replace placeholders. Keep L1 summary inline for OpenCode L2.

## Runtime contract (counters / finding / checkpoint / replan / sandbox)

| 字段 | 落点 | 触发 | 不可变 |
|---|---|---|---|
| `counters.total_retries` | `status.json` | 任务 fail 时 += 1（含首次失败） | 跨 `--resume` 累加 |
| `counters.retry_count` | `status.json` | 任务本次执行前 prior_status 中已 failed 时 += 1 | 跨 `--resume` 累加；映射 SOUL "≤8 轮 per run" |
| `counters.findings` | `status.json` | `key = "<task_id>:<fp8>"`, `value = 重试次数` | fp 跨 run 稳定 |
| `finding_fingerprint()` | 内部 | sha256(规范化 stderr) 前 8 位 | 8 条正则去时间戳/pid/hex |
| `checkpoint.tick` | `events.jsonl` | 距上次 ≥ `CHECKPOINT_INTERVAL_SECONDS` (3600s) | 用 `time.monotonic()` |
| `last_checkpoint_at` | `status.json` | 同上 | ISO8601 |
| `last_checkpoint_mono` | `status.json` | 同上 | float (time.monotonic); 跨 --resume 持久化避免静默 |
| `replan` | `events.jsonl` | run 结束 `run_status ∈ {partial_success, failed}` | reason = `run_status=<status>` |
| `sandbox` | plan 顶层 → normalized → `build_command` | 默认 `fs:loose` | **v28 已强制**：plan.sandbox 映射 codex `-s`（`fs:strict/fs:loose→workspace-write`, `fs:read-only→read-only`）|
| `rollback_on_fail` | task 级 → normalized | 默认 `false`; 失败任务 summary.md 追加 `rollback: git checkout -- <project_root>` | **装饰字段**：仅文字提示，不真执行 git (v28 仍未硬化) |
| `verification_command` | task 级（可选） | 通过 `build_prompt` 注入 worker prompt 的 "## Verification" 段 | SOUL v28: per-task verify 透传; worker 跑完报 exit code |

旧 plan.json 不带这些字段仍能跑（向后兼容）。


