import os
from io import BytesIO
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Request, HTTPException
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageChops
from telegram import Update, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ------------------------------------------------------------
# Config
# ------------------------------------------------------------

MAX_INPUT = 10**12

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SECRET_PATH = os.getenv("SECRET_PATH", "telegram-webhook")

# Use FOOTBALL_DATA_TOKEN in Render.
# FOOTBALL_API_KEY fallback is only here in case you already named it that.
FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN") or os.getenv("FOOTBALL_API_KEY")
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"

WORLD_CUP_COMPETITION = os.getenv("WORLD_CUP_COMPETITION", "WC")
WORLD_CUP_SEASON = int(os.getenv("WORLD_CUP_SEASON", "2026"))

EU_TIMEZONE = os.getenv("WORLD_CUP_EU_TIMEZONE", "Europe/Berlin")
IRAN_TIMEZONE = os.getenv("WORLD_CUP_IRAN_TIMEZONE", "Asia/Tehran")

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")

telegram_app = Application.builder().token(TOKEN).build()
api = FastAPI(title="Collatz Multi Tool Telegram Bot")


# ------------------------------------------------------------
# General helpers
# ------------------------------------------------------------

def split_long_text(text: str, limit: int = 3500) -> List[str]:
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""

    for line in text.splitlines():
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line

    if current:
        chunks.append(current)

    return chunks


def text_to_file(text: str, filename: str) -> BytesIO:
    output = BytesIO()
    output.write(text.encode("utf-8"))
    output.seek(0)
    output.name = filename
    return output


# ------------------------------------------------------------
# Collatz logic
# ------------------------------------------------------------

def collatz_sequence(n: int) -> List[int]:
    if n <= 0:
        raise ValueError("Please send a positive integer greater than 0.")

    seq = [n]

    while n != 1:
        if n % 2 == 0:
            n //= 2
        else:
            n = 3 * n + 1

        seq.append(n)

    return seq


def build_collatz_text_report(n: int) -> Tuple[str, int, int, int, int]:
    if n > MAX_INPUT:
        raise ValueError(f"Please use a number up to {MAX_INPUT:,}.")

    seq = collatz_sequence(n)

    steps = len(seq) - 1
    max_value = max(seq)
    peak_index = seq.index(max_value)
    sequence_length = len(seq)

    lines = [
        f"Collatz report for n = {n}",
        "",
        f"Steps to reach 1: {steps}",
        f"Maximum value reached: {max_value}",
        f"Peak reached at step: {peak_index}",
        f"Sequence length: {sequence_length} numbers",
        "",
        "Full step-by-step sequence:",
        "",
        f"Start: {seq[0]}",
    ]

    for index in range(len(seq) - 1):
        current_value = seq[index]
        next_value = seq[index + 1]

        if current_value % 2 == 0:
            rule = f"{current_value} is even, so {current_value} / 2 = {next_value}"
        else:
            rule = f"{current_value} is odd, so 3 * {current_value} + 1 = {next_value}"

        lines.append(f"Step {index + 1}: {rule}")

    lines.extend(
        [
            "",
            f"Final result: reached 1 after {steps} steps.",
            "",
            "Raw sequence:",
            " -> ".join(map(str, seq)),
        ]
    )

    report_text = "\n".join(lines)
    return report_text, steps, max_value, peak_index, sequence_length


# ------------------------------------------------------------
# football-data.org World Cup logic
# ------------------------------------------------------------

async def football_data_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not FOOTBALL_DATA_TOKEN:
        raise ValueError(
            "Missing FOOTBALL_DATA_TOKEN environment variable in Render. "
            "Add it in Render → Environment."
        )

    headers = {
        "X-Auth-Token": FOOTBALL_DATA_TOKEN,
    }

    url = f"{FOOTBALL_DATA_BASE_URL}/{endpoint.lstrip('/')}"

    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.get(url, headers=headers, params=params or {})

    if response.status_code >= 400:
        try:
            details = response.json()
        except Exception:
            details = response.text

        raise ValueError(
            f"football-data.org API error {response.status_code}: {details}"
        )

    return response.json()


