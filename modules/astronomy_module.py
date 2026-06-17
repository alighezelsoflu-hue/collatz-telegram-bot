import math
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from telegram import InputFile, Update
from telegram.ext import Application, CommandHandler, ContextTypes


# ------------------------------------------------------------
# Settings and constants
# ------------------------------------------------------------

SYNODIC_MONTH_DAYS = 29.53058867
# Known new moon: 2000-01-06 18:14 UTC
MOON_EPOCH = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)

AU_KM = 149_597_870.7
LIGHT_YEAR_KM = 9_460_730_472_580.8
PARSEC_KM = 30_856_775_814_913.672
EARTH_G = 9.80665
G_CONST = 6.67430e-11

MAX_DISTANCE_VALUE = 1e30


# ------------------------------------------------------------
# Optional AI explanation integration
# ------------------------------------------------------------

ASTRO_AI_TRIGGER_WORDS = {"ai", "explain", "explanation", "interpret", "tutor", "teach", "lesson"}


TUTOR_LANGUAGES = {
    "en": "English",
    "english": "English",
    "fa": "Persian/Farsi",
    "farsi": "Persian/Farsi",
    "persian": "Persian/Farsi",
    "de": "German",
    "german": "German",
    "it": "Italian",
    "italian": "Italian",
    "fr": "French",
    "french": "French",
    "es": "Spanish",
    "spanish": "Spanish",
    "ar": "Arabic",
    "arabic": "Arabic",
}


def normalize_tutor_token(token: str) -> str:
    return token.strip().lower().strip(".,!?:;()[]{}")


def language_from_token(token: str):
    return TUTOR_LANGUAGES.get(normalize_tutor_token(token))


def extract_tutor_language(text: str) -> tuple[str, str]:
    """Return (text_without_initial_language_code, language_name)."""
    parts = text.strip().split()
    if not parts:
        return "", "English"

    language = language_from_token(parts[0])
    if language:
        return " ".join(parts[1:]).strip(), language

    return text.strip(), "English"

try:
    from modules.ai_module import call_ai, AIProviderError
except Exception:
    call_ai = None

    class AIProviderError(Exception):
        pass


def split_long_text(text: str, limit: int = 3500) -> List[str]:
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current = ""
    for line in text.splitlines():
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line
    if current:
        chunks.append(current)
    return chunks


def split_astro_ai_request(args: List[str]) -> Tuple[List[str], bool, str]:
    """Remove optional AI/tutor trigger words and optional tutor language."""
    cleaned: List[str] = []
    wants_ai = False
    language = "English"
    skip_next = False

    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue

        normalized = normalize_tutor_token(arg)
        if normalized in ASTRO_AI_TRIGGER_WORDS or normalized in {"teach", "lesson"}:
            wants_ai = True
            if normalized in {"tutor", "teach", "lesson"} and index + 1 < len(args):
                selected_language = language_from_token(args[index + 1])
                if selected_language:
                    language = selected_language
                    skip_next = True
            continue

        cleaned.append(arg)

    return cleaned, wants_ai, language


