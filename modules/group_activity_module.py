import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

DB_PATH = os.getenv("GROUP_ACTIVITY_DB_PATH", "group_activity.db")
GROUP_ACTIVITY_TIMEZONE = os.getenv("GROUP_ACTIVITY_TIMEZONE", "Europe/Berlin")

try:
    LOCAL_TZ = ZoneInfo(GROUP_ACTIVITY_TIMEZONE)
except Exception:
    LOCAL_TZ = ZoneInfo("UTC")


# ------------------------------------------------------------
# Database
# ------------------------------------------------------------

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_activity_db() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            chat_title TEXT,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            display_name TEXT,
            message_id INTEGER,
            message_date_iso TEXT,
            message_date_ts REAL,
            local_date TEXT,
            local_hour INTEGER,
            local_weekday TEXT,
            message_type TEXT,
            word_count INTEGER DEFAULT 0,
            char_count INTEGER DEFAULT 0,
            emoji_count INTEGER DEFAULT 0,
            has_link INTEGER DEFAULT 0,
            is_reply INTEGER DEFAULT 0,
            reply_to_user_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_chat_date ON group_messages(chat_id, message_date_ts)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_user_date ON group_messages(chat_id, user_id, message_date_ts)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_type_date ON group_messages(chat_id, message_type, message_date_ts)")

    conn.commit()
    conn.close()


init_activity_db()


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def is_group_chat(update: Update) -> bool:
    chat = update.effective_chat
    if not chat:
        return False

    return chat.type in ("group", "supergroup")


def get_display_name(user) -> str:
    if not user:
        return "Unknown"

    if user.username:
        return f"@{user.username}"

    name_parts = []

    if user.first_name:
        name_parts.append(user.first_name)

    if user.last_name:
        name_parts.append(user.last_name)

    if name_parts:
        return " ".join(name_parts)

    return str(user.id)


def detect_message_type(message) -> str:
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.voice:
        return "voice"
    if message.video_note:
        return "video_note"
    if message.sticker:
        return "sticker"
    if message.animation:
        return "animation"
    if message.document:
        return "document"
    if message.audio:
        return "audio"
    if message.poll:
        return "poll"
    if message.location:
        return "location"
    if message.contact:
        return "contact"
    if message.text:
        return "text"
    if message.caption:
        return "caption"

    return "other"


def count_words(text: str) -> int:
    if not text:
        return 0

    words = re.findall(r"\b[\wآ-ی]+\b", text, flags=re.UNICODE)
    return len(words)


def count_emojis(text: str) -> int:
    if not text:
        return 0

    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\u2600-\u26FF"
        "\u2700-\u27BF"
        "]+",
        flags=re.UNICODE,
    )

    return len(emoji_pattern.findall(text))


def has_link(message, text: str) -> bool:
    if text and re.search(r"https?://|www\.", text, flags=re.IGNORECASE):
        return True

    entities = []

    if message.entities:
        entities.extend(message.entities)

    if message.caption_entities:
        entities.extend(message.caption_entities)

    for entity in entities:
        if entity.type in ("url", "text_link"):
            return True

    return False


def get_message_text_for_counts(message) -> str:
    if message.text:
        return message.text

    if message.caption:
        return message.caption

    return ""


def local_datetime_from_message(message) -> datetime:
    msg_dt = message.date

    if msg_dt.tzinfo is None:
        msg_dt = msg_dt.replace(tzinfo=timezone.utc)

    return msg_dt.astimezone(LOCAL_TZ)


def timestamp_from_local_start(local_dt: datetime) -> float:
    return local_dt.astimezone(timezone.utc).timestamp()


def get_period_start(period: str) -> Tuple[float, str]:
    now_local = datetime.now(LOCAL_TZ)

    if period == "today":
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "today"

    elif period == "week":
        start_local = now_local - timedelta(days=7)
        label = "last 7 days"

    else:
        start_local = now_local - timedelta(days=7)
        label = "last 7 days"

    return timestamp_from_local_start(start_local), label


def format_member_name(row: sqlite3.Row) -> str:
    return row["display_name"] or row["username"] or row["first_name"] or str(row["user_id"])


def ensure_group_message(update: Update) -> Optional[str]:
    if not is_group_chat(update):
        return "This command works inside Telegram groups. Add me to a group and try again."

    return None


# ------------------------------------------------------------
# Silent tracker
# ------------------------------------------------------------