def parse_football_data_datetime(utc_date: str) -> datetime:
    cleaned = utc_date.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


def format_dual_time(utc_date: Optional[str]) -> str:
    if not utc_date:
        return "EU: time unavailable\nIran: time unavailable"

    dt = parse_football_data_datetime(utc_date)

    eu_dt = dt.astimezone(ZoneInfo(EU_TIMEZONE))
    iran_dt = dt.astimezone(ZoneInfo(IRAN_TIMEZONE))

    eu_text = eu_dt.strftime("%d %b %Y, %H:%M %Z")
    iran_text = iran_dt.strftime("%d %b %Y, %H:%M %Z")

    return f"EU: {eu_text}\nIran: {iran_text}"


def format_match_score(match: Dict[str, Any]) -> str:
    home_team = match.get("homeTeam", {}).get("name") or "Home"
    away_team = match.get("awayTeam", {}).get("name") or "Away"

    score = match.get("score", {}) or {}
    full_time = score.get("fullTime", {}) or {}
    half_time = score.get("halfTime", {}) or {}

    home_score = full_time.get("home")
    away_score = full_time.get("away")

    if home_score is None or away_score is None:
        home_score = half_time.get("home")
        away_score = half_time.get("away")

    if home_score is None or away_score is None:
        return f"{home_team} vs {away_team}"

    return f"{home_team} {home_score} - {away_score} {away_team}"


def format_match_status(match: Dict[str, Any]) -> str:
    status = match.get("status", "UNKNOWN")

    status_names = {
        "SCHEDULED": "Scheduled",
        "TIMED": "Scheduled",
        "IN_PLAY": "Live",
        "PAUSED": "Half-time / paused",
        "FINISHED": "Finished",
        "SUSPENDED": "Suspended",
        "POSTPONED": "Postponed",
        "CANCELLED": "Cancelled",
        "AWARDED": "Awarded",
    }

    return status_names.get(status, status)


def format_match_item(match: Dict[str, Any], index: int) -> str:
    score_text = format_match_score(match)
    status_text = format_match_status(match)

    stage = match.get("stage") or "World Cup"
    group = match.get("group") or ""
    matchday = match.get("matchday")

    utc_date = match.get("utcDate")
    time_text = format_dual_time(utc_date)

    extra_parts = []
    if group:
        extra_parts.append(str(group).replace("_", " ").title())
    if matchday:
        extra_parts.append(f"Matchday {matchday}")
    if stage:
        extra_parts.append(str(stage).replace("_", " ").title())

    extra = " | ".join(extra_parts) if extra_parts else "World Cup"

    return (
        f"{index}. {score_text}\n"
        f"Status: {status_text}\n"
        f"Round: {extra}\n"
        f"{time_text}"
    )


async def get_world_cup_matches_by_date(date_text: str) -> List[Dict[str, Any]]:
    endpoint = f"competitions/{WORLD_CUP_COMPETITION}/matches"

    params = {
        "dateFrom": date_text,
        "dateTo": date_text,
        "season": WORLD_CUP_SEASON,
    }

    data = await football_data_get(endpoint, params)
    return data.get("matches", [])


async def get_world_cup_matches_range(date_from: str, date_to: str) -> List[Dict[str, Any]]:
    endpoint = f"competitions/{WORLD_CUP_COMPETITION}/matches"

    params = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "season": WORLD_CUP_SEASON,
    }

    data = await football_data_get(endpoint, params)
    return data.get("matches", [])


async def get_world_cup_live_matches() -> List[Dict[str, Any]]:
    today = datetime.now(ZoneInfo(EU_TIMEZONE)).date()
    date_from = (today - timedelta(days=1)).isoformat()
    date_to = (today + timedelta(days=1)).isoformat()

    matches = await get_world_cup_matches_range(date_from, date_to)

    live_statuses = {"IN_PLAY", "PAUSED"}
    return [match for match in matches if match.get("status") in live_statuses]


