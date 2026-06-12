import re
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
    FOOTBALL_DATA_TOKEN,
    FOOTBALL_DATA_BASE_URL,
    WORLD_CUP_COMPETITION,
    WORLD_CUP_SEASON,
    EU_TIMEZONE,
    IRAN_TIMEZONE,
)
from utils import split_long_text, text_to_file


# ------------------------------------------------------------
# football-data.org API
# ------------------------------------------------------------

async def football_data_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not FOOTBALL_DATA_TOKEN:
        raise ValueError(
            "Missing FOOTBALL_DATA_TOKEN environment variable in Render. "
            "Add it in Render -> Environment."
        )

    headers = {"X-Auth-Token": FOOTBALL_DATA_TOKEN}
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


# ------------------------------------------------------------
# Match helpers
# ------------------------------------------------------------

def parse_football_data_datetime(utc_date: str) -> datetime:
    return datetime.fromisoformat(utc_date.replace("Z", "+00:00"))


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
    home = match.get("homeTeam", {}).get("name") or "Home"
    away = match.get("awayTeam", {}).get("name") or "Away"

    score = match.get("score", {}) or {}
    full_time = score.get("fullTime", {}) or {}
    half_time = score.get("halfTime", {}) or {}

    home_goals = full_time.get("home")
    away_goals = full_time.get("away")

    if home_goals is None or away_goals is None:
        home_goals = half_time.get("home")
        away_goals = half_time.get("away")

    if home_goals is None or away_goals is None:
        return f"{home} vs {away}"

    return f"{home} {home_goals} - {away_goals} {away}"


