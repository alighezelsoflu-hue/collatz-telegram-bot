"""
Physics module for LakLak Telegram Bot.

Lightweight implementation using only standard Python + Pillow.
No numpy, scipy, matplotlib, or sklearn required.

Commands:
/physicshelp
/kinematics
/motionplot
/projectile
/projectileplot
/force
/weight
/friction
/kinetic
/potential
/momentum
/wave
/waveplot
/ohm
/series
/parallel
/spring
/shmplot
/lens
/gravity
/gravityplot
/convert
"""

from __future__ import annotations

import math
import re
from io import BytesIO
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont
from telegram import InputFile, Update
from telegram.ext import Application, CommandHandler, ContextTypes


# ------------------------------------------------------------
# Limits and constants
# ------------------------------------------------------------

G_EARTH = 9.80665
G_GRAVITY = 6.67430e-11
MAX_PLOT_SAMPLES = 600
MAX_SERIES_POINTS = 800


# ------------------------------------------------------------
# General helpers
# ------------------------------------------------------------

def clean_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def parse_float(value: str) -> float:
    value = value.strip().replace(",", "")
    if not value:
        raise ValueError("empty number")
    return float(value)


def parse_key_values(args: Sequence[str]) -> Dict[str, float]:
    """
    Parses command arguments like:
    u=0 a=9.8 t=5
    speed=20 angle=45

    Also accepts comma-separated chunks:
    u=0, a=9.8, t=5
    """
    text = " ".join(args).replace(",", " ").strip()
    if not text:
        return {}

    result: Dict[str, float] = {}
    tokens = [token for token in text.split() if token.strip()]

    aliases = {
        "velocity": "v",
        "final": "v",
        "initial": "u",
        "distance": "s",
        "displacement": "s",
        "acceleration": "a",
        "time": "t",
        "mass": "m",
        "speed": "speed",
        "theta": "angle",
        "lambda": "wavelength",
        "lam": "wavelength",
        "l": "wavelength",
        "freq": "f",
        "frequency": "f",
        "period": "period",
        "amp": "amplitude",
        "a0": "amplitude",
        "normal": "normal",
        "n": "normal",
        "mu": "mu",
        "voltage": "v_voltage",
        "current": "i_current",
        "resistance": "r_resistance",
        "power": "p_power",
        "object": "object_distance",
        "object_distance": "object_distance",
        "do": "object_distance",
        "d_o": "object_distance",
        "di": "image_distance",
        "d_i": "image_distance",
        "image": "image_distance",
        "focal": "focal_length",
        "focal_length": "focal_length",
        "radius": "r",
        "distance_r": "r",
    }

    for token in tokens:
        if "=" not in token:
            continue

        key, raw_value = token.split("=", 1)
        key = clean_key(key)
        key = aliases.get(key, key)
        result[key] = parse_float(raw_value)

    return result


def require(params: Dict[str, float], *keys: str) -> None:
    missing = [key for key in keys if key not in params]
    if missing:
        raise ValueError("Missing: " + ", ".join(missing))


def fmt(value: float, digits: int = 6) -> str:
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "∞" if value > 0 else "-∞"
    if abs(value) < 1e-12:
        value = 0.0
    if abs(value - round(value)) < 1e-10:
        return str(int(round(value)))
    if abs(value) >= 1e6 or (0 < abs(value) < 1e-4):
        return f"{value:.{digits}e}"
    return f"{value:.{digits}g}"


def maybe_get(params: Dict[str, float], *keys: str) -> Optional[float]:
    for key in keys:
        if key in params:
            return params[key]
    return None


def parse_number_list(args: Sequence[str]) -> List[float]:
    text = " ".join(args).replace(",", " ").replace(";", " ")
    values = []
    for part in text.split():
        if part.strip():
            values.append(parse_float(part))
    if not values:
        raise ValueError("Please provide numbers.")
    return values


def split_long_text(text: str, limit: int = 3500) -> List[str]:
    if len(text) <= limit:
        return [text]

    chunks = []
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


# ------------------------------------------------------------
# Plot helpers using Pillow
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


def nice_axis_label(value: float) -> str:
    return fmt(value, 4)


