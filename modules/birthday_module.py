import os
import sqlite3
from datetime import date, datetime
from typing import List, Optional, Tuple

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

BIRTHDAY_DB_PATH = os.getenv("BIRTHDAY_DB_PATH", "birthdays.db")


# ------------------------------------------------------------
# Database
# ------------------------------------------------------------

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(BIRTHDAY_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_birthday_db() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS birthdays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            chat_title TEXT,
            name TEXT NOT NULL,
            birth_year INTEGER,
            birth_month INTEGER NOT NULL,
            birth_day INTEGER NOT NULL,
            added_by_user_id INTEGER,
            added_by_name TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chat_id, name)
        )
        """
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_birthdays_chat "
        "ON birthdays(chat_id)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_birthdays_date "
        "ON birthdays(chat_id, birth_month, birth_day)"
    )

    conn.commit()
    conn.close()


init_birthday_db()


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def birthday_help_text() -> str:
    return (
        "Birthday commands:\n\n"
        "/add_birthday Ali 1990-05-12 - add birthday with year\n"
        "/add_birthday Sara 05-12 - add birthday without year\n"
        "/birthdays - show all saved birthdays\n"
        "/next_birthday - show the next upcoming birthday\n"
        "/birthday_today - show today's birthdays\n"
        "/remove_birthday Ali - remove a birthday\n"
        "/birthday_help - show this help\n\n"
        "Date formats:\n"
        "YYYY-MM-DD, DD-MM-YYYY, MM-DD, or DD-MM\n\n"
        "Examples:\n"
        "/add_birthday Ali 1990-05-12\n"
        "/add_birthday Sara 12-05"
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


def parse_birthday_date(text: str) -> Tuple[Optional[int], int, int]:
    """
    Supports:
    YYYY-MM-DD
    DD-MM-YYYY
    YYYY/MM/DD
    DD/MM/YYYY
    MM-DD
    DD-MM

    For two-part dates, we use DD-MM by default if the first number is > 12.
    If both are <= 12, we treat it as DD-MM because most users here likely use European/Iranian style.
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
        first = int(parts[0])
        second = int(parts[1])

        # Default: DD-MM
        day = first
        month = second

    else:
        raise ValueError("Invalid date format.")

    if year is not None:
        if year < 1900 or year > date.today().year:
            raise ValueError("Birth year looks invalid.")

    if month < 1 or month > 12:
        raise ValueError("Month must be between 1 and 12.")

    if day < 1 or day > 31:
        raise ValueError("Day must be between 1 and 31.")

    # Validate real calendar date.
    # Use leap year 2000 for yearless dates so 29 Feb is allowed.
    validation_year = year if year is not None else 2000

    try:
        date(validation_year, month, day)
    except ValueError:
        raise ValueError("This is not a valid calendar date.")

    return year, month, day


def calculate_age(birth_year: Optional[int], month: int, day: int, on_date: Optional[date] = None) -> Optional[int]:
    if birth_year is None:
        return None

    today = on_date or date.today()
    age = today.year - birth_year

    if (today.month, today.day) < (month, day):
        age -= 1

    return age


def days_until_birthday(month: int, day: int, today: Optional[date] = None) -> int:
    today = today or date.today()

    try:
        birthday_this_year = date(today.year, month, day)
    except ValueError:
        # 29 Feb handling on non-leap years.
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


def ensure_chat(update: Update) -> Optional[str]:
    if not update.effective_chat:
        return "Chat not found."

    return None


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
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO birthdays (
            chat_id,
            chat_title,
            name,
            birth_year,
            birth_month,
            birth_day,
            added_by_user_id,
            added_by_name
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, name)
        DO UPDATE SET
            birth_year = excluded.birth_year,
            birth_month = excluded.birth_month,
            birth_day = excluded.birth_day,
            added_by_user_id = excluded.added_by_user_id,
            added_by_name = excluded.added_by_name,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            chat_id,
            chat_title,
            name,
            birth_year,
            birth_month,
            birth_day,
            added_by_user_id,
            added_by_name,
        ),
    )

    conn.commit()
    conn.close()


def get_all_birthdays(chat_id: int) -> List[sqlite3.Row]:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM birthdays
        WHERE chat_id = ?
        ORDER BY birth_month ASC, birth_day ASC, name ASC
        """,
        (chat_id,),
    )

    rows = cursor.fetchall()
    conn.close()

    return rows


def get_today_birthdays(chat_id: int) -> List[sqlite3.Row]:
    today = date.today()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM birthdays
        WHERE chat_id = ?
          AND birth_month = ?
          AND birth_day = ?
        ORDER BY name ASC
        """,
        (chat_id, today.month, today.day),
    )

    rows = cursor.fetchall()
    conn.close()

    return rows


def get_next_birthdays(chat_id: int, limit: int = 5) -> List[sqlite3.Row]:
    rows = get_all_birthdays(chat_id)

    rows = sorted(
        rows,
        key=lambda row: days_until_birthday(row["birth_month"], row["birth_day"]),
    )

    return rows[:limit]


def remove_birthday(chat_id: int, name: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM birthdays
        WHERE chat_id = ? AND LOWER(name) = LOWER(?)
        """,
        (chat_id, name),
    )

    deleted = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return deleted


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

async def add_birthday_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
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

    if birth_year:
        birthday_display = f"{birth_year:04d}-{birth_month:02d}-{birth_day:02d}"
    else:
        birthday_display = f"{birth_day:02d}-{birth_month:02d}"

    await update.message.reply_text(
        f"Birthday saved 🎂\n\n"
        f"Name: {name}\n"
        f"Birthday: {birthday_display}"
    )


async def birthdays_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    rows = get_all_birthdays(update.effective_chat.id)

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

    rows = get_next_birthdays(update.effective_chat.id, limit=5)

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

    rows = get_today_birthdays(update.effective_chat.id)

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

    if not context.args:
        await update.message.reply_text(
            "Please provide a name.\n\n"
            "Example:\n"
            "/remove_birthday Ali"
        )
        return

    name = normalize_name(" ".join(context.args))
    deleted = remove_birthday(update.effective_chat.id, name)

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