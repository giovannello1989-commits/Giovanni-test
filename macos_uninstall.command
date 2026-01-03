#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_ID="com.tradingbot.revolutx"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_ID}.plist"

echo "== Trading Bot (macOS) uninstall =="

if [ -f "$PLIST_PATH" ]; then
  echo "Stopping LaunchAgent..."
  launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
  rm -f "$PLIST_PATH"
  echo "Removed: $PLIST_PATH"
else
  echo "No LaunchAgent found at: $PLIST_PATH"
fi

echo
echo "Optional: you can delete the project folder if you want:"
echo "  $ROOT_DIR"
echo
read -r -p "Press Enter to close..."
