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


# Optional modules. The bot will still deploy if a module is not present yet.
MODULE_STATUS = {"math": True}

try:
    from modules.photo_module import register_photo_handlers
    MODULE_STATUS["photo"] = True
except Exception as error:
    register_photo_handlers = None
    MODULE_STATUS["photo"] = f"disabled: {error}"

try:
    from modules.ai_photo_module import register_ai_photo_handlers
    MODULE_STATUS["ai_photo"] = True
except Exception as error:
    register_ai_photo_handlers = None
    MODULE_STATUS["ai_photo"] = f"disabled: {error}"

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
        "Hi! I am AhBashin Bot.\n\n"
        "Math:\n"
        "/calc sin(pi / 2) + sqrt(16) - calculator\n"
        "/collatz 27 - Collatz sequence\n"
        "/collatzplot 27 - plot Collatz sequence\n"
        "/fib 100 - Fibonacci number\n"
        "/fiblist 20 - Fibonacci list\n"
        "/fibspiral 10 - draw Fibonacci spiral\n"
        "/stats 4, pi, 4, sin(pi/2), 7, 2 - statistics\n"
        "/polyroots 1 -5 6 - find polynomial roots\n"
        "/polyplot 1 -5 6 range -2 8 - plot polynomial\n"
        "/primes 100 - primes less than n\n"
        "/primesfile 10000 - primes as text file\n"
        "/plot sin(x) range -6.28 6.28 - plot function\n"
        "/derivative x^3 - 2*x at 2 - numerical derivative\n"
        "/tangent x^3 - 2*x at 2 - tangent plot\n"
        "/integral x^2 from 0 to 3 - numerical integral\n"
        "/areaplot sin(x) from 0 to 3.14 - area plot\n"
        "/newton x^3 - x - 2 start 1 - Newton method plot\n"
        "/primecount 1000 - prime counting plot\n"
        "/primegap 500 - prime gap plot\n"
        "/polarplot 1 + sin(theta) range 0 6.28 - polar plot\n"
        "/paramplot cos(t); sin(t) range 0 6.28 - parametric plot\n"
        "/mathhelp - full math help\n\n"
        "World Cup:\n"
        "/wc_today - World Cup matches today\n"
        "/wc_tomorrow - World Cup matches tomorrow\n"
        "/wc_live - live World Cup matches\n"
        "/wc_group A - World Cup group table\n"
        "/wc_standings - World Cup standings\n\n"
        "News:\n"
        "/trump - latest Trump news with Farsi translation\n"
        "/trumpfile - news report as file\n\n"
        "Downloads:\n"
        "/download <X/Twitter link> - download video when available\n"
        "/audio <X/Twitter link> - audio when available\n"
        "/downloader_help - downloader help\n\n"
        "Birthdays:\n"
        "/add_birthday Ali 1990-05-12 - save birthday\n"
        "/birthdays - show saved birthdays\n"
        "/next_birthday - upcoming birthdays\n"
        "/birthday_today - birthdays today\n"
        "/remove_birthday Ali - remove birthday\n\n"
        "Games:\n"
        "/dart - throw one dart\n"
        "/dart_battle - start dart battle\n"
        "/join_dart - join dart battle\n"
        "/start_dart - start battle throws\n"
        "/dart_top - dart tournament scoreboard\n\n"
        "Group activity:\n"
        "/activity_today - today activity\n"
        "/activity_week - last 7 days\n"
        "/activity_month - last 30 days\n"
        "/activity_year - since 1 January 2025\n"
        "/leaderboard - group leaderboard\n"
        "/activity_chart - chart\n"
        "/awards - weekly awards\n\n"
        "Photo tools:\n"
        "/photohelp - normal photo effects\n"
        "/ai_photohelp - AI-style photo effects\n"
    )

    await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def setup_bot_commands() -> None:
    commands = [
        BotCommand("start", "Start bot"),
        BotCommand("help", "Show help"),
        BotCommand("mathhelp", "Math help"),
        BotCommand("calc", "Scientific calculator"),
        BotCommand("collatz", "Collatz sequence"),
        BotCommand("collatzplot", "Plot Collatz sequence"),
        BotCommand("fib", "Fibonacci number"),
        BotCommand("fiblist", "Fibonacci list"),
        BotCommand("fibspiral", "Fibonacci spiral"),
        BotCommand("stats", "Statistics"),
        BotCommand("statsfile", "Statistics as file"),
        BotCommand("polyroots", "Find polynomial roots"),
        BotCommand("roots", "Find polynomial roots"),
        BotCommand("polyplot", "Plot polynomial"),
        BotCommand("plotpoly", "Plot polynomial"),
        BotCommand("primes", "Prime numbers less than n"),
        BotCommand("primesfile", "Prime numbers as file"),
        BotCommand("plot", "Plot function"),
        BotCommand("derivative", "Numerical derivative"),
        BotCommand("tangent", "Tangent line plot"),
        BotCommand("integral", "Numerical integral"),
        BotCommand("areaplot", "Area under curve plot"),
        BotCommand("newton", "Newton method"),
        BotCommand("primecount", "Prime counting plot"),
        BotCommand("primegap", "Prime gap plot"),
        BotCommand("polarplot", "Polar plot"),
        BotCommand("paramplot", "Parametric plot"),
        BotCommand("wc_today", "World Cup matches today"),
        BotCommand("wc_tomorrow", "World Cup matches tomorrow"),
        BotCommand("wc_live", "Live World Cup matches"),
        BotCommand("wc_group", "World Cup group table"),
        BotCommand("wc_standings", "World Cup standings"),
        BotCommand("trump", "Latest Trump news"),
        BotCommand("trumpfile", "Trump news as file"),
        BotCommand("download", "Download X/Twitter media"),
        BotCommand("audio", "Download audio"),
        BotCommand("downloader_help", "Downloader help"),
        BotCommand("add_birthday", "Add birthday"),
        BotCommand("birthdays", "Show birthdays"),
        BotCommand("next_birthday", "Upcoming birthdays"),
        BotCommand("birthday_today", "Birthdays today"),
        BotCommand("remove_birthday", "Remove birthday"),
        BotCommand("birthday_help", "Birthday help"),
        BotCommand("dart", "Throw one dart"),
        BotCommand("dart_battle", "Start dart battle"),
        BotCommand("join_dart", "Join dart battle"),
        BotCommand("start_dart", "Start dart battle"),
        BotCommand("cancel_dart", "Cancel dart battle"),
        BotCommand("dart_score", "Dart stats"),
        BotCommand("dart_top", "Dart scoreboard"),
        BotCommand("dart_help", "Dart help"),
        BotCommand("activity_today", "Today group activity"),
        BotCommand("activity_week", "Weekly group activity"),
        BotCommand("activity_month", "Monthly group activity"),
        BotCommand("activity_year", "Yearly group activity"),
        BotCommand("leaderboard", "Group leaderboard"),
        BotCommand("activity_chart", "Group chart"),
        BotCommand("awards", "Weekly awards"),
        BotCommand("photohelp", "Photo help"),
        BotCommand("ai_photohelp", "AI photo help"),
    ]

    await telegram_app.bot.set_my_commands(commands)


def register_handlers() -> None:
    global _handlers_registered
    if _handlers_registered:
        return

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_command))

    register_math_handlers(telegram_app)

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
    if register_ai_photo_handlers:
        register_ai_photo_handlers(telegram_app)
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
        "bot": "AhBashin Telegram Bot",
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
