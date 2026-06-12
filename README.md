# LakLak Modular Telegram Bot

Project structure:

```text
main.py
config.py
utils.py
modules/
  math_module.py
  photo_module.py
  news_module.py
  fifa_module.py
```

Render start command:

```text
uvicorn main:api --host 0.0.0.0 --port $PORT
```

Required Render environment variables:

```text
TELEGRAM_BOT_TOKEN=your BotFather token
WEBHOOK_URL=https://your-render-service-name.onrender.com
SECRET_PATH=collatz-webhook
```

Optional variables:

```text
FOOTBALL_DATA_TOKEN=your football-data.org token
WORLD_CUP_COMPETITION=WC
WORLD_CUP_SEASON=2026
WORLD_CUP_EU_TIMEZONE=Europe/Berlin
WORLD_CUP_IRAN_TIMEZONE=Asia/Tehran
TRUMP_NEWS_QUERY=Trump latest news OR post OR tweet
TRUMP_NEWS_ITEMS=5
```
