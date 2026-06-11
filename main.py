import os
import re
import html
import time
from deep_translator import GoogleTranslator
from io import BytesIO
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import feedparser
from urllib.parse import quote_plus
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

# football-data.org
FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN") or os.getenv("FOOTBALL_API_KEY")
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"
WORLD_CUP_COMPETITION = os.getenv("WORLD_CUP_COMPETITION", "WC")
WORLD_CUP_SEASON = int(os.getenv("WORLD_CUP_SEASON", "2026"))

EU_TIMEZONE = os.getenv("WORLD_CUP_EU_TIMEZONE", "Europe/Berlin")
IRAN_TIMEZONE = os.getenv("WORLD_CUP_IRAN_TIMEZONE", "Asia/Tehran")

# X / Twitter API
TRUMP_X_USERNAME = os.getenv("TRUMP_X_USERNAME", "realDonaldTrump")

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
            "Add it in Render -> Environment."
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

        raise ValueError(f"football-data.org API error {response.status_code}: {details}")

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


async def get_all_world_cup_matches() -> List[Dict[str, Any]]:
    endpoint = f"competitions/{WORLD_CUP_COMPETITION}/matches"

    params = {
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


def extract_group_label_from_value(value: Any) -> str:
    if value is None:
        return "Unknown Group"

    value = str(value).strip()

    if not value:
        return "Unknown Group"

    return value


def normalize_group_label(value: Any) -> str:
    label = extract_group_label_from_value(value).upper().strip()
    label = label.replace("-", "_").replace(" ", "_")
    return label


def extract_group_letter_from_label(value: Any) -> Optional[str]:
    label = normalize_group_label(value)

    match = re.search(r"GROUP_?([A-Z])", label)
    if match:
        return match.group(1)

    if re.fullmatch(r"[A-Z]", label):
        return label

    return None


def extract_group_label(standing: Dict[str, Any]) -> str:
    raw_group = standing.get("group")
    raw_type = standing.get("type")

    value = raw_group or raw_type or "Unknown Group"
    return extract_group_label_from_value(value)


def extract_group_letter(standing: Dict[str, Any]) -> Optional[str]:
    return extract_group_letter_from_label(extract_group_label(standing))


def group_matches_requested_group(standing: Dict[str, Any], requested_group: str) -> bool:
    requested = requested_group.strip().upper()
    requested = requested.replace("GROUP", "").replace("_", "").replace("-", "").strip()

    standing_letter = extract_group_letter(standing)

    if standing_letter and standing_letter == requested:
        return True

    label = normalize_group_label(extract_group_label(standing))

    possible_labels = {
        requested,
        f"GROUP_{requested}",
        f"GROUP{requested}",
    }

    return label in possible_labels or label.endswith(f"GROUP_{requested}") or label.endswith(f"GROUP{requested}")


def format_standing_table(standing: Dict[str, Any]) -> str:
    group_label = extract_group_label(standing)
    group_letter = extract_group_letter(standing)

    if group_letter:
        group_title = f"Group {group_letter}"
    else:
        group_title = str(group_label).replace("_", " ").title()

    table = standing.get("table", [])

    lines = [
        group_title,
        f"Raw API group label: {group_label}",
        "",
    ]

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
            f"(P{played}, W{won}, D{draw}, L{lost}, "
            f"GF{goals_for}, GA{goals_against}, GD{goal_difference})"
        )

    return "\n".join(lines)


def initialize_group_team(table: Dict[str, Dict[str, Any]], team_name: str) -> None:
    if team_name not in table:
        table[team_name] = {
            "team": team_name,
            "played": 0,
            "won": 0,
            "draw": 0,
            "lost": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "points": 0,
        }


