import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None
    dict_row = None


# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Active dart battles are stored in memory.
# If Render restarts during a battle, only the active battle is lost.
# Scores and leaderboard are saved permanently in Neon Postgres.
ACTIVE_DART_BATTLES: Dict[int, Dict] = {}


# ------------------------------------------------------------
# Database
# ------------------------------------------------------------

def database_is_configured() -> bool:
    return bool(DATABASE_URL) and psycopg is not None


def get_db_connection():
    if psycopg is None:
        raise RuntimeError(
            "psycopg is not installed. Add psycopg[binary] to requirements.txt and redeploy."
        )

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing. Add your Neon Postgres connection string to Render."
        )

    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_game_db() -> None:
    if not database_is_configured():
        return

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS dart_scores (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    chat_title TEXT,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    display_name TEXT,
                    total_throws INTEGER DEFAULT 0,
                    total_score INTEGER DEFAULT 0,
                    bullseyes INTEGER DEFAULT 0,
                    battle_wins INTEGER DEFAULT 0,
                    battles_played INTEGER DEFAULT 0,
                    last_played_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(chat_id, user_id)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS dart_history (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    chat_title TEXT,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    display_name TEXT,
                    score INTEGER NOT NULL,
                    is_bullseye INTEGER DEFAULT 0,
                    game_type TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_dart_scores_chat
                ON dart_scores(chat_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_dart_history_chat_date
                ON dart_history(chat_id, created_at)
                """
            )


try:
    init_game_db()
except Exception as error:
    print(f"Game database init failed: {error}")


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def db_error_text() -> str:
    return (
        "Game database is not ready.\n\n"
        "Please check:\n"
        "1. DATABASE_URL exists in Render Environment Variables\n"
        "2. psycopg[binary] exists in requirements.txt\n"
        "3. Render was redeployed after adding DATABASE_URL"
    )


def get_display_name(user) -> str:
    if not user:
        return "Unknown"

    if user.username:
        return f"@{user.username}"

    parts = []

    if user.first_name:
        parts.append(user.first_name)

    if user.last_name:
        parts.append(user.last_name)

    return " ".join(parts) if parts else str(user.id)


def get_username(user) -> str:
    if not user:
        return ""

    return user.username or ""


def get_chat_title(update: Update) -> str:
    chat = update.effective_chat

    if not chat:
        return ""

    return chat.title or chat.full_name or ""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def dart_help_text() -> str:
    return (
        "Dart game commands 🎯\n\n"
        "/dart - throw one dart and save your score\n"
        "/dart_battle - start a group dart battle\n"
        "/join_dart - join the current dart battle\n"
        "/start_dart - start the battle and throw darts for all players\n"
        "/cancel_dart - cancel the current battle\n"
        "/dart_score - show your personal dart stats\n"
        "/dart_top - show group tournament scoreboard\n"
        "/dart_help - show this help\n\n"
        "Rules:\n"
        "- Telegram dart score is from 1 to 6\n"
        "- 6 is bullseye 🎯\n"
        "- In dart battle, highest score wins\n"
        "- If multiple players tie for highest score, all tied players get a win\n"
        "- Scores are saved permanently in Neon Postgres"
    )


# ------------------------------------------------------------
# Database operations
# ------------------------------------------------------------

def record_dart_throw(
    chat_id: int,
    chat_title: str,
    user_id: int,
    username: str,
    display_name: str,
    score: int,
    game_type: str,
    battle_played: bool = False,
    battle_win: bool = False,
) -> None:
    is_bullseye = 1 if score == 6 else 0
    played_increment = 1 if battle_played else 0
    win_increment = 1 if battle_win else 0

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO dart_scores (
                    chat_id,
                    chat_title,
                    user_id,
                    username,
                    display_name,
                    total_throws,
                    total_score,
                    bullseyes,
                    battle_wins,
                    battles_played,
                    last_played_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(chat_id, user_id)
                DO UPDATE SET
                    chat_title = EXCLUDED.chat_title,
                    username = EXCLUDED.username,
                    display_name = EXCLUDED.display_name,
                    total_throws = dart_scores.total_throws + EXCLUDED.total_throws,
                    total_score = dart_scores.total_score + EXCLUDED.total_score,
                    bullseyes = dart_scores.bullseyes + EXCLUDED.bullseyes,
                    battle_wins = dart_scores.battle_wins + EXCLUDED.battle_wins,
                    battles_played = dart_scores.battles_played + EXCLUDED.battles_played,
                    last_played_at = EXCLUDED.last_played_at,
                    updated_at = NOW()
                """,
                (
                    chat_id,
                    chat_title,
                    user_id,
                    username,
                    display_name,
                    1,
                    score,
                    is_bullseye,
                    win_increment,
                    played_increment,
                    now_utc(),
                ),
            )

            cursor.execute(
                """
                INSERT INTO dart_history (
                    chat_id,
                    chat_title,
                    user_id,
                    username,
                    display_name,
                    score,
                    is_bullseye,
                    game_type
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    chat_id,
                    chat_title,
                    user_id,
                    username,
                    display_name,
                    score,
                    is_bullseye,
                    game_type,
                ),
            )


def get_user_dart_score(chat_id: int, user_id: int) -> Optional[dict]:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM dart_scores
                WHERE chat_id = %s AND user_id = %s
                """,
                (chat_id, user_id),
            )

            return cursor.fetchone()


def get_dart_top(chat_id: int, limit: int = 10) -> List[dict]:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    *,
                    CASE
                        WHEN total_throws > 0
                        THEN ROUND((total_score::numeric / total_throws), 2)
                        ELSE 0
                    END AS average_score
                FROM dart_scores
                WHERE chat_id = %s
                ORDER BY battle_wins DESC, bullseyes DESC, average_score DESC, total_score DESC
                LIMIT %s
                """,
                (chat_id, limit),
            )

            return cursor.fetchall()


def format_score_row(row: dict, index: Optional[int] = None) -> str:
    prefix = ""

    if index is not None:
        medals = ["🥇", "🥈", "🥉"]
        prefix = medals[index - 1] if index <= 3 else f"{index}."

    total_throws = row["total_throws"] or 0
    total_score = row["total_score"] or 0
    average = total_score / total_throws if total_throws else 0

    return (
        f"{prefix} {row['display_name']} — "
        f"wins: {row['battle_wins']}, "
        f"bullseyes: {row['bullseyes']}, "
        f"throws: {total_throws}, "
        f"avg: {average:.2f}"
    ).strip()


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

async def dart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    if not database_is_configured():
        await update.message.reply_text(db_error_text())
        return

    try:
        init_game_db()
    except Exception as error:
        await update.message.reply_text(f"Game database init failed.\n\nError: {error}")
        return

    user = update.effective_user
    chat = update.effective_chat

    sent = await update.message.reply_dice(emoji="🎯")
    score = sent.dice.value if sent.dice else 0

    try:
        record_dart_throw(
            chat_id=chat.id,
            chat_title=get_chat_title(update),
            user_id=user.id,
            username=get_username(user),
            display_name=get_display_name(user),
            score=score,
            game_type="solo",
            battle_played=False,
            battle_win=False,
        )
    except Exception as error:
        await update.message.reply_text(f"Dart score could not be saved.\n\nError: {error}")
        return

    if score == 6:
        result_text = f"{get_display_name(user)} hit bullseye! 🎯🔥\nScore: {score}"
    else:
        result_text = f"{get_display_name(user)} scored {score} 🎯"

    await update.message.reply_text(result_text)


async def dart_battle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    if not database_is_configured():
        await update.message.reply_text(db_error_text())
        return

    chat = update.effective_chat
    user = update.effective_user

    if chat.id in ACTIVE_DART_BATTLES:
        battle = ACTIVE_DART_BATTLES[chat.id]
        players = battle["players"]

        await update.message.reply_text(
            "A dart battle is already active 🎯\n\n"
            f"Players joined: {len(players)}\n"
            "Use /join_dart to join or /start_dart to start."
        )
        return

    ACTIVE_DART_BATTLES[chat.id] = {
        "chat_title": get_chat_title(update),
        "created_by": user.id,
        "players": {
            user.id: {
                "user_id": user.id,
                "username": get_username(user),
                "display_name": get_display_name(user),
            }
        },
    }

    await update.message.reply_text(
        "Dart battle started 🎯\n\n"
        f"{get_display_name(user)} joined automatically.\n\n"
        "Others can join with:\n"
        "/join_dart\n\n"
        "Start the battle with:\n"
        "/start_dart"
    )


async def join_dart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat = update.effective_chat
    user = update.effective_user

    if chat.id not in ACTIVE_DART_BATTLES:
        await update.message.reply_text(
            "No active dart battle.\n\n"
            "Start one with:\n"
            "/dart_battle"
        )
        return

    battle = ACTIVE_DART_BATTLES[chat.id]
    players = battle["players"]

    if user.id in players:
        await update.message.reply_text(f"{get_display_name(user)} is already in the battle 🎯")
        return

    players[user.id] = {
        "user_id": user.id,
        "username": get_username(user),
        "display_name": get_display_name(user),
    }

    await update.message.reply_text(
        f"{get_display_name(user)} joined the dart battle 🎯\n\n"
        f"Players joined: {len(players)}"
    )


async def start_dart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    if not database_is_configured():
        await update.message.reply_text(db_error_text())
        return

    try:
        init_game_db()
    except Exception as error:
        await update.message.reply_text(f"Game database init failed.\n\nError: {error}")
        return

    chat = update.effective_chat

    if chat.id not in ACTIVE_DART_BATTLES:
        await update.message.reply_text(
            "No active dart battle.\n\n"
            "Start one with:\n"
            "/dart_battle"
        )
        return

    battle = ACTIVE_DART_BATTLES[chat.id]
    players = list(battle["players"].values())

    if len(players) < 2:
        await update.message.reply_text(
            "At least 2 players are needed for a dart battle.\n\n"
            "Others can join with:\n"
            "/join_dart"
        )
        return

    await update.message.reply_text(
        f"Dart battle begins 🎯\n\n"
        f"Players: {len(players)}"
    )

    results = []

    for player in players:
        await update.message.reply_text(f"{player['display_name']} throws 🎯")
        sent = await update.message.reply_dice(emoji="🎯")
        score = sent.dice.value if sent.dice else 0

        results.append(
            {
                "player": player,
                "score": score,
            }
        )

    highest_score = max(result["score"] for result in results)
    winners = [result for result in results if result["score"] == highest_score]

    try:
        for result in results:
            player = result["player"]
            score = result["score"]
            is_winner = score == highest_score

            record_dart_throw(
                chat_id=chat.id,
                chat_title=battle["chat_title"],
                user_id=player["user_id"],
                username=player["username"],
                display_name=player["display_name"],
                score=score,
                game_type="battle",
                battle_played=True,
                battle_win=is_winner,
            )
    except Exception as error:
        await update.message.reply_text(f"Battle scores could not be saved.\n\nError: {error}")
        return

    lines = [
        "Dart battle result 🎯🏆",
        "",
    ]

    sorted_results = sorted(results, key=lambda item: item["score"], reverse=True)

    for index, result in enumerate(sorted_results, start=1):
        player = result["player"]
        score = result["score"]
        bullseye = " 🎯🔥" if score == 6 else ""

        lines.append(f"{index}. {player['display_name']} — {score}{bullseye}")

    lines.append("")

    if len(winners) == 1:
        winner = winners[0]["player"]
        lines.append(f"Winner: {winner['display_name']} 🏆")
    else:
        winner_names = ", ".join(winner["player"]["display_name"] for winner in winners)
        lines.append(f"Tie winners: {winner_names} 🏆")

    del ACTIVE_DART_BATTLES[chat.id]

    await update.message.reply_text("\n".join(lines))


async def cancel_dart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    chat = update.effective_chat

    if chat.id not in ACTIVE_DART_BATTLES:
        await update.message.reply_text("No active dart battle to cancel.")
        return

    del ACTIVE_DART_BATTLES[chat.id]

    await update.message.reply_text("Current dart battle cancelled.")


async def dart_score_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    if not database_is_configured():
        await update.message.reply_text(db_error_text())
        return

    chat = update.effective_chat
    user = update.effective_user

    try:
        row = get_user_dart_score(chat.id, user.id)
    except Exception as error:
        await update.message.reply_text(f"Could not load dart stats.\n\nError: {error}")
        return

    if not row:
        await update.message.reply_text(
            "You do not have dart stats yet.\n\n"
            "Throw your first dart with:\n"
            "/dart"
        )
        return

    total_throws = row["total_throws"] or 0
    total_score = row["total_score"] or 0
    average = total_score / total_throws if total_throws else 0

    await update.message.reply_text(
        f"Dart stats for {row['display_name']} 🎯\n\n"
        f"Total throws: {total_throws}\n"
        f"Total score: {total_score}\n"
        f"Average score: {average:.2f}\n"
        f"Bullseyes: {row['bullseyes']}\n"
        f"Battles played: {row['battles_played']}\n"
        f"Battle wins: {row['battle_wins']}"
    )


async def dart_top_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    if not database_is_configured():
        await update.message.reply_text(db_error_text())
        return

    chat = update.effective_chat

    try:
        rows = get_dart_top(chat.id, limit=10)
    except Exception as error:
        await update.message.reply_text(f"Could not load dart scoreboard.\n\nError: {error}")
        return

    if not rows:
        await update.message.reply_text(
            "No dart tournament data yet.\n\n"
            "Start with:\n"
            "/dart\n"
            "or\n"
            "/dart_battle"
        )
        return

    lines = [
        "Group dart tournament scoreboard 🎯🏆",
        "",
    ]

    for index, row in enumerate(rows, start=1):
        lines.append(format_score_row(row, index=index))

    await update.message.reply_text("\n".join(lines))


async def dart_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(dart_help_text())


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

def register_game_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("dart", dart_command))
    app.add_handler(CommandHandler("dart_battle", dart_battle_command))
    app.add_handler(CommandHandler("join_dart", join_dart_command))
    app.add_handler(CommandHandler("start_dart", start_dart_command))
    app.add_handler(CommandHandler("cancel_dart", cancel_dart_command))
    app.add_handler(CommandHandler("dart_score", dart_score_command))
    app.add_handler(CommandHandler("dart_top", dart_top_command))
    app.add_handler(CommandHandler("dart_help", dart_help_command))