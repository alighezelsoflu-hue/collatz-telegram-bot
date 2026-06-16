import os
from datetime import date, datetime
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

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
BIRTHDAY_TIMEZONE = os.getenv("BIRTHDAY_TIMEZONE", "Europe/Berlin")

try:
    LOCAL_TZ = ZoneInfo(BIRTHDAY_TIMEZONE)
except Exception:
    LOCAL_TZ = ZoneInfo("UTC")


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


def init_birthday_db() -> None:
    if not database_is_configured():
        return

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS birthdays (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    chat_title TEXT,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    birth_year INTEGER,
                    birth_month INTEGER NOT NULL,
                    birth_day INTEGER NOT NULL,
                    added_by_user_id BIGINT,
                    added_by_name TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(chat_id, name_key)
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_birthdays_chat
                ON birthdays(chat_id)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_birthdays_date
                ON birthdays(chat_id, birth_month, birth_day)
                """
            )


# Create table automatically on Render when DATABASE_URL exists.
try:
    init_birthday_db()
except Exception as error:
    print(f"Birthday database init failed: {error}")


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def today_local() -> date:
    return datetime.now(LOCAL_TZ).date()


def birthday_help_text() -> str:
    return (
        "Birthday commands:\n\n"
        "/add_birthday Ali 1990-05-12 - add birthday with year\n"
        "/add_birthday Sara 12-05 - add birthday without year\n"
        "/birthdays - show all saved birthdays\n"
        "/next_birthday - show the next upcoming birthday\n"
        "/birthday_today - show today's birthdays\n"
        "/remove_birthday Ali - remove a birthday\n"
        "/birthday_help - show this help\n\n"
        "Date formats:\n"
        "YYYY-MM-DD, DD-MM-YYYY, or DD-MM\n\n"
        "Examples:\n"
        "/add_birthday Ali 1990-05-12\n"
        "/add_birthday Sara 12-05"
    )


def db_error_text() -> str:
    return (
        "Birthday database is not ready.\n\n"
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


def normalize_name(name: str) -> str:
    return " ".join(name.strip().split())


def name_key(name: str) -> str:
    return normalize_name(name).casefold()


def parse_birthday_date(text: str) -> Tuple[Optional[int], int, int]:
    """
    Supports:
    YYYY-MM-DD
    DD-MM-YYYY
    YYYY/MM/DD
    DD/MM/YYYY
    DD-MM

    For two-part dates, the default is DD-MM.
    Example:
    12-05 => 12 May
    """
    text = text.strip().replace("/", "-").replace(".", "-")
    parts = [p for p in text.split("-") if p]

    if len(parts) == 3:
        a, b, c = parts

        if len(a) == 4:
            year = int(a)
            month = int(b)
            day = int(c)

        elif len(c) == 4:
            day = int(a)
            month = int(b)
            year = int(c)

        else:
            raise ValueError("Invalid date format.")

    elif len(parts) == 2:
        year = None
        day = int(parts[0])
        month = int(parts[1])

    else:
        raise ValueError("Invalid date format.")

    current_year = today_local().year

    if year is not None:
        if year < 1900 or year > current_year:
            raise ValueError("Birth year looks invalid.")

    if month < 1 or month > 12:
        raise ValueError("Month must be between 1 and 12.")

    if day < 1 or day > 31:
        raise ValueError("Day must be between 1 and 31.")

    validation_year = year if year is not None else 2000

    try:
        date(validation_year, month, day)
    except ValueError:
        raise ValueError("This is not a valid calendar date.")

    return year, month, day


def calculate_age(
    birth_year: Optional[int],
    month: int,
    day: int,
    on_date: Optional[date] = None,
) -> Optional[int]:
    if birth_year is None:
        return None

    today = on_date or today_local()
    age = today.year - birth_year

    if (today.month, today.day) < (month, day):
        age -= 1

    return age


def days_until_birthday(month: int, day: int, on_date: Optional[date] = None) -> int:
    today = on_date or today_local()

    try:
        birthday_this_year = date(today.year, month, day)
    except ValueError:
        birthday_this_year = date(today.year, 2, 28)

    if birthday_this_year >= today:
        return (birthday_this_year - today).days

    try:
        birthday_next_year = date(today.year + 1, month, day)
    except ValueError:
        birthday_next_year = date(today.year + 1, 2, 28)

    return (birthday_next_year - today).days


def format_birthday_date(row) -> str:
    year = row["birth_year"]
    month = row["birth_month"]
    day = row["birth_day"]

    if year:
        return f"{year:04d}-{month:02d}-{day:02d}"

    return f"{day:02d}-{month:02d}"


def format_birthday_line(row, index: Optional[int] = None) -> str:
    name = row["name"]
    birthday_text = format_birthday_date(row)
    age = calculate_age(row["birth_year"], row["birth_month"], row["birth_day"])
    remaining = days_until_birthday(row["birth_month"], row["birth_day"])

    prefix = f"{index}. " if index is not None else ""

    if age is not None:
        age_text = f", age: {age}"
    else:
        age_text = ""

    if remaining == 0:
        remaining_text = "today 🎉"
    elif remaining == 1:
        remaining_text = "tomorrow"
    else:
        remaining_text = f"in {remaining} days"

    return f"{prefix}{name} — {birthday_text}{age_text} — {remaining_text}"


# ------------------------------------------------------------
# Database operations
# ------------------------------------------------------------

def upsert_birthday(
    chat_id: int,
    chat_title: str,
    name: str,
    birth_year: Optional[int],
    birth_month: int,
    birth_day: int,
    added_by_user_id: Optional[int],
    added_by_name: str,
) -> None:
    normalized_name = normalize_name(name)

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO birthdays (
                    chat_id,
                    chat_title,
                    name,
                    name_key,
                    birth_year,
                    birth_month,
                    birth_day,
                    added_by_user_id,
                    added_by_name
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(chat_id, name_key)
                DO UPDATE SET
                    chat_title = EXCLUDED.chat_title,
                    name = EXCLUDED.name,
                    birth_year = EXCLUDED.birth_year,
                    birth_month = EXCLUDED.birth_month,
                    birth_day = EXCLUDED.birth_day,
                    added_by_user_id = EXCLUDED.added_by_user_id,
                    added_by_name = EXCLUDED.added_by_name,
                    updated_at = NOW()
                """,
                (
                    chat_id,
                    chat_title,
                    normalized_name,
                    name_key(normalized_name),
                    birth_year,
                    birth_month,
                    birth_day,
                    added_by_user_id,
                    added_by_name,
                ),
            )


