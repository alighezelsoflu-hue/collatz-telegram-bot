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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Example: https://your-app-name.onrender.com
SECRET_PATH = os.getenv("SECRET_PATH", "telegram-webhook")

FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN")
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
# General helper functions
# ------------------------------------------------------------

def split_long_text(text: str, limit: int = 3500) -> List[str]:
    """
    Telegram messages have a max size, so split long replies safely.
    """
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
    """
    Build a full Collatz report as plain text.

    Returns:
    report_text, steps, max_value, peak_index, sequence_length
    """
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


def text_to_file(text: str, filename: str) -> BytesIO:
    output = BytesIO()
    output.write(text.encode("utf-8"))
    output.seek(0)
    output.name = filename
    return output


# ------------------------------------------------------------
# World Cup 2026 logic
# ------------------------------------------------------------

async def football_data_get(endpoint: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not FOOTBALL_DATA_TOKEN:
        raise ValueError(
            "Missing FOOTBALL_DATA_TOKEN environment variable in Render. "
            "Add it in Render → Environment."
        )

    headers = {
        "X-Auth-Token": FOOTBALL_DATA_TOKEN,
    }

    url = f"{FOOTBALL_DATA_BASE_URL}/{endpoint.lstrip('/')}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, headers=headers, params=params or {})
        response.raise_for_status()
        return response.json()


def parse_api_datetime(api_datetime: str) -> datetime:
    """
    Parse API-Football fixture datetime.
    """
    cleaned = api_datetime.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


def format_dual_time(api_datetime: str) -> str:
    """
    Show both Central Europe time and Iran time.
    """
    dt = parse_api_datetime(api_datetime)

    eu_dt = dt.astimezone(ZoneInfo(EU_TIMEZONE))
    iran_dt = dt.astimezone(ZoneInfo(IRAN_TIMEZONE))

    eu_text = eu_dt.strftime("%d %b %Y, %H:%M %Z")
    iran_text = iran_dt.strftime("%d %b %Y, %H:%M %Z")

    return f"EU: {eu_text}\nIran: {iran_text}"


def get_fixture_score_text(fixture_item: Dict[str, Any]) -> str:
    teams = fixture_item.get("teams", {})
    goals = fixture_item.get("goals", {})

    home = teams.get("home", {}).get("name", "Home")
    away = teams.get("away", {}).get("name", "Away")

    home_goals = goals.get("home")
    away_goals = goals.get("away")

    if home_goals is None or away_goals is None:
        return f"{home} vs {away}"

    return f"{home} {home_goals} - {away_goals} {away}"


def get_fixture_status_text(fixture_item: Dict[str, Any]) -> str:
    fixture = fixture_item.get("fixture", {})
    status = fixture.get("status", {})

    long_status = status.get("long") or "Unknown"
    short_status = status.get("short") or ""
    elapsed = status.get("elapsed")

    if elapsed is not None and short_status not in ["FT", "AET", "PEN"]:
        return f"{long_status} - {elapsed}'"

    return long_status


def format_fixture_item(fixture_item: Dict[str, Any], index: int) -> str:
    fixture = fixture_item.get("fixture", {})
    league = fixture_item.get("league", {})

    score_text = get_fixture_score_text(fixture_item)
    status_text = get_fixture_status_text(fixture_item)

    venue = fixture.get("venue", {}) or {}
    venue_name = venue.get("name") or "Unknown stadium"
    city = venue.get("city") or "Unknown city"

    round_name = league.get("round") or "World Cup"

    fixture_date = fixture.get("date")
    if fixture_date:
        time_text = format_dual_time(fixture_date)
    else:
        time_text = "Time unavailable"

    return (
        f"{index}. {score_text}\n"
        f"Status: {status_text}\n"
        f"Round: {round_name}\n"
        f"{time_text}\n"
        f"Venue: {venue_name}, {city}"
    )


async def get_world_cup_fixtures_by_date(date_text: str) -> List[Dict[str, Any]]:
    params = {
        "league": WORLD_CUP_LEAGUE_ID,
        "season": WORLD_CUP_SEASON,
        "date": date_text,
        "timezone": EU_TIMEZONE,
    }

    data = await api_football_get("fixtures", params)
    return data.get("response", [])


async def get_world_cup_live_fixtures() -> List[Dict[str, Any]]:
    params = {
        "live": "all",
        "timezone": EU_TIMEZONE,
    }

    data = await api_football_get("fixtures", params)
    fixtures = data.get("response", [])

    # Keep only World Cup fixtures.
    return [
        item for item in fixtures
        if item.get("league", {}).get("id") == WORLD_CUP_LEAGUE_ID
    ]


async def get_world_cup_standings() -> List[List[Dict[str, Any]]]:
    params = {
        "league": WORLD_CUP_LEAGUE_ID,
        "season": WORLD_CUP_SEASON,
    }

    data = await api_football_get("standings", params)
    response = data.get("response", [])

    if not response:
        return []

    league_data = response[0].get("league", {})
    standings = league_data.get("standings", [])

    return standings


def format_standings_group(group_rows: List[Dict[str, Any]]) -> str:
    if not group_rows:
        return "No standings available."

    group_name = group_rows[0].get("group", "Group")

    lines = [f"{group_name}"]

    for row in group_rows:
        rank = row.get("rank", "-")
        team_name = row.get("team", {}).get("name", "Unknown team")
        points = row.get("points", 0)
        played = row.get("all", {}).get("played", 0)
        win = row.get("all", {}).get("win", 0)
        draw = row.get("all", {}).get("draw", 0)
        lose = row.get("all", {}).get("lose", 0)
        goals_for = row.get("all", {}).get("goals", {}).get("for", 0)
        goals_against = row.get("all", {}).get("goals", {}).get("against", 0)
        goal_diff = row.get("goalsDiff", 0)

        lines.append(
            f"{rank}. {team_name} — {points} pts "
            f"(P{played}, W{win}, D{draw}, L{lose}, GF{goals_for}, GA{goals_against}, GD{goal_diff})"
        )

    return "\n".join(lines)


# ------------------------------------------------------------
# Image helper functions
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
    """
    Converts:
    /vintage
    /vintage@MyBot

    into:
    vintage
    """
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
    """
    Summer / beach style as a clean photo filter only.

    No sunglasses.
    No stickers.
    No clothing/body changes.
    """
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
            document=file_output,
            filename=filename,
            caption=f"Full Collatz steps for n = {n}",
        )

    except ValueError as error:
        await update.message.reply_text(
            f"{error}\n\nPlease send a positive whole number, for example:\n/collatz 27"
        )