def build_group_tables_from_matches(matches: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """
    Builds group tables from match list.

    It includes scheduled teams with 0 points and updates stats for FINISHED matches.
    This helps when football-data.org does not expose group standings yet.
    """
    groups: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for match in matches:
        raw_group = match.get("group")

        if not raw_group:
            continue

        group_letter = extract_group_letter_from_label(raw_group)
        group_key = group_letter or str(raw_group).replace("_", " ").title()

        home = match.get("homeTeam", {}).get("name")
        away = match.get("awayTeam", {}).get("name")

        if not home or not away:
            continue

        if group_key not in groups:
            groups[group_key] = {}

        table = groups[group_key]

        initialize_group_team(table, home)
        initialize_group_team(table, away)

        status = match.get("status")
        if status != "FINISHED":
            continue

        score = match.get("score", {}) or {}
        full_time = score.get("fullTime", {}) or {}

        home_goals = full_time.get("home")
        away_goals = full_time.get("away")

        if home_goals is None or away_goals is None:
            continue

        table[home]["played"] += 1
        table[away]["played"] += 1

        table[home]["goals_for"] += home_goals
        table[home]["goals_against"] += away_goals

        table[away]["goals_for"] += away_goals
        table[away]["goals_against"] += home_goals

        if home_goals > away_goals:
            table[home]["won"] += 1
            table[away]["lost"] += 1
            table[home]["points"] += 3
        elif away_goals > home_goals:
            table[away]["won"] += 1
            table[home]["lost"] += 1
            table[away]["points"] += 3
        else:
            table[home]["draw"] += 1
            table[away]["draw"] += 1
            table[home]["points"] += 1
            table[away]["points"] += 1

        table[home]["goal_difference"] = table[home]["goals_for"] - table[home]["goals_against"]
        table[away]["goal_difference"] = table[away]["goals_for"] - table[away]["goals_against"]

    return groups


def format_derived_group_table(group_key: str, table: Dict[str, Dict[str, Any]]) -> str:
    rows = list(table.values())

    rows.sort(
        key=lambda row: (
            row["points"],
            row["goal_difference"],
            row["goals_for"],
            row["team"],
        ),
        reverse=True,
    )

    group_title = f"Group {group_key}" if re.fullmatch(r"[A-Z]", str(group_key)) else str(group_key)

    lines = [
        group_title,
        "Source: calculated from football-data.org match list",
        "",
    ]

    if not rows:
        lines.append("No teams found for this group.")
        return "\n".join(lines)

    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. {row['team']} — {row['points']} pts "
            f"(P{row['played']}, W{row['won']}, D{row['draw']}, L{row['lost']}, "
            f"GF{row['goals_for']}, GA{row['goals_against']}, GD{row['goal_difference']})"
        )

    return "\n".join(lines)


async def get_best_world_cup_group_tables() -> Dict[str, str]:
    """
    Returns group tables as text.

    First tries official standings endpoint.
    If groups are not available there, derives group tables from matches.
    """
    result: Dict[str, str] = {}

    try:
        standings = await get_world_cup_standings()
    except Exception:
        standings = []

    for standing in standings:
        letter = extract_group_letter(standing)
        if letter:
            result[letter] = format_standing_table(standing)

    if result:
        return result

    matches = await get_all_world_cup_matches()
    derived_groups = build_group_tables_from_matches(matches)

    for group_key, table in derived_groups.items():
        result[str(group_key).upper()] = format_derived_group_table(str(group_key).upper(), table)

    return result


def build_available_groups_debug_from_matches(matches: List[Dict[str, Any]]) -> str:
    lines = ["Available group labels from match list:", ""]

    seen = set()

    for match in matches:
        raw_group = match.get("group")
        if not raw_group:
            continue

        home = match.get("homeTeam", {}).get("name") or "Home"
        away = match.get("awayTeam", {}).get("name") or "Away"

        item = f"{raw_group}: {home} vs {away}"
        if item not in seen:
            lines.append(item)
            seen.add(item)

    if len(lines) == 2:
        lines.append("No group labels found in match list.")

    return "\n".join(lines)


# ------------------------------------------------------------
# X / Trump latest posts logic
# ------------------------------------------------------------

