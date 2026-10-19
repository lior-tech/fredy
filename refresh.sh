#!/bin/zsh
# Daily refresh for Fredy's dashboard. Run unattended by launchd.
# Scans the market, publishes prices/measures/recommendations, deploys.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")" || exit 1
LOG="$HOME/Library/Logs/fredy-refresh.log"
echo "=== $(date) starting ===" >> "$LOG"
export SSL_CERT_FILE="$(python3 -c 'import certifi;print(certifi.where())' 2>/dev/null)"
rm -f data/.scanskip.json
# the sweep takes ~40 minutes; run it to completion
python3 scripts/build_ideas.py >> "$LOG" 2>&1
./deploy.sh "Daily refresh $(date -u +%Y-%m-%d)" >> "$LOG" 2>&1
echo "=== $(date) done ===" >> "$LOG"