async def get_world_cup_standings() -> List[Dict[str, Any]]:
    endpoint = f"competitions/{WORLD_CUP_COMPETITION}/standings"

    params = {
        "season": WORLD_CUP_SEASON,
    }

    data = await football_data_get(endpoint, params)
    return data.get("standings", [])


def format_standing_table(standing: Dict[str, Any]) -> str:
    group_name = standing.get("group") or standing.get("type") or "Standings"
    group_title = str(group_name).replace("_", " ").title()

    table = standing.get("table", [])
    lines = [group_title]

    if not table:
        lines.append("No table data available.")
        return "\n".join(lines)

    for row in table:
        position = row.get("position", "-")
        team_name = row.get("team", {}).get("name", "Unknown team")
        played = row.get("playedGames", 0)
        won = row.get("won", 0)
        draw = row.get("draw", 0)
        lost = row.get("lost", 0)
        points = row.get("points", 0)
        goals_for = row.get("goalsFor", 0)
        goals_against = row.get("goalsAgainst", 0)
        goal_difference = row.get("goalDifference", 0)

        lines.append(
            f"{position}. {team_name} — {points} pts "
            f"(P{played}, W{won}, D{draw}, L{lost}, GF{goals_for}, GA{goals_against}, GD{goal_difference})"
        )

    return "\n".join(lines)


def group_matches_requested_group(standing: Dict[str, Any], requested_group: str) -> bool:
    group_name = str(standing.get("group") or "").upper()
    requested = requested_group.strip().upper()

    possible_names = {
        requested,
        f"GROUP_{requested}",
        f"GROUP {requested}",
    }

    normalized = group_name.replace("-", "_").replace(" ", "_")

    return (
        group_name in possible_names
        or normalized in possible_names
        or normalized.endswith(f"GROUP_{requested}")
        or group_name.endswith(f"GROUP {requested}")
    )


# ------------------------------------------------------------
# Image helpers
# ------------------------------------------------------------

def resize_for_telegram(img: Image.Image, max_size: int = 1400) -> Image.Image:
    img = img.copy()
    img.thumbnail((max_size, max_size))
    return img


def image_to_bytes(img: Image.Image, image_format: str = "JPEG") -> BytesIO:
    output = BytesIO()

    if image_format.upper() == "JPEG":
        img = img.convert("RGB")
        img.save(output, format="JPEG", quality=92, optimize=True)
        output.name = "edited_photo.jpg"

    elif image_format.upper() == "PNG":
        img.save(output, format="PNG", optimize=True)
        output.name = "edited_photo.png"

    else:
        raise ValueError("Unsupported image format.")

    output.seek(0)
    return output


def normalize_caption_command(caption: Optional[str]) -> Optional[str]:
    if not caption:
        return None

    first = caption.strip().split()[0].lower()

    if not first.startswith("/"):
        return None

    first = first[1:]

    if "@" in first:
        first = first.split("@", 1)[0]

    return first


# ------------------------------------------------------------
# Image filters
# ------------------------------------------------------------

def apply_vintage_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = resize_for_telegram(img)

    img = ImageEnhance.Color(img).enhance(0.58)
    img = ImageEnhance.Contrast(img).enhance(1.14)
    img = ImageEnhance.Brightness(img).enhance(1.03)

    sepia = ImageOps.grayscale(img)
    sepia = ImageOps.colorize(sepia, "#3b2614", "#f2d6a2")
    img = Image.blend(img, sepia, 0.60)

    img = img.filter(ImageFilter.GaussianBlur(radius=0.25))

    width, height = img.size
    small = 280
    mask = Image.new("L", (small, small), 0)
    cx, cy = small / 2, small / 2

    for y in range(small):
        for x in range(small):
            dx = (x - cx) / cx
            dy = (y - cy) / cy
            distance = (dx * dx + dy * dy) ** 0.5
            value = int(255 * max(0, 1 - distance * 0.9))
            mask.putpixel((x, y), value)

    mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    dark = Image.new("RGB", (width, height), "#1f1308")
    img = Image.composite(img, dark, mask)

    return img