def make_plot_image(
    title: str,
    series: Sequence[Dict],
    x_label: str = "x",
    y_label: str = "y",
    filename: str = "physics_plot.png",
    width: int = 1200,
    height: int = 800,
    show_zero_axes: bool = True,
) -> BytesIO:
    """
    series item example:
    {
      "name": "position",
      "points": [(x, y), ...],
      "color": "#1f77b4",
      "width": 4,
      "dots": False,
      "fill_to_y": None,
    }
    """
    all_points: List[Tuple[float, float]] = []
    for item in series:
        all_points.extend(item.get("points", []))

    finite_points = [
        (x, y)
        for x, y in all_points
        if math.isfinite(x) and math.isfinite(y)
    ]
    if not finite_points:
        raise ValueError("No finite points to plot.")

    x_values = [p[0] for p in finite_points]
    y_values = [p[1] for p in finite_points]

    xmin, xmax = min(x_values), max(x_values)
    ymin, ymax = min(y_values), max(y_values)

    if show_zero_axes:
        xmin = min(xmin, 0.0)
        xmax = max(xmax, 0.0)
        ymin = min(ymin, 0.0)
        ymax = max(ymax, 0.0)

    if abs(xmax - xmin) < 1e-12:
        xmin -= 1
        xmax += 1
    if abs(ymax - ymin) < 1e-12:
        ymin -= 1
        ymax += 1

    x_pad = (xmax - xmin) * 0.08
    y_pad = (ymax - ymin) * 0.12
    xmin -= x_pad
    xmax += x_pad
    ymin -= y_pad
    ymax += y_pad

    margin_left = 110
    margin_right = 60
    margin_top = 95
    margin_bottom = 115
    plot_left = margin_left
    plot_right = width - margin_right
    plot_top = margin_top
    plot_bottom = height - margin_bottom
    plot_width = plot_right - plot_left
    plot_height = plot_bottom - plot_top

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = load_font(34)
    label_font = load_font(22)
    small_font = load_font(18)

    draw.text((margin_left, 32), title[:90], fill="black", font=title_font)
    draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), outline="#222222", width=2, fill="#fbfbfb")

    def map_x(x: float) -> int:
        return int(plot_left + (x - xmin) / (xmax - xmin) * plot_width)

    def map_y(y: float) -> int:
        return int(plot_bottom - (y - ymin) / (ymax - ymin) * plot_height)

    grid_lines = 10
    for i in range(grid_lines + 1):
        gx = plot_left + i * plot_width / grid_lines
        gy = plot_top + i * plot_height / grid_lines
        draw.line((gx, plot_top, gx, plot_bottom), fill="#dddddd", width=1)
        draw.line((plot_left, gy, plot_right, gy), fill="#dddddd", width=1)

    if show_zero_axes and xmin <= 0 <= xmax:
        x0 = map_x(0)
        draw.line((x0, plot_top, x0, plot_bottom), fill="#333333", width=3)
    if show_zero_axes and ymin <= 0 <= ymax:
        y0 = map_y(0)
        draw.line((plot_left, y0, plot_right, y0), fill="#333333", width=3)

    for i in range(grid_lines + 1):
        x_value = xmin + i * (xmax - xmin) / grid_lines
        x_pixel = plot_left + i * plot_width / grid_lines
        draw.text((x_pixel - 28, plot_bottom + 16), nice_axis_label(x_value), fill="#333333", font=small_font)

        y_value = ymax - i * (ymax - ymin) / grid_lines
        y_pixel = plot_top + i * plot_height / grid_lines
        draw.text((14, y_pixel - 10), nice_axis_label(y_value), fill="#333333", font=small_font)

    default_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]

    for idx, item in enumerate(series):
        points = item.get("points", [])
        color = item.get("color", default_colors[idx % len(default_colors)])
        line_width = int(item.get("width", 4))
        dots = bool(item.get("dots", False))
        fill_to_y = item.get("fill_to_y")

        pixel_points = []
        for x, y in points:
            if not math.isfinite(x) or not math.isfinite(y):
                pixel_points.append(None)
                continue
            if y < ymin or y > ymax or x < xmin or x > xmax:
                pixel_points.append(None)
            else:
                pixel_points.append((map_x(x), map_y(y)))

        if fill_to_y is not None:
            fill_base = max(min(float(fill_to_y), ymax), ymin)
            base_y = map_y(fill_base)
            polygon = [(map_x(x), map_y(y)) for x, y in points if math.isfinite(x) and math.isfinite(y) and xmin <= x <= xmax and ymin <= y <= ymax]
            if len(polygon) >= 2:
                fill_polygon = polygon + [(polygon[-1][0], base_y), (polygon[0][0], base_y)]
                draw.polygon(fill_polygon, fill="#d8e8ff")

        current_segment = []
        for point in pixel_points:
            if point is None:
                if len(current_segment) >= 2:
                    draw.line(current_segment, fill=color, width=line_width)
                current_segment = []
            else:
                current_segment.append(point)
        if len(current_segment) >= 2:
            draw.line(current_segment, fill=color, width=line_width)

        if dots:
            for point in pixel_points:
                if point is not None:
                    x, y = point
                    draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)

    # Legend
    legend_x = plot_left
    legend_y = height - 78
    for idx, item in enumerate(series):
        name = item.get("name")
        if not name:
            continue
        color = item.get("color", default_colors[idx % len(default_colors)])
        lx = legend_x + idx * 230
        draw.line((lx, legend_y + 10, lx + 40, legend_y + 10), fill=color, width=5)
        draw.text((lx + 50, legend_y), str(name)[:22], fill="black", font=small_font)

    draw.text((plot_left, height - 45), f"{x_label}  |  {y_label}", fill="#555555", font=label_font)

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = filename
    return output


