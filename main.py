from fastapi import FastAPI, Request, HTTPException
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes
from modules.graph_math_module import register_graph_math_handlers
from modules.data_science_module import register_data_science_handlers
from modules.physics_module import register_physics_handlers

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
        "Graph theory:\n"
        "/convexhull 0,0 1,2 2,1 0,3 3,0 - convex hull plot\n"
        "/graphdraw A B; A C; B D - draw a graph\n"
        "/dijkstra A D | A B 4; A C 2; C B 1; B D 5 - weighted shortest path\n"
        "/shortestpath A E | A B; A C; B D; D E - unweighted shortest path\n"
        "/mst A B 4; A C 2; C B 1; B D 5 - minimum spanning tree\n"
        "/bfs A | A B; A C; B D - breadth-first search\n"
        "/dfs A | A B; A C; B D - depth-first search\n"
        "/components A B; B C; D E - connected components\n"
        "/toposort shop cook; cook eat; study exam - topological sort\n"
        "/bipartite A 1; A 2; B 1; B 2 - bipartite check\n"
        "/cycle A B; B C; C A - cycle detection\n"
        "/graphhelp - graph theory help\n\n"
        "Data science:"
        "/data_summary 4,7,9,10,10,12 - descriptive statistics"
        "/histogram 4,5,5,6,7,8,8,9 - histogram image"
        "/boxplot 3,4,5,5,6,7,8,20 - box plot image"
        "/correlation 1,2; 2,4; 3,5; 4,8 - Pearson correlation"
        "/linear_regression 1,2; 2,4; 3,5; 4,8 - regression plot"
        "/kmeans 2 | 1,1; 1,2; 8,8; 9,8 - k-means clustering"
        "/outliers iqr | 3,4,5,5,6,7,8,20 - outliers"
        "/normalize minmax | 10,20,30,40 - normalize values"
        "/confusion_matrix cat,cat; dog,cat; dog,dog - classification metrics"
        "/csv_analyze - analyze a CSV file"
        "/dshelp - data science help"
        "Physics:\n"
        "/physicshelp - physics command help\n"
        "/kinematics u=0 a=9.8 t=5 - motion solver\n"
        "/motionplot u=0 a=9.8 t=10 - motion graph\n"
        "/projectile speed=20 angle=45 - projectile result\n"
        "/projectileplot speed=20 angle=45 - projectile graph\n"
        "/force m=10 a=3 - force calculator\n"
        "/weight m=70 - weight calculator\n"
        "/friction mu=0.4 normal=200 - friction force\n"
        "/kinetic m=2 v=10 - kinetic energy\n"
        "/potential m=5 h=20 - potential energy\n"
        "/momentum m=4 v=12 - momentum\n"
        "/wave f=440 wavelength=0.78 - wave calculator\n"
        "/waveplot amplitude=2 frequency=3 duration=2 - wave graph\n"
        "/ohm V=12 R=4 - Ohm's law\n"
        "/series 10 20 30 - series resistance\n"
        "/parallel 10 20 30 - parallel resistance\n"
        "/spring k=200 x=0.1 - spring force\n"
        "/shmplot amplitude=2 period=4 - SHM graph\n"
        "/lens f=10 object=30 - thin lens\n"
        "/gravity m1=5.97e24 m2=70 r=6.37e6 - gravity\n"
        "/gravityplot m1=5.97e24 m2=70 rmin=6.37e6 rmax=5e7 - gravity plot\n"
        "/convert 10 m/s to km/h - unit converter\n\n"
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
        BotCommand("polyroots", "Find polynomial roots"),
        BotCommand("polyplot", "Plot polynomial"),
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
        BotCommand("convexhull", "Convex hull of points"),
        BotCommand("graphdraw", "Draw a graph"),
        BotCommand("dijkstra", "Weighted shortest path"),
        BotCommand("shortestpath", "Unweighted shortest path"),
        BotCommand("mst", "Minimum spanning tree"),
        BotCommand("bfs", "Breadth-first search"),
        BotCommand("dfs", "Depth-first search"),
        BotCommand("components", "Connected components"),
        BotCommand("toposort", "Topological sort"),
        BotCommand("bipartite", "Check bipartite graph"),
        BotCommand("cycle", "Detect graph cycle"),
        BotCommand("graphhelp", "Graph theory help"),
        BotCommand("data_summary", "Data summary statistics"),
        BotCommand("histogram", "Create histogram"),
        BotCommand("boxplot", "Create box plot"),
        BotCommand("correlation", "Pearson correlation"),
        BotCommand("linear_regression", "Linear regression"),
        BotCommand("kmeans", "K-means clustering"),
        BotCommand("outliers", "Detect outliers"),
        BotCommand("normalize", "Normalize values"),
        BotCommand("confusion_matrix", "Classification metrics"),
        BotCommand("csv_analyze", "Analyze CSV file"),
        BotCommand("dshelp", "Data science help"),
        BotCommand("physicshelp", "Physics help"),
        BotCommand("kinematics", "Kinematics solver"),
        BotCommand("motionplot", "Motion plot"),
        BotCommand("projectile", "Projectile motion"),
        BotCommand("projectileplot", "Projectile trajectory plot"),
        BotCommand("force", "Force calculator"),
        BotCommand("weight", "Weight calculator"),
        BotCommand("friction", "Friction calculator"),
        BotCommand("kinetic", "Kinetic energy"),
        BotCommand("potential", "Potential energy"),
        BotCommand("momentum", "Momentum calculator"),
        BotCommand("wave", "Wave calculator"),
        BotCommand("waveplot", "Wave plot"),
        BotCommand("ohm", "Ohm's law"),
        BotCommand("series", "Series resistance"),
        BotCommand("parallel", "Parallel resistance"),
        BotCommand("spring", "Spring and Hooke's law"),
        BotCommand("shmplot", "Simple harmonic motion plot"),
        BotCommand("lens", "Thin lens calculator"),
        BotCommand("gravity", "Gravity force"),
        BotCommand("gravityplot", "Gravity force plot"),
        BotCommand("convert", "Physics unit converter"),
        BotCommand("wc_today", "World Cup matches today"),
        BotCommand("wc_tomorrow", "World Cup matches tomorrow"),
        BotCommand("wc_live", "Live World Cup matches"),
        BotCommand("wc_group", "World Cup group table"),
        BotCommand("wc_standings", "World Cup standings"),
        BotCommand("trump", "Latest Trump news"),
        BotCommand("download", "Download X/Twitter media"),
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

    ]

    await telegram_app.bot.set_my_commands(commands)


def register_handlers() -> None:
    global _handlers_registered
    if _handlers_registered:
        return

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_command))

    register_math_handlers(telegram_app)
    register_graph_math_handlers(telegram_app)
    register_data_science_handlers(telegram_app)
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
