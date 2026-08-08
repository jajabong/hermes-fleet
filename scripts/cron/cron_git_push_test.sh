#!/bin/bash
# git-push auto-regression (v29.8 P1 #9 fix verification)
# 跑 hermes-fleet scripts/tests/test_auto_run_git_push.py + 真实推 hermes-fleet/hermes-wiki
# 输出 /tmp/cron-git-push-test-{ts}.log
set -u

LOG="/tmp/cron-git-push-test-$(date +%Y%m%d-%H%M%S).log"
echo "=== git-push auto-regression (v29.8 P1 #9) ===" > "$LOG"
echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
echo "" >> "$LOG"

# 1. 跑 pytest
echo "--- 1. pytest scripts/tests/test_auto_run_git_push.py ---" >> "$LOG"
cd /Users/henry/scratch/hermes-fleet
python3 -m pytest scripts/tests/test_auto_run_git_push.py -v --tb=short 2>&1 | tee -a "$LOG" | tail -15
PYTEST_RC=${PIPESTATUS[0]}
echo "pytest exit: $PYTEST_RC" >> "$LOG"
echo "" >> "$LOG"

# 2. 真实推 hermes-fleet (auto_run.py git-push)
echo "--- 2. auto_run.py git-push hermes-fleet ---" >> "$LOG"
python3 scripts/auto_run.py git-push --repo-dir /Users/henry/scratch/hermes-fleet 2>&1 | tee -a "$LOG" | tail -10
FLEET_RC=${PIPESTATUS[0]}
echo "hermes-fleet push exit: $FLEET_RC" >> "$LOG"
echo "" >> "$LOG"

# 3. 真实推 hermes-wiki
echo "--- 3. auto_run.py git-push hermes-wiki ---" >> "$LOG"
python3 scripts/auto_run.py git-push --repo-dir ~/hermes-wiki 2>&1 | tee -a "$LOG" | tail -10
WIKI_RC=${PIPESTATUS[0]}
echo "hermes-wiki push exit: $WIKI_RC" >> "$LOG"
echo "" >> "$LOG"

# 4. 总结
echo "--- Summary ---" >> "$LOG"
if [ "$PYTEST_RC" = "0" ] && [ "$FLEET_RC" = "0" ] && [ "$WIKI_RC" = "0" ]; then
  echo "STATUS: PASS (3/3)" >> "$LOG"
else
  echo "STATUS: FAIL (pytest=$PYTEST_RC fleet=$FLEET_RC wiki=$WIKI_RC)" >> "$LOG"
fi

echo "Log: $LOG"