# ------------------------------------------------------------
# Physics help
# ------------------------------------------------------------

def physics_help_text() -> str:
    return (
        "Physics commands ⚛️\n\n"
        "Motion:\n"
        "/kinematics u=0 a=9.8 t=5\n"
        "/motionplot u=0 a=9.8 t=10\n"
        "/projectile speed=20 angle=45\n"
        "/projectileplot speed=20 angle=45\n\n"
        "Forces and energy:\n"
        "/force m=10 a=3\n"
        "/weight m=70\n"
        "/friction mu=0.4 normal=200\n"
        "/kinetic m=2 v=10\n"
        "/potential m=5 h=20\n"
        "/momentum m=4 v=12\n\n"
        "Waves and circuits:\n"
        "/wave f=440 wavelength=0.78\n"
        "/waveplot amplitude=2 frequency=3 duration=2\n"
        "/ohm V=12 R=4\n"
        "/series 10 20 30\n"
        "/parallel 10 20 30\n\n"
        "Springs, optics, gravity, units:\n"
        "/spring k=200 x=0.1\n"
        "/shmplot amplitude=2 period=4\n"
        "/lens f=10 object=30\n"
        "/gravity m1=5.97e24 m2=70 r=6.37e6\n"
        "/gravityplot m1=5.97e24 m2=70 rmin=6.37e6 rmax=5e7\n"
        "/convert 10 m/s to km/h\n"
        "/convert 25 c to k\n\n"
        "Units are SI by default unless a converter unit is given."
    )


async def physics_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(physics_help_text())


# ------------------------------------------------------------
# Kinematics and projectile motion
# ------------------------------------------------------------

def solve_kinematics(params: Dict[str, float]) -> Dict[str, float]:
    values = dict(params)

    # Use common constant-acceleration formula sets.
    # Variables: s, u, v, a, t.
    if all(k in values for k in ("u", "a", "t")):
        u, a, t = values["u"], values["a"], values["t"]
        values.setdefault("v", u + a * t)
        values.setdefault("s", u * t + 0.5 * a * t * t)

    if all(k in values for k in ("u", "v", "t")) and "a" not in values:
        u, v, t = values["u"], values["v"], values["t"]
        if abs(t) < 1e-12:
            raise ValueError("time t cannot be zero")
        values["a"] = (v - u) / t
        values.setdefault("s", (u + v) * 0.5 * t)

    if all(k in values for k in ("u", "v", "a")) and "t" not in values:
        u, v, a = values["u"], values["v"], values["a"]
        if abs(a) < 1e-12:
            raise ValueError("acceleration a cannot be zero for this case")
        values["t"] = (v - u) / a
        values.setdefault("s", (v * v - u * u) / (2 * a))

    if all(k in values for k in ("u", "a", "s")) and "v" not in values:
        u, a, s = values["u"], values["a"], values["s"]
        discriminant = u * u + 2 * a * s
        if discriminant < 0:
            raise ValueError("No real final velocity for these values.")
        v = math.sqrt(discriminant)
        # Choose sign that follows acceleration direction when possible.
        values["v"] = v if a >= 0 else -v
        if abs(a) > 1e-12:
            values.setdefault("t", (values["v"] - u) / a)

    if all(k in values for k in ("v", "a", "t")) and "u" not in values:
        v, a, t = values["v"], values["a"], values["t"]
        values["u"] = v - a * t
        values.setdefault("s", values["u"] * t + 0.5 * a * t * t)

    if all(k in values for k in ("s", "u", "t")) and "a" not in values:
        s, u, t = values["s"], values["u"], values["t"]
        if abs(t) < 1e-12:
            raise ValueError("time t cannot be zero")
        values["a"] = 2 * (s - u * t) / (t * t)
        values.setdefault("v", u + values["a"] * t)

    if all(k in values for k in ("s", "v", "t")) and "a" not in values:
        s, v, t = values["s"], values["v"], values["t"]
        if abs(t) < 1e-12:
            raise ValueError("time t cannot be zero")
        u = 2 * s / t - v
        values["u"] = u
        values["a"] = (v - u) / t

    if not any(all(k in params for k in combo) for combo in [
        ("u", "a", "t"),
        ("u", "v", "t"),
        ("u", "v", "a"),
        ("u", "a", "s"),
        ("v", "a", "t"),
        ("s", "u", "t"),
        ("s", "v", "t"),
    ]):
        raise ValueError("Provide one valid set, e.g. u=0 a=9.8 t=5")

    return values


