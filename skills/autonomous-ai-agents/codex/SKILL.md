---
name: codex
description: "Delegate coding to OpenAI Codex CLI (features, PRs)."
version: 1.0.1
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Codex, OpenAI, Code-Review, Refactoring]
    related_skills: [claude-code, hermes-agent]
---

# Codex CLI

Delegate coding tasks to [Codex](https://github.com/openai/codex) via the Hermes terminal. Codex is OpenAI's autonomous coding agent CLI.

## When to use

- Building features
- Refactoring
- PR reviews
- Batch issue fixing

Requires the codex CLI and a git repository.

## Prerequisites

- Codex installed: `npm install -g @openai/codex`
- OpenAI auth configured: either `OPENAI_API_KEY` or Codex OAuth credentials
  from the Codex CLI login flow
- **Must run inside a git repository** — Codex refuses to run outside one
- Use `pty=true` in terminal calls — Codex is an interactive terminal app

For Hermes itself, `model.provider: openai-codex` uses Hermes-managed Codex
OAuth from `~/.hermes/auth.json` after `hermes auth add openai-codex`. For the
standalone Codex CLI, a valid CLI OAuth session may live under
`~/.codex/auth.json`; do not treat a missing `OPENAI_API_KEY` alone as proof
that Codex auth is missing.

## One-Shot Tasks

```
terminal(command="codex exec 'Add dark mode toggle to settings'", workdir="~/project", pty=true)
```

For scratch work (Codex needs a git repo):
```
terminal(command="cd $(mktemp -d) && git init && codex exec 'Build a snake game in Python'", pty=true)
```

## Background Mode (Long Tasks)

```
# Start in background with PTY
terminal(command="codex exec --sandbox workspace-write 'Refactor the auth module'", workdir="~/project", background=true, pty=true)
# Returns session_id

# Monitor progress
process(action="poll", session_id="<id>")
process(action="log", session_id="<id>")

# Send input if Codex asks a question
process(action="submit", session_id="<id>", data="yes")

# Kill if needed
process(action="kill", session_id="<id>")
```

## Key Flags

| Flag | Effect |
|------|--------|
| `exec "prompt"` | One-shot execution, exits when done |
| `--sandbox workspace-write` (`-s`) | Sandboxed but auto-approves file changes in the workspace (the recommended auto-build mode) |
| `--dangerously-bypass-approvals-and-sandbox` | No sandbox, no approvals (fastest, most dangerous; `--yolo` still works as a hidden alias) |
| `--sandbox danger-full-access` | No Codex sandbox; useful when the host service context breaks bubblewrap |

> **Deprecated:** `--full-auto` still works but the live CLI warns to use `--sandbox workspace-write` instead.

## Hermes Gateway Caveat

When invoking the Codex CLI from a Hermes gateway/service context (for example,
Telegram-driven agent sessions), Codex `workspace-write` sandboxing may fail even
when the same command works in the user's interactive shell. A typical symptom is
bubblewrap/user-namespace errors such as `setting up uid map: Permission denied`
or `loopback: Failed RTM_NEWADDR: Operation not permitted`.

In that context, prefer:

```
codex exec --sandbox danger-full-access "<task>"
```

Use process boundaries as the safety layer instead: explicit `workdir`, clean git
status before launch, narrow task prompts, `git diff` review, targeted tests, and
human/agent confirmation before committing broad changes.

## PR Reviews

Clone to a temp directory for safe review:

```
terminal(command="REVIEW=$(mktemp -d) && git clone https://github.com/user/repo.git $REVIEW && cd $REVIEW && gh pr checkout 42 && codex review --base origin/main", pty=true)
```

## Parallel Issue Fixing with Worktrees

```
# Create worktrees
terminal(command="git worktree add -b fix/issue-78 /tmp/issue-78 main", workdir="~/project")
terminal(command="git worktree add -b fix/issue-99 /tmp/issue-99 main", workdir="~/project")

# Launch Codex in each
terminal(command="codex --sandbox workspace-write exec 'Fix issue #78: <description>. Commit when done.'", workdir="/tmp/issue-78", background=true, pty=true)
terminal(command="codex --sandbox workspace-write exec 'Fix issue #99: <description>. Commit when done.'", workdir="/tmp/issue-99", background=true, pty=true)

# Monitor
process(action="list")

# After completion, push and create PRs
terminal(command="cd /tmp/issue-78 && git push -u origin fix/issue-78")
terminal(command="gh pr create --repo user/repo --head fix/issue-78 --title 'fix: ...' --body '...'")

# Cleanup
terminal(command="git worktree remove /tmp/issue-78", workdir="~/project")
```

## Batch PR Reviews

```
# Fetch all PR refs
terminal(command="git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'", workdir="~/project")

# Review multiple PRs in parallel
terminal(command="codex exec 'Review PR #86. git diff origin/main...origin/pr/86'", workdir="~/project", background=true, pty=true)
terminal(command="codex exec 'Review PR #87. git diff origin/main...origin/pr/87'", workdir="~/project", background=true, pty=true)

# Post results
terminal(command="gh pr comment 86 --body '<review>'", workdir="~/project")
```

## Rules

1. **Always use `pty=true`** — Codex is an interactive terminal app and hangs without a PTY
2. **Git repo required** — Codex won't run outside a git directory. Use `mktemp -d && git init` for scratch
3. **Use `exec` for one-shots** — `codex exec "prompt"` runs and exits cleanly
4. **`--sandbox workspace-write` for building** — auto-approves changes within the sandbox (`--full-auto` is deprecated for this)
5. **Background for long tasks** — use `background=true` and monitor with `process` tool
6. **Don't interfere** — monitor with `poll`/`log`, be patient with long-running tasks
7. **Parallel is fine** — run multiple Codex processes at once for batch work

## §Queen 协同协议 (v29.0)

### 何时被 Queen 派
- SOUL §舰队表 L141: 写功能 / 修 bug / PR — 默认 worker
- 写代码路径首选；Queen 决策树 §1 "简单/确定" 也可能直跑不派

### Queen 派单时该传什么
- `goal`: 实现描述 (e.g. "实现 X 功能, 改 src/foo.py:10")
- `context`: file:line 引用 + 期望行为 (不要 paste 完整文件, 派单 §硬规则 L5)
- `execution_mode`: "write" 默认; 调研任务用 "read_only"
- 隔离边界 (派单 §硬规则 L4): workdir: <abs path>; writable: [<glob>]; forbidden: [<abs path|glob>]

### 该期待什么产出
- `summary.md`: 改了哪些文件 + 验证结果
- `status.json#exit_code`: 0=绿, 非0=红
- `--json -o <last-message>` 自动落 review artifact (per SOUL §舰队表 L141 注释)

### 沙箱边界
- `read_only`: `-s read-only` — 只读 + 跑测试, 不能改文件
- `write`: `-s workspace-write` — 默认, 项目内可写
- v28.3+ plan.sandbox 字段 enforce: `fs:strict` / `fs:loose` 都映射 workspace-write; `fs:read-only` 映射 read-only

### Verify 责任分工
- worker 跑 Queen 在 task 里给的 `verification_command`, 报 exit code
- Queen 复核 exit code 不重跑 (派单 §硬规则 L2)

### 升级触发器
- codex → claude-code: 上下文 >50k token, 或前一轮 verify 红 + 调试需架构权衡
- codex → pi: 通常不升级, codex 已是写代码最优
- 默认不走降级 (codex 写不了才降级 pi/opencode 调研)

### Abort / 打断规则 (SOUL §打断处理)
- 用户插话引用 task_id/file: → 立即 abort, 改动丢弃 (默认)
- 用户插话改 goal → Queen 重派, 不修改当前 task
- abort 半成品: 还没写文件 → 安全; 正在写 → 留垃圾 → Queen 后续 git status 检查

### 与其他 worker 接力
- codex 写完 → 通常接 **opencode** L2 review (per queen-dispatch/SKILL.md L200-209 review-gate)
- HIGH risk → 接 **pi** L3 review
- 接力时 context 必传: codex 改了哪些文件 + 验证结果
