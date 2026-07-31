#!/usr/bin/env bash
# wiki-lint-daily cron: scan for stale pages + emit notify.
set -u
WIKI=~/hermes-wiki
HUB=~/.hermes/skills/queen-dispatch/event-hub/scripts/hub.py
STALE=0
NEW=0
for f in "$WIKI"/concepts/*.md "$WIKI"/projects/**/*.md; do
  [ -f "$f" ] || continue
  mtime=$(stat -f %m "$f" 2>/dev/null || echo 0)
  now=$(date +%s)
  age_days=$(( (now - mtime) / 86400 ))
  if [ "$age_days" -gt 90 ]; then
    STALE=$((STALE+1))
  else
    NEW=$((NEW+1))
  fi
done

echo "## wiki-lint-daily"
echo "scanned: $((STALE+NEW))"
echo "fresh: $NEW"
echo "stale (>90d): $STALE"
echo
echo "## event-hub notify (default)"
"$HOME/.hermes/bin/hermes-python" "$HUB" notify --policy default 2>&1 || echo "hub failed"