async def send_astro_ai_explanation(
    update: Update,
    command_name: str,
    user_input: str,
    deterministic_context: str = "",
    mode: str = "explain",
    language: str = "English",
) -> None:
    if not update.message:
        return

    if call_ai is None:
        await update.message.reply_text(
            "AI explanation is not available because modules.ai_module could not be imported."
        )
        return

    user_input = user_input.strip()
    deterministic_context = deterministic_context.strip()

    if deterministic_context and len(deterministic_context) > 2500:
        deterministic_context = deterministic_context[:2500] + "\n...[truncated]"

    is_tutor = mode.lower() == "tutor"

    if is_tutor:
        system_prompt = (
            "You are AhBashin Bot's dedicated Astronomy AI Tutor. Teach astronomy like a patient, "
            "expert human tutor. Build intuition first, then connect the idea to the relevant astronomy facts, "
            "geometry, units, dates, or physical laws. Explain moon phases, illumination, orbital periods, "
            "planet properties, astronomical distances, gravity, meteor showers, and solar-system diagrams. "
            "Use simple analogies when useful, but stay scientifically accurate. If a deterministic result from "
            "the astronomy module is provided, do not override it; explain it. Clearly separate observation facts "
            "from interpretation. Avoid astrology or horoscope claims unless the user explicitly asks for a cultural/entertainment comparison. "
            "Keep answers friendly, structured, and student-focused."
        )
        final_instruction = (
            "Tutor the user on this astronomy topic/result. Structure the answer as:\n"
            "1) Big idea\n2) What the result means\n3) Why it happens\n4) How to visualize it\n5) Quick practice question or sky-watching tip."
        )
        title = "AI astronomy tutor 🧑‍🏫🌌\n\n"
        temperature = 0.35
    else:
        system_prompt = (
            "You are AhBashin Bot's astronomy tutor. Explain astronomy results clearly, briefly, "
            "and accurately for a student. The deterministic astronomy module already performed the "
            "calculation or lookup, so do not override or contradict it. Explain moon phases, planets, "
            "astronomical distances, gravity comparisons, and meteor showers in simple terms. Keep the answer concise."
        )
        final_instruction = (
            "Explain what this astronomy result means, which concept is involved, and how the user should interpret it. "
            "For moon plots or solar-system diagrams, explain the visual meaning."
        )
        title = "AI astronomy explanation 🧠🌙\n\n"
        temperature = 0.25

    system_prompt += f"\n\nRespond in {language}."

    prompt_parts = [
        f"Astronomy command: /{command_name}",
        f"User input: {user_input or '(no input)'}",
    ]

    if deterministic_context:
        prompt_parts.append(f"Result/context from the astronomy module:\n{deterministic_context}")

    prompt_parts.append(final_instruction)

    try:
        explanation = await call_ai(system_prompt, "\n\n".join(prompt_parts), temperature=temperature)
    except Exception as error:
        label = "tutor" if is_tutor else "explanation"
        await update.message.reply_text(f"AI astronomy {label} error.\n\nError: {error}")
        return

    text = title + explanation
    for chunk in split_long_text(text, limit=3500):
        await update.message.reply_text(chunk)


def detect_astro_ai_mode(args: List[str]) -> str:
    for arg in args:
        normalized = arg.strip().lower().strip(".,!?:;()[]{}")
        if normalized in {"tutor", "teach", "lesson"}:
            return "tutor"
    return "explain"


def astro_ai_wrapper(command_name: str, handler):
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        original_args = list(getattr(context, "args", []) or [])
        cleaned_args, wants_ai, ai_language = split_astro_ai_request(original_args)
        ai_mode = detect_astro_ai_mode(original_args)
        context.args = cleaned_args

        try:
            await handler(update, context)
        finally:
            context.args = original_args

        if wants_ai:
            await send_astro_ai_explanation(
                update,
                command_name=command_name,
                user_input=" ".join(cleaned_args),
                mode=ai_mode,
                language=ai_language,
            )

    return wrapped


async def astro_ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain an astronomy request/result using AI.

    Usage:
    /astro_ai explain moon phases
    or reply to an astronomy result/plot caption with /astro_ai
    """
    if not update.message:
        return

    text = " ".join(context.args).strip()

    if not text and update.message.reply_to_message:
        reply = update.message.reply_to_message
        if reply.text:
            text = reply.text.strip()
        elif reply.caption:
            text = reply.caption.strip()

    if not text:
        await update.message.reply_text(
            "Astronomy AI usage:\n\n"
            "Add ai/explain to an astronomy command:\n"
            "/moon explain\n"
            "/planet mars ai\n\n"
            "Or reply to an astronomy result with:\n"
            "/astro_ai"
        )
        return

    await send_astro_ai_explanation(
        update,
        command_name="astro_ai",
        user_input=text,
        deterministic_context=text,
    )


async def astro_tutor_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dedicated astronomy tutor mode.

    Usage:
    /astro_tutor explain moon phases
    /astro_tutor teach me why Mars looks red
    or reply to an astronomy result/problem with /astro_tutor
    """
    if not update.message:
        return

    text = " ".join(context.args).strip()

    if not text and update.message.reply_to_message:
        reply = update.message.reply_to_message
        if reply.text:
            text = reply.text.strip()
        elif reply.caption:
            text = reply.caption.strip()

    text, tutor_language = extract_tutor_language(text)

    if not text:
        await update.message.reply_text(
            "Astronomy tutor usage:\n\nDefault language is English. Add fa, de, it, fr, es, or ar after the tutor command.\n\nLanguage examples:\n/astro_tutor fa explain moon phases\n/astro_tutor de teach me why Mars looks red\n/astro_tutor it explain astronomical units\n\n"
            "/astro_tutor explain moon phases\n"
            "/astro_tutor teach me why Mars looks red\n"
            "/astro_tutor why do meteor showers happen?\n"
            "/astro_tutor explain astronomical units\n\n"
            "Or reply to an astronomy result/problem with /astro_tutor"
        )
        return

    await send_astro_ai_explanation(
        update,
        command_name="astro_tutor",
        user_input=text,
        deterministic_context=text,
        mode="tutor",
        language=tutor_language,
    )


