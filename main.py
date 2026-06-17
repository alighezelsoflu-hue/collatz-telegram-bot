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


# Optional modules. The bot will still deploy if an optional module is not present yet.
MODULE_STATUS = {"math": True}

try:
    from modules.graph_math_module import register_graph_math_handlers
    MODULE_STATUS["graph_math"] = True
except Exception as error:
    register_graph_math_handlers = None
    MODULE_STATUS["graph_math"] = f"disabled: {error}"

try:
    from modules.data_science_module import register_data_science_handlers
    MODULE_STATUS["data_science"] = True
except Exception as error:
    register_data_science_handlers = None
    MODULE_STATUS["data_science"] = f"disabled: {error}"

try:
    from modules.physics_module import register_physics_handlers
    MODULE_STATUS["physics"] = True
except Exception as error:
    register_physics_handlers = None
    MODULE_STATUS["physics"] = f"disabled: {error}"

try:
    from modules.photo_module import register_photo_handlers
    MODULE_STATUS["photo"] = True
except Exception as error:
    register_photo_handlers = None
    MODULE_STATUS["photo"] = f"disabled: {error}"

try:
    from modules.news_module import register_news_handlers
    MODULE_STATUS["news"] = True
except Exception as error:
    register_news_handlers = None
    MODULE_STATUS["news"] = f"disabled: {error}"

try:
    from modules.fifa_module import register_fifa_handlers
    MODULE_STATUS["fifa"] = True
except Exception as error:
    register_fifa_handlers = None
    MODULE_STATUS["fifa"] = f"disabled: {error}"

try:
    from modules.group_activity_module import register_group_activity_handlers
    MODULE_STATUS["group_activity"] = True
except Exception as error:
    register_group_activity_handlers = None
    MODULE_STATUS["group_activity"] = f"disabled: {error}"

try:
    from modules.downloader_module import register_downloader_handlers
    MODULE_STATUS["downloader"] = True
except Exception as error:
    register_downloader_handlers = None
    MODULE_STATUS["downloader"] = f"disabled: {error}"

try:
    from modules.birthday_module import register_birthday_handlers
    MODULE_STATUS["birthdays"] = True
except Exception as error:
    register_birthday_handlers = None
    MODULE_STATUS["birthdays"] = f"disabled: {error}"

try:
    from modules.game_module import register_game_handlers
    MODULE_STATUS["games"] = True
except Exception as error:
    register_game_handlers = None
    MODULE_STATUS["games"] = f"disabled: {error}"


if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable")

api = FastAPI()
telegram_app = Application.builder().token(TOKEN).build()
_handlers_registered = False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    text = (
        "Hi! I am LakLak Bot.\n\n"
        "The Telegram slash-command menu is now category based, so it stays under Telegram's 100-command limit.\n"
        "All registered commands still work if you type them manually.\n\n"
        "Main help menus:\n"
        "/mathhelp - math, functions, plotting, primes, Collatz, Fibonacci\n"
        "/graphhelp - graph theory and convex hull\n"
        "/dshelp - data science and CSV analysis\n"
        "/physicshelp - physics calculators and plots\n"
        "/photohelp - photo tools\n"
        "/birthday_help - birthday commands\n"
        "/dart_help - dart game commands\n"
        "/downloader_help - X/Twitter downloader help\n"
        "/wc_help - World Cup commands\n"
        "/news_help - news commands\n"
        "/activity_help - group activity commands\n\n"
        "Quick examples:\n"
        "/calc sin(pi / 2) + sqrt(16)\n"
        "/plot sin(x) range -6.28 6.28\n"
        "/dijkstra A D | A B 4; A C 2; C B 1; B D 5\n"
        "/data_summary 4, 7, 9, 10, 10, 12\n"
        "/kinematics u=0 a=9.8 t=5\n"
        "/birthdays\n"
        "/dart\n"
    )

    await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def wc_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "World Cup commands:\n\n"
        "/wc_today - World Cup matches today\n"
        "/wc_tomorrow - World Cup matches tomorrow\n"
        "/wc_live - live World Cup matches\n"
        "/wc_group A - World Cup group table\n"
        "/wc_standings - World Cup standings"
    )


