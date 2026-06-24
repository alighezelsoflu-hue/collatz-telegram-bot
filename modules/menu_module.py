"""
User-friendly menu module for AhBashin Telegram Bot.

Adds:
- /start beautiful inline menu
- /help menu
- /modulehelp advanced command list by category
- /examples quick examples
- Inline callback menus for beginners
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes


# ------------------------------------------------------------
# Shared send helpers
# ------------------------------------------------------------


def chunks(text: str, limit: int = 3900) -> List[str]:
    if len(text) <= limit:
        return [text]
    parts: List[str] = []
    current = ""
    for line in text.splitlines(True):
        if len(current) + len(line) > limit:
            if current:
                parts.append(current.rstrip())
            current = line
        else:
            current += line
    if current:
        parts.append(current.rstrip())
    return parts


async def send_or_edit(update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard, disable_web_page_preview=True)
        except Exception:
            if query.message:
                await query.message.reply_text(text, reply_markup=keyboard, disable_web_page_preview=True)
        return

    if update.message:
        pieces = chunks(text)
        for index, piece in enumerate(pieces):
            await update.message.reply_text(
                piece,
                reply_markup=keyboard if index == 0 else None,
                disable_web_page_preview=True,
            )


# ------------------------------------------------------------
# Keyboards
# ------------------------------------------------------------


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🤖 AI Chat", callback_data="menu:ai"),
                InlineKeyboardButton("🧠 Smart Assistant", callback_data="menu:smart"),
            ],
            [
                InlineKeyboardButton("🧮 Math", callback_data="menu:math"),
                InlineKeyboardButton("📊 Data Science", callback_data="menu:data_science"),
            ],
            [
                InlineKeyboardButton("⚛️ Physics", callback_data="menu:physics"),
                InlineKeyboardButton("🧪 Chemistry", callback_data="menu:chemistry"),
            ],
            [
                InlineKeyboardButton("🌙 Astronomy", callback_data="menu:astronomy"),
                InlineKeyboardButton("📸 Photo AI", callback_data="menu:photo"),
            ],
            [
                InlineKeyboardButton("🕸 Graph", callback_data="menu:graph"),
                InlineKeyboardButton("🎂 Games & Birthdays", callback_data="menu:personal"),
            ],
            [
                InlineKeyboardButton("⚽ News & World Cup", callback_data="menu:news_wc"),
                InlineKeyboardButton("📥 Downloader", callback_data="menu:downloader"),
            ],
            [
                InlineKeyboardButton("📚 Advanced command list", callback_data="menu:modulehelp"),
            ],
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to main menu", callback_data="menu:main")]])


def modulehelp_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧮 Math", callback_data="modulehelp:math"), InlineKeyboardButton("📊 Data", callback_data="modulehelp:data_science")],
            [InlineKeyboardButton("⚛️ Physics", callback_data="modulehelp:physics"), InlineKeyboardButton("🧪 Chemistry", callback_data="modulehelp:chemistry")],
            [InlineKeyboardButton("🌙 Astronomy", callback_data="modulehelp:astronomy"), InlineKeyboardButton("🤖 AI", callback_data="modulehelp:ai")],
            [InlineKeyboardButton("📸 Photo", callback_data="modulehelp:photo"), InlineKeyboardButton("🕸 Graph", callback_data="modulehelp:graph")],
            [InlineKeyboardButton("🎂 Birthday", callback_data="modulehelp:birthday"), InlineKeyboardButton("🎮 Games", callback_data="modulehelp:games")],
            [InlineKeyboardButton("📥 Downloader", callback_data="modulehelp:downloader"), InlineKeyboardButton("⚽ World Cup", callback_data="modulehelp:worldcup")],
            [InlineKeyboardButton("📰 News", callback_data="modulehelp:news"), InlineKeyboardButton("📊 Activity", callback_data="modulehelp:activity")],
            [InlineKeyboardButton("⬅️ Back", callback_data="menu:main")],
        ]
    )


# ------------------------------------------------------------
# Menu text
# ------------------------------------------------------------


def start_text() -> str:
    return (
        "AhBashin 👋\n\n"
        "I can help with math, data science, physics, chemistry, astronomy, photo AI, files, games, and AI tutoring.\n\n"
        "Choose a button below, or use:\n"
        "/smart describe what you want in normal language\n"
        "/aihelp for AI tools\n"
        "/modulehelp for advanced commands\n\n"
        "Examples:\n"
        "• /smart plot sin x from -10 to 10\n"
        "• /smart balance propane combustion\n"
        "• /smart explain moon phases in Farsi\n"
        "• /smart make my photo professional\n"
    )


MENU_TEXTS: Dict[str, str] = {
    "main": start_text(),
    "smart": (
        "🧠 Smart Assistant\n\n"
        "Use /smart when you do not know the exact command.\n\n"
        "Examples:\n"
        "/smart calculate molar mass of glucose\n"
        "/smart forecast next 5 values from 10 12 14 18\n"
        "/smart explain projectile motion in German\n"
        "/smart what command should I use to analyze a CSV?\n\n"
        "AhBashin will suggest the best command and explain how to use it."
    ),
    "ai": (
        "🤖 AI Chat Tools\n\n"
        "/askai your question - chat with memory\n"
        "/chat math your question - continue a topic\n"
        "/newchat - clear active topic memory\n"
        "/chat_status - see your private memory topics\n"
        "/aihelp - full AI tools help\n\n"
        "Examples:\n"
        "/askai explain black holes simply\n"
        "/chat math give me another example\n"
        "/chat data_science explain overfitting in Farsi"
    ),
    "math": (
        "🧮 Math Menu\n\n"
        "Try these:\n"
        "/calc sin(pi/2) + sqrt(16)\n"
        "/plot sin(x) range -6.28 6.28\n"
        "/stats 4,7,9,10,10,12 tutor fa\n"
        "/integral x^2 from 0 to 3 tutor de\n"
        "/math_tutor fa explain derivatives\n\n"
        "Full list: /modulehelp math"
    ),
    "data_science": (
        "📊 Data Science Menu\n\n"
        "Try these:\n"
        "/data_summary 4,7,9,10,10,12 tutor fa\n"
        "/linear_regression 1,2; 2,4; 3,5; 4,8 tutor de\n"
        "/forecast steps 5 | 10,12,13,15,18,21 tutor it\n"
        "Reply to a CSV with /dataset_profile ai\n"
        "/ds_tutor fa explain overfitting\n\n"
        "Full list: /modulehelp data"
    ),
    "physics": (
        "⚛️ Physics Menu\n\n"
        "Try these:\n"
        "/projectile speed=20 angle=45 tutor fa\n"
        "/ohm V=12 R=4 tutor de\n"
        "/wave f=440 wavelength=0.78\n"
        "/convert 10 m/s to km/h\n"
        "/physics_tutor it explain momentum\n\n"
        "Full list: /modulehelp physics"
    ),
    "chemistry": (
        "🧪 Chemistry Menu\n\n"
        "Try these:\n"
        "/element oxygen\n"
        "/molar_mass Ca(OH)2 tutor fa\n"
        "/balance C3H8 + O2 -> CO2 + H2O tutor de\n"
        "/ph H=1e-7\n"
        "/chem_tutor it explain molarity\n\n"
        "Full list: /modulehelp chemistry"
    ),
    "astronomy": (
        "🌙 Astronomy Menu\n\n"
        "Try these:\n"
        "/moon tutor fa\n"
        "/moonplot\n"
        "/planet mars tutor de\n"
        "/astro_distance 1 au to km\n"
        "/astro_tutor it explain moon phases\n\n"
        "Full list: /modulehelp astronomy"
    ),
    "photo": (
        "📸 Photo AI Menu\n\n"
        "Try these:\n"
        "/photo_ai - send or reply to a photo for AI description\n"
        "/ask_photo what should I improve?\n"
        "/caption_photo instagram\n"
        "/photo_feedback\n"
        "/smart_photo make this professional for LinkedIn\n\n"
        "Full list: /modulehelp photo"
    ),
    "graph": (
        "🕸 Graph Theory Menu\n\n"
        "Try these:\n"
        "/dijkstra A D | A B 4; A C 2; C B 1; B D 5\n"
        "/shortestpath Ali Nima | Ali Sara; Sara Nima\n"
        "/convexhull 0,0 2,1 4,0 1,3\n"
        "/mst A B 4; A C 2; B C 1\n\n"
        "Full list: /modulehelp graph"
    ),
    "personal": (
        "🎂 Games & Birthdays\n\n"
        "Birthdays:\n"
        "/add_birthday Ali 1990-05-12\n"
        "/birthdays\n"
        "/next_birthday\n\n"
        "Games:\n"
        "/dart\n"
        "/dart_battle\n"
        "/dart_top\n\n"
        "Full lists: /modulehelp birthday and /modulehelp games"
    ),
    "news_wc": (
        "⚽ News & World Cup\n\n"
        "World Cup:\n"
        "/wc_today\n"
        "/wc_tomorrow\n"
        "/wc_group A\n\n"
        "News:\n"
        "/trump\n"
        "/trumpfile\n\n"
        "Full lists: /modulehelp worldcup and /modulehelp news"
    ),
    "downloader": (
        "📥 Downloader\n\n"
        "X/Twitter downloader:\n"
        "/download https://x.com/...\n"
        "/audio https://x.com/...\n"
        "/downloader_help\n\n"
        "Full list: /modulehelp downloader"
    ),
}


MODULE_HELP: Dict[str, Tuple[str, str]] = {
    "math": ("🧮 Math commands", "/mathhelp\n/calc\n/plot\n/polyplot\n/polyroots\n/stats\n/statsfile\n/primes\n/primesfile\n/collatz\n/collatzplot\n/fib\n/fiblist\n/fibspiral\n/derivative\n/tangent\n/integral\n/areaplot\n/newton\n/primecount\n/primegap\n/polarplot\n/paramplot\n/math_ai\n/math_tutor"),
    "data_science": ("📊 Data science commands", "/dshelp\n/data_summary\n/histogram\n/boxplot\n/correlation\n/linear_regression\n/kmeans\n/outliers\n/normalize\n/confusion_matrix\n/csv_analyze\n/corr_matrix\n/pairplot\n/poly_regression\n/multiple_regression\n/logistic_regression\n/pca\n/kmeans_auto\n/moving_average\n/forecast\n/ttest\n/chisquare\n/dataset_profile\n/ds_ai\n/ds_tutor"),
    "physics": ("⚛️ Physics commands", "/physicshelp\n/kinematics\n/motionplot\n/projectile\n/projectileplot\n/force\n/weight\n/friction\n/kinetic\n/potential\n/momentum\n/wave\n/waveplot\n/ohm\n/series\n/parallel\n/spring\n/shmplot\n/lens\n/gravity\n/gravityplot\n/convert\n/physics_ai\n/physics_tutor"),
    "chemistry": ("🧪 Chemistry commands", "/chemhelp\n/element\n/molar_mass\n/molarmass\n/balance\n/idealgas\n/molarity\n/dilution\n/ph\n/gasplot\n/chem_ai\n/chem_tutor"),
    "astronomy": ("🌙 Astronomy commands", "/astrohelp\n/moon\n/moonplot\n/planet\n/solar_system\n/astro_distance\n/gravity_compare\n/meteor\n/astro_ai\n/astro_tutor"),
    "ai": ("🤖 AI commands", "/aihelp\n/smart\n/askai\n/ai\n/chat\n/continue\n/newchat\n/clear_chat\n/chat_status\n/chat_history\n/summarize\n/rewrite\n/explain\n/translate_ai\n/quiz\n/flashcards\n/code_explain\n/code_fix\n/regex\n/sql\n/keywords\n/sentiment"),
    "photo": ("📸 Photo commands", "/photohelp\n/enhance\n/vintage\n/bw\n/cinematic\n/clean\n/profile\n/cartoon\n/caricature\n/sticker\n/beach\n/summer\n/vacation\n/portrait\n/soft\n/hdr\n/photoinfo\n/cancel\n/photo_ai\n/ask_photo\n/caption_photo\n/photo_description\n/photo_feedback\n/smart_photo\n/photo_suggest"),
    "graph": ("🕸 Graph commands", "/graphhelp\n/convexhull\n/graphdraw\n/dijkstra\n/shortestpath\n/mst\n/bfs\n/dfs\n/components\n/toposort\n/bipartite\n/cycle"),
    "birthday": ("🎂 Birthday commands", "/birthday_help\n/add_birthday\n/birthdays\n/next_birthday\n/birthday_today\n/remove_birthday"),
    "games": ("🎮 Game commands", "/dart_help\n/dart\n/dart_battle\n/join_dart\n/start_dart\n/cancel_dart\n/dart_score\n/dart_top"),
    "downloader": ("📥 Downloader commands", "/downloader_help\n/download\n/dl\n/audio\n/mp3"),
    "worldcup": ("⚽ World Cup commands", "/wc_today\n/wc_tomorrow\n/wc_live\n/wc_group A\n/wc_standings"),
    "news": ("📰 News commands", "/trump\n/trumpfile"),
    "activity": ("📊 Group activity commands", "/activity_today\n/activity_week\n/activity_month\n/activity_year\n/leaderboard\n/activity_chart\n/awards"),
}

ALIASES = {
    "data": "data_science",
    "ds": "data_science",
    "chem": "chemistry",
    "astro": "astronomy",
    "world": "worldcup",
    "wc": "worldcup",
    "birthday_help": "birthday",
    "game": "games",
}


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, start_text(), main_menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, start_text(), main_menu_keyboard())


async def modulehelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args).strip().lower().replace("-", "_") if context.args else ""
    key = ALIASES.get(raw, raw)

    if not key:
        text = (
            "📚 Advanced command list\n\n"
            "Choose a module below, or type:\n"
            "/modulehelp math\n"
            "/modulehelp data\n"
            "/modulehelp physics\n"
            "/modulehelp chemistry\n"
            "/modulehelp astronomy\n"
            "/modulehelp ai\n"
            "/modulehelp photo\n"
        )
        await send_or_edit(update, text, modulehelp_keyboard())
        return

    if key == "all":
        text = "📚 AhBashin advanced command list\n\n"
        for title, body in MODULE_HELP.values():
            text += f"{title}\n{body}\n\n"
        await send_or_edit(update, text, modulehelp_keyboard())
        return

    if key not in MODULE_HELP:
        await send_or_edit(update, "Unknown module. Use /modulehelp to choose from the list.", modulehelp_keyboard())
        return

    title, body = MODULE_HELP[key]
    await send_or_edit(update, f"{title}\n\n{body}\n\nTip: use /smart if you do not know exact syntax.", modulehelp_keyboard())


async def examples_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    module = " ".join(context.args).strip().lower() if context.args else ""
    if module in {"math", ""}:
        text = (
            "Quick examples ✨\n\n"
            "Math: /plot sin(x) range -6.28 6.28\n"
            "Data: /forecast steps 5 | 10,12,13,15,18,21\n"
            "Physics: /projectile speed=20 angle=45 tutor fa\n"
            "Chemistry: /balance C3H8 + O2 -> CO2 + H2O tutor de\n"
            "Astronomy: /moon tutor it\n"
            "Photo: /ask_photo what should I improve?\n"
            "Smart: /smart analyze this CSV with AI summary\n"
        )
    else:
        text = MENU_TEXTS.get(module, "Use /examples without arguments, or /modulehelp for advanced commands.")
    await send_or_edit(update, text, back_keyboard())


async def wc_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    title, body = MODULE_HELP["worldcup"]
    await send_or_edit(update, f"{title}\n\n{body}", back_keyboard())


async def news_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    title, body = MODULE_HELP["news"]
    await send_or_edit(update, f"{title}\n\n{body}", back_keyboard())


async def activity_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    title, body = MODULE_HELP["activity"]
    await send_or_edit(update, f"{title}\n\n{body}\n\nFor full group tracking, turn off BotFather group privacy and re-add the bot.", back_keyboard())


# ------------------------------------------------------------
# Callback handler
# ------------------------------------------------------------


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data

    if data.startswith("menu:"):
        key = data.split(":", 1)[1]
        if key == "modulehelp":
            await send_or_edit(update, "📚 Advanced command list\n\nChoose a module:", modulehelp_keyboard())
            return
        text = MENU_TEXTS.get(key, start_text())
        keyboard = main_menu_keyboard() if key == "main" else back_keyboard()
        await send_or_edit(update, text, keyboard)
        return

    if data.startswith("modulehelp:"):
        key = data.split(":", 1)[1]
        if key not in MODULE_HELP:
            await send_or_edit(update, "Unknown module.", modulehelp_keyboard())
            return
        title, body = MODULE_HELP[key]
        await send_or_edit(update, f"{title}\n\n{body}\n\nTip: use /smart if you do not know exact syntax.", modulehelp_keyboard())
        return


# ------------------------------------------------------------
# BotCommand setup
# ------------------------------------------------------------


async def setup_bot_commands(app: Application) -> None:
    """Visible slash-command menu. Keep short and beginner-friendly."""
    from telegram import BotCommand

    commands = [
        BotCommand("start", "Open AhBashin menu"),
        BotCommand("help", "Open help menu"),
        BotCommand("smart", "Natural-language assistant"),
        BotCommand("aihelp", "AI tools"),
        BotCommand("modulehelp", "Advanced command list"),
        BotCommand("mathhelp", "Math help"),
        BotCommand("dshelp", "Data science help"),
        BotCommand("physicshelp", "Physics help"),
        BotCommand("chemhelp", "Chemistry help"),
        BotCommand("astrohelp", "Astronomy help"),
        BotCommand("photohelp", "Photo help"),
    ]
    await app.bot.set_my_commands(commands[:100])


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------


def register_menu_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menu", start_command))
    app.add_handler(CommandHandler("modulehelp", modulehelp_command))
    app.add_handler(CommandHandler("examples", examples_command))
    app.add_handler(CommandHandler("wc_help", wc_help_command))
    app.add_handler(CommandHandler("news_help", news_help_command))
    app.add_handler(CommandHandler("activity_help", activity_help_command))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^(menu|modulehelp):"))
