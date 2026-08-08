#!/bin/bash
# hermes-agent upstream weekly report (v29.8 P1-2)
# 调研 NousResearch/hermes-agent 最近 7d commits + releases
# 输出 /tmp/hermes-agent-upstream-weekly-{ts}.log
LOG="/tmp/hermes-agent-upstream-weekly-$(date +%Y%m%d-%H%M%S).log"
echo "=== hermes-agent upstream weekly report (v29.8 P1-2) ===" > "$LOG"
echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
echo "" >> "$LOG"

# 1. 本地 hermes-agent 当前版本
echo "--- Local hermes-agent ---" >> "$LOG"
HERMES_DIR="/Users/henry/.hermes/hermes-agent"
cd "$HERMES_DIR" 2>/dev/null || { echo "hermes-agent dir not found"; exit 1; }
LOCAL_HEAD=$(git log --oneline -1 2>&1 | head -1)
LOCAL_BRANCH=$(git branch --show-current 2>&1)
LOCAL_TAGS=$(git tag --sort=-creatordate 2>&1 | head -5)
echo "Branch: $LOCAL_BRANCH" >> "$LOG"
echo "Head:   $LOCAL_HEAD" >> "$LOG"
echo "Tags:   $LOCAL_TAGS" >> "$LOG"
echo "" >> "$LOG"

# 2. 本地 vs upstream
echo "--- Local vs upstream (NousResearch/hermes-agent) ---" >> "$LOG"
git fetch upstream 2>&1 | head -3 >> "$LOG" || true
git fetch origin 2>&1 | head -3 >> "$LOG" || true
BEHIND=$(git rev-list --count HEAD..upstream/main 2>/dev/null || echo "n/a")
AHEAD=$(git rev-list --count upstream/main..HEAD 2>/dev/null || echo "n/a")
echo "Local behind upstream: $BEHIND commits" >> "$LOG"
echo "Local ahead of upstream: $AHEAD commits" >> "$LOG"
echo "" >> "$LOG"

# 3. 工作区状态
echo "--- Working tree status ---" >> "$LOG"
git status -s 2>&1 | head -10 >> "$LOG"
WORKTREE_DIRTY=$(git status -s 2>&1 | wc -l | tr -d ' ')
echo "Dirty files: $WORKTREE_DIRTY" >> "$LOG"
echo "" >> "$LOG"

# 4. 我们 patch 过的 hermes-agent 仓 + fork
echo "--- Patches (jajabong fork + hermes-fleet) ---" >> "$LOG"
FORKS=$(grep -c '"upstream"' /Users/henry/scratch/hermes-fleet/SOUL.md 2>/dev/null || echo 0)
echo "hermes-fleet SOUL mentions upstream: $FORKS" >> "$LOG"

# 5. cron 已经存在 jobs
echo "--- Existing hermes cron jobs ---" >> "$LOG"
crontab -l 2>/dev/null | grep -c "^.*\bhermes\|insights\|monitor\|kanban" 2>/dev/null || echo 0
echo "Cron jobs (hermes-related): $(crontab -l 2>/dev/null | grep -E 'hermes|insights|monitor|kanban' | wc -l | tr -d ' ')" >> "$LOG"

echo "" >> "$LOG"
echo "Log: $LOG"
