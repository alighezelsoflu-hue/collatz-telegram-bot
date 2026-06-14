from fastapi import FastAPI, Request, HTTPException
from telegram import Update, BotCommand
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
from modules.ai_photo_module import register_ai_photo_handlers
from modules.news_module import register_news_handlers
from modules.fifa_module import register_fifa_handlers
from modules.group_activity_module import register_group_activity_handlers

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")


telegram_app = Application.builder().token(TOKEN).build()
api = FastAPI(title="LakLak Multi Tool Telegram Bot")


# ------------------------------------------------------------
# Start/help
# ------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "Hello! I am LakLak Bot.\n"
        "I can calculate math problems, edit photos, show World Cup 2026 info, and summarize news.\n\n"

        "Math:\n"
        "/collatz 27 - calculate Collatz and send all steps as a text file\n"
        "/fib 20 - calculate Fibonacci number F(20)\n"
        "/fibonacci 20 - same as /fib\n"
        "/fiblist 30 - send the first 30 Fibonacci numbers as a text file\n"
        "/stats 4 7 9 10 10 - calculate statistics\n"
        "/statsfile 4 7 9 10 10 - send complete statistics report as a text file\n"
        "/calc sin(pi / 2) - scientific calculator\n"
        "/pi - show pi number\n"
        "/e - show Euler's number\n"
        "/mathhelp - show calculator examples\n\n"

        "Photo tools:\n"
        "/enhance - improve brightness, contrast, color, and sharpness\n"
        "/vintage - vintage photo effect\n"
        "/bw - black and white photo\n"
        "/cinematic - cinematic photo look\n"
        "/clean - clean and sharpen photo\n"
        "/profile - square profile-style crop\n"
        "/cartoon - cartoon photo style\n"
        "/caricature - stronger caricature style\n"
        "/sticker - sticker-style PNG\n"
        "/beach - summer/beach filter\n"
        "/portrait - soft portrait focus effect\n"
        "/soft - soft dreamy filter\n"
        "/hdr - strong detail and contrast\n"
        "/photoinfo - show photo information\n"
        "/photohelp - show photo commands\n\n"

        "Free AI-style photo tools:\n"
        "/ai_enhance - local AI-style photo enhancement\n"
        "/ai_portrait - portrait look with soft background\n"
        "/ai_cartoon - cartoon style\n"
        "/ai_anime - anime-inspired style\n"
        "/ai_studio - studio portrait look\n"
        "/ai_background - blur and improve background style\n"
        "/ai_bg - same as /ai_background\n"
        "/ai_magic - colorful artistic transformation\n"
        "/ai_profile - square profile-style AI enhancement\n"
        "/ai_avatar - same as /ai_profile\n"
        "/ai_photohelp - show AI photo commands\n"
        "/ai_reset - reset AI photo mode\n\n"

        "World Cup 2026:\n"
        "/wc_today - today's matches in EU and Iran time\n"
        "/wc_tomorrow - tomorrow's matches in EU and Iran time\n"
        "/wc_live - live World Cup matches\n"
        "/wc_group A - Group A standings as a text file\n"
        "/wc_standings - all group standings as a text file\n\n"

        "News:\n"
        "/trump - latest Trump-related news with detailed English and Farsi report\n"
        "/trumpfile - send detailed Trump-related news as a text file\n\n"

        "Group activity:\n"
        "/activity_today - show today's group activity report\n"
        "/activity_week - show last 7 days group activity report\n"
        "/activity_month - show last 30 days group activity report\n"
        "/activity_year - show group activity since 1 January 2025\n"
        "/leaderboard - show most active members from last 7 days\n"
        "/activity_chart - send leaderboard chart as image\n"
        "/awards - fun weekly group awards\n\n"

        "/cancel - cancel current photo mode\n\n"
        "Tip: type / to see the command menu."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


# ------------------------------------------------------------
# Telegram command preview menu
# ------------------------------------------------------------