PLANETS: Dict[str, Dict] = {
    "mercury": {
        "name": "Mercury",
        "type": "Terrestrial planet",
        "mass_kg": 3.3011e23,
        "radius_km": 2439.7,
        "gravity": 3.70,
        "day": "58.6 Earth days",
        "year": "88 Earth days",
        "moons": 0,
        "distance_au": 0.387,
        "fact": "Smallest planet and closest to the Sun.",
    },
    "venus": {
        "name": "Venus",
        "type": "Terrestrial planet",
        "mass_kg": 4.8675e24,
        "radius_km": 6051.8,
        "gravity": 8.87,
        "day": "243 Earth days",
        "year": "225 Earth days",
        "moons": 0,
        "distance_au": 0.723,
        "fact": "Hottest planet because of its thick CO₂ atmosphere.",
    },
    "earth": {
        "name": "Earth",
        "type": "Terrestrial planet",
        "mass_kg": 5.97237e24,
        "radius_km": 6371.0,
        "gravity": 9.80665,
        "day": "23h 56m",
        "year": "365.25 days",
        "moons": 1,
        "distance_au": 1.000,
        "fact": "Only known planet with life.",
    },
    "moon": {
        "name": "Moon",
        "type": "Natural satellite",
        "mass_kg": 7.342e22,
        "radius_km": 1737.4,
        "gravity": 1.62,
        "day": "27.3 Earth days",
        "year": "orbits Earth in 27.3 days",
        "moons": 0,
        "distance_au": 0.00257,
        "fact": "Earth's only natural satellite.",
    },
    "mars": {
        "name": "Mars",
        "type": "Terrestrial planet",
        "mass_kg": 6.4171e23,
        "radius_km": 3389.5,
        "gravity": 3.71,
        "day": "24h 37m",
        "year": "687 Earth days",
        "moons": 2,
        "distance_au": 1.524,
        "fact": "Known as the Red Planet.",
    },
    "jupiter": {
        "name": "Jupiter",
        "type": "Gas giant",
        "mass_kg": 1.8982e27,
        "radius_km": 69911,
        "gravity": 24.79,
        "day": "9h 56m",
        "year": "11.86 Earth years",
        "moons": 95,
        "distance_au": 5.203,
        "fact": "Largest planet in the Solar System.",
    },
    "saturn": {
        "name": "Saturn",
        "type": "Gas giant",
        "mass_kg": 5.6834e26,
        "radius_km": 58232,
        "gravity": 10.44,
        "day": "10h 42m",
        "year": "29.45 Earth years",
        "moons": 146,
        "distance_au": 9.537,
        "fact": "Famous for its bright ring system.",
    },
    "uranus": {
        "name": "Uranus",
        "type": "Ice giant",
        "mass_kg": 8.6810e25,
        "radius_km": 25362,
        "gravity": 8.69,
        "day": "17h 14m",
        "year": "84 Earth years",
        "moons": 28,
        "distance_au": 19.191,
        "fact": "Rotates almost sideways.",
    },
    "neptune": {
        "name": "Neptune",
        "type": "Ice giant",
        "mass_kg": 1.02413e26,
        "radius_km": 24622,
        "gravity": 11.15,
        "day": "16h 6m",
        "year": "164.8 Earth years",
        "moons": 16,
        "distance_au": 30.07,
        "fact": "Has the fastest winds in the Solar System.",
    },
    "pluto": {
        "name": "Pluto",
        "type": "Dwarf planet",
        "mass_kg": 1.303e22,
        "radius_km": 1188.3,
        "gravity": 0.62,
        "day": "6.39 Earth days",
        "year": "248 Earth years",
        "moons": 5,
        "distance_au": 39.48,
        "fact": "A dwarf planet in the Kuiper belt.",
    },
}