async def kinematics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        params = parse_key_values(context.args)
        values = solve_kinematics(params)
    except Exception as error:
        await update.message.reply_text(
            "Kinematics error.\n\n"
            f"Error: {error}\n\n"
            "Examples:\n"
            "/kinematics u=0 a=9.8 t=5\n"
            "/kinematics u=10 v=30 t=4\n"
            "/kinematics u=0 a=2 s=50\n\n"
            "Variables: s=displacement, u=initial velocity, v=final velocity, a=acceleration, t=time"
        )
        return

    text = (
        "Kinematics result\n\n"
        f"s = {fmt(values.get('s', float('nan')))} m\n"
        f"u = {fmt(values.get('u', float('nan')))} m/s\n"
        f"v = {fmt(values.get('v', float('nan')))} m/s\n"
        f"a = {fmt(values.get('a', float('nan')))} m/s²\n"
        f"t = {fmt(values.get('t', float('nan')))} s"
    )
    await update.message.reply_text(text)


async def motionplot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        params = parse_key_values(context.args)
        require(params, "u", "a", "t")
        u, a, t_end = params["u"], params["a"], params["t"]
        if t_end <= 0 or t_end > 100000:
            raise ValueError("t must be positive and not too large.")
        samples = min(MAX_PLOT_SAMPLES, max(80, int(t_end * 60)))
        position_points = []
        velocity_points = []
        for i in range(samples + 1):
            t = t_end * i / samples
            s = u * t + 0.5 * a * t * t
            v = u + a * t
            position_points.append((t, s))
            velocity_points.append((t, v))

        image = make_plot_image(
            "Constant acceleration motion",
            [
                {"name": "position s(t)", "points": position_points, "color": "#1f77b4", "width": 4},
                {"name": "velocity v(t)", "points": velocity_points, "color": "#ff7f0e", "width": 4},
            ],
            x_label="time t (s)",
            y_label="position / velocity",
            filename="motion_plot.png",
        )
    except Exception as error:
        await update.message.reply_text(
            "Motion plot error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/motionplot u=0 a=9.8 t=10"
        )
        return

    await update.message.reply_photo(photo=InputFile(image, filename="motion_plot.png"), caption="Motion plot")


def projectile_values(speed: float, angle_deg: float, g: float = G_EARTH) -> Dict[str, float]:
    if speed < 0:
        raise ValueError("speed must be non-negative")
    if g <= 0:
        raise ValueError("g must be positive")

    theta = math.radians(angle_deg)
    vx = speed * math.cos(theta)
    vy = speed * math.sin(theta)
    flight_time = 2 * vy / g if vy >= 0 else 0
    range_x = vx * flight_time
    max_height = (vy * vy) / (2 * g) if vy >= 0 else 0

    return {
        "vx": vx,
        "vy": vy,
        "flight_time": flight_time,
        "range": range_x,
        "max_height": max_height,
    }


async def projectile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        params = parse_key_values(context.args)
        require(params, "speed", "angle")
        speed = params["speed"]
        angle = params["angle"]
        g = params.get("g", G_EARTH)
        values = projectile_values(speed, angle, g)
    except Exception as error:
        await update.message.reply_text(
            "Projectile error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/projectile speed=20 angle=45\n"
            "/projectile speed=30 angle=60 g=9.81"
        )
        return

    text = (
        "Projectile result\n\n"
        f"Initial speed: {fmt(speed)} m/s\n"
        f"Angle: {fmt(angle)}°\n"
        f"vx = {fmt(values['vx'])} m/s\n"
        f"vy = {fmt(values['vy'])} m/s\n"
        f"Flight time = {fmt(values['flight_time'])} s\n"
        f"Range = {fmt(values['range'])} m\n"
        f"Maximum height = {fmt(values['max_height'])} m"
    )
    await update.message.reply_text(text)


async def projectileplot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        params = parse_key_values(context.args)
        require(params, "speed", "angle")
        speed = params["speed"]
        angle = params["angle"]
        g = params.get("g", G_EARTH)
        values = projectile_values(speed, angle, g)
        vx, vy, flight_time = values["vx"], values["vy"], values["flight_time"]

        if flight_time <= 0:
            raise ValueError("Projectile does not rise with this angle.")

        points = []
        samples = min(MAX_PLOT_SAMPLES, 400)
        for i in range(samples + 1):
            t = flight_time * i / samples
            x = vx * t
            y = vy * t - 0.5 * g * t * t
            points.append((x, max(y, 0.0)))

        image = make_plot_image(
            "Projectile trajectory",
            [{"name": "trajectory", "points": points, "color": "#1f77b4", "width": 4}],
            x_label="horizontal distance x (m)",
            y_label="height y (m)",
            filename="projectile_plot.png",
        )
    except Exception as error:
        await update.message.reply_text(
            "Projectile plot error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/projectileplot speed=20 angle=45"
        )
        return

    await update.message.reply_photo(photo=InputFile(image, filename="projectile_plot.png"), caption="Projectile trajectory")


# ------------------------------------------------------------
# Forces, energy, momentum
# ------------------------------------------------------------

async def force_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        params = parse_key_values(context.args)
        require(params, "m", "a")
        force = params["m"] * params["a"]
        await update.message.reply_text(
            "Force result\n\n"
            f"F = ma = {fmt(params['m'])} × {fmt(params['a'])}\n"
            f"F = {fmt(force)} N"
        )
    except Exception as error:
        await update.message.reply_text(f"Force error.\n\nError: {error}\n\nUsage:\n/force m=10 a=3")


