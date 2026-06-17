from fastapi import FastAPI, Request, HTTPException
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TOKEN, WEBHOOK_URL, SECRET_PATH

from modules.math_module import register_math_handlers
from modules.graph_math_module import register_graph_math_handlers
from modules.data_science_module import register_data_science_handlers
from modules.physics_module import register_physics_handlers
from modules.astronomy_module import register_astronomy_handlers
from modules.chemistry_module import register_chemistry_handlers

from modules.photo_module import register_photo_handlers
from modules.news_module import register_news_handlers
from modules.fifa_module import register_fifa_handlers
from modules.group_activity_module import register_group_activity_handlers
from modules.downloader_module import register_downloader_handlers
from modules.birthday_module import register_birthday_handlers
from modules.game_module import register_game_handlers


# ------------------------------------------------------------
# Config checks
# ------------------------------------------------------------

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")

if not WEBHOOK_URL:
    raise RuntimeError("Missing WEBHOOK_URL environment variable.")


WEBHOOK_PATH = SECRET_PATH.strip("/") if SECRET_PATH else "telegram-webhook"
FULL_WEBHOOK_URL = f"{WEBHOOK_URL.rstrip('/')}/{WEBHOOK_PATH}"


# ------------------------------------------------------------
# Apps
# ------------------------------------------------------------

telegram_app = Application.builder().token(TOKEN).build()
api = FastAPI(title="AhBashin Telegram Bot")


# ------------------------------------------------------------
# Help texts
# ------------------------------------------------------------

def main_help_text() -> str:
    return (
        "AhBashin Bot 🦆\n\n"
        "The Telegram slash menu shows only category help commands to avoid Telegram's "
        "100-command limit. Hidden commands still work when typed manually.\n\n"
        "Main help menus:\n"
        "/mathhelp - math, plots, calculus, primes, Collatz, Fibonacci\n"
        "/graphhelp - graph theory, Dijkstra, shortest path, MST, convex hull\n"
        "/dshelp - data science, ML, CSV analysis, regression, PCA, forecasting\n"
        "/physicshelp - physics calculators and plots\n"
        "/astrohelp - astronomy, moon, planets, meteor showers\n"
        "/chemhelp - chemistry, elements, molar mass, balancing, pH, gas law\n"
        "/photohelp - photo tools\n"
        "/birthday_help - birthday manager\n"
        "/dart_help - dart game\n"
        "/downloader_help - X/Twitter downloader\n"
        "/wc_help - World Cup commands\n"
        "/news_help - news commands\n"
        "/activity_help - group activity commands\n\n"
        "Examples:\n"
        "/plot sin(x) range -6.28 6.28\n"
        "/poly_regression degree 2 | 1,2; 2,5; 3,10; 4,17; 5,26\n"
        "/forecast steps 5 | 10,12,13,15,18,21\n"
        "/projectile speed=20 angle=45\n"
        "/moonplot\n"
        "/molar_mass Ca(OH)2\n"
        "/balance C3H8 + O2 -> CO2 + H2O\n"
        "/dart\n"
    )


def wc_help_text() -> str:
    return (
        "World Cup commands ⚽\n\n"
        "/wc_today - today's World Cup matches\n"
        "/wc_tomorrow - tomorrow's World Cup matches\n"
        "/wc_live - live World Cup matches\n"
        "/wc_group A - group table, example group A\n"
        "/wc_standings - World Cup standings\n\n"
        "Examples:\n"
        "/wc_today\n"
        "/wc_group A\n"
    )


def news_help_text() -> str:
    return (
        "News commands 📰\n\n"
        "/trump - latest Trump news with English and Persian summary\n"
        "/trumpfile - send Trump news as a text file\n\n"
        "Examples:\n"
        "/trump\n"
        "/trumpfile\n"
    )


