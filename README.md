# hermes-fleet

Henry 的 hermes-agent 自定义补丁与扩展。只装 *新东西*，原生 hermes-agent 更新就好。

## 目录

- `scripts/`：dispatcher.py 与 patch 后的派单/notify 输出（来自 `~/.hermes/skills/queen-dispatch/scripts/`）。
- `commits/`：每次对脚本级补丁的归档（commit message + diff + 完整文件快照）。
- `selftest/`：dispatcher 自检证据 — `notify-selftest`、`resume-truly` 的 `notify.jsonl` 与 `summary.md`。

## 引擎架构 (v29.21+)

dispatcher 支持 3 种引擎 + auto 路由：

| 引擎 | 用途 | 委派给 |
|---|---|---|
| `shell` | 直接子进程 | `task["argv"]` |
| `dsh` | 复杂工具 (Excel/PPT/Browser/Docker/DB) | `dsh-bridge/hermes_dsh_bridge.py` |
| `hermes` | 纯对话/轻量任务 (省 5-10x tokens) | `scripts/hermes_subagent.py` |
| `auto` | 关键字感知路由 | shell/dsh/hermes by argv + 插件关键字 |

`hermes_subagent.py` 是 stdlib-only 的直连 LLM 子代理（DeepSeek/MiniMax/Anthropic），
支持 7 个轻量工具（web_search/web_fetch/read_file/write_file/bash/list_dir/search_files）。
详见 `scripts/hermes_subagent.py` 文档。

## 与原生的边界

- 原生 hermes-agent (`NousResearch/hermes-agent`)：直接拉 release / 官方更新，不 fork。
- 本仓：只装 *patch* — 即"在原生之上、这次改了什么、为什么"。遇到新版原生时，本仓按 commit 顺序逐个 rebase/cherry-pick（或在新版上重写补丁）。

## 第一笔 patch

`fix-notify-collapse-double-append`：dispatcher 循环里 except 块外侧的 append_notify 误触发了"正常路径"的通知 → 现在只 crash 路径追加。详见 `commits/fix-notify-collapse-double-append_*.txt`。

## 自检结果

详见 `selftest/*.notify.json`。所有 `notify.jsonl` 行数与原始期望匹配，无 `runtime exception` 误报。

## 2026-07-31 48h tuning patch

`tune-48h-preflight-parser-runtime_*`:
- review-gate L2/L3 verdict parser accepts Markdown bold (`**Verdict: PASS**`, `### Verdict\n**PASS**`)
- `scripts/bin/hermes-python` wrapper forces Hermes venv Python 3.11
- cron scripts use hermes-python instead of system python3
- config note: `voice.auto_tts=false` for silent 48h background
- preflight baseline artifact lives under `~/.hermes/artifacts/verify-report-2026-07-31/`

See `commits/tune-48h-preflight-parser-runtime_*.txt` and `scripts/review-gate/`, `scripts/cron/`, `scripts/bin/`.