async def weight_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        params = parse_key_values(context.args)
        require(params, "m")
        g = params.get("g", G_EARTH)
        weight = params["m"] * g
        await update.message.reply_text(
            "Weight result\n\n"
            f"W = mg = {fmt(params['m'])} × {fmt(g)}\n"
            f"W = {fmt(weight)} N"
        )
    except Exception as error:
        await update.message.reply_text(f"Weight error.\n\nError: {error}\n\nUsage:\n/weight m=70")


async def friction_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        params = parse_key_values(context.args)
        require(params, "mu")
        normal = params.get("normal")
        if normal is None:
            require(params, "m")
            normal = params["m"] * params.get("g", G_EARTH)
        friction = params["mu"] * normal
        await update.message.reply_text(
            "Friction result\n\n"
            f"F_f = μN = {fmt(params['mu'])} × {fmt(normal)}\n"
            f"F_f = {fmt(friction)} N"
        )
    except Exception as error:
        await update.message.reply_text(
            "Friction error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/friction mu=0.4 normal=200\n"
            "/friction mu=0.4 m=10"
        )


async def kinetic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        params = parse_key_values(context.args)
        require(params, "m", "v")
        ke = 0.5 * params["m"] * params["v"] ** 2
        await update.message.reply_text(
            "Kinetic energy result\n\n"
            f"KE = 1/2 mv² = 1/2 × {fmt(params['m'])} × {fmt(params['v'])}²\n"
            f"KE = {fmt(ke)} J"
        )
    except Exception as error:
        await update.message.reply_text(f"Kinetic energy error.\n\nError: {error}\n\nUsage:\n/kinetic m=2 v=10")


async def potential_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        params = parse_key_values(context.args)
        require(params, "m", "h")
        g = params.get("g", G_EARTH)
        pe = params["m"] * g * params["h"]
        await update.message.reply_text(
            "Potential energy result\n\n"
            f"PE = mgh = {fmt(params['m'])} × {fmt(g)} × {fmt(params['h'])}\n"
            f"PE = {fmt(pe)} J"
        )
    except Exception as error:
        await update.message.reply_text(f"Potential energy error.\n\nError: {error}\n\nUsage:\n/potential m=5 h=20")


async def momentum_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        params = parse_key_values(context.args)
        require(params, "m", "v")
        p = params["m"] * params["v"]
        await update.message.reply_text(
            "Momentum result\n\n"
            f"p = mv = {fmt(params['m'])} × {fmt(params['v'])}\n"
            f"p = {fmt(p)} kg·m/s"
        )
    except Exception as error:
        await update.message.reply_text(f"Momentum error.\n\nError: {error}\n\nUsage:\n/momentum m=4 v=12")


# ------------------------------------------------------------
# Waves
# ------------------------------------------------------------

async def wave_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        params = parse_key_values(context.args)
        speed = maybe_get(params, "v", "speed")
        frequency = maybe_get(params, "f")
        wavelength = maybe_get(params, "wavelength")

        if speed is None and frequency is not None and wavelength is not None:
            speed = frequency * wavelength
        elif frequency is None and speed is not None and wavelength is not None:
            if abs(wavelength) < 1e-12:
                raise ValueError("wavelength cannot be zero")
            frequency = speed / wavelength
        elif wavelength is None and speed is not None and frequency is not None:
            if abs(frequency) < 1e-12:
                raise ValueError("frequency cannot be zero")
            wavelength = speed / frequency
        else:
            raise ValueError("Provide any two of v, f, wavelength.")

        period = 1 / frequency if frequency and abs(frequency) > 1e-12 else float("nan")
        omega = 2 * math.pi * frequency if frequency is not None else float("nan")

        await update.message.reply_text(
            "Wave result\n\n"
            f"v = {fmt(speed)} m/s\n"
            f"f = {fmt(frequency)} Hz\n"
            f"λ = {fmt(wavelength)} m\n"
            f"T = {fmt(period)} s\n"
            f"ω = {fmt(omega)} rad/s"
        )
    except Exception as error:
        await update.message.reply_text(
            "Wave error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/wave f=440 wavelength=0.78\n"
            "/wave v=343 f=440"
        )


async def waveplot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        params = parse_key_values(context.args)
        amplitude = params.get("amplitude", 1.0)
        frequency = params.get("f", params.get("frequency", 1.0))
        phase = params.get("phase", 0.0)
        duration = params.get("duration", 2.0)

        if duration <= 0 or duration > 1000:
            raise ValueError("duration must be positive and not too large")
        if frequency <= 0 or frequency > 1_000_000:
            raise ValueError("frequency must be positive and not too large")

        samples = min(MAX_PLOT_SAMPLES, 500)
        points = []
        for i in range(samples + 1):
            t = duration * i / samples
            y = amplitude * math.sin(2 * math.pi * frequency * t + phase)
            points.append((t, y))

        image = make_plot_image(
            "Sine wave",
            [{"name": "wave", "points": points, "color": "#1f77b4", "width": 4}],
            x_label="time t (s)",
            y_label="amplitude",
            filename="wave_plot.png",
        )
    except Exception as error:
        await update.message.reply_text(
            "Wave plot error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/waveplot amplitude=2 frequency=3 duration=2"
        )
        return

    await update.message.reply_photo(photo=InputFile(image, filename="wave_plot.png"), caption="Wave plot")


