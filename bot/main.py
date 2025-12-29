import logging
import json
import os
import sys

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

from bot.telegram_interface import BotInterface

def load_token():
    # Try reading from secrets.json
    if os.path.exists("secrets.json"):
        try:
            with open("secrets.json", "r") as f:
                data = json.load(f)
                return data.get("telegram_bot_token")
        except Exception as e:
            logger.error(f"Failed to read secrets.json: {e}")
    
    # Try env var as fallback (for dev)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        return token
        
    return None

def main():
    token = load_token()
    if not token:
        logger.error("No Telegram Bot Token found! Please create 'secrets.json' with {'telegram_bot_token': 'YOUR_TOKEN'}.")
        sys.exit(1)

    logger.info("Starting Trading Bot...")
    bot = BotInterface(token)
    bot.run()

if __name__ == '__main__':
    main()