async def track_group_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not is_group_chat(update):
        return

    user = update.effective_user

    if not user or user.is_bot:
        return

    message = update.message
    chat = update.effective_chat

    text = get_message_text_for_counts(message)
    local_dt = local_datetime_from_message(message)

    reply_to_user_id = None
    is_reply = 0

    if message.reply_to_message and message.reply_to_message.from_user:
        is_reply = 1
        reply_to_user_id = message.reply_to_message.from_user.id

    message_type = detect_message_type(message)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO group_messages (
            chat_id,
            chat_title,
            user_id,
            username,
            first_name,
            last_name,
            display_name,
            message_id,
            message_date_iso,
            message_date_ts,
            local_date,
            local_hour,
            local_weekday,
            message_type,
            word_count,
            char_count,
            emoji_count,
            has_link,
            is_reply,
            reply_to_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat.id,
            chat.title or "",
            user.id,
            user.username or "",
            user.first_name or "",
            user.last_name or "",
            get_display_name(user),
            message.message_id,
            local_dt.isoformat(),
            message.date.timestamp(),
            local_dt.strftime("%Y-%m-%d"),
            local_dt.hour,
            local_dt.strftime("%A"),
            message_type,
            count_words(text),
            len(text),
            count_emojis(text),
            1 if has_link(message, text) else 0,
            is_reply,
            reply_to_user_id,
        ),
    )

    conn.commit()
    conn.close()


# ------------------------------------------------------------
# Queries
# ------------------------------------------------------------

def get_basic_stats(chat_id: int, period: str) -> Dict:
    start_ts, label = get_period_start(period)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_messages,
            COUNT(DISTINCT user_id) AS active_members,
            COALESCE(SUM(word_count), 0) AS total_words,
            COALESCE(SUM(emoji_count), 0) AS total_emojis,
            COALESCE(SUM(has_link), 0) AS total_links,
            COALESCE(SUM(is_reply), 0) AS total_replies
        FROM group_messages
        WHERE chat_id = ? AND message_date_ts >= ?
        """,
        (chat_id, start_ts),
    )
    summary = cursor.fetchone()

    cursor.execute(
        """
        SELECT user_id, display_name, COUNT(*) AS message_count
        FROM group_messages
        WHERE chat_id = ? AND message_date_ts >= ?
        GROUP BY user_id, display_name
        ORDER BY message_count DESC
        LIMIT 10
        """,
        (chat_id, start_ts),
    )
    top_users = cursor.fetchall()

    cursor.execute(
        """
        SELECT message_type, COUNT(*) AS count
        FROM group_messages
        WHERE chat_id = ? AND message_date_ts >= ?
        GROUP BY message_type
        ORDER BY count DESC
        """,
        (chat_id, start_ts),
    )
    content_types = cursor.fetchall()

    cursor.execute(
        """
        SELECT local_hour, COUNT(*) AS count
        FROM group_messages
        WHERE chat_id = ? AND message_date_ts >= ?
        GROUP BY local_hour
        ORDER BY count DESC
        LIMIT 1
        """,
        (chat_id, start_ts),
    )
    peak_hour = cursor.fetchone()

    conn.close()

    return {
        "period_label": label,
        "summary": summary,
        "top_users": top_users,
        "content_types": content_types,
        "peak_hour": peak_hour,
    }


def get_leaderboard_rows(chat_id: int, period: str = "week", limit: int = 10) -> List[sqlite3.Row]:
    start_ts, _ = get_period_start(period)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            user_id,
            display_name,
            COUNT(*) AS message_count,
            COALESCE(SUM(word_count), 0) AS word_count,
            COALESCE(SUM(emoji_count), 0) AS emoji_count,
            COALESCE(SUM(has_link), 0) AS link_count,
            COALESCE(SUM(is_reply), 0) AS reply_count
        FROM group_messages
        WHERE chat_id = ? AND message_date_ts >= ?
        GROUP BY user_id, display_name
        ORDER BY message_count DESC
        LIMIT ?
        """,
        (chat_id, start_ts, limit),
    )

    rows = cursor.fetchall()
    conn.close()

    return rows