# ------------------------------------------------------------
# Electricity
# ------------------------------------------------------------

async def ohm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        params = parse_key_values(context.args)

        V = maybe_get(params, "V", "v_voltage")
        # parse_key_values lowercases keys, so raw V becomes v. That conflicts with velocity.
        # Support both v and voltage alias for /ohm.
        if V is None:
            V = params.get("v")
        I = maybe_get(params, "I", "i_current")
        if I is None:
            I = params.get("i")
        R = maybe_get(params, "R", "r_resistance")
        if R is None:
            R = params.get("r")

        known = sum(x is not None for x in (V, I, R))
        if known < 2:
            raise ValueError("Provide any two of V, I, R.")

        if V is None:
            V = I * R
        elif I is None:
            if abs(R) < 1e-12:
                raise ValueError("R cannot be zero")
            I = V / R
        elif R is None:
            if abs(I) < 1e-12:
                raise ValueError("I cannot be zero")
            R = V / I

        P = V * I

        await update.message.reply_text(
            "Ohm's law result\n\n"
            f"V = {fmt(V)} V\n"
            f"I = {fmt(I)} A\n"
            f"R = {fmt(R)} Ω\n"
            f"P = VI = {fmt(P)} W"
        )
    except Exception as error:
        await update.message.reply_text(
            "Ohm error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/ohm V=12 R=4\n"
            "/ohm I=3 R=4"
        )


async def series_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        values = parse_number_list(context.args)
        if any(v < 0 for v in values):
            raise ValueError("Resistances must be non-negative.")
        total = sum(values)
        await update.message.reply_text(
            "Series resistance\n\n"
            f"R_total = {' + '.join(fmt(v) for v in values)}\n"
            f"R_total = {fmt(total)} Ω"
        )
    except Exception as error:
        await update.message.reply_text(f"Series error.\n\nError: {error}\n\nUsage:\n/series 10 20 30")


async def parallel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        values = parse_number_list(context.args)
        if any(v <= 0 for v in values):
            raise ValueError("Parallel resistances must be positive.")
        total = 1 / sum(1 / v for v in values)
        await update.message.reply_text(
            "Parallel resistance\n\n"
            f"1/R_total = {' + '.join('1/' + fmt(v) for v in values)}\n"
            f"R_total = {fmt(total)} Ω"
        )
    except Exception as error:
        await update.message.reply_text(f"Parallel error.\n\nError: {error}\n\nUsage:\n/parallel 10 20 30")


# ------------------------------------------------------------
# Spring and SHM
# ------------------------------------------------------------

async def spring_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        params = parse_key_values(context.args)
        require(params, "k", "x")
        k, x = params["k"], params["x"]
        force = -k * x
        energy = 0.5 * k * x * x
        await update.message.reply_text(
            "Spring result\n\n"
            f"F = -kx = -{fmt(k)} × {fmt(x)}\n"
            f"F = {fmt(force)} N\n"
            f"Elastic potential energy = 1/2 kx² = {fmt(energy)} J"
        )
    except Exception as error:
        await update.message.reply_text(f"Spring error.\n\nError: {error}\n\nUsage:\n/spring k=200 x=0.1")


async def shmplot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        params = parse_key_values(context.args)
        amplitude = params.get("amplitude", 1.0)
        period = params.get("period")
        frequency = params.get("f", params.get("frequency"))
        duration = params.get("duration")

        if frequency is None:
            if period is None:
                period = 4.0
            if period <= 0:
                raise ValueError("period must be positive")
            frequency = 1 / period
        else:
            if frequency <= 0:
                raise ValueError("frequency must be positive")
            period = 1 / frequency

        if duration is None:
            duration = 3 * period
        if duration <= 0 or duration > 100000:
            raise ValueError("duration must be positive and not too large")

        points = []
        samples = min(MAX_PLOT_SAMPLES, 500)
        for i in range(samples + 1):
            t = duration * i / samples
            x = amplitude * math.cos(2 * math.pi * frequency * t)
            points.append((t, x))

        image = make_plot_image(
            "Simple harmonic motion",
            [{"name": "x(t)", "points": points, "color": "#1f77b4", "width": 4}],
            x_label="time t (s)",
            y_label="displacement x",
            filename="shm_plot.png",
        )
    except Exception as error:
        await update.message.reply_text(
            "SHM plot error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/shmplot amplitude=2 period=4\n"
            "/shmplot amplitude=2 frequency=1 duration=5"
        )
        return
    await update.message.reply_photo(photo=InputFile(image, filename="shm_plot.png"), caption="Simple harmonic motion")


