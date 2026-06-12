import os

MAX_INPUT = 10**12

# Telegram / Render
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SECRET_PATH = os.getenv("SECRET_PATH", "telegram-webhook")

# football-data.org
FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN") or os.getenv("FOOTBALL_API_KEY")
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"
WORLD_CUP_COMPETITION = os.getenv("WORLD_CUP_COMPETITION", "WC")
WORLD_CUP_SEASON = int(os.getenv("WORLD_CUP_SEASON", "2026"))

# Time zones
EU_TIMEZONE = os.getenv("WORLD_CUP_EU_TIMEZONE", "Europe/Berlin")
IRAN_TIMEZONE = os.getenv("WORLD_CUP_IRAN_TIMEZONE", "Asia/Tehran")

# News
TRUMP_NEWS_QUERY = os.getenv("TRUMP_NEWS_QUERY", "Trump latest news OR post OR tweet")
TRUMP_NEWS_ITEMS = int(os.getenv("TRUMP_NEWS_ITEMS", "5"))