def get_all_birthdays(chat_id: int) -> List[dict]:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM birthdays
                WHERE chat_id = %s
                ORDER BY birth_month ASC, birth_day ASC, name ASC
                """,
                (chat_id,),
            )

            return cursor.fetchall()


def get_today_birthdays(chat_id: int) -> List[dict]:
    today = today_local()

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM birthdays
                WHERE chat_id = %s
                  AND birth_month = %s
                  AND birth_day = %s
                ORDER BY name ASC
                """,
                (chat_id, today.month, today.day),
            )

            return cursor.fetchall()


def get_next_birthdays(chat_id: int, limit: int = 5) -> List[dict]:
    rows = get_all_birthdays(chat_id)

    rows = sorted(
        rows,
        key=lambda row: days_until_birthday(row["birth_month"], row["birth_day"]),
    )

    return rows[:limit]


def remove_birthday(chat_id: int, name: str) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM birthdays
                WHERE chat_id = %s AND name_key = %s
                """,
                (chat_id, name_key(name)),
            )

            return cursor.rowcount > 0


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

async def add_birthday_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    if not database_is_configured():
        await update.message.reply_text(db_error_text())
        return

    try:
        init_birthday_db()
    except Exception as error:
        await update.message.reply_text(f"Birthday database init failed.\n\nError: {error}")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Please use:\n"
            "/add_birthday Name YYYY-MM-DD\n\n"
            "Examples:\n"
            "/add_birthday Ali 1990-05-12\n"
            "/add_birthday Sara 12-05"
        )
        return

    birthday_text = context.args[-1]
    name = normalize_name(" ".join(context.args[:-1]))

    if not name:
        await update.message.reply_text("Please provide a name.")
        return

    try:
        birth_year, birth_month, birth_day = parse_birthday_date(birthday_text)
    except Exception as error:
        await update.message.reply_text(
            f"Invalid birthday date.\n\n"
            f"Error: {error}\n\n"
            "Use one of these formats:\n"
            "YYYY-MM-DD, DD-MM-YYYY, DD-MM"
        )
        return

    user = update.effective_user
    added_by_user_id = user.id if user else None
    added_by_name = get_display_name(user)

    try:
        upsert_birthday(
            chat_id=update.effective_chat.id,
            chat_title=update.effective_chat.title or update.effective_chat.full_name or "",
            name=name,
            birth_year=birth_year,
            birth_month=birth_month,
            birth_day=birth_day,
            added_by_user_id=added_by_user_id,
            added_by_name=added_by_name,
        )
    except Exception as error:
        await update.message.reply_text(f"Could not save birthday.\n\nError: {error}")
        return

    if birth_year:
        birthday_display = f"{birth_year:04d}-{birth_month:02d}-{birth_day:02d}"
    else:
        birthday_display = f"{birth_day:02d}-{birth_month:02d}"

    await update.message.reply_text(
        f"Birthday saved permanently 🎂\n\n"
        f"Name: {name}\n"
        f"Birthday: {birthday_display}"
    )


async def birthdays_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    if not database_is_configured():
        await update.message.reply_text(db_error_text())
        return

    try:
        rows = get_all_birthdays(update.effective_chat.id)
    except Exception as error:
        await update.message.reply_text(f"Could not load birthdays.\n\nError: {error}")
        return

    if not rows:
        await update.message.reply_text(
            "No birthdays saved yet.\n\n"
            "Add one with:\n"
            "/add_birthday Ali 1990-05-12"
        )
        return

    lines = [
        "Saved birthdays 🎂",
        "",
    ]

    for index, row in enumerate(rows, start=1):
        lines.append(format_birthday_line(row, index=index))

    await update.message.reply_text("\n".join(lines))


async def next_birthday_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    if not database_is_configured():
        await update.message.reply_text(db_error_text())
        return

    try:
        rows = get_next_birthdays(update.effective_chat.id, limit=5)
    except Exception as error:
        await update.message.reply_text(f"Could not load next birthdays.\n\nError: {error}")
        return

    if not rows:
        await update.message.reply_text(
            "No birthdays saved yet.\n\n"
            "Add one with:\n"
            "/add_birthday Ali 1990-05-12"
        )
        return

    lines = [
        "Next birthdays 🎂",
        "",
    ]

    for index, row in enumerate(rows, start=1):
        lines.append(format_birthday_line(row, index=index))

    await update.message.reply_text("\n".join(lines))


async def birthday_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    if not database_is_configured():
        await update.message.reply_text(db_error_text())
        return

    try:
        rows = get_today_birthdays(update.effective_chat.id)
    except Exception as error:
        await update.message.reply_text(f"Could not load today's birthdays.\n\nError: {error}")
        return

    if not rows:
        await update.message.reply_text("No birthdays today.")
        return

    lines = [
        "Today is birthday day 🎉🎂",
        "",
    ]

    for row in rows:
        age = calculate_age(row["birth_year"], row["birth_month"], row["birth_day"])

        if age is not None:
            lines.append(f"🎉 Happy birthday {row['name']}! You are {age} today!")
        else:
            lines.append(f"🎉 Happy birthday {row['name']}!")

    await update.message.reply_text("\n".join(lines))


async def remove_birthday_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    if not database_is_configured():
        await update.message.reply_text(db_error_text())
        return

    if not context.args:
        await update.message.reply_text(
            "Please provide a name.\n\n"
            "Example:\n"
            "/remove_birthday Ali"
        )
        return

    name = normalize_name(" ".join(context.args))

    try:
        deleted = remove_birthday(update.effective_chat.id, name)
    except Exception as error:
        await update.message.reply_text(f"Could not remove birthday.\n\nError: {error}")
        return

    if deleted:
        await update.message.reply_text(f"Removed birthday for {name}.")
    else:
        await update.message.reply_text(f"No birthday found for {name}.")


async def birthday_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(birthday_help_text())


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

def register_birthday_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("add_birthday", add_birthday_command))
    app.add_handler(CommandHandler("birthdays", birthdays_command))
    app.add_handler(CommandHandler("next_birthday", next_birthday_command))
    app.add_handler(CommandHandler("birthday_today", birthday_today_command))
    app.add_handler(CommandHandler("remove_birthday", remove_birthday_command))
    app.add_handler(CommandHandler("birthday_help", birthday_help_command))