def apply_cartoon_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = resize_for_telegram(img)

    base = img.filter(ImageFilter.MedianFilter(size=5))
    base = base.filter(ImageFilter.SMOOTH_MORE)
    base = ImageEnhance.Color(base).enhance(1.65)
    base = ImageEnhance.Contrast(base).enhance(1.25)
    base = ImageEnhance.Brightness(base).enhance(1.04)
    base = ImageOps.posterize(base, bits=4)

    gray = ImageOps.grayscale(img)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.autocontrast(edges)
    edges = ImageOps.invert(edges)
    edges = edges.point(lambda p: 255 if p > 80 else 0)

    cartoon = ImageChops.multiply(base, edges.convert("RGB"))
    cartoon = ImageEnhance.Sharpness(cartoon).enhance(1.4)

    return cartoon


def apply_caricature_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = resize_for_telegram(img)

    base = img.filter(ImageFilter.MedianFilter(size=7))
    base = base.filter(ImageFilter.SMOOTH_MORE)
    base = ImageEnhance.Color(base).enhance(2.0)
    base = ImageEnhance.Contrast(base).enhance(1.45)
    base = ImageEnhance.Brightness(base).enhance(1.05)
    base = ImageOps.posterize(base, bits=3)

    gray = ImageOps.grayscale(img)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.autocontrast(edges)
    edges = ImageOps.invert(edges)
    edges = edges.point(lambda p: 255 if p > 90 else 0)

    caricature = ImageChops.multiply(base, edges.convert("RGB"))
    caricature = ImageEnhance.Sharpness(caricature).enhance(1.8)

    return caricature


def apply_sticker_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    img = resize_for_telegram(img, max_size=512)

    rgb = img.convert("RGB")
    rgb = ImageEnhance.Color(rgb).enhance(1.35)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.18)
    img = rgb.convert("RGBA")

    border_size = 24
    shadow_offset = 10

    bordered = Image.new(
        "RGBA",
        (img.width + border_size * 2, img.height + border_size * 2),
        (255, 255, 255, 255),
    )
    bordered.paste(img, (border_size, border_size), img)

    final_img = Image.new(
        "RGBA",
        (bordered.width + shadow_offset, bordered.height + shadow_offset),
        (0, 0, 0, 0),
    )

    shadow = Image.new("RGBA", bordered.size, (0, 0, 0, 85))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=5))

    final_img.paste(shadow, (shadow_offset, shadow_offset), shadow)
    final_img.paste(bordered, (0, 0), bordered)

    return final_img


def apply_beach_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = resize_for_telegram(img)

    img = ImageEnhance.Color(img).enhance(1.30)
    img = ImageEnhance.Contrast(img).enhance(1.10)
    img = ImageEnhance.Brightness(img).enhance(1.10)

    warm_overlay = Image.new("RGB", img.size, "#ffd89a")
    img = Image.blend(img, warm_overlay, 0.10)

    img = ImageEnhance.Sharpness(img).enhance(1.15)

    return img


