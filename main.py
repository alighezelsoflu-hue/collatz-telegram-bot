from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
    TOKEN,
    WEBHOOK_URL,
    SECRET_PATH,
    WORLD_CUP_COMPETITION,
    WORLD_CUP_SEASON,
    EU_TIMEZONE,
    IRAN_TIMEZONE,
)

from modules.math_module import register_math_handlers
from modules.photo_module import register_photo_handlers
from modules.news_module import register_news_handlers
from modules.fifa_module import register_fifa_handlers


if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")


telegram_app = Application.builder().token(TOKEN).build()
api = FastAPI(title="LakLak Multi Tool Telegram Bot")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "Hello! I can calculate math sequences, edit photos, show World Cup 2026 info, and summarize Trump-related news.\n\n"
        "Math:\n"
        "/collatz 27 - calculate Collatz and send all steps as a text file\n"
        "/fib 20 - calculate Fibonacci number F(20)\n"
        "/fibonacci 20 - same as /fib\n"
        "/fiblist 30 - send the first 30 Fibonacci numbers as a text file\n"
        "/stats 4 7 9 10 10 - calculate mean, median, mode, variance, std dev, quartiles\n"
        "/statistics 4 7 9 10 10 - same as /stats\n"
        "/statsfile 4 7 9 10 10 - send a complete statistics report as a text file\n"
        "/calc sin(pi / 2) - scientific calculator\n"
        "/calc log(100, 10) - logarithm calculator\n"
        "/calc sqrt(144) - square root calculator\n"
        "/pi - show pi number\n"
        "/e - show Euler's number\n"
        "/mathhelp - show calculator examples\n\n"
        "Photos:\n"
        "/vintage - send a photo and I make it vintage\n"
        "/cartoon - send a photo and I make it cartoon style\n"
        "/caricature - send a photo and I make it fun caricature style\n"
        "/sticker - send a photo and I make it sticker style\n"
        "/beach - send a photo and I make it summer/beach style\n\n"
        "World Cup 2026:\n"
        "/wc_today - today's matches in EU and Iran time\n"
        "/wc_tomorrow - tomorrow's matches in EU and Iran time\n"
        "/wc_live - live World Cup matches\n"
        "/wc_group A - Group A standings as a text file\n"
        "/wc_standings - all group standings as a text file\n\n"
        "News:\n"
        "/trump - latest Trump-related news with detailed summaries and Farsi translation\n"
        "/trumpfile - send detailed Trump-related news as a text file\n\n"
        "/cancel - cancel current photo mode"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


def register_handlers() -> None:
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_command))

    register_math_handlers(telegram_app)
    register_fifa_handlers(telegram_app)
    register_news_handlers(telegram_app)
    register_photo_handlers(telegram_app)


register_handlers()


@api.on_event("startup")
async def startup() -> None:
    await telegram_app.initialize()
    await telegram_app.start()

    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{SECRET_PATH}"
        await telegram_app.bot.set_webhook(url=webhook_url)
        print(f"Webhook set to: {webhook_url}")
    else:
        print("WEBHOOK_URL is not set. App is running, but Telegram webhook was not configured.")


@api.on_event("shutdown")
async def shutdown() -> None:
    await telegram_app.stop()
    await telegram_app.shutdown()


@api.get("/")
async def root():
    return {
        "status": "ok",
        "message": "LakLak multi-tool Telegram bot is running.",
        "usage": [
            "/collatz 27",
            "/wc_today",
            "/wc_tomorrow",
            "/wc_live",
            "/wc_group A",
            "/wc_standings",
            "/trump",
            "/vintage",
            "/cartoon",
            "/caricature",
            "/sticker",
            "/beach",
        ],
        "football_provider": "football-data.org",
        "world_cup_competition": WORLD_CUP_COMPETITION,
        "world_cup_season": WORLD_CUP_SEASON,
        "timezones": {
            "central_europe": EU_TIMEZONE,
            "iran": IRAN_TIMEZONE,
        },
    }


@api.head("/")
async def head_root():
    return {}


@api.post("/{path}")
async def telegram_webhook(path: str, request: Request):
    if path != SECRET_PATH:
        raise HTTPException(status_code=404, detail="Not found")

    data = await request.json()
    update = Update.de_json(data=data, bot=telegram_app.bot)

    await telegram_app.process_update(update)

    return {"ok": True}