METEOR_SHOWERS = [
    {"name": "Quadrantids", "peak_month": 1, "peak_day": 4, "active": "Dec 28 – Jan 12", "rate": "Up to 120/hour", "tip": "Best after midnight under dark skies."},
    {"name": "Lyrids", "peak_month": 4, "peak_day": 22, "active": "Apr 16 – Apr 25", "rate": "10–20/hour", "tip": "Look toward Lyra after midnight."},
    {"name": "Eta Aquariids", "peak_month": 5, "peak_day": 6, "active": "Apr 19 – May 28", "rate": "Up to 50/hour", "tip": "Best before dawn; stronger in the Southern Hemisphere."},
    {"name": "Perseids", "peak_month": 8, "peak_day": 12, "active": "Jul 17 – Aug 24", "rate": "Up to 100/hour", "tip": "One of the easiest annual showers to watch."},
    {"name": "Draconids", "peak_month": 10, "peak_day": 8, "active": "Oct 6 – Oct 10", "rate": "Variable", "tip": "Best in the evening, unusual for meteor showers."},
    {"name": "Orionids", "peak_month": 10, "peak_day": 21, "active": "Oct 2 – Nov 7", "rate": "10–20/hour", "tip": "Fast meteors from Halley's Comet debris."},
    {"name": "Leonids", "peak_month": 11, "peak_day": 17, "active": "Nov 6 – Nov 30", "rate": "10–15/hour", "tip": "Occasionally produces meteor storms."},
    {"name": "Geminids", "peak_month": 12, "peak_day": 14, "active": "Dec 4 – Dec 17", "rate": "Up to 120/hour", "tip": "Often the strongest and most reliable shower."},
    {"name": "Ursids", "peak_month": 12, "peak_day": 22, "active": "Dec 17 – Dec 26", "rate": "5–10/hour", "tip": "Best near the north celestial pole."},
]


# ------------------------------------------------------------
# General helpers
# ------------------------------------------------------------

def load_font(size: int = 22):
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


def fmt(value: float, digits: int = 6) -> str:
    if abs(value) < 1e-15:
        value = 0.0

    if abs(value - round(value)) < 1e-12 and abs(value) < 1e12:
        return str(int(round(value)))

    return f"{value:.{digits}g}"


def parse_date_arg(args: List[str]) -> date:
    if not args:
        return datetime.now(timezone.utc).date()

    text = args[0].strip()

    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        raise ValueError("Date must be in YYYY-MM-DD format, for example: 2026-06-17")


def astronomy_help_text() -> str:
    return (
        "Astronomy commands 🌙🪐\n\n"
        "Moon:\n"
        "/moon - today's moon phase\n"
        "/moon 2026-06-17 - moon phase for a date\n"
        "/moonplot - draw today's moon phase\n"
        "/moonplot 2026-06-17 - draw moon phase for a date\n\n"
        "Solar System:\n"
        "/planet mars - planet facts\n"
        "/planet jupiter - planet facts\n"
        "/solar_system - planets in order and simple diagram\n\n"
        "Distances and gravity:\n"
        "/astro_distance 1 au to km - astronomy unit conversion\n"
        "/astro_distance 4.2 ly to km\n"
        "/gravity_compare 70 - compare weight for 70 kg mass\n\n"
        "Meteor showers:\n"
        "/meteor - upcoming meteor showers\n\n"
        "AI explanation:\n"
        "Add ai/explain to any astronomy command, example:\n"
        "/moon explain\n"
        "/astro_ai - explain a replied astronomy result\n\n"
        "Works offline and does not need an API key."
    )


# ------------------------------------------------------------
# Moon calculations
# ------------------------------------------------------------