# ------------------------------------------------------------
# Optics
# ------------------------------------------------------------

async def lens_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        params = parse_key_values(context.args)
        f = params.get("f", params.get("focal_length"))
        do = params.get("object_distance")
        di = params.get("image_distance")

        if f is None:
            raise ValueError("Missing focal length f.")
        if do is None and di is None:
            raise ValueError("Provide object distance or image distance.")

        if di is None:
            if abs(1 / f - 1 / do) < 1e-12:
                raise ValueError("Image distance is infinite for these values.")
            di = 1 / (1 / f - 1 / do)
        elif do is None:
            if abs(1 / f - 1 / di) < 1e-12:
                raise ValueError("Object distance is infinite for these values.")
            do = 1 / (1 / f - 1 / di)

        magnification = -di / do

        await update.message.reply_text(
            "Thin lens result\n\n"
            f"f = {fmt(f)}\n"
            f"object distance d_o = {fmt(do)}\n"
            f"image distance d_i = {fmt(di)}\n"
            f"magnification m = -d_i/d_o = {fmt(magnification)}"
        )
    except Exception as error:
        await update.message.reply_text(
            "Lens error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/lens f=10 object=30\n"
            "/lens f=10 do=30"
        )


# ------------------------------------------------------------
# Gravity
# ------------------------------------------------------------

async def gravity_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        params = parse_key_values(context.args)
        require(params, "m1", "m2", "r")
        m1, m2, r = params["m1"], params["m2"], params["r"]
        if r <= 0:
            raise ValueError("r must be positive")
        force = G_GRAVITY * m1 * m2 / (r * r)
        await update.message.reply_text(
            "Gravity result\n\n"
            f"F = G m₁m₂ / r²\n"
            f"F = {fmt(force)} N"
        )
    except Exception as error:
        await update.message.reply_text(
            "Gravity error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/gravity m1=5.97e24 m2=70 r=6.37e6"
        )


async def gravityplot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        params = parse_key_values(context.args)
        require(params, "m1", "m2", "rmin", "rmax")
        m1, m2 = params["m1"], params["m2"]
        rmin, rmax = params["rmin"], params["rmax"]
        if rmin <= 0 or rmax <= 0 or rmin >= rmax:
            raise ValueError("Require 0 < rmin < rmax")

        points = []
        samples = min(MAX_PLOT_SAMPLES, 500)
        for i in range(samples + 1):
            r = rmin + (rmax - rmin) * i / samples
            force = G_GRAVITY * m1 * m2 / (r * r)
            points.append((r, force))

        image = make_plot_image(
            "Gravitational force vs distance",
            [{"name": "F(r)", "points": points, "color": "#1f77b4", "width": 4}],
            x_label="distance r (m)",
            y_label="force F (N)",
            filename="gravity_plot.png",
            show_zero_axes=False,
        )
    except Exception as error:
        await update.message.reply_text(
            "Gravity plot error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/gravityplot m1=5.97e24 m2=70 rmin=6.37e6 rmax=5e7"
        )
        return
    await update.message.reply_photo(photo=InputFile(image, filename="gravity_plot.png"), caption="Gravity plot")


# ------------------------------------------------------------
# Unit converter
# ------------------------------------------------------------

UNIT_FACTORS = {
    # base unit: meter
    "m": ("length", 1.0),
    "meter": ("length", 1.0),
    "meters": ("length", 1.0),
    "km": ("length", 1000.0),
    "cm": ("length", 0.01),
    "mm": ("length", 0.001),
    "ft": ("length", 0.3048),
    "feet": ("length", 0.3048),
    "in": ("length", 0.0254),
    "inch": ("length", 0.0254),
    "mi": ("length", 1609.344),
    "mile": ("length", 1609.344),

    # base unit: kg
    "kg": ("mass", 1.0),
    "g": ("mass", 0.001),
    "gram": ("mass", 0.001),
    "mg": ("mass", 1e-6),
    "lb": ("mass", 0.45359237),
    "lbs": ("mass", 0.45359237),

    # base unit: second
    "s": ("time", 1.0),
    "sec": ("time", 1.0),
    "second": ("time", 1.0),
    "min": ("time", 60.0),
    "h": ("time", 3600.0),
    "hr": ("time", 3600.0),
    "hour": ("time", 3600.0),
    "day": ("time", 86400.0),

    # base unit: m/s
    "m/s": ("speed", 1.0),
    "ms": ("speed", 1.0),
    "km/h": ("speed", 1000.0 / 3600.0),
    "kmh": ("speed", 1000.0 / 3600.0),
    "mph": ("speed", 0.44704),
    "ft/s": ("speed", 0.3048),

    # force, energy, power, pressure
    "n": ("force", 1.0),
    "newton": ("force", 1.0),
    "kn": ("force", 1000.0),
    "lbf": ("force", 4.4482216152605),

    "j": ("energy", 1.0),
    "joule": ("energy", 1.0),
    "kj": ("energy", 1000.0),
    "cal": ("energy", 4.184),
    "kcal": ("energy", 4184.0),
    "wh": ("energy", 3600.0),
    "kwh": ("energy", 3_600_000.0),
    "ev": ("energy", 1.602176634e-19),

    "w": ("power", 1.0),
    "kw": ("power", 1000.0),
    "hp": ("power", 745.699872),

    "pa": ("pressure", 1.0),
    "kpa": ("pressure", 1000.0),
    "bar": ("pressure", 100000.0),
    "atm": ("pressure", 101325.0),
    "psi": ("pressure", 6894.757293168),
}

