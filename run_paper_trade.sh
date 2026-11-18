#!/bin/zsh
# Scheduled daily paper-trading run (see paper_trade.py). Writes a dated log.
cd "$(dirname "$0")" || exit 1
LOG="paper_trading/logs/$(date +%Y-%m-%d).log"
mkdir -p paper_trading/logs
{ echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="; ./venv/bin/python paper_trade.py; echo "exit code $?"; } >> "$LOG" 2>&1
