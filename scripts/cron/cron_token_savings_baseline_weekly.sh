#!/bin/bash
# token savings baseline weekly (v29.8 follow-up to audit-v29.8-token-savings.md)
# 每周一跑, 记录 1d/7d/30d 窗口的 total_tokens / tool_calls / avg_session
# Aug 15+ 才有干净窗口 (v29.8 commits 在 Aug 08 落地, 需 7 天后回归)
# 0 LLM token, no_agent cron
set -u

LOG="/tmp/cron-token-savings-baseline-$(date +%Y%m%d-%H%M%S).log"
WIKI=~/hermes-wiki
TS=$(date +%Y-%m-%d)

exec > "$LOG" 2>&1
echo "=== token savings baseline weekly (v29.8 follow-up) ==="
echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Sample date: $TS"
echo ""

# 1. 跑 hermes insights 1d/7d/30d
echo "--- 1. hermes insights (1d/7d/30d) ---"
for d in 1 7 30; do
  echo ""
  echo "[window=${d}d]"
  python3 /Users/henry/scratch/hermes-fleet/scripts/auto_run.py insights --days $d
done
echo ""

# 2. 解析 + 检查长会话污染
echo "--- 2. parse + long session check (>4h) ---"
python3 /tmp/parse_insights.py 2>&1
echo ""

# 3. 写 hermes-wiki checkpoint
echo "--- 3. write hermes-wiki checkpoint ---"
CKPT="$WIKI/projects/hermes/checkpoints/${TS}-token-baseline.md"
mkdir -p "$(dirname "$CKPT")"
python3 /tmp/write_checkpoint.py "$TS" "$CKPT" 2>&1

echo ""
echo "Log: $LOG"