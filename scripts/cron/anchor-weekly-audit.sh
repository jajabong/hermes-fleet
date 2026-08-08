#!/bin/bash
# anchor upstream weekly audit (v29.8 P1-1)
# 派 opencode 调研 github.com/jajabong/anchor 最近 7 天 commits
# 输出 /tmp/anchor-weekly-audit-{ts}.log + stdout
LOG="/tmp/anchor-weekly-audit-$(date +%Y%m%d-%H%M%S).log"
echo "=== anchor weekly audit (v29.8 P1-1) ===" > "$LOG"
echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
echo "" >> "$LOG"

# 1. 本地 anchor commits 最近 7 天
echo "--- Local anchor (since 7d ago) ---" >> "$LOG"
cd /Users/henry/anchor
SINCE=$(date -u -v-7d +%Y-%m-%d 2>/dev/null || date -u -d '7 days ago' +%Y-%m-%d)
git log --since="$SINCE" --oneline --no-merges 2>&1 | head -30 >> "$LOG"
LOCAL_COUNT=$(git log --since="$SINCE" --oneline --no-merges 2>&1 | wc -l | tr -d ' ')
echo "Local commits (7d): $LOCAL_COUNT" >> "$LOG"
echo "" >> "$LOG"

# 2. anchor remote github 上 origin/main vs 本地
echo "--- anchor local vs github/main ---" >> "$LOG"
git log --oneline github/main..HEAD 2>&1 | head -10 >> "$LOG"
AHEAD=$(git log --oneline github/main..HEAD 2>&1 | wc -l | tr -d ' ')
echo "Local ahead of github/main: $AHEAD commits" >> "$LOG"
echo "" >> "$LOG"

# 3. anchor 当前状态
echo "--- anchor working tree status ---" >> "$LOG"
git status -s 2>&1 | head -10 >> "$LOG"
echo "" >> "$LOG"

# 4. hermes-fleet 关联 audit 报告数
echo "--- hermes-wiki anchor-related audits ---" >> "$LOG"
ls -la /Users/henry/hermes-wiki/projects/anchor/ 2>/dev/null | head -10 >> "$LOG"
WIKI_COUNT=$(ls /Users/henry/hermes-wiki/projects/anchor/ 2>/dev/null | wc -l | tr -d ' ')
echo "Wiki anchor reports: $WIKI_COUNT" >> "$LOG"

echo "" >> "$LOG"
echo "Log: $LOG"