def format_match_status(match: Dict[str, Any]) -> str:
    status = match.get("status", "UNKNOWN")

    names = {
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

    return names.get(status, status)


def format_match_item(match: Dict[str, Any], index: int) -> str:
    stage = match.get("stage") or "World Cup"
    group = match.get("group") or ""
    matchday = match.get("matchday")

    parts = []

    if group:
        parts.append(str(group).replace("_", " ").title())

    if matchday:
        parts.append(f"Matchday {matchday}")

    if stage:
        parts.append(str(stage).replace("_", " ").title())

    extra = " | ".join(parts) if parts else "World Cup"

    return (
        f"{index}. {format_match_score(match)}\n"
        f"Status: {format_match_status(match)}\n"
        f"Round: {extra}\n"
        f"{format_dual_time(match.get('utcDate'))}"
    )


# ------------------------------------------------------------
# Match API calls
# ------------------------------------------------------------

async def get_world_cup_matches_by_date(date_text: str) -> List[Dict[str, Any]]:
    data = await football_data_get(
        f"competitions/{WORLD_CUP_COMPETITION}/matches",
        {
            "dateFrom": date_text,
            "dateTo": date_text,
            "season": WORLD_CUP_SEASON,
        },
    )

    return data.get("matches", [])


async def get_world_cup_matches_range(date_from: str, date_to: str) -> List[Dict[str, Any]]:
    data = await football_data_get(
        f"competitions/{WORLD_CUP_COMPETITION}/matches",
        {
            "dateFrom": date_from,
            "dateTo": date_to,
            "season": WORLD_CUP_SEASON,
        },
    )

    return data.get("matches", [])


async def get_all_world_cup_matches() -> List[Dict[str, Any]]:
    data = await football_data_get(
        f"competitions/{WORLD_CUP_COMPETITION}/matches",
        {
            "season": WORLD_CUP_SEASON,
        },
    )

    return data.get("matches", [])


async def get_world_cup_live_matches() -> List[Dict[str, Any]]:
    today = datetime.now(ZoneInfo(EU_TIMEZONE)).date()

    date_from = (today - timedelta(days=1)).isoformat()
    date_to = (today + timedelta(days=1)).isoformat()

    matches = await get_world_cup_matches_range(date_from, date_to)

    return [match for match in matches if match.get("status") in {"IN_PLAY", "PAUSED"}]


async def get_world_cup_standings() -> List[Dict[str, Any]]:
    data = await football_data_get(
        f"competitions/{WORLD_CUP_COMPETITION}/standings",
        {
            "season": WORLD_CUP_SEASON,
        },
    )

    return data.get("standings", [])


# ------------------------------------------------------------
# Group / standings helpers
# ------------------------------------------------------------

def extract_group_label_from_value(value: Any) -> str:
    if value is None:
        return "Unknown Group"

    value = str(value).strip()

    return value or "Unknown Group"


def normalize_group_label(value: Any) -> str:
    return (
        extract_group_label_from_value(value)
        .upper()
        .strip()
        .replace("-", "_")
        .replace(" ", "_")
    )


def extract_group_letter_from_label(value: Any) -> Optional[str]:
    label = normalize_group_label(value)

    match = re.search(r"GROUP_?([A-Z])", label)

    if match:
        return match.group(1)

    if re.fullmatch(r"[A-Z]", label):
        return label

    return None


def extract_group_label(standing: Dict[str, Any]) -> str:
    return extract_group_label_from_value(
        standing.get("group") or standing.get("type") or "Unknown Group"
    )


def extract_group_letter(standing: Dict[str, Any]) -> Optional[str]:
    return extract_group_letter_from_label(extract_group_label(standing))


def format_standing_table(standing: Dict[str, Any]) -> str:
    group_label = extract_group_label(standing)
    letter = extract_group_letter(standing)

    title = f"Group {letter}" if letter else str(group_label).replace("_", " ").title()

    lines = [
        title,
        f"Raw API group label: {group_label}",
        "",
    ]

    table = standing.get("table", [])

    if not table:
        lines.append("No table data available.")
        return "\n".join(lines)

    for row in table:
        team = row.get("team", {}).get("name", "Unknown team")

        lines.append(
            f"{row.get('position', '-')}. {team} — {row.get('points', 0)} pts "
            f"(P{row.get('playedGames', 0)}, "
            f"W{row.get('won', 0)}, "
            f"D{row.get('draw', 0)}, "
            f"L{row.get('lost', 0)}, "
            f"GF{row.get('goalsFor', 0)}, "
            f"GA{row.get('goalsAgainst', 0)}, "
            f"GD{row.get('goalDifference', 0)})"
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


def build_group_tables_from_matches(
    matches: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    groups: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for match in matches:
        raw_group = match.get("group")

        if not raw_group:
            continue

        group_key = extract_group_letter_from_label(raw_group) or str(raw_group).replace("_", " ").title()

        home = match.get("homeTeam", {}).get("name")
        away = match.get("awayTeam", {}).get("name")

        if not home or not away:
            continue

        groups.setdefault(group_key, {})

        table = groups[group_key]

        initialize_group_team(table, home)
        initialize_group_team(table, away)

        if match.get("status") != "FINISHED":
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

        table[home]["goal_difference"] = (
            table[home]["goals_for"] - table[home]["goals_against"]
        )
        table[away]["goal_difference"] = (
            table[away]["goals_for"] - table[away]["goals_against"]
        )

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

    title = f"Group {group_key}" if re.fullmatch(r"[A-Z]", str(group_key)) else str(group_key)

    lines = [
        title,
        "Source: calculated from football-data.org match list",
        "",
    ]

    if not rows:
        lines.append("No teams found for this group.")
        return "\n".join(lines)

    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. {row['team']} — {row['points']} pts "
            f"(P{row['played']}, "
            f"W{row['won']}, "
            f"D{row['draw']}, "
            f"L{row['lost']}, "
            f"GF{row['goals_for']}, "
            f"GA{row['goals_against']}, "
            f"GD{row['goal_difference']})"
        )

    return "\n".join(lines)


async def get_best_world_cup_group_tables() -> Dict[str, str]:
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

    for key, table in derived_groups.items():
        group_key = str(key).upper()
        result[group_key] = format_derived_group_table(group_key, table)

    return result


def build_available_groups_debug_from_matches(matches: List[Dict[str, Any]]) -> str:
    lines = [
        "Available group labels from match list:",
        "",
    ]

    seen = set()

    for match in matches:
        raw_group = match.get("group")

        if not raw_group:
            continue

        home = match.get("homeTeam", {}).get("name", "Home")
        away = match.get("awayTeam", {}).get("name", "Away")

        item = f"{raw_group}: {home} vs {away}"

        if item not in seen:
            lines.append(item)
            seen.add(item)

    if len(lines) == 2:
        lines.append("No group labels found in match list.")

    return "\n".join(lines)


# ------------------------------------------------------------
# Telegram commands
# ------------------------------------------------------------

async def wc_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

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
    if not update.message:
        return

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
    if not update.message:
        return

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
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage: /wc_group A")
        return

    requested = context.args[0].strip().upper()
    requested = requested.replace("GROUP", "").replace("_", "").replace("-", "").strip()

    try:
        group_tables = await get_best_world_cup_group_tables()

        if requested in group_tables:
            text = group_tables[requested]
            filename = f"world_cup_group_{requested}_standings.txt"

            await update.message.reply_text(
                f"World Cup Group {requested} standings are ready.\n"
                "I attached them as a text file."
            )

            await update.message.reply_document(
                document=InputFile(text_to_file(text, filename), filename=filename),
                caption=f"World Cup Group {requested} standings",
            )
            return

        matches = await get_all_world_cup_matches()
        debug_text = build_available_groups_debug_from_matches(matches)

        if group_tables:
            debug_text += "\n\nAvailable generated group tables:\n"
            debug_text += "\n".join([f"Group {key}" for key in sorted(group_tables.keys())])

        filename = "world_cup_available_groups_debug.txt"

        await update.message.reply_text(
            f"Could not find Group {requested}.\n\n"
            "I attached a debug file showing available group labels."
        )

        await update.message.reply_document(
            document=InputFile(text_to_file(debug_text, filename), filename=filename),
            caption="Available World Cup group labels",
        )

    except Exception as error:
        await update.message.reply_text(f"Could not load World Cup standings.\n\nError: {error}")


async def wc_standings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        group_tables = await get_best_world_cup_group_tables()

        if not group_tables:
            matches = await get_all_world_cup_matches()
            debug_text = build_available_groups_debug_from_matches(matches)
            filename = "world_cup_standings_debug.txt"

            await update.message.reply_text(
                "No World Cup group standings found yet.\n"
                "I attached a debug file showing match/group labels returned by the API."
            )

            await update.message.reply_document(
                document=InputFile(text_to_file(debug_text, filename), filename=filename),
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

        await update.message.reply_text(
            "World Cup 2026 group standings are ready.\n"
            "I attached them as a text file."
        )

        await update.message.reply_document(
            document=InputFile(text_to_file(text, filename), filename=filename),
            caption="World Cup 2026 all group standings",
        )

    except Exception as error:
        await update.message.reply_text(f"Could not load World Cup standings.\n\nError: {error}")


def register_fifa_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("wc_today", wc_today_command))
    app.add_handler(CommandHandler("wc_tomorrow", wc_tomorrow_command))
    app.add_handler(CommandHandler("wc_live", wc_live_command))
    app.add_handler(CommandHandler("wc_group", wc_group_command))
    app.add_handler(CommandHandler("wc_standings", wc_standings_command))