def moon_phase_data(target_date: date) -> Dict:
    dt = datetime(target_date.year, target_date.month, target_date.day, 12, 0, tzinfo=timezone.utc)
    days_since_epoch = (dt - MOON_EPOCH).total_seconds() / 86400.0
    age = days_since_epoch % SYNODIC_MONTH_DAYS
    phase_fraction = age / SYNODIC_MONTH_DAYS
    angle = 2 * math.pi * phase_fraction
    illumination = (1 - math.cos(angle)) / 2 * 100
    waxing = age < SYNODIC_MONTH_DAYS / 2

    phase_name, emoji = moon_phase_name(age)
    next_new = days_until_moon_age(age, 0.0)
    next_full = days_until_moon_age(age, SYNODIC_MONTH_DAYS / 2)

    return {
        "date": target_date,
        "age": age,
        "phase_fraction": phase_fraction,
        "angle": angle,
        "illumination": illumination,
        "waxing": waxing,
        "phase_name": phase_name,
        "emoji": emoji,
        "next_new_date": target_date + timedelta(days=round(next_new)),
        "next_full_date": target_date + timedelta(days=round(next_full)),
        "days_to_new": next_new,
        "days_to_full": next_full,
    }


def days_until_moon_age(current_age: float, target_age: float) -> float:
    delta = target_age - current_age

    if delta <= 0:
        delta += SYNODIC_MONTH_DAYS

    return delta


def moon_phase_name(age: float) -> Tuple[str, str]:
    # Names based on approximate age in days.
    if age < 1.84566:
        return "New Moon", "🌑"
    if age < 5.53699:
        return "Waxing Crescent", "🌒"
    if age < 9.22831:
        return "First Quarter", "🌓"
    if age < 12.91963:
        return "Waxing Gibbous", "🌔"
    if age < 16.61096:
        return "Full Moon", "🌕"
    if age < 20.30228:
        return "Waning Gibbous", "🌖"
    if age < 23.99361:
        return "Last Quarter", "🌗"
    if age < 27.68493:
        return "Waning Crescent", "🌘"

    return "New Moon", "🌑"


def build_moon_report(data: Dict) -> str:
    direction = "waxing" if data["waxing"] else "waning"

    return (
        f"Moon phase {data['emoji']}\n\n"
        f"Date: {data['date'].isoformat()}\n"
        f"Phase: {data['phase_name']} ({direction})\n"
        f"Moon age: {data['age']:.2f} days\n"
        f"Illumination: {data['illumination']:.1f}%\n\n"
        f"Next full moon: {data['next_full_date'].isoformat()} "
        f"in {data['days_to_full']:.1f} days\n"
        f"Next new moon: {data['next_new_date'].isoformat()} "
        f"in {data['days_to_new']:.1f} days\n\n"
        "Note: moon phase is an offline approximation."
    )


def create_moon_image(data: Dict) -> BytesIO:
    width = 900
    height = 760
    moon_size = 420
    moon_radius = moon_size // 2
    moon_left = (width - moon_size) // 2
    moon_top = 150
    center_x = moon_left + moon_radius
    center_y = moon_top + moon_radius

    image = Image.new("RGB", (width, height), "#07111f")
    draw = ImageDraw.Draw(image)

    title_font = load_font(36)
    label_font = load_font(24)
    small_font = load_font(20)

    draw.text((50, 35), "Moon Phase", fill="white", font=title_font)
    draw.text(
        (50, 85),
        f"{data['date'].isoformat()} | {data['phase_name']} | {data['illumination']:.1f}% illuminated",
        fill="#cbd5e1",
        font=label_font,
    )

    # Draw a physically-inspired illuminated lunar disk.
    # Viewer looks along +z. Sun direction rotates around the x-z plane.
    alpha = data["angle"]
    sun = (math.sin(alpha), 0.0, -math.cos(alpha))

    for py in range(moon_size):
        y = (py - moon_radius) / moon_radius
        for px in range(moon_size):
            x = (px - moon_radius) / moon_radius
            r2 = x * x + y * y
            if r2 > 1:
                continue

            z = math.sqrt(max(0.0, 1.0 - r2))
            dot = x * sun[0] + y * sun[1] + z * sun[2]

            # Base moon texture: subtle radial gray variation.
            radial = 1 - math.sqrt(r2)
            crater_texture = 10 * math.sin(18 * x + 9 * y) + 7 * math.sin(25 * x - 11 * y)

            if dot > 0:
                brightness = 145 + 75 * max(0.0, dot) + 20 * radial + crater_texture
            else:
                brightness = 22 + 28 * radial + crater_texture * 0.25

            brightness = max(8, min(235, int(brightness)))
            image.putpixel((moon_left + px, moon_top + py), (brightness, brightness, brightness))

    # Moon outline
    draw.ellipse(
        (moon_left, moon_top, moon_left + moon_size, moon_top + moon_size),
        outline="#e5e7eb",
        width=3,
    )

    info_y = moon_top + moon_size + 40
    direction = "waxing" if data["waxing"] else "waning"

    lines = [
        f"Phase: {data['phase_name']} ({direction}) {data['emoji']}",
        f"Moon age: {data['age']:.2f} days of {SYNODIC_MONTH_DAYS:.2f}",
        f"Next full moon: {data['next_full_date'].isoformat()} | Next new moon: {data['next_new_date'].isoformat()}",
    ]

    for i, line in enumerate(lines):
        draw.text((50, info_y + i * 35), line, fill="#e5e7eb", font=small_font)

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = "moon_phase.png"
    return output


