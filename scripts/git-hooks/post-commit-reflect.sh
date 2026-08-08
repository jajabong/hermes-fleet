#!/bin/bash
# hermes-fleet post-commit reflection hook (v29.8 P1-3)
# 每次 commit 后自动记录 pattern + 暴露的架构问题
# 输出 /tmp/hermes-fleet-post-commit-{ts}.log
LOG="/tmp/hermes-fleet-post-commit-$(date +%Y%m%d-%H%M%S).log"
echo "=== hermes-fleet post-commit reflection (v29.8 P1-3) ===" > "$LOG"
echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
echo "" >> "$LOG"

# 1. 最近 1 个 commit 信息
echo "--- Last commit ---" >> "$LOG"
git log -1 --pretty=full 2>&1 >> "$LOG"
echo "" >> "$LOG"

# 2. 改了什么文件
echo "--- Files changed ---" >> "$LOG"
git diff-tree --no-commit-id --name-only -r HEAD 2>&1 >> "$LOG"
FILES=$(git diff-tree --no-commit-id --name-only -r HEAD 2>&1 | wc -l | tr -d ' ')
echo "Files: $FILES" >> "$LOG"
echo "" >> "$LOG"

# 3. 改了多少行
echo "--- Diff stats ---" >> "$LOG"
git diff --stat HEAD~1..HEAD 2>&1 | tail -3 >> "$LOG"
INSERTIONS=$(git diff --shortstat HEAD~1..HEAD 2>&1 | grep -oE '[0-9]+ insertion' | grep -oE '[0-9]+')
DELETIONS=$(git diff --shortstat HEAD~1..HEAD 2>&1 | grep -oE '[0-9]+ deletion' | grep -oE '[0-9]+')
echo "Insertions: ${INSERTIONS:-0}, Deletions: ${DELETIONS:-0}" >> "$LOG"
echo "" >> "$LOG"

# 4. Commit message 分类 (pattern detection)
echo "--- Pattern classification ---" >> "$LOG"
MSG=$(git log -1 --pretty=%s 2>&1)
if echo "$MSG" | grep -qE "^feat"; then echo "Type: feature" >> "$LOG"; fi
if echo "$MSG" | grep -qE "^fix"; then echo "Type: bugfix" >> "$LOG"; fi
if echo "$MSG" | grep -qE "^docs"; then echo "Type: docs" >> "$LOG"; fi
if echo "$MSG" | grep -qE "^chore"; then echo "Type: chore" >> "$LOG"; fi
if echo "$MSG" | grep -qE "^audit"; then echo "Type: audit" >> "$LOG"; fi
if echo "$MSG" | grep -qE "v29"; then echo "Version: v29.x" >> "$LOG"; fi
if echo "$MSG" | grep -qE "NO_PROXY|mihomo"; then echo "Category: mihomo/proxy fix" >> "$LOG"; fi
if echo "$MSG" | grep -qE "kanban"; then echo "Category: Kanban integration" >> "$LOG"; fi
if echo "$MSG" | grep -qE "cron"; then echo "Category: cron job" >> "$LOG"; fi
echo "" >> "$LOG"

# 5. SOUL §Queen 架构观察 引用 (detect 如果 commit 提到)
echo "--- Cross-reference ---" >> "$LOG"
if echo "$MSG" | grep -qE "Queen 架构观察"; then
  echo "References: §Queen 架构观察" >> "$LOG"
fi
echo "" >> "$LOG"

# 6. SKILL.md auto-sync (repo skills/ → ~/.hermes/skills/)
echo "--- SKILL.md auto-sync ---" >> "$LOG"
SKILL_CHANGES=$(git diff-tree --no-commit-id --name-only -r HEAD 2>&1 | grep '^skills/.*/SKILL.md$' || true)
if [ -n "$SKILL_CHANGES" ]; then
  SYNC_COUNT=0
  for skill_file in $SKILL_CHANGES; do
    target="$HOME/.hermes/skills/${skill_file#skills/}"
    if [ -f "$skill_file" ]; then
      mkdir -p "$(dirname "$target")"
      cp "$skill_file" "$target"
      echo "Synced: $skill_file -> $target" >> "$LOG"
      SYNC_COUNT=$((SYNC_COUNT + 1))
    fi
  done
  echo "SKILL.md synced: $SYNC_COUNT file(s)" >> "$LOG"
else
  echo "SKILL.md changes: none" >> "$LOG"
fi
echo "" >> "$LOG"

echo "Log: $LOG"