async def x_api_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not X_BEARER_TOKEN:
        raise ValueError(
            "Missing X_BEARER_TOKEN environment variable in Render. "
            "Add it if you want /trump to fetch latest X posts."
        )

    headers = {
        "Authorization": f"Bearer {X_BEARER_TOKEN}",
    }

    url = f"https://api.x.com/2/{endpoint.lstrip('/')}"

    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.get(url, headers=headers, params=params or {})

    if response.status_code >= 400:
        try:
            details = response.json()
        except Exception:
            details = response.text

        raise ValueError(f"X API error {response.status_code}: {details}")

    return response.json()


async def get_x_user_id(username: str) -> str:
    data = await x_api_get(
        f"users/by/username/{username}",
        {
            "user.fields": "id,name,username",
        },
    )

    user_data = data.get("data")
    if not user_data or not user_data.get("id"):
        raise ValueError(f"Could not find X user @{username}.")

    return user_data["id"]


async def get_latest_x_posts(username: str, limit: int = 5) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 10))

    user_id = await get_x_user_id(username)

    data = await x_api_get(
        f"users/{user_id}/tweets",
        {
            "max_results": max(5, limit),
            "tweet.fields": "created_at,public_metrics",
            "exclude": "retweets,replies",
        },
    )

    posts = data.get("data", [])
    return posts[:limit]