# ------------------------------------------------------------
# Telegram commands
# ------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hello! I can calculate Collatz sequences, edit photos, and show World Cup 2026 info.\n\n"
        "Math:\n"
        "/collatz 27 - calculate Collatz and send all steps as a text file\n\n"
        "Photos:\n"
        "/vintage - send a photo and I make it vintage\n"
        "/cartoon - send a photo and I make it cartoon style\n"
        "/caricature - send a photo and I make it fun caricature style\n"
        "/caricator - same as /caricature\n"
        "/sticker - send a photo and I make it sticker style\n"
        "/stiker - same as /sticker\n"
        "/beach - send a photo and I make it summer/beach style\n"
        "/summer - same as /beach\n"
        "/vacation - same as /beach\n\n"
        "World Cup 2026:\n"
        "/wc_today - today's matches in EU and Iran time\n"
        "/wc_tomorrow - tomorrow's matches in EU and Iran time\n"
        "/wc_live - live World Cup matches\n"
        "/wc_group A - Group A standings\n"
        "/wc_standings - all group standings\n\n"
        "/cancel - cancel current photo mode\n\n"
        "In a group, commands are the most reliable way to talk to me."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def collatz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /collatz 27")
        return

    try:
        n = int(context.args[0])

        report_text, steps, max_value, peak_index, sequence_length = build_collatz_text_report(n)

        filename = f"collatz_{n}_steps.txt"
        file_output = text_to_file(report_text, filename)

        await update.message.reply_text(
            f"Collatz result for n = {n}\n\n"
            f"Steps to reach 1: {steps}\n"
            f"Maximum value reached: {max_value}\n"
            f"Peak reached at step: {peak_index}\n"
            f"Sequence length: {sequence_length} numbers\n\n"
            f"I attached the full step-by-step sequence as a text file."
        )

        await update.message.reply_document(
            document=InputFile(file_output, filename=filename),
            caption=f"Full Collatz steps for n = {n}",
        )

    except ValueError as error:
        await update.message.reply_text(
            f"{error}\n\nPlease send a positive whole number, for example:\n/collatz 27"
        )


async def wc_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        today = datetime.now(ZoneInfo(EU_TIMEZONE)).date().isoformat()
        matches = await get_world_cup_matches_by_date(today)

        if not matches:
            await update.message.reply_text(
                f"No World Cup matches found for today.\n"
                f"Date checked: {today}\n"
                f"Times are shown in Central Europe and Iran time."
            )
            return

        lines = [
            "World Cup 2026 matches today",
            f"Date: {today}",
            "Times shown in Central Europe and Iran time",
            "",
        ]

        for index, match in enumerate(matches, start=1):
            lines.append(format_match_item(match, index))
            lines.append("")

        for chunk in split_long_text("\n".join(lines)):
            await update.message.reply_text(chunk)

    except Exception as error:
        await update.message.reply_text(f"Could not load World Cup matches.\n\nError: {error}")


async def wc_tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        tomorrow = (datetime.now(ZoneInfo(EU_TIMEZONE)).date() + timedelta(days=1)).isoformat()
        matches = await get_world_cup_matches_by_date(tomorrow)

        if not matches:
            await update.message.reply_text(
                f"No World Cup matches found for tomorrow.\n"
                f"Date checked: {tomorrow}\n"
                f"Times are shown in Central Europe and Iran time."
            )
            return

        lines = [
            "World Cup 2026 matches tomorrow",
            f"Date: {tomorrow}",
            "Times shown in Central Europe and Iran time",
            "",
        ]

        for index, match in enumerate(matches, start=1):
            lines.append(format_match_item(match, index))
            lines.append("")

        for chunk in split_long_text("\n".join(lines)):
            await update.message.reply_text(chunk)

    except Exception as error:
        await update.message.reply_text(f"Could not load World Cup matches.\n\nError: {error}")


async def wc_live_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        matches = await get_world_cup_live_matches()

        if not matches:
            await update.message.reply_text("No live World Cup matches right now.")
            return

        lines = [
            "Live World Cup 2026 matches",
            "Times shown in Central Europe and Iran time",
            "",
        ]

        for index, match in enumerate(matches, start=1):
            lines.append(format_match_item(match, index))
            lines.append("")

        for chunk in split_long_text("\n".join(lines)):
            await update.message.reply_text(chunk)

    except Exception as error:
        await update.message.reply_text(f"Could not load live World Cup matches.\n\nError: {error}")