async def setup_bot_commands() -> None:
    commands = [
        BotCommand("start", "Show main menu"),
        BotCommand("help", "Show help menu"),

        BotCommand("activity_today", "Today group activity report"),
        BotCommand("activity_week", "Weekly group activity report"),
        BotCommand("activity_month", "Monthly group activity report"),
        BotCommand("activity_year", "Activity since Jan 1 2025"),
        BotCommand("leaderboard", "Most active members"),
        BotCommand("activity_chart", "Group activity chart"),
        BotCommand("awards", "Weekly group awards"),

        BotCommand("collatz", "Calculate Collatz sequence"),
        BotCommand("fib", "Calculate Fibonacci number"),
        BotCommand("fibonacci", "Calculate Fibonacci number"),
        BotCommand("fiblist", "Send Fibonacci series as file"),
        BotCommand("stats", "Calculate statistics"),
        BotCommand("statistics", "Calculate statistics"),
        BotCommand("statsfile", "Send statistics report as file"),
        BotCommand("calc", "Scientific calculator"),
        BotCommand("pi", "Show pi number"),
        BotCommand("e", "Show Euler number"),
        BotCommand("mathhelp", "Show math examples"),

        BotCommand("enhance", "Improve photo quality"),
        BotCommand("vintage", "Vintage photo effect"),
        BotCommand("bw", "Black and white photo"),
        BotCommand("cinematic", "Cinematic photo look"),
        BotCommand("clean", "Clean and sharpen photo"),
        BotCommand("profile", "Square profile photo"),
        BotCommand("cartoon", "Cartoon photo effect"),
        BotCommand("caricature", "Caricature photo effect"),
        BotCommand("sticker", "Sticker style image"),
        BotCommand("beach", "Summer beach photo effect"),
        BotCommand("portrait", "Portrait photo effect"),
        BotCommand("soft", "Soft photo effect"),
        BotCommand("hdr", "HDR photo effect"),
        BotCommand("photoinfo", "Show photo information"),
        BotCommand("photohelp", "Show photo commands"),

        BotCommand("ai_enhance", "Free AI-style enhance"),
        BotCommand("ai_portrait", "Free AI-style portrait"),
        BotCommand("ai_cartoon", "Free AI-style cartoon"),
        BotCommand("ai_anime", "Free AI-style anime"),
        BotCommand("ai_studio", "Free AI-style studio"),
        BotCommand("ai_background", "Free AI-style background"),
        BotCommand("ai_bg", "Free AI-style background"),
        BotCommand("ai_magic", "Free AI-style magic"),
        BotCommand("ai_profile", "Free AI-style profile"),
        BotCommand("ai_avatar", "Free AI-style avatar"),
        BotCommand("ai_photohelp", "Show AI photo commands"),
        BotCommand("ai_reset", "Reset AI photo mode"),

        BotCommand("wc_today", "World Cup matches today"),
        BotCommand("wc_tomorrow", "World Cup matches tomorrow"),
        BotCommand("wc_live", "Live World Cup matches"),
        BotCommand("wc_group", "World Cup group standings"),
        BotCommand("wc_standings", "All World Cup standings"),

        BotCommand("trump", "Latest Trump news summary"),
        BotCommand("trumpfile", "Trump news report file"),

        BotCommand("cancel", "Cancel current photo mode"),
    ]

    await telegram_app.bot.set_my_commands(commands)


# ------------------------------------------------------------
# Register handlers
# ------------------------------------------------------------

def register_handlers() -> None:
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_command))

    register_math_handlers(telegram_app)
    register_fifa_handlers(telegram_app)
    register_news_handlers(telegram_app)

    # Normal photo handler group=1, AI photo handler group=2.
    # Normal photo handler ignores ai_ modes, so AI photo handler can process them.
    register_photo_handlers(telegram_app)
    register_ai_photo_handlers(telegram_app)

    register_group_activity_handlers(telegram_app)


register_handlers()


# ------------------------------------------------------------
# FastAPI lifecycle
# ------------------------------------------------------------

@api.on_event("startup")
async def startup() -> None:
    await telegram_app.initialize()
    await telegram_app.start()

    await setup_bot_commands()

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


# ------------------------------------------------------------
# FastAPI routes
# ------------------------------------------------------------

@api.get("/")
async def root():
    return {
        "status": "ok",
        "message": "LakLak multi-tool Telegram bot is running.",
        "usage": [
            "/start",
            "/help",

            "/collatz 27",
            "/fib 20",
            "/fibonacci 20",
            "/fiblist 30",
            "/stats 4 7 9 10 10",
            "/stats 4, pi, sin(pi / 2), log(100, 10)",
            "/statsfile 4 7 9 10 10",
            "/calc sin(pi / 2)",
            "/pi",
            "/e",
            "/mathhelp",

            "/enhance",
            "/vintage",
            "/bw",
            "/cinematic",
            "/clean",
            "/profile",
            "/cartoon",
            "/caricature",
            "/sticker",
            "/beach",
            "/portrait",
            "/soft",
            "/hdr",
            "/photoinfo",
            "/photohelp",

            "/ai_enhance",
            "/ai_portrait",
            "/ai_cartoon",
            "/ai_anime",
            "/ai_studio",
            "/ai_background",
            "/ai_bg",
            "/ai_magic",
            "/ai_profile",
            "/ai_avatar",
            "/ai_photohelp",
            "/ai_reset",

            "/wc_today",
            "/wc_tomorrow",
            "/wc_live",
            "/wc_group A",
            "/wc_standings",

            "/trump",
            "/trumpfile",

            "/cancel",
        ],
        "modules": {
            "math": True,
            "photo": True,
            "ai_photo_free_local": True,
            "news": True,
            "fifa": True,
        },
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