def format_x_post(username: str, post: Dict[str, Any], index: int) -> str:
    post_id = post.get("id")
    text = post.get("text", "")
    created_at = post.get("created_at")

    created_text = "time unavailable"
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            eu_dt = dt.astimezone(ZoneInfo(EU_TIMEZONE))
            iran_dt = dt.astimezone(ZoneInfo(IRAN_TIMEZONE))
            created_text = (
                f"EU: {eu_dt.strftime('%d %b %Y, %H:%M %Z')} | "
                f"Iran: {iran_dt.strftime('%d %b %Y, %H:%M %Z')}"
            )
        except Exception:
            created_text = created_at

    url = f"https://x.com/{username}/status/{post_id}" if post_id else f"https://x.com/{username}"

    return (
        f"{index}. @{username}\n"
        f"{created_text}\n"
        f"{text}\n"
        f"{url}"
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
        "Hello! I can calculate Collatz sequences, edit photos, show World Cup 2026 info, and fetch latest X posts.\n\n"
        "Math:\n"
        "/collatz 27 - calculate Collatz and send all steps as a text file\n\n"
        "Photos:\n"
        "/vintage - send a photo and I make it vintage\n"
        "/cartoon - send a photo and I make it cartoon style\n"
        "/caricature - send a photo and I make it fun caricature style\n"
        "/sticker - send a photo and I make it sticker style\n"
        "/beach - send a photo and I make it summer/beach style\n\n"
        "World Cup 2026:\n"
        "/wc_today - today's matches in EU and Iran time\n"
        "/wc_tomorrow - tomorrow's matches in EU and Iran time\n"
        "/wc_live - live World Cup matches\n"
        "/wc_group A - Group A standings as a text file\n"
        "/wc_standings - all group standings as a text file\n\n"
        "X / Twitter:\n"
        "/trump - latest posts from configured Trump X account\n\n"
        "/cancel - cancel current photo mode"
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
    requested_group = requested_group.replace("GROUP", "").replace("_", "").replace("-", "").strip()

    try:
        group_tables = await get_best_world_cup_group_tables()

        if requested_group in group_tables:
            text = group_tables[requested_group]
            filename = f"world_cup_group_{requested_group}_standings.txt"
            file_output = text_to_file(text, filename)

            await update.message.reply_text(
                f"World Cup Group {requested_group} standings are ready.\n"
                "I attached them as a text file."
            )

            await update.message.reply_document(
                document=InputFile(file_output, filename=filename),
                caption=f"World Cup Group {requested_group} standings",
            )
            return

        matches = await get_all_world_cup_matches()
        debug_text = build_available_groups_debug_from_matches(matches)

        if group_tables:
            debug_text += "\n\nAvailable generated group tables:\n"
            debug_text += "\n".join([f"Group {key}" for key in sorted(group_tables.keys())])

        filename = "world_cup_available_groups_debug.txt"
        file_output = text_to_file(debug_text, filename)

        await update.message.reply_text(
            f"Could not find Group {requested_group}.\n\n"
            "I attached a debug file showing available group labels."
        )

        await update.message.reply_document(
            document=InputFile(file_output, filename=filename),
            caption="Available World Cup group labels",
        )

    except Exception as error:
        await update.message.reply_text(f"Could not load World Cup standings.\n\nError: {error}")


async def wc_standings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        group_tables = await get_best_world_cup_group_tables()

        if not group_tables:
            matches = await get_all_world_cup_matches()
            debug_text = build_available_groups_debug_from_matches(matches)

            filename = "world_cup_standings_debug.txt"
            file_output = text_to_file(debug_text, filename)

            await update.message.reply_text(
                "No World Cup group standings found yet.\n"
                "I attached a debug file showing match/group labels returned by the API."
            )

            await update.message.reply_document(
                document=InputFile(file_output, filename=filename),
                caption="World Cup standings debug",
            )
            return

        lines = [
            "World Cup 2026 group standings",
            "",
        ]

        for key in sorted(group_tables.keys()):
            lines.append(group_tables[key])
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


def clean_rss_text(text: str) -> str:
    if not text:
        return ""

    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def summarize_news_entry(entry) -> str:
    title = clean_rss_text(getattr(entry, "title", ""))
    summary = clean_rss_text(getattr(entry, "summary", ""))

    # Google News RSS often includes the source name inside the title.
    # Example: "Trump says ... - CNN"
    if " - " in title:
        headline, source = title.rsplit(" - ", 1)
    else:
        headline, source = title, "Unknown source"

    if summary and summary != title:
        short_summary = summary
    else:
        short_summary = headline

    # Keep summary short for Telegram.
    if len(short_summary) > 350:
        short_summary = short_summary[:347] + "..."

    return headline, source, short_summary

def translate_to_farsi(text: str) -> str:
    if not text:
        return ""

    try:
        # Keep text shorter to avoid translation issues.
        text = text[:450]
        return GoogleTranslator(source="auto", target="fa").translate(text)
    except Exception:
        return "ترجمه در دسترس نیست."
    

async def trump_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        query = quote_plus("Trump latest news OR post OR tweet")
        rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

        feed = feedparser.parse(rss_url)
        entries = list(feed.entries)

        if not entries:
            await update.message.reply_text(
                "I could not find recent Trump-related news right now."
            )
            return

        # Sort chronologically: newest first.
        entries.sort(
            key=lambda entry: time.mktime(entry.published_parsed)
            if hasattr(entry, "published_parsed") and entry.published_parsed
            else 0,
            reverse=True,
        )

        entries = entries[:5]

        lines = [
            "Latest Trump-related news summary",
            "Sorted chronologically, newest first",
            "English + Farsi translation",
            "Source: Google News RSS",
            "",
        ]

        for index, entry in enumerate(entries, start=1):
            headline, source, short_summary = summarize_news_entry(entry)
            published = clean_rss_text(getattr(entry, "published", "time unavailable"))

            headline_fa = translate_to_farsi(headline)
            summary_fa = translate_to_farsi(short_summary)

            lines.append(f"{index}. {headline}")
            lines.append(f"Source: {source}")
            lines.append(f"Published: {published}")
            lines.append(f"Summary: {short_summary}")
            lines.append("")
            lines.append("ترجمه فارسی:")
            lines.append(f"عنوان: {headline_fa}")
            lines.append(f"خلاصه: {summary_fa}")
            lines.append("")
            lines.append("-" * 40)
            lines.append("")

        text = "\n".join(lines)

        for chunk in split_long_text(text):
            await update.message.reply_text(chunk)

    except Exception as error:
        await update.message.reply_text(
            f"Could not load Trump-related news summary.\n\nError: {error}"
        )

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

telegram_app.add_handler(CommandHandler(["trump", "Trump"], trump_command))

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
            "/trump",
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
        "x_username": TRUMP_X_USERNAME,
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