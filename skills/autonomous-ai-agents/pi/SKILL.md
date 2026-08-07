---
name: pi
description: "Delegate coding to pi-anchor CLI (通用多轮/精简探索, default via Anchor 路由)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Pi, Anchor, MultiTurn]
    related_skills: [codex, opencode, hermes-agent]
---

# Pi / pi-anchor CLI

Delegate coding/general tasks to [Pi](https://github.com/badlogic/pi-mono) via the Hermes terminal. Pi is a CLI coding assistant with read/bash/edit/write tools; **pi-anchor** is the Hermes-flavored wrapper that defaults to the Anchor provider (Claude 系 model via Anchor routing).

## When to Use

- 通用 / 多轮 / 精简探索 (per SOUL §舰队表 L142)
- L2/L3 review where read-only tools (`read,grep,find,ls`) suffice
- CHEAP parallel review (single model, free or near-free tier)
- 不需要 codex 的 Git-PR 流程 / 不需要 opencode 的 free 模型池

## Prerequisites

- pi-anchor installed: `npm i -g pi-anchor@latest` (or via Hermes profile setup)
- Auth: Anchor API key in env (handled by Hermes config)
- Verify: `pi-anchor --version`

## One-Shot (Non-Interactive)

Per SOUL §舰队表 L142, default template:

```bash
pi-anchor -p --provider anchor --model anchor --mode json --no-session \
  --tools read,grep,find,ls,bash,edit,write "<goal>"
```

`--mode json` makes output machine-readable for dispatcher `status.json#summaries`.
`--no-session` keeps it ephemeral (no session resume state).

### Read-Only Variant (L2 review)

```bash
pi-anchor -p --provider anchor --model anchor --mode json --no-session \
  --tools read,grep,find,ls "<review-goal>"
```

## Interactive Sessions (Background)

For multi-turn iteration, start pi TUI in background:

```bash
pi-anchor --mode text --no-session
```

Send prompts via stdin; exit with Ctrl+D.

## Dispatcher Integration

Pi is in `dispatcher.py:31 ENGINES = {"codex", "pi", "opencode", "shell", "claude"}`. When the dispatcher routes a task to `engine: "pi"`, `build_command` (dispatcher.py:424-435) constructs the same command template above. Sandbox:

- `execution_mode: "read_only"` → `--tools read,grep,find,ls`
- `execution_mode: "write"` → `--tools read,grep,find,ls,bash,edit,write`

## Pitfalls

- `--provider anchor --model anchor` 是 Hermes 默认；不要手写其他 provider，会绕过 Anchor 计费/审计。
- `--mode json` 不是 text — 没有 json 时输出会污染 dispatcher `status.json` 解析。
- `--no-session` 默认开；想续 session 改成 `--session <id>`（一般不要）。
- pi 默认系统提示词是 "coding assistant"，可用 `--append-system-prompt` 覆盖。

## Verification

Smoke test:

```bash
pi-anchor -p --provider anchor --model anchor --mode json --no-session \
  --tools read,grep,find,ls "Respond with exactly: PI_SMOKE_OK"
```

Success criteria: stdout contains `PI_SMOKE_OK` and exit code 0.

## Rules

1. 默认模板走 `pi-anchor`（不是裸 `pi`），保证走 Anchor provider。
2. 精简多轮场景优先用 pi；超过 50k token 或 pi 上一轮失败 → 升级到 claude-code。
3. dispatcher `build_command` 已在管 sandbox；Queen 不必手传 `--tools`。

## §Queen 协同协议 (v29.0)

### 何时被 Queen 派
- SOUL §舰队表 L142: 通用 / 多轮 / 精简探索 — 默认 worker
- L2/L3 review where read-only tools (`read,grep,find,ls`) suffice
- CHEAP parallel review (Anchor-routed, free or near-free tier)

### Queen 派单时该传什么
- `goal`: 探索目标 (e.g. "找 X 文件的入口函数")
- `context`: file:line 引用 + 探索方向
- `execution_mode`: "read_only" 默认; 写代码不用 pi (那是 codex)
- `--tools`: dispatcher 自动管 (read_only → `read,grep,find,ls`)

### 该期待什么产出
- `summary.md`: 探索结论 + path:line 引用
- `--mode json` 让 stdout 可被 dispatcher 解析

### 沙箱边界
- read_only 默认 (`--tools read,grep,find,ls`)
- write: `--tools read,grep,find,ls,bash,edit,write` (Queen 不应派 pi 写)

### Verify 责任分工
- worker 跑 Queen 在 task 里给的 `verification_command`, 报 exit code
- Queen 复核 exit code 不重跑

### 升级触发器 (per SOUL §claude-code 升级触发器 L147-157)
- pi → claude-code: 上下文 >50k, 或前一轮 pi verify 红 + timeout >3min
- 链式判断 ≥3 层 / 架构权衡 / 失败调试 → 建议升级
- 不要手动 swap, 触发器命中才升级

### Abort / 打断规则 (SOUL §打断处理)
- 用户插话引用 task_id → 立即 kill `pi-anchor` subprocess
- 探索任务无文件副作用, abort 安全
- dispatcher 派单: abort 走 status.json#counters; Queen 直接 shell: 手动 kill

### 与其他 worker 接力
- pi 通常独立使用 (精简多轮不需要接力)
- 升级路径: pi → claude-code (压不动时)
- 接力时 context 必传: pi 失败的 finding + verify 输出
4. 退出 pi TUI 用 Ctrl+D 或 `process(action="kill")`，不要 `exit`。