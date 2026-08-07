---
name: opencode
description: "Delegate coding to OpenCode CLI (features, PR review)."
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, OpenCode, Autonomous, Refactoring, Code-Review]
    related_skills: [claude-code, codex, hermes-agent]
---

# OpenCode CLI

Use [OpenCode](https://opencode.ai) as an autonomous coding worker orchestrated by Hermes terminal/process tools. OpenCode is a provider-agnostic, open-source AI coding agent with a TUI and CLI.

## When to Use

- User explicitly asks to use OpenCode
- You want an external coding agent to implement/refactor/review code
- You need long-running coding sessions with progress checks
- You want parallel task execution in isolated workdirs/worktrees

## Prerequisites

- OpenCode installed: `npm i -g opencode-ai@latest` or `brew install anomalyco/tap/opencode`
- Auth configured: `opencode auth login` or set provider env vars (OPENROUTER_API_KEY, etc.)
- Verify: `opencode auth list` should show at least one provider
- Git repository for code tasks (recommended)
- `pty=true` for interactive TUI sessions

## Binary Resolution (Important)

Shell environments may resolve different OpenCode binaries. If behavior differs between your terminal and Hermes, check:

```
terminal(command="which -a opencode")
terminal(command="opencode --version")
```

If needed, pin an explicit binary path:

```
terminal(command="$HOME/.opencode/bin/opencode run '...'", workdir="~/project", pty=true)
```

## One-Shot Tasks

Use `opencode run` for bounded, non-interactive tasks:

```
terminal(command="opencode run 'Add retry logic to API calls and update tests'", workdir="~/project")
```

Attach context files with `-f`:

```
terminal(command="opencode run 'Review this config for security issues' -f config.yaml -f .env.example", workdir="~/project")
```

Show model thinking with `--thinking`:

```
terminal(command="opencode run 'Debug why tests fail in CI' --thinking", workdir="~/project")
```

Force a specific model:

```
terminal(command="opencode run 'Refactor auth module' --model openrouter/anthropic/claude-sonnet-4", workdir="~/project")
```

## Interactive Sessions (Background)

For iterative work requiring multiple exchanges, start the TUI in background:

```
terminal(command="opencode", workdir="~/project", background=true, pty=true)
# Returns session_id

# Send a prompt
process(action="submit", session_id="<id>", data="Implement OAuth refresh flow and add tests")

# Monitor progress
process(action="poll", session_id="<id>")
process(action="log", session_id="<id>")

# Send follow-up input
process(action="submit", session_id="<id>", data="Now add error handling for token expiry")

# Exit cleanly — Ctrl+C
process(action="write", session_id="<id>", data="\x03")
# Or just kill the process
process(action="kill", session_id="<id>")
```

**Important:** Do NOT use `/exit` — it is not a valid OpenCode command and will open an agent selector dialog instead. Use Ctrl+C (`\x03`) or `process(action="kill")` to exit.

### TUI Keybindings

| Key | Action |
|-----|--------|
| `Enter` | Submit message (press twice if needed) |
| `Tab` | Switch between agents (build/plan) |
| `Ctrl+P` | Open command palette |
| `Ctrl+X L` | Switch session |
| `Ctrl+X M` | Switch model |
| `Ctrl+X N` | New session |
| `Ctrl+X E` | Open editor |
| `Ctrl+C` | Exit OpenCode |

### Resuming Sessions

After exiting, OpenCode prints a session ID. Resume with:

```
terminal(command="opencode -c", workdir="~/project", background=true, pty=true)  # Continue last session
terminal(command="opencode -s ses_abc123", workdir="~/project", background=true, pty=true)  # Specific session
```

## Common Flags

| Flag | Use |
|------|-----|
| `run 'prompt'` | One-shot execution and exit |
| `--continue` / `-c` | Continue the last OpenCode session |
| `--session <id>` / `-s` | Continue a specific session |
| `--agent <name>` | Choose OpenCode agent (build or plan) |
| `--model provider/model` | Force specific model |
| `--format json` | Machine-readable output/events |
| `--file <path>` / `-f` | Attach file(s) to the message |
| `--thinking` | Show model thinking blocks |
| `--variant <level>` | Reasoning effort (high, max, minimal) |
| `--title <name>` | Name the session |
| `--attach <url>` | Connect to a running opencode server |

## Procedure

1. Verify tool readiness:
   - `terminal(command="opencode --version")`
   - `terminal(command="opencode auth list")`
2. For bounded tasks, use `opencode run '...'` (no pty needed).
3. For iterative tasks, start `opencode` with `background=true, pty=true`.
4. Monitor long tasks with `process(action="poll"|"log")`.
5. If OpenCode asks for input, respond via `process(action="submit", ...)`.
6. Exit with `process(action="write", data="\x03")` or `process(action="kill")`.
7. Summarize file changes, test results, and next steps back to user.

## PR Review Workflow

OpenCode has a built-in PR command:

```
terminal(command="opencode pr 42", workdir="~/project", pty=true)
```

Or review in a temporary clone for isolation:

```
terminal(command="REVIEW=$(mktemp -d) && git clone https://github.com/user/repo.git $REVIEW && cd $REVIEW && opencode run 'Review this PR vs main. Report bugs, security risks, test gaps, and style issues.' -f $(git diff origin/main --name-only | head -20 | tr '\n' ' ')", pty=true)
```

## Parallel Work Pattern

Use separate workdirs/worktrees to avoid collisions:

```
terminal(command="opencode run 'Fix issue #101 and commit'", workdir="/tmp/issue-101", background=true, pty=true)
terminal(command="opencode run 'Add parser regression tests and commit'", workdir="/tmp/issue-102", background=true, pty=true)
process(action="list")
```

## Session & Cost Management

List past sessions:

```
terminal(command="opencode session list")
```

Check token usage and costs:

```
terminal(command="opencode stats")
terminal(command="opencode stats --days 7 --models anthropic/claude-sonnet-4")
```

## Pitfalls

- Interactive `opencode` (TUI) sessions require `pty=true`. The `opencode run` command does NOT need pty.
- `/exit` is NOT a valid command — it opens an agent selector. Use Ctrl+C to exit the TUI.
- PATH mismatch can select the wrong OpenCode binary/model config.
- If OpenCode appears stuck, inspect logs before killing:
  - `process(action="log", session_id="<id>")`
- Avoid sharing one working directory across parallel OpenCode sessions.
- Enter may need to be pressed twice to submit in the TUI (once to finalize text, once to send).

## Verification

Smoke test:

```
terminal(command="opencode run 'Respond with exactly: OPENCODE_SMOKE_OK'")
```

Success criteria:
- Output includes `OPENCODE_SMOKE_OK`
- Command exits without provider/model errors
- For code tasks: expected files changed and tests pass

## Rules

1. Prefer `opencode run` for one-shot automation — it's simpler and doesn't need pty.
2. Use interactive background mode only when iteration is needed.
3. Always scope OpenCode sessions to a single repo/workdir.
4. For long tasks, provide progress updates from `process` logs.
5. Report concrete outcomes (files changed, tests, remaining risks).
6. Exit interactive sessions with Ctrl+C or kill, never `/exit`.

## §Queen 协同协议 (v29.0)

### 何时被 Queen 派
- SOUL §舰队表 L143: 调研 / 源码 / 并行 review — 高频 L2 review engine (per audit ~13 次历史)
- 默认 free 模型 (`kilocode/kilo-auto/free`), 备选 `opencode/laguna-s-2.1-free` / `opencode/nemotron-3-ultra-free`

### Queen 派单时该传什么
- `goal`: 调研目标 (e.g. "找出 X 函数所有调用点")
- `context`: file:line 引用 + 调研方向 (不要 paste 完整文件)
- `execution_mode`: "read_only" 默认 (L2 review 是只读)
- `model`: 默认 `kilocode/kilo-auto/free`; 复杂链可换 `laguna`/`nemotron`

### 该期待什么产出
- `summary.md`: 调研结论 + path:line 引用
- 决策证据 (派单 §决策树 依赖调研结论时)
- L2 review verdict: PASS / FAIL / NEEDS_WORK

### 沙箱边界
- L2 review 必须 read_only — `execution_mode: "read_only"`, 默认
- write 模式 → 需显式声明 (通常不该派 opencode 写代码, 那是 codex 的事)

### Verify 责任分工
- L2 review: opencode 跑 review, 写 verdict; Queen 读 verdict 决策 PASS/FAIL
- 调研: opencode 给结论; Queen 复核证据 path:line (派单 §硬规则 L2 不重跑)

### 升级触发器
- opencode → claude-code: 链式判断 ≥3 层 (per SOUL §claude-code 升级触发器 L153-155)
- opencode → pi: 通常不切换, opencode free 模型够用
- 默认不走降级 (opencode 调研受阻才升级)

### Abort / 打断规则 (SOUL §打断处理)
- 调研中途用户改问题 → 立即 kill 当前 session, 不保留中间结论 (调研没写文件, 安全)
- 用户插话引用 task_id → abort

### 限流报告规范 (v29.2)
- 当 model 被 rate-limited (HTTP 429 / quota exceeded / "rate_limit" 错误), opencode **必须** stderr 输出 `rate_limited: <model_id>` 单行
- 限流时尝试 fallback model (kilocode/... → opencodezen/... → anchor)，记录 fallback 链
- 若所有 fallback 都限流, 输出 `rate_limited: all_models_failed` 到 stderr, exit 75 (rate_limit exit code)
- dispatcher 检测到 `rate_limited:` stderr 行会标 finding_key 让 Queen 决定: 重派换 model / 重派同 model 等待 / 报用户
- Queen 不需要 worker 默默重试到死 — 限流是 Queen 重派决策信号, 不是 worker 内部循环
- 参考: SOUL §Queen 架构观察 #4, dispatcher.py v29.2 限流检测

### 与其他 worker 接力
- **L2 review 接力**: codex 写完 → opencode review (per queen-dispatch/SKILL.md L200-209)
- **并行 review**: 多 issue 并行派 opencode (per §Parallel Work Pattern)
- 接力时 context 必传: codex 改了哪些文件 + 期望行为