async def wc_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /wc_group A")
        return

    requested_group = context.args[0].strip().upper()

    try:
        standings = await get_world_cup_standings()

        if not standings:
            await update.message.reply_text("No World Cup standings found yet.")
            return

        match = None

        for standing in standings:
            if group_matches_requested_group(standing, requested_group):
                match = standing
                break

        if not match:
            await update.message.reply_text(
                f"Could not find Group {requested_group}.\n"
                f"Try /wc_standings"
            )
            return

        text = format_standing_table(match)
        filename = f"world_cup_group_{requested_group}_standings.txt"
        file_output = text_to_file(text, filename)

        await update.message.reply_text(
            f"World Cup Group {requested_group} standings are ready.\n"
            f"I attached them as a text file."
        )

        await update.message.reply_document(
            document=InputFile(file_output, filename=filename),
            caption=f"World Cup Group {requested_group} standings",
        )

    except Exception as error:
        await update.message.reply_text(f"Could not load World Cup standings.\n\nError: {error}")


async def wc_standings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        standings = await get_world_cup_standings()

        if not standings:
            await update.message.reply_text("No World Cup standings found yet.")
            return

        lines = [
            "World Cup 2026 group standings",
            "",
        ]

        for standing in standings:
            lines.append(format_standing_table(standing))
            lines.append("")
            lines.append("-" * 60)
            lines.append("")

        text = "\n".join(lines)

        filename = "world_cup_2026_all_group_standings.txt"
        file_output = text_to_file(text, filename)

        await update.message.reply_text(
            "World Cup 2026 group standings are ready.\n"
            "I attached them as a text file."
        )

        await update.message.reply_document(
            document=InputFile(file_output, filename=filename),
            caption="World Cup 2026 all group standings",
        )

    except Exception as error:
        await update.message.reply_text(f"Could not load World Cup standings.\n\nError: {error}")


async def set_photo_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    context.user_data["photo_mode"] = mode

    messages = {
        "vintage": "Vintage mode selected. Now send me a photo 📸",
        "cartoon": "Cartoon mode selected. Now send me a photo 🎨",
        "caricature": "Caricature mode selected. Now send me a photo 😄",
        "sticker": "Sticker mode selected. Now send me a photo 🖼️",
        "beach": "Beach mode selected. Now send me a photo 🌴",
    }

    await update.message.reply_text(messages.get(mode, "Mode selected. Now send me a photo."))


async def vintage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "vintage")


async def cartoon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "cartoon")


async def caricature_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "caricature")


async def sticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "sticker")


async def beach_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "beach")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("photo_mode", None)

    await update.message.reply_text(
        "Cancelled. Send /vintage, /cartoon, /caricature, /sticker, /beach, or /collatz 27."
    )


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    if not message or not message.photo:
        return

    mode = context.user_data.get("photo_mode")
    caption_command = normalize_caption_command(message.caption)

    if caption_command == "vintage":
        mode = "vintage"
    elif caption_command == "cartoon":
        mode = "cartoon"
    elif caption_command in ["caricature", "caricator"]:
        mode = "caricature"
    elif caption_command in ["sticker", "stiker"]:
        mode = "sticker"
    elif caption_command in ["beach", "summer", "vacation"]:
        mode = "beach"

    if not mode:
        await message.reply_text(
            "Please choose a photo mode first:\n\n"
            "/vintage\n"
            "/cartoon\n"
            "/caricature\n"
            "/sticker\n"
            "/beach"
        )
        return

    await message.reply_text("Processing your photo...")

    try:
        photo = message.photo[-1]
        telegram_file = await photo.get_file()

        input_bytes = BytesIO()
        await telegram_file.download_to_memory(out=input_bytes)
        input_bytes.seek(0)

        img = Image.open(input_bytes)

        if mode == "vintage":
            edited = apply_vintage_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(
                photo=InputFile(output, filename="vintage.jpg"),
                caption="Your vintage photo is ready 📸",
            )

        elif mode == "cartoon":
            edited = apply_cartoon_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(
                photo=InputFile(output, filename="cartoon.jpg"),
                caption="Your cartoon photo is ready 🎨",
            )

        elif mode == "caricature":
            edited = apply_caricature_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(
                photo=InputFile(output, filename="caricature.jpg"),
                caption="Your caricature photo is ready 😄",
            )

        elif mode == "sticker":
            edited = apply_sticker_filter(img)
            output = image_to_bytes(edited, "PNG")
            await message.reply_document(
                document=InputFile(output, filename="sticker_style.png"),
                caption="Your sticker-style image is ready 🖼️",
            )

        elif mode == "beach":
            edited = apply_beach_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(
                photo=InputFile(output, filename="beach.jpg"),
                caption="Your beach photo is ready 🌴",
            )

        else:
            await message.reply_text(
                "Unknown mode. Use /vintage, /cartoon, /caricature, /sticker, or /beach."
            )

    except Exception as error:
        await message.reply_text(f"Sorry, I could not process that photo.\n\nError: {error}")

    finally:
        context.user_data.pop("photo_mode", None)


