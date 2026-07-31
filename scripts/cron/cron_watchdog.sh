#!/usr/bin/env bash
# watchdog-heartbeat cron: run kanban dispatch + emit event-hub notify.
# Stderr/stdout both go to the job's output file so the agent pass is skipped.
set -u
HUB=~/.hermes/skills/queen-dispatch/event-hub/scripts/hub.py
LOG=~/.hermes/artifacts/queen/queen/_event-log.jsonl
MARK=~/.hermes/cron/output/watchdog-last.txt
date '+%Y-%m-%dT%H:%M:%S%z' > "$MARK"

DISPATCH_OUT="$(hermes kanban dispatch --max 5 2>&1)" || true
echo "## kanban dispatch" >> "$MARK"
echo "$DISPATCH_OUT" | tail -20 >> "$MARK"
echo >> "$MARK"

# Always run notify; if event-log missing, create empty dir first
mkdir -p "$(dirname "$LOG")"
echo "## event-hub notify default" >> "$MARK"
"$HOME/.hermes/bin/hermes-python" "$HUB" notify --policy default >> "$MARK" 2>&1 || echo "hub notify failed" >> "$MARK"
echo "## event-hub notify quiet" >> "$MARK"
"$HOME/.hermes/bin/hermes-python" "$HUB" notify --policy quiet >> "$MARK" 2>&1 || true
echo "## events.jsonl count" >> "$MARK"
find ~/.hermes/artifacts/queen -maxdepth 2 -name events.jsonl 2>/dev/null | wc -l >> "$MARK"
cat "$MARK"
