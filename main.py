from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import Application

from config import TOKEN, WEBHOOK_URL, SECRET_PATH

from modules.menu_module import register_menu_handlers, setup_bot_commands
from modules.math_module import register_math_handlers
from modules.graph_math_module import register_graph_math_handlers
from modules.data_science_module import register_data_science_handlers
from modules.physics_module import register_physics_handlers
from modules.astronomy_module import register_astronomy_handlers
from modules.chemistry_module import register_chemistry_handlers
from modules.ai_module import register_ai_handlers

from modules.photo_module import register_photo_handlers
from modules.news_module import register_news_handlers
from modules.fifa_module import register_fifa_handlers
from modules.group_activity_module import register_group_activity_handlers
from modules.downloader_module import register_downloader_handlers
from modules.birthday_module import register_birthday_handlers
from modules.game_module import register_game_handlers


if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")

if not WEBHOOK_URL:
    raise RuntimeError("Missing WEBHOOK_URL environment variable.")

WEBHOOK_PATH = SECRET_PATH.strip("/") if SECRET_PATH else "telegram-webhook"
FULL_WEBHOOK_URL = f"{WEBHOOK_URL.rstrip('/')}/{WEBHOOK_PATH}"

telegram_app = Application.builder().token(TOKEN).build()
api = FastAPI(title="AhBashin Telegram Bot")


def register_handlers() -> None:
    # Beginner-friendly menus first, so /start and /help open the button UI.
    register_menu_handlers(telegram_app)

    # Deterministic subject modules.
    register_math_handlers(telegram_app)
    register_graph_math_handlers(telegram_app)
    register_data_science_handlers(telegram_app)
    register_physics_handlers(telegram_app)
    register_astronomy_handlers(telegram_app)
    register_chemistry_handlers(telegram_app)

    # AI text, memory, smart router, and vision helpers.
    register_ai_handlers(telegram_app)

    # Other modules.
    register_fifa_handlers(telegram_app)
    register_news_handlers(telegram_app)
    register_downloader_handlers(telegram_app)
    register_birthday_handlers(telegram_app)
    register_game_handlers(telegram_app)
    register_photo_handlers(telegram_app)

    # Keep this near the end because it includes the silent group activity tracker.
    register_group_activity_handlers(telegram_app)


register_handlers()


@api.on_event("startup")
async def on_startup() -> None:
    await telegram_app.initialize()
    await telegram_app.start()
    await setup_bot_commands(telegram_app)
    await telegram_app.bot.set_webhook(url=FULL_WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
    print(f"Webhook set to: {FULL_WEBHOOK_URL}")


@api.on_event("shutdown")
async def on_shutdown() -> None:
    await telegram_app.stop()
    await telegram_app.shutdown()


@api.get("/")
async def root():
    return {
        "status": "ok",
        "bot": "AhBashin Bot",
        "webhook": FULL_WEBHOOK_URL,
        "visible_command_menu": "friendly core commands",
        "friendly_features": {
            "start_menu": True,
            "aihelp_tools": True,
            "smart_router": True,
            "modulehelp_advanced_list": True,
            "per_user_ai_memory": True,
        },
        "modules": {
            "menu": True,
            "math": True,
            "graph_math": True,
            "data_science": True,
            "physics": True,
            "astronomy": True,
            "chemistry": True,
            "ai": True,
            "photos": True,
            "ai_vision": True,
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