def activity_help_text() -> str:
    return (
        "Group activity commands 📊\n\n"
        "/activity_today - today's group activity\n"
        "/activity_week - last 7 days group activity\n"
        "/activity_month - last 30 days group activity\n"
        "/activity_year - activity since 1 January 2025\n"
        "/leaderboard - weekly group leaderboard\n"
        "/activity_chart - weekly activity chart\n"
        "/awards - weekly group awards\n\n"
        "Important:\n"
        "The bot can only count messages after the activity module is deployed.\n"
        "For full group tracking, turn off BotFather group privacy and re-add the bot to the group."
    )


# ------------------------------------------------------------
# Main command handlers
# ------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(main_help_text())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(main_help_text())


async def wc_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(wc_help_text())


async def news_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(news_help_text())


async def activity_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(activity_help_text())


# ------------------------------------------------------------
# Telegram visible slash-command menu
# Category/help commands only.
# ------------------------------------------------------------

async def setup_bot_commands() -> None:
    commands = [
        BotCommand("start", "Start bot"),
        BotCommand("help", "Show help"),

        BotCommand("mathhelp", "Math help"),
        BotCommand("graphhelp", "Graph theory help"),
        BotCommand("dshelp", "Data science help"),
        BotCommand("physicshelp", "Physics help"),
        BotCommand("astrohelp", "Astronomy help"),
        BotCommand("chemhelp", "Chemistry help"),
        BotCommand("photohelp", "Photo help"),
        BotCommand("birthday_help", "Birthday help"),
        BotCommand("dart_help", "Dart game help"),
        BotCommand("downloader_help", "Downloader help"),
        BotCommand("wc_help", "World Cup help"),
        BotCommand("news_help", "News help"),
        BotCommand("activity_help", "Group activity help"),
    ]

    await telegram_app.bot.set_my_commands(commands[:100])


# ------------------------------------------------------------
# Register all handlers
# ------------------------------------------------------------

def register_handlers() -> None:
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_command))

    telegram_app.add_handler(CommandHandler("wc_help", wc_help_command))
    telegram_app.add_handler(CommandHandler("news_help", news_help_command))
    telegram_app.add_handler(CommandHandler("activity_help", activity_help_command))

    register_math_handlers(telegram_app)
    register_graph_math_handlers(telegram_app)
    register_data_science_handlers(telegram_app)
    register_physics_handlers(telegram_app)
    register_astronomy_handlers(telegram_app)
    register_chemistry_handlers(telegram_app)

    register_fifa_handlers(telegram_app)
    register_news_handlers(telegram_app)
    register_downloader_handlers(telegram_app)
    register_birthday_handlers(telegram_app)
    register_game_handlers(telegram_app)
    register_photo_handlers(telegram_app)

    # Keep this near the end because it includes the silent group activity tracker.
    register_group_activity_handlers(telegram_app)


register_handlers()


# ------------------------------------------------------------
# FastAPI lifecycle
# ------------------------------------------------------------

@api.on_event("startup")
async def on_startup() -> None:
    await telegram_app.initialize()
    await telegram_app.start()

    await setup_bot_commands()

    await telegram_app.bot.set_webhook(
        url=FULL_WEBHOOK_URL,
        allowed_updates=Update.ALL_TYPES,
    )

    print(f"Webhook set to: {FULL_WEBHOOK_URL}")


@api.on_event("shutdown")
async def on_shutdown() -> None:
    await telegram_app.stop()
    await telegram_app.shutdown()


# ------------------------------------------------------------
# Web routes
# ------------------------------------------------------------

@api.get("/")
async def root():
    return {
        "status": "ok",
        "bot": "AhBashin Bot",
        "webhook": FULL_WEBHOOK_URL,
        "visible_command_menu": "category-only",
        "modules": {
            "math": True,
            "graph_math": True,
            "data_science": True,
            "physics": True,
            "astronomy": True,
            "chemistry": True,
            "photos": True,
            "world_cup": True,
            "news": True,
            "downloader": True,
            "birthdays": True,
            "games": True,
            "group_activity": True,
            "ai_photo": False,
        },
    }


@api.get("/health")
async def health():
    return {"status": "healthy"}


@api.post(f"/{WEBHOOK_PATH}")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)
    except Exception as error:
        print(f"Webhook processing error: {error}")
        return {"ok": False, "error": str(error)}

    return {"ok": True}