# ------------------------------------------------------------
# Planet and solar system
# ------------------------------------------------------------

def planet_report(name: str) -> str:
    key = name.strip().lower()

    if key not in PLANETS:
        valid = ", ".join(p["name"] for p in PLANETS.values())
        raise ValueError(f"Unknown planet/body. Try one of: {valid}")

    p = PLANETS[key]
    escape_velocity = math.sqrt(2 * G_CONST * p["mass_kg"] / (p["radius_km"] * 1000))

    return (
        f"{p['name']} 🪐\n\n"
        f"Type: {p['type']}\n"
        f"Mass: {p['mass_kg']:.4g} kg\n"
        f"Mean radius: {fmt(p['radius_km'])} km\n"
        f"Surface gravity: {fmt(p['gravity'])} m/s²\n"
        f"Escape velocity: {fmt(escape_velocity / 1000)} km/s\n"
        f"Day length: {p['day']}\n"
        f"Orbital period: {p['year']}\n"
        f"Moons: {p['moons']}\n"
        f"Mean distance from Sun/Earth reference: {fmt(p['distance_au'])} AU\n\n"
        f"Fact: {p['fact']}"
    )


def create_solar_system_image() -> BytesIO:
    width = 1500
    height = 620
    image = Image.new("RGB", (width, height), "#06101f")
    draw = ImageDraw.Draw(image)

    title_font = load_font(40)
    label_font = load_font(20)
    small_font = load_font(16)

    draw.text((50, 35), "Solar System", fill="white", font=title_font)
    draw.text(
        (50, 85),
        "Planet sizes and distances are stylized for readability, not to scale.",
        fill="#cbd5e1",
        font=label_font,
    )

    sun_x = 90
    sun_y = 310
    draw.ellipse((sun_x - 48, sun_y - 48, sun_x + 48, sun_y + 48), fill="#facc15", outline="#fde68a", width=3)
    draw.text((sun_x - 20, sun_y + 58), "Sun", fill="white", font=label_font)

    order = ["mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune"]
    xs = [210, 330, 455, 585, 760, 950, 1160, 1360]
    radii = [10, 16, 17, 13, 44, 38, 29, 28]
    colors = ["#a3a3a3", "#f6c177", "#38bdf8", "#ef4444", "#d6a05d", "#e7c98d", "#67e8f9", "#3b82f6"]

    for key, x, radius, color in zip(order, xs, radii, colors):
        y = sun_y
        p = PLANETS[key]

        draw.line((sun_x + 60, y, x - radius - 8, y), fill="#1e293b", width=2)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline="white", width=2)

        if key == "saturn":
            draw.ellipse((x - 58, y - 18, x + 58, y + 18), outline="#f8e7a2", width=3)

        draw.text((x - 45, y + 58), p["name"], fill="white", font=small_font)
        draw.text((x - 35, y + 82), f"{p['distance_au']} AU", fill="#94a3b8", font=small_font)

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = "solar_system.png"
    return output


def solar_system_text() -> str:
    order = ["mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune"]
    lines = [
        "Solar System 🪐",
        "",
        "Planets in order from the Sun:",
        "Mercury → Venus → Earth → Mars → Jupiter → Saturn → Uranus → Neptune",
        "",
        "Quick facts:",
    ]

    for index, key in enumerate(order, start=1):
        p = PLANETS[key]
        lines.append(
            f"{index}. {p['name']} — {p['type']}, gravity {fmt(p['gravity'])} m/s², distance {fmt(p['distance_au'])} AU"
        )

    lines.extend([
        "",
        "Use /planet mars or /planet jupiter for detailed facts.",
    ])

    return "\n".join(lines)


