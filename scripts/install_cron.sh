#!/usr/bin/env bash
# Install a daily cron job. By default it RENDERS today's post and waits for you
# to review + publish (matches publish.mode: review). For fully automatic posting
# set AUTO=1 (requires the MCP server to be running + logged in).
#
#   bash scripts/install_cron.sh                 # 10:00 daily, render-only
#   HOUR=9 MIN=30 bash scripts/install_cron.sh    # custom time
#   AUTO=1 bash scripts/install_cron.sh           # render AND auto-publish
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v "${PYTHON:-python3}")"
HOUR="${HOUR:-10}"; MIN="${MIN:-0}"
FLAG=""; [ "${AUTO:-0}" = "1" ] && FLAG=" --auto"

MARKER="# auto_xhs daily"
LINE="$MIN $HOUR * * * cd $ROOT && $PY run.py run-daily$FLAG >> $ROOT/state/cron.log 2>&1 $MARKER"

# Replace any existing auto_xhs line, then append the new one.
EXISTING="$(crontab -l 2>/dev/null | grep -v "$MARKER" || true)"
printf '%s\n%s\n' "$EXISTING" "$LINE" | sed '/^$/d' | crontab -

echo "installed cron entry:"
echo "  $LINE"
[ -z "$FLAG" ] && echo "(render-only; review then 'python run.py publish <date>'. Set AUTO=1 to auto-post.)"
echo "remove with: crontab -e  (delete the line marked '$MARKER')"