TEMP_UNITS = {"c", "celsius", "f", "fahrenheit", "k", "kelvin"}


def normalize_unit(unit: str) -> str:
    return unit.strip().lower().replace("°", "")


def temperature_to_celsius(value: float, unit: str) -> float:
    unit = normalize_unit(unit)
    if unit in ("c", "celsius"):
        return value
    if unit in ("k", "kelvin"):
        return value - 273.15
    if unit in ("f", "fahrenheit"):
        return (value - 32) * 5 / 9
    raise ValueError(f"Unknown temperature unit: {unit}")


def celsius_to_temperature(value_c: float, unit: str) -> float:
    unit = normalize_unit(unit)
    if unit in ("c", "celsius"):
        return value_c
    if unit in ("k", "kelvin"):
        return value_c + 273.15
    if unit in ("f", "fahrenheit"):
        return value_c * 9 / 5 + 32
    raise ValueError(f"Unknown temperature unit: {unit}")


def convert_value(value: float, from_unit: str, to_unit: str) -> float:
    fu = normalize_unit(from_unit)
    tu = normalize_unit(to_unit)

    if fu in TEMP_UNITS or tu in TEMP_UNITS:
        if fu not in TEMP_UNITS or tu not in TEMP_UNITS:
            raise ValueError("Temperature units can only convert to temperature units.")
        return celsius_to_temperature(temperature_to_celsius(value, fu), tu)

    if fu not in UNIT_FACTORS:
        raise ValueError(f"Unknown unit: {from_unit}")
    if tu not in UNIT_FACTORS:
        raise ValueError(f"Unknown unit: {to_unit}")

    category_from, factor_from = UNIT_FACTORS[fu]
    category_to, factor_to = UNIT_FACTORS[tu]

    if category_from != category_to:
        raise ValueError(f"Cannot convert {from_unit} to {to_unit}; different categories.")

    base_value = value * factor_from
    return base_value / factor_to


async def convert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        text = " ".join(context.args).strip()
        match = re.match(r"^\s*([-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?)\s+(.+?)\s+to\s+(.+?)\s*$", text, flags=re.IGNORECASE)
        if not match:
            raise ValueError("Use: /convert value unit to unit")
        value = parse_float(match.group(1))
        from_unit = match.group(2).strip()
        to_unit = match.group(3).strip()
        result = convert_value(value, from_unit, to_unit)
        await update.message.reply_text(
            "Unit conversion\n\n"
            f"{fmt(value)} {from_unit} = {fmt(result)} {to_unit}"
        )
    except Exception as error:
        await update.message.reply_text(
            "Conversion error.\n\n"
            f"Error: {error}\n\n"
            "Examples:\n"
            "/convert 10 m/s to km/h\n"
            "/convert 5 kg to g\n"
            "/convert 1 atm to pa\n"
            "/convert 25 c to k"
        )


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

def register_physics_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("physicshelp", physics_help_command))

    app.add_handler(CommandHandler("kinematics", kinematics_command))
    app.add_handler(CommandHandler("motionplot", motionplot_command))
    app.add_handler(CommandHandler("projectile", projectile_command))
    app.add_handler(CommandHandler("projectileplot", projectileplot_command))

    app.add_handler(CommandHandler("force", force_command))
    app.add_handler(CommandHandler("weight", weight_command))
    app.add_handler(CommandHandler("friction", friction_command))
    app.add_handler(CommandHandler("kinetic", kinetic_command))
    app.add_handler(CommandHandler("potential", potential_command))
    app.add_handler(CommandHandler("momentum", momentum_command))

    app.add_handler(CommandHandler("wave", wave_command))
    app.add_handler(CommandHandler("waveplot", waveplot_command))

    app.add_handler(CommandHandler("ohm", ohm_command))
    app.add_handler(CommandHandler("series", series_command))
    app.add_handler(CommandHandler("parallel", parallel_command))

    app.add_handler(CommandHandler("spring", spring_command))
    app.add_handler(CommandHandler("shmplot", shmplot_command))

    app.add_handler(CommandHandler("lens", lens_command))

    app.add_handler(CommandHandler("gravity", gravity_command))
    app.add_handler(CommandHandler("gravityplot", gravityplot_command))

    app.add_handler(CommandHandler("convert", convert_command))