def get_hourly_rows(chat_id: int, period: str = "week") -> List[sqlite3.Row]:
    start_ts, _ = get_period_start(period)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT local_hour, COUNT(*) AS count
        FROM group_messages
        WHERE chat_id = ? AND message_date_ts >= ?
        GROUP BY local_hour
        ORDER BY local_hour ASC
        """,
        (chat_id, start_ts),
    )

    rows = cursor.fetchall()
    conn.close()

    return rows


def get_award_data(chat_id: int) -> Dict:
    start_ts, _ = get_period_start("week")

    conn = get_db_connection()
    cursor = conn.cursor()

    queries = {
        "most_active": """
            SELECT display_name, COUNT(*) AS value
            FROM group_messages
            WHERE chat_id = ? AND message_date_ts >= ?
            GROUP BY user_id, display_name
            ORDER BY value DESC
            LIMIT 1
        """,
        "emoji_master": """
            SELECT display_name, SUM(emoji_count) AS value
            FROM group_messages
            WHERE chat_id = ? AND message_date_ts >= ?
            GROUP BY user_id, display_name
            ORDER BY value DESC
            LIMIT 1
        """,
        "link_hunter": """
            SELECT display_name, SUM(has_link) AS value
            FROM group_messages
            WHERE chat_id = ? AND message_date_ts >= ?
            GROUP BY user_id, display_name
            ORDER BY value DESC
            LIMIT 1
        """,
        "best_replier": """
            SELECT display_name, SUM(is_reply) AS value
            FROM group_messages
            WHERE chat_id = ? AND message_date_ts >= ?
            GROUP BY user_id, display_name
            ORDER BY value DESC
            LIMIT 1
        """,
        "photo_star": """
            SELECT display_name, COUNT(*) AS value
            FROM group_messages
            WHERE chat_id = ? AND message_date_ts >= ? AND message_type = 'photo'
            GROUP BY user_id, display_name
            ORDER BY value DESC
            LIMIT 1
        """,
        "night_owl": """
            SELECT display_name, COUNT(*) AS value
            FROM group_messages
            WHERE chat_id = ? AND message_date_ts >= ? AND (local_hour >= 22 OR local_hour <= 4)
            GROUP BY user_id, display_name
            ORDER BY value DESC
            LIMIT 1
        """,
    }

    result = {}

    for key, sql in queries.items():
        cursor.execute(sql, (chat_id, start_ts))
        result[key] = cursor.fetchone()

    conn.close()

    return result


# ------------------------------------------------------------
# Chart generation with Pillow
# ------------------------------------------------------------

def load_font(size: int = 24):
    possible_fonts = [
        "arial.ttf",
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    for font_path in possible_fonts:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass

    return ImageFont.load_default()


def create_leaderboard_chart(rows: List[sqlite3.Row], title: str) -> BytesIO:
    width = 1200
    height = 760

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = load_font(36)
    label_font = load_font(24)
    small_font = load_font(20)

    draw.text((50, 35), title, fill="black", font=title_font)

    if not rows:
        draw.text((50, 120), "No activity data yet.", fill="black", font=label_font)
        output = BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        output.name = "activity_chart.png"
        return output

    max_value = max(row["message_count"] for row in rows)
    chart_left = 290
    chart_top = 120
    bar_height = 42
    gap = 24
    max_bar_width = 760

    for index, row in enumerate(rows):
        y = chart_top + index * (bar_height + gap)

        name = format_member_name(row)
        value = row["message_count"]

        if len(name) > 20:
            name = name[:17] + "..."

        bar_width = int((value / max_value) * max_bar_width) if max_value else 0

        draw.text((50, y + 6), f"{index + 1}. {name}", fill="black", font=label_font)

        draw.rounded_rectangle(
            (chart_left, y, chart_left + bar_width, y + bar_height),
            radius=10,
            fill="#4f8cff",
        )

        draw.text(
            (chart_left + bar_width + 15, y + 7),
            str(value),
            fill="black",
            font=small_font,
        )

    draw.text(
        (50, height - 55),
        f"Timezone: {GROUP_ACTIVITY_TIMEZONE} | Generated by LakLak Bot",
        fill="#555555",
        font=small_font,
    )

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = "activity_chart.png"

    return output


# ------------------------------------------------------------
# Report builders
# ------------------------------------------------------------

def build_activity_report(chat_title: str, stats: Dict) -> str:
    summary = stats["summary"]
    top_users = stats["top_users"]
    content_types = stats["content_types"]
    peak_hour = stats["peak_hour"]
    period_label = stats["period_label"]

    total_messages = summary["total_messages"] or 0
    active_members = summary["active_members"] or 0
    total_words = summary["total_words"] or 0
    total_emojis = summary["total_emojis"] or 0
    total_links = summary["total_links"] or 0
    total_replies = summary["total_replies"] or 0

    lines = [
        f"Group activity report — {period_label}",
        f"Group: {chat_title}",
        "",
        f"Total messages: {total_messages}",
        f"Active members: {active_members}",
        f"Total words: {total_words}",
        f"Emojis used: {total_emojis}",
        f"Links shared: {total_links}",
        f"Replies: {total_replies}",
    ]

    if peak_hour:
        lines.append(f"Peak hour: {peak_hour['local_hour']:02d}:00 with {peak_hour['count']} messages")

    lines.extend(["", "Top members:"])

    if top_users:
        for index, row in enumerate(top_users, start=1):
            lines.append(f"{index}. {format_member_name(row)} — {row['message_count']} messages")
    else:
        lines.append("No activity data yet.")

    lines.extend(["", "Content types:"])

    if content_types:
        for row in content_types:
            lines.append(f"- {row['message_type']}: {row['count']}")
    else:
        lines.append("No content type data yet.")

    return "\n".join(lines)


def build_leaderboard_text(rows: List[sqlite3.Row], period_label: str) -> str:
    lines = [
        f"Leaderboard — {period_label}",
        "",
    ]

    if not rows:
        lines.append("No activity data yet.")
        return "\n".join(lines)

    medals = ["🥇", "🥈", "🥉"]

    for index, row in enumerate(rows, start=1):
        medal = medals[index - 1] if index <= 3 else f"{index}."
        lines.append(
            f"{medal} {format_member_name(row)} — "
            f"{row['message_count']} messages, "
            f"{row['word_count']} words, "
            f"{row['reply_count']} replies"
        )

    return "\n".join(lines)


def build_awards_text(awards: Dict) -> str:
    def winner(row, empty_text: str) -> str:
        if not row:
            return empty_text

        value = row["value"] or 0

        if value <= 0:
            return empty_text

        return f"{row['display_name']} ({value})"

    return (
        "This week's group awards 🏆\n\n"
        f"🏆 Most active: {winner(awards.get('most_active'), 'No winner yet')}\n"
        f"😂 Emoji master: {winner(awards.get('emoji_master'), 'No emoji data yet')}\n"
        f"🔗 Link hunter: {winner(awards.get('link_hunter'), 'No links yet')}\n"
        f"💬 Best replier: {winner(awards.get('best_replier'), 'No replies yet')}\n"
        f"📸 Photo star: {winner(awards.get('photo_star'), 'No photos yet')}\n"
        f"🌙 Night owl: {winner(awards.get('night_owl'), 'No night activity yet')}\n\n"
        "Awards are based on the last 7 days."
    )


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

async def activity_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    error = ensure_group_message(update)
    if error:
        await update.message.reply_text(error)
        return

    stats = get_basic_stats(update.effective_chat.id, "today")
    text = build_activity_report(update.effective_chat.title or "This group", stats)

    await update.message.reply_text(text)


async def activity_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    error = ensure_group_message(update)
    if error:
        await update.message.reply_text(error)
        return

    stats = get_basic_stats(update.effective_chat.id, "week")
    text = build_activity_report(update.effective_chat.title or "This group", stats)

    await update.message.reply_text(text)


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    error = ensure_group_message(update)
    if error:
        await update.message.reply_text(error)
        return

    rows = get_leaderboard_rows(update.effective_chat.id, "week", limit=10)
    text = build_leaderboard_text(rows, "last 7 days")

    await update.message.reply_text(text)


async def activity_chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    error = ensure_group_message(update)
    if error:
        await update.message.reply_text(error)
        return

    rows = get_leaderboard_rows(update.effective_chat.id, "week", limit=10)
    chart = create_leaderboard_chart(rows, "Group Activity Leaderboard — Last 7 Days")

    await update.message.reply_photo(
        photo=InputFile(chart, filename="activity_chart.png"),
        caption="Group activity chart — last 7 days",
    )


async def awards_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    error = ensure_group_message(update)
    if error:
        await update.message.reply_text(error)
        return

    awards = get_award_data(update.effective_chat.id)
    text = build_awards_text(awards)

    await update.message.reply_text(text)


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

def register_group_activity_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("activity_today", activity_today_command))
    app.add_handler(CommandHandler("activity_week", activity_week_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("activity_chart", activity_chart_command))
    app.add_handler(CommandHandler("awards", awards_command))

    # Silent tracker.
    # It does not reply to normal messages.
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.ALL, track_group_activity),
        group=50,
    )