async def news_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "News commands:\n\n"
        "/trump - latest Trump news with Farsi translation\n"
        "/trumpfile - same report as a text file"
    )


async def activity_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "Group activity commands:\n\n"
        "/activity_today - today's group activity\n"
        "/activity_week - last 7 days\n"
        "/activity_month - last 30 days\n"
        "/activity_year - since 1 January 2025\n"
        "/leaderboard - group leaderboard\n"
        "/activity_chart - leaderboard chart\n"
        "/awards - weekly awards\n\n"
        "Note: the bot can only track messages after it is added and privacy mode is configured."
    )


async def setup_bot_commands() -> None:
    # Keep the visible Telegram slash-command menu category based.
    # Telegram allows a maximum of 100 commands in setMyCommands.
    # All other handlers still work if users type commands manually.
    commands = [
        BotCommand("start", "Start bot"),
        BotCommand("help", "Show help"),
        BotCommand("mathhelp", "Math help"),
        BotCommand("graphhelp", "Graph theory help"),
        BotCommand("dshelp", "Data science help"),
        BotCommand("physicshelp", "Physics help"),
        BotCommand("photohelp", "Photo help"),
        BotCommand("birthday_help", "Birthday help"),
        BotCommand("dart_help", "Dart game help"),
        BotCommand("downloader_help", "Downloader help"),
        BotCommand("wc_help", "World Cup help"),
        BotCommand("news_help", "News help"),
        BotCommand("activity_help", "Group activity help"),
    ]

    await telegram_app.bot.set_my_commands(commands[:100])


def register_handlers() -> None:
    global _handlers_registered
    if _handlers_registered:
        return

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_command))
    telegram_app.add_handler(CommandHandler("wc_help", wc_help_command))
    telegram_app.add_handler(CommandHandler("news_help", news_help_command))
    telegram_app.add_handler(CommandHandler("activity_help", activity_help_command))

    register_math_handlers(telegram_app)

    if register_graph_math_handlers:
        register_graph_math_handlers(telegram_app)
    if register_data_science_handlers:
        register_data_science_handlers(telegram_app)
    if register_physics_handlers:
        register_physics_handlers(telegram_app)
    if register_fifa_handlers:
        register_fifa_handlers(telegram_app)
    if register_news_handlers:
        register_news_handlers(telegram_app)
    if register_downloader_handlers:
        register_downloader_handlers(telegram_app)
    if register_birthday_handlers:
        register_birthday_handlers(telegram_app)
    if register_game_handlers:
        register_game_handlers(telegram_app)
    if register_photo_handlers:
        register_photo_handlers(telegram_app)
    if register_group_activity_handlers:
        register_group_activity_handlers(telegram_app)

    _handlers_registered = True


@api.on_event("startup")
async def on_startup() -> None:
    register_handlers()
    await telegram_app.initialize()
    await setup_bot_commands()

    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{SECRET_PATH}"
        await telegram_app.bot.set_webhook(webhook_url)
        print(f"Webhook set to: {webhook_url}")

    await telegram_app.start()


@api.on_event("shutdown")
async def on_shutdown() -> None:
    await telegram_app.stop()
    await telegram_app.shutdown()


@api.get("/")
async def root():
    return {
        "status": "ok",
        "bot": "LakLak Telegram Bot",
        "webhook_path": f"/{SECRET_PATH}",
        "world_cup": {
            "competition": WORLD_CUP_COMPETITION,
            "season": WORLD_CUP_SEASON,
            "eu_timezone": EU_TIMEZONE,
            "iran_timezone": IRAN_TIMEZONE,
        },
        "modules": MODULE_STATUS,
    }


@api.post(f"/{SECRET_PATH}")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)

    return {"ok": True}
