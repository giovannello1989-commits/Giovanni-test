#!/bin/bash
set -euo pipefail

# Double-click this file on macOS to install + auto-start bot on login.
# It will open Terminal and guide you.

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

echo "== Trading Bot (macOS) installer =="
echo "Project: $ROOT_DIR"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3 first (e.g. from python.org)."
  exit 1
fi

echo "Creating virtualenv..."
python3 -m venv .venv

echo "Installing dependencies..."
source .venv/bin/activate
python3 -m pip install --upgrade pip >/dev/null
python3 -m pip install -r requirements.txt

SECRETS_FILE="$ROOT_DIR/secrets.json"
if [ ! -f "$SECRETS_FILE" ]; then
  echo
  echo "Telegram Bot Token is required."
  echo "Paste it now (it will be saved locally in secrets.json):"
  read -r TOKEN
  cat > "$SECRETS_FILE" <<EOF
{
  "telegram_bot_token": "$TOKEN"
}
EOF
  echo "Created: $SECRETS_FILE"
else
  echo "Found existing secrets.json"
fi

echo
echo "IMPORTANT (Revolut X): put your Ed25519 private key file as:"
echo "  $ROOT_DIR/private.pem"
echo "Then on Telegram wizard when asked for private key, reply: -"
echo

PLIST_ID="com.tradingbot.revolutx"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_ID}.plist"
LOG_DIR="$HOME/Library/Logs"
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${PLIST_ID}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>${ROOT_DIR}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${ROOT_DIR}/.venv/bin/python3</string>
    <string>-m</string>
    <string>bot.main</string>
  </array>
  <key>StandardOutPath</key><string>${LOG_DIR}/tradingbot.out.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/tradingbot.err.log</string>
</dict>
</plist>
EOF

echo "Installed LaunchAgent: $PLIST_PATH"

echo "Loading LaunchAgent (auto-start now + on login)..."
launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo
echo "DONE."
echo "Now open Telegram and send: /start"
echo "Status command: /status"
echo
echo "Logs:"
echo "  $LOG_DIR/tradingbot.out.log"
echo "  $LOG_DIR/tradingbot.err.log"
echo
read -r -p "Press Enter to close..."