async def wc_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        today = datetime.now(ZoneInfo(EU_TIMEZONE)).date().isoformat()
        fixtures = await get_world_cup_fixtures_by_date(today)

        if not fixtures:
            await update.message.reply_text(
                f"No World Cup matches found for today.\n"
                f"Date checked: {today}\n"
                f"Times are shown in Central Europe and Iran time."
            )
            return

        lines = [
            f"World Cup 2026 matches today",
            f"Date: {today}",
            f"Times shown in Central Europe and Iran time",
            "",
        ]

        for index, item in enumerate(fixtures, start=1):
            lines.append(format_fixture_item(item, index))
            lines.append("")

        text = "\n".join(lines)

        for chunk in split_long_text(text):
            await update.message.reply_text(chunk)

    except Exception as error:
        await update.message.reply_text(f"Could not load World Cup matches.\n\nError: {error}")


async def wc_tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        tomorrow = (datetime.now(ZoneInfo(EU_TIMEZONE)).date() + timedelta(days=1)).isoformat()
        fixtures = await get_world_cup_fixtures_by_date(tomorrow)

        if not fixtures:
            await update.message.reply_text(
                f"No World Cup matches found for tomorrow.\n"
                f"Date checked: {tomorrow}\n"
                f"Times are shown in Central Europe and Iran time."
            )
            return

        lines = [
            f"World Cup 2026 matches tomorrow",
            f"Date: {tomorrow}",
            f"Times shown in Central Europe and Iran time",
            "",
        ]

        for index, item in enumerate(fixtures, start=1):
            lines.append(format_fixture_item(item, index))
            lines.append("")

        text = "\n".join(lines)

        for chunk in split_long_text(text):
            await update.message.reply_text(chunk)

    except Exception as error:
        await update.message.reply_text(f"Could not load World Cup matches.\n\nError: {error}")


async def wc_live_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        fixtures = await get_world_cup_live_fixtures()

        if not fixtures:
            await update.message.reply_text("No live World Cup matches right now.")
            return

        lines = [
            "Live World Cup 2026 matches",
            "Times shown in Central Europe and Iran time",
            "",
        ]

        for index, item in enumerate(fixtures, start=1):
            lines.append(format_fixture_item(item, index))
            lines.append("")

        text = "\n".join(lines)

        for chunk in split_long_text(text):
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

        matching_group = None

        for group_rows in standings:
            if not group_rows:
                continue

            group_name = group_rows[0].get("group", "")
            normalized = group_name.upper()

            if normalized.endswith(f"GROUP {requested_group}") or normalized.endswith(f"GROUP {requested_group.upper()}"):
                matching_group = group_rows
                break

            if f"GROUP {requested_group}" in normalized:
                matching_group = group_rows
                break

        if not matching_group:
            await update.message.reply_text(
                f"Could not find Group {requested_group}.\n"
                f"Try: /wc_standings"
            )
            return

        await update.message.reply_text(format_standings_group(matching_group))

    except Exception as error:
        await update.message.reply_text(f"Could not load World Cup standings.\n\nError: {error}")


async def wc_standings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        standings = await get_world_cup_standings()

        if not standings:
            await update.message.reply_text("No World Cup standings found yet.")
            return

        lines = ["World Cup 2026 group standings", ""]

        for group_rows in standings:
            lines.append(format_standings_group(group_rows))
            lines.append("")

        text = "\n".join(lines)

        for chunk in split_long_text(text):
            await update.message.reply_text(chunk)

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
                photo=InputFile(output),
                caption="Your vintage photo is ready 📸",
            )

        elif mode == "cartoon":
            edited = apply_cartoon_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(
                photo=InputFile(output),
                caption="Your cartoon photo is ready 🎨",
            )

        elif mode == "caricature":
            edited = apply_caricature_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(
                photo=InputFile(output),
                caption="Your caricature photo is ready 😄",
            )

        elif mode == "sticker":
            edited = apply_sticker_filter(img)
            output = image_to_bytes(edited, "PNG")
            await message.reply_document(
                document=InputFile(output),
                caption="Your sticker-style image is ready 🖼️",
            )

        elif mode == "beach":
            edited = apply_beach_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(
                photo=InputFile(output),
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