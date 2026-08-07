---
name: claude-code
description: "Delegate deep reasoning to Claude Code CLI (升级触发器: 上下文 >50k / pi 失败 / 链式判断 ≥3 层)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Claude, Anthropic, DeepReasoning, UpgradeTrigger]
    related_skills: [pi, codex, opencode, hermes-agent]
---

# Claude Code CLI

Delegate deep-reasoning / complex chains to [Claude Code](https://github.com/anthropics/claude-code). **Upgrade engine** — per SOUL §舰队表 L145 + §claude-code 升级触发器 L147-157, claude-code 仅在 pi 压不动时才派。

## When to Use (升级触发器)

**必升级（任一命中立刻升级）**:

- 上下文 >50k tokens (单任务描述 / 历史 / 引用总长)
- 前一轮 pi 失败 (verify 红 或 timeout >3min)

**建议升级（命中后优先考虑，可仍走 pi）**:

- 链式判断 ≥3 层 (e.g. A → B → C + 决策依赖)
- 任务涉架构权衡 / 失败调试 / 多步博弈

## Prerequisites

- Claude Code installed: `npm i -g @anthropic-ai/claude-code@latest`
- Auth: Anthropic API key in env, OR Claude Code OAuth (`claude auth login`)
- Verify: `claude --version` (current: 2.1.220+)

## One-Shot (Non-Interactive)

Per SOUL §舰队表 L145, default template:

```bash
claude -p "<goal>" --output-format json
```

`-p` / `--print` = non-interactive; `--output-format json` = machine-readable for dispatcher.

### Read-Only Variant

```bash
claude -p --allowedTools "Read,Grep,Glob,LS" "<review-goal>"
```

### With Extra Directories

```bash
claude -p --add-dir /path/to/repo "<goal>"
```

## Dispatcher Integration (v2.3+)

Claude is in `dispatcher.py:31 ENGINES = {"codex", "pi", "opencode", "shell", "claude"}` as of v2.3. When the dispatcher routes a task to `engine: "claude"`, `build_command` (dispatcher.py:441-450) constructs:

```python
["claude", "-p", prompt, "--output-format", "json", *task.get("extra_args", [])]
```

**This closes the gap**: before v2.3, §舰队表 had claude-code row but dispatcher.py would `raise ValueError`. Now both Queen-direct (`claude -p` shell) and dispatcher-routed work.

## Upgrade vs. Pi (Decision Rule)

Same model, different toolchain + context handling:

- **Default**: pi (cheaper, faster, Anchor-routed)
- **Upgrade to claude-code when**:
  - 上下文 >50k
  - pi verified red / timeout >3min
  - 链式判断 ≥3 层
  - 架构权衡 / 失败调试 / 多步博弈

Don't manually swap unless trigger fires; pi is the cheaper default.

## Pitfalls

- `claude` (without `-p`) starts **interactive session** — dispatcher calls must use `-p`.
- `--output-format json` makes output parseable; text mode dumps conversation transcript.
- `-p` 后加 positional prompt 即可；不要 `--prompt` flag (legacy)。
- OAuth users: `claude auth login` once, keychain cached. API-key users: `ANTHROPIC_API_KEY` env.
- `--bare` mode strips hooks/LSP/memory — useful in sandbox/CI contexts.
- `claude --resume` is interactive-only; one-shot jobs use `--session <id>` (rare).

## Verification

Smoke test:

```bash
claude -p "Respond with exactly: CLAUDE_SMOKE_OK" --output-format json
```

Success criteria: JSON output `{"result": "CLAUDE_SMOKE_OK"}` or text contains the marker, exit code 0.

## Rules

1. 永远带 `-p` + `--output-format json` for dispatcher context.
2. 默认走 pi; 升级触发器命中才走 claude-code.
3. Queen 直接 `claude -p` shell 调 与 dispatcher 派单 等价 (v2.3+).

## §Queen 协同协议 (v29.0)

### Abort / 打断规则 (SOUL §打断处理)
- 用户插话引用 task_id 或改了 goal → 立即 abort `claude -p` (subprocess kill, 安全)
- abort 半成品: claude-code 通常写 `--allowedTools` 受限目录, 即使半成品影响小; 但仍需 Queen 后续 git status 检查
- 不续 session (`--resume` 在 abort 后不要用, 默认 `--no-session`)
- v2.3+ dispatcher ENGINES 支持 claude, abort 走 dispatcher.status.json#counters 标准路径

### 与其他 worker 接力
- claude-code 用于"压不动时" (per §升级触发器), 通常不写代码
- 接力: pi → claude-code (升级) / claude-code → pi (回退失败后)
- 升级时 context 必传: pi 失败的 finding + verify 输出

### 沙箱边界
- dispatcher 派单: read_only → `--allowedTools Read,Grep,Glob,LS`; write → `--add-dir project_root` (per dispatcher.py:441-470)
- Queen 直接 shell: 默认全权限, 需 `--allowedTools` 自加