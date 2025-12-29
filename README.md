# Automated Trading Bot

A fully automated trading bot controlled via Telegram.

## Features

- **Crypto Trading**: Automates trading on Revolut X (spot only).
- **Stock Alerts**: Monitors fiat markets and sends alerts.
- **Safety**: STRICT 100 USDC capital limit. No leverage.
- **Telegram Wizard**: Zero-config setup via Telegram.
- **Static IP**: Auto-provisioning logic included.

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configuration**:
   Create a file named `secrets.json` in the root directory:
   ```json
   {
       "telegram_bot_token": "YOUR_TELEGRAM_BOT_TOKEN"
   }
   ```

3. **Run**:
   ```bash
   python3 -m bot.main
   ```

4. **Telegram Setup**:
   - Open your bot in Telegram.
   - Send `/start`.
   - Follow the wizard instructions.

## Deployment on Google Cloud

1. Create a VM instance.
2. Clone this repo.
3. Install dependencies.
4. Set up `secrets.json`.
5. Run the bot (use `nohup` or `systemd` to keep it running).

## Commands

- `/start` - Run setup wizard
- `/status` - Check bot status
- `/balance` - Check current exposure
- `/emergency_stop` - Stop all trading immediately
- `/resume` - Resume trading
- `/logs` - View recent activity