# ------------------------------------------------------------
# Register Telegram handlers
# ------------------------------------------------------------

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(CommandHandler("collatz", collatz_command))

telegram_app.add_handler(CommandHandler("wc_today", wc_today_command))
telegram_app.add_handler(CommandHandler("wc_tomorrow", wc_tomorrow_command))
telegram_app.add_handler(CommandHandler("wc_live", wc_live_command))
telegram_app.add_handler(CommandHandler("wc_group", wc_group_command))
telegram_app.add_handler(CommandHandler("wc_standings", wc_standings_command))

telegram_app.add_handler(CommandHandler("vintage", vintage_command))
telegram_app.add_handler(CommandHandler("cartoon", cartoon_command))
telegram_app.add_handler(CommandHandler("caricature", caricature_command))
telegram_app.add_handler(CommandHandler("caricator", caricature_command))
telegram_app.add_handler(CommandHandler("sticker", sticker_command))
telegram_app.add_handler(CommandHandler("stiker", sticker_command))
telegram_app.add_handler(CommandHandler("beach", beach_command))
telegram_app.add_handler(CommandHandler("summer", beach_command))
telegram_app.add_handler(CommandHandler("vacation", beach_command))
telegram_app.add_handler(CommandHandler("cancel", cancel_command))

telegram_app.add_handler(MessageHandler(filters.PHOTO, photo_handler))


# ------------------------------------------------------------
# FastAPI webhook
# ------------------------------------------------------------

@api.on_event("startup")
async def startup() -> None:
    await telegram_app.initialize()
    await telegram_app.start()

    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{SECRET_PATH}"
        await telegram_app.bot.set_webhook(url=webhook_url)
        print(f"Webhook set to: {webhook_url}")
    else:
        print("WEBHOOK_URL is not set. App is running, but Telegram webhook was not configured.")


@api.on_event("shutdown")
async def shutdown() -> None:
    await telegram_app.stop()
    await telegram_app.shutdown()


@api.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Collatz multi-tool Telegram bot is running.",
        "usage": [
            "/collatz 27",
            "/wc_today",
            "/wc_tomorrow",
            "/wc_live",
            "/wc_group A",
            "/wc_standings",
            "/vintage",
            "/cartoon",
            "/caricature",
            "/sticker",
            "/beach",
        ],
        "football_provider": "football-data.org",
        "world_cup_competition": WORLD_CUP_COMPETITION,
        "world_cup_season": WORLD_CUP_SEASON,
        "timezones": {
            "central_europe": EU_TIMEZONE,
            "iran": IRAN_TIMEZONE,
        },
    }


@api.head("/")
async def head_root():
    return {}


@api.post("/{path}")
async def telegram_webhook(path: str, request: Request):
    if path != SECRET_PATH:
        raise HTTPException(status_code=404, detail="Not found")

    data = await request.json()
    update = Update.de_json(data=data, bot=telegram_app.bot)

    await telegram_app.process_update(update)

    return {"ok": True}