# ------------------------------------------------------------
# Distance conversion and gravity compare
# ------------------------------------------------------------

def normalize_unit(unit: str) -> str:
    unit = unit.strip().lower()

    aliases = {
        "meter": "m", "meters": "m", "metre": "m", "metres": "m", "m": "m",
        "km": "km", "kilometer": "km", "kilometers": "km", "kilometre": "km", "kilometres": "km",
        "au": "au", "astronomicalunit": "au", "astronomicalunits": "au",
        "ly": "ly", "lightyear": "ly", "lightyears": "ly", "light-year": "ly", "light-years": "ly",
        "pc": "pc", "parsec": "pc", "parsecs": "pc",
    }

    compact = unit.replace(" ", "").replace("_", "")

    if compact in aliases:
        return aliases[compact]

    raise ValueError("Supported units: m, km, au, ly, pc")


def unit_to_km(value: float, unit: str) -> float:
    if unit == "m":
        return value / 1000
    if unit == "km":
        return value
    if unit == "au":
        return value * AU_KM
    if unit == "ly":
        return value * LIGHT_YEAR_KM
    if unit == "pc":
        return value * PARSEC_KM

    raise ValueError("Unsupported unit.")


def km_to_unit(value_km: float, unit: str) -> float:
    if unit == "m":
        return value_km * 1000
    if unit == "km":
        return value_km
    if unit == "au":
        return value_km / AU_KM
    if unit == "ly":
        return value_km / LIGHT_YEAR_KM
    if unit == "pc":
        return value_km / PARSEC_KM

    raise ValueError("Unsupported unit.")


def parse_astro_distance(args: List[str]) -> Tuple[float, str, str]:
    if len(args) < 4:
        raise ValueError("Usage: /astro_distance 1 au to km")

    try:
        value = float(args[0].replace(",", ""))
    except Exception:
        raise ValueError("Distance value must be a number.")

    if not math.isfinite(value) or abs(value) > MAX_DISTANCE_VALUE:
        raise ValueError("Distance value is too large.")

    lowered = [arg.lower() for arg in args]

    if "to" not in lowered:
        raise ValueError("Use 'to', for example: /astro_distance 1 au to km")

    to_index = lowered.index("to")

    if to_index != 2 or len(args) != 4:
        raise ValueError("Usage: /astro_distance 1 au to km")

    from_unit = normalize_unit(args[1])
    to_unit = normalize_unit(args[3])

    return value, from_unit, to_unit


def build_gravity_compare_report(mass_kg: float) -> str:
    if mass_kg <= 0 or mass_kg > 1e9:
        raise ValueError("Mass must be positive and reasonable, for example: /gravity_compare 70")

    order = ["moon", "mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto"]
    lines = [
        f"Gravity comparison for mass = {fmt(mass_kg)} kg",
        "",
        "Weight force and Earth-equivalent scale reading:",
        "",
    ]

    for key in order:
        p = PLANETS[key]
        weight_n = mass_kg * p["gravity"]
        earth_equiv_kg = weight_n / EARTH_G
        lines.append(
            f"{p['name']}: {fmt(weight_n)} N | {fmt(earth_equiv_kg)} kg-equivalent"
        )

    lines.extend([
        "",
        "Mass stays the same everywhere; weight changes with gravity.",
    ])

    return "\n".join(lines)


# ------------------------------------------------------------
# Meteor showers
# ------------------------------------------------------------

def meteor_report() -> str:
    today = datetime.now(timezone.utc).date()
    year = today.year

    upcoming = []
    for shower in METEOR_SHOWERS:
        peak = date(year, shower["peak_month"], shower["peak_day"])
        if peak < today:
            peak = date(year + 1, shower["peak_month"], shower["peak_day"])
        upcoming.append((peak, shower))

    upcoming.sort(key=lambda item: item[0])

    lines = [
        "Meteor showers 🌠",
        "",
        "Next upcoming showers:",
        "",
    ]

    for peak, shower in upcoming[:6]:
        days_left = (peak - today).days
        lines.append(f"{shower['name']} — peak around {peak.isoformat()} ({days_left} days)")
        lines.append(f"Active: {shower['active']} | Rate: {shower['rate']}")
        lines.append(f"Tip: {shower['tip']}")
        lines.append("")

    lines.append("For best viewing: dark sky, no bright Moon, after midnight except Draconids.")

    return "\n".join(lines).strip()


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

