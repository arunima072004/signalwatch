#!/usr/bin/env bash
# scripts/start_live.sh
# Usage: ./scripts/start_live.sh [interval_minutes]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INTERVAL_MINUTES="${1:-360}"
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/live.log"
echo "SignalWatch live loop: interval=$INTERVAL_MINUTES min, log=$LOG"
while true; do
  echo "[$(date '%Y-%m-%d %H:%M:%S')] Starting cycle" | tee -a "$LOG"
  python "$ROOT/scripts/run_cycle.py" --source channel3 --provider cached 2>&1 | tee -a "$LOG"
  sleep $(( INTERVAL_MINUTES * 60 ))
done