async def astrohelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(astronomy_help_text())


async def moon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        target_date = parse_date_arg(context.args)
        data = moon_phase_data(target_date)
        await update.message.reply_text(build_moon_report(data))
    except Exception as error:
        await update.message.reply_text(
            "Moon command error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/moon\n"
            "/moon 2026-06-17"
        )


async def moonplot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        target_date = parse_date_arg(context.args)
        data = moon_phase_data(target_date)
        image = create_moon_image(data)
        await update.message.reply_photo(
            photo=InputFile(image, filename="moon_phase.png"),
            caption=(
                f"{data['date'].isoformat()} — {data['phase_name']} {data['emoji']} "
                f"({data['illumination']:.1f}% illuminated)"
            ),
        )
    except Exception as error:
        await update.message.reply_text(
            "Moon plot error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/moonplot\n"
            "/moonplot 2026-06-17"
        )


async def planet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Please provide a planet/body name.\n\n"
            "Examples:\n"
            "/planet mars\n"
            "/planet jupiter\n"
            "/planet moon"
        )
        return

    try:
        await update.message.reply_text(planet_report(context.args[0]))
    except Exception as error:
        await update.message.reply_text(f"Planet command error.\n\nError: {error}")


async def solar_system_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        await update.message.reply_text(solar_system_text())
        image = create_solar_system_image()
        await update.message.reply_photo(
            photo=InputFile(image, filename="solar_system.png"),
            caption="Solar System diagram — stylized, not to scale",
        )
    except Exception as error:
        await update.message.reply_text(f"Solar system error.\n\nError: {error}")


async def astro_distance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        value, from_unit, to_unit = parse_astro_distance(context.args)
        value_km = unit_to_km(value, from_unit)
        result = km_to_unit(value_km, to_unit)

        await update.message.reply_text(
            "Astronomy distance conversion 🌌\n\n"
            f"{fmt(value)} {from_unit} = {fmt(result, 10)} {to_unit}\n\n"
            f"In kilometers: {fmt(value_km, 10)} km"
        )
    except Exception as error:
        await update.message.reply_text(
            "Astronomy distance error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/astro_distance 1 au to km\n"
            "/astro_distance 4.2 ly to km\n"
            "/astro_distance 384400 km to au"
        )


async def gravity_compare_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Please provide mass in kg.\n\n"
            "Example:\n"
            "/gravity_compare 70"
        )
        return

    try:
        mass_kg = float(context.args[0].replace(",", ""))
        await update.message.reply_text(build_gravity_compare_report(mass_kg))
    except Exception as error:
        await update.message.reply_text(f"Gravity comparison error.\n\nError: {error}")


async def meteor_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(meteor_report())


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

def register_astronomy_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("astrohelp", astrohelp_command))
    app.add_handler(CommandHandler("astro_ai", astro_ai_command))
    app.add_handler(CommandHandler("astroai", astro_ai_command))
    app.add_handler(CommandHandler("astronomy_ai", astro_ai_command))
    app.add_handler(CommandHandler("astrology_ai", astro_ai_command))
    app.add_handler(CommandHandler("astro_tutor", astro_tutor_command))
    app.add_handler(CommandHandler("astrotutor", astro_tutor_command))
    app.add_handler(CommandHandler("astronomy_tutor", astro_tutor_command))
    app.add_handler(CommandHandler("tutor_astro", astro_tutor_command))
    app.add_handler(CommandHandler("tutor_astronomy", astro_tutor_command))
    app.add_handler(CommandHandler("astrology_tutor", astro_tutor_command))

    def add(names: List[str], handler, command_name: str) -> None:
        wrapped = astro_ai_wrapper(command_name, handler)
        for name in names:
            app.add_handler(CommandHandler(name, wrapped))

    add(["moon"], moon_command, "moon")
    add(["moonplot"], moonplot_command, "moonplot")
    add(["planet"], planet_command, "planet")
    add(["solar_system"], solar_system_command, "solar_system")
    add(["astro_distance"], astro_distance_command, "astro_distance")
    add(["gravity_compare"], gravity_compare_command, "gravity_compare")
    add(["meteor"], meteor_command, "meteor")
