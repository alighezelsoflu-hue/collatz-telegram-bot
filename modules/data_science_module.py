import csv
import math
import random
import re
from collections import Counter, defaultdict
from io import BytesIO, StringIO
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from telegram import InputFile, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

try:
    from utils import split_long_text, text_to_file
except Exception:
    def split_long_text(text: str, limit: int = 3500) -> List[str]:
        if len(text) <= limit:
            return [text]
        chunks = []
        while text:
            chunks.append(text[:limit])
            text = text[limit:]
        return chunks

    def text_to_file(text: str, filename: str) -> BytesIO:
        output = BytesIO()
        output.write(text.encode("utf-8"))
        output.seek(0)
        output.name = filename
        return output


# ------------------------------------------------------------
# Limits for Render Free safety
# ------------------------------------------------------------

MAX_NUMBERS = 5000
MAX_POINTS = 1000
MAX_KMEANS_POINTS = 200
MAX_KMEANS_K = 10
MAX_CONFUSION_ITEMS = 5000
MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 5000
MAX_CSV_COLUMNS = 50


# ------------------------------------------------------------
# General helpers
# ------------------------------------------------------------

FLOAT_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def ds_help_text() -> str:
    return (
        "Data science commands 📊\n\n"
        "Basic data:\n"
        "/data_summary 4,7,9,10,10,12 - descriptive statistics\n"
        "/histogram 4,5,5,6,7,8,8,9 - histogram image\n"
        "/histogram bins 5 | 4,5,5,6,7,8,8,9 - custom bins\n"
        "/boxplot 3,4,5,5,6,7,8,20 - box plot image\n\n"
        "Relationships:\n"
        "/correlation 1,2; 2,4; 3,5; 4,8 - Pearson correlation\n"
        "/linear_regression 1,2; 2,4; 3,5; 4,8 - regression plot\n\n"
        "ML demos:\n"
        "/kmeans 2 | 1,1; 1,2; 8,8; 9,8 - k-means clustering\n"
        "/outliers iqr | 3,4,5,5,6,7,8,20 - IQR outliers\n"
        "/outliers zscore | 10,11,12,13,100 - z-score outliers\n"
        "/normalize minmax | 10,20,30,40 - min-max scaling\n"
        "/normalize zscore | 10,20,30,40 - z-score normalization\n\n"
        "Classification:\n"
        "/confusion_matrix cat,cat; dog,cat; dog,dog - metrics and matrix\n\n"
        "CSV:\n"
        "Reply to a CSV file with /csv_analyze\n"
        "or upload a CSV file with caption /csv_analyze\n\n"
        "Limits:\n"
        f"numbers: {MAX_NUMBERS}, points: {MAX_POINTS}, CSV: 1 MB / {MAX_CSV_ROWS} rows / {MAX_CSV_COLUMNS} columns"
    )


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


def nice_number(value: float, digits: int = 6) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"

    if abs(value) < 1e-12:
        value = 0.0

    if abs(value - round(value)) < 1e-12:
        return str(int(round(value)))

    return f"{value:.{digits}g}"


def parse_numbers_from_text(text: str, max_count: int = MAX_NUMBERS) -> List[float]:
    numbers = [float(match.group(0)) for match in FLOAT_PATTERN.finditer(text)]

    if not numbers:
        raise ValueError("No numbers found.")

    if len(numbers) > max_count:
        raise ValueError(f"Too many numbers. Maximum is {max_count}.")

    for number in numbers:
        if not math.isfinite(number):
            raise ValueError("Numbers must be finite.")

    return numbers


def split_method_and_data(text: str, default_method: str) -> Tuple[str, str]:
    text = text.strip()

    if "|" in text:
        left, right = text.split("|", 1)
        method = left.strip().lower() or default_method
        data_text = right.strip()
        return method, data_text

    parts = text.split(maxsplit=1)

    if parts and parts[0].lower() in {"iqr", "zscore", "minmax"}:
        method = parts[0].lower()
        data_text = parts[1] if len(parts) > 1 else ""
        return method, data_text

    return default_method, text


def parse_points(text: str, max_points: int = MAX_POINTS) -> List[Tuple[float, float]]:
    segments = [segment.strip() for segment in text.replace("\n", ";").split(";") if segment.strip()]
    points = []

    for segment in segments:
        values = [float(match.group(0)) for match in FLOAT_PATTERN.finditer(segment)]

        if len(values) != 2:
            raise ValueError(f"Invalid point: {segment}. Use x,y")

        x, y = values

        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("Point values must be finite.")

        points.append((x, y))

    if not points:
        raise ValueError("No points found.")

    if len(points) > max_points:
        raise ValueError(f"Too many points. Maximum is {max_points}.")

    return points


def quantile(sorted_values: List[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("Empty data.")

    if len(sorted_values) == 1:
        return sorted_values[0]

    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return sorted_values[int(position)]

    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def mean(values: List[float]) -> float:
    return sum(values) / len(values)


def sample_variance(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return sum((value - avg) ** 2 for value in values) / (len(values) - 1)


def population_variance(values: List[float]) -> float:
    avg = mean(values)
    return sum((value - avg) ** 2 for value in values) / len(values)


def mode_text(values: List[float]) -> str:
    counts = Counter(values)
    highest = max(counts.values())

    if highest <= 1:
        return "∅"

    modes = [value for value, count in counts.items() if count == highest]

    if len(modes) == len(counts):
        return "∅"

    return ", ".join(nice_number(value) for value in sorted(modes))


# ------------------------------------------------------------
# Plot helpers
# ------------------------------------------------------------

class PlotMapper:
    def __init__(self, left: int, top: int, right: int, bottom: int, xmin: float, xmax: float, ymin: float, ymax: float):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom
        self.xmin = xmin
        self.xmax = xmax
        self.ymin = ymin
        self.ymax = ymax
        self.width = right - left
        self.height = bottom - top

    def x(self, value: float) -> int:
        return int(self.left + (value - self.xmin) / (self.xmax - self.xmin) * self.width)

    def y(self, value: float) -> int:
        return int(self.bottom - (value - self.ymin) / (self.ymax - self.ymin) * self.height)


def padded_range(values: List[float], include_zero: bool = False) -> Tuple[float, float]:
    finite_values = [v for v in values if math.isfinite(v)]

    if not finite_values:
        return -1.0, 1.0

    vmin = min(finite_values)
    vmax = max(finite_values)

    if include_zero:
        vmin = min(vmin, 0.0)
        vmax = max(vmax, 0.0)

    if abs(vmax - vmin) < 1e-12:
        padding = 1.0 if abs(vmax) < 1 else abs(vmax) * 0.1
        return vmin - padding, vmax + padding

    padding = (vmax - vmin) * 0.1
    return vmin - padding, vmax + padding


def draw_plot_frame(draw: ImageDraw.ImageDraw, mapper: PlotMapper, title: str, x_label: str = "x", y_label: str = "y") -> None:
    title_font = load_font(32)
    label_font = load_font(18)
    small_font = load_font(16)

    draw.text((mapper.left, 25), title, fill="black", font=title_font)
    draw.rectangle((mapper.left, mapper.top, mapper.right, mapper.bottom), outline="#222222", width=2, fill="#fbfbfb")

    grid_lines = 8

    for i in range(grid_lines + 1):
        gx = mapper.left + i * mapper.width / grid_lines
        gy = mapper.top + i * mapper.height / grid_lines
        draw.line((gx, mapper.top, gx, mapper.bottom), fill="#dddddd", width=1)
        draw.line((mapper.left, gy, mapper.right, gy), fill="#dddddd", width=1)

        x_value = mapper.xmin + i * (mapper.xmax - mapper.xmin) / grid_lines
        y_value = mapper.ymax - i * (mapper.ymax - mapper.ymin) / grid_lines

        draw.text((gx - 22, mapper.bottom + 12), nice_number(x_value, 4), fill="#333333", font=small_font)
        draw.text((12, gy - 9), nice_number(y_value, 4), fill="#333333", font=small_font)

    if mapper.xmin <= 0 <= mapper.xmax:
        x0 = mapper.x(0)
        draw.line((x0, mapper.top, x0, mapper.bottom), fill="#333333", width=2)

    if mapper.ymin <= 0 <= mapper.ymax:
        y0 = mapper.y(0)
        draw.line((mapper.left, y0, mapper.right, y0), fill="#333333", width=2)

    draw.text((mapper.right - 20, mapper.bottom + 45), x_label, fill="black", font=label_font)
    draw.text((mapper.left - 45, mapper.top - 5), y_label, fill="black", font=label_font)


def image_to_buffer(image: Image.Image, filename: str) -> BytesIO:
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = filename
    return output


# ------------------------------------------------------------
# Data summary
# ------------------------------------------------------------

def build_summary_report(values: List[float]) -> str:
    sorted_values = sorted(values)
    n = len(values)
    avg = mean(values)
    median = quantile(sorted_values, 0.5)
    q1 = quantile(sorted_values, 0.25)
    q3 = quantile(sorted_values, 0.75)
    iqr = q3 - q1
    min_value = sorted_values[0]
    max_value = sorted_values[-1]
    pop_var = population_variance(values)
    sam_var = sample_variance(values)

    return (
        "Data summary 📊\n\n"
        f"Count: {n}\n"
        f"Mean: {nice_number(avg)}\n"
        f"Median: {nice_number(median)}\n"
        f"Mode: {mode_text(values)}\n"
        f"Minimum: {nice_number(min_value)}\n"
        f"Maximum: {nice_number(max_value)}\n"
        f"Range: {nice_number(max_value - min_value)}\n"
        f"Q1: {nice_number(q1)}\n"
        f"Q3: {nice_number(q3)}\n"
        f"IQR: {nice_number(iqr)}\n"
        f"Population variance: {nice_number(pop_var)}\n"
        f"Population std dev: {nice_number(math.sqrt(pop_var))}\n"
        f"Sample variance: {nice_number(sam_var)}\n"
        f"Sample std dev: {nice_number(math.sqrt(sam_var))}"
    )


async def data_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        values = parse_numbers_from_text(" ".join(context.args))
        report = build_summary_report(values)
    except Exception as error:
        await update.message.reply_text(
            "Data summary error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/data_summary 4, 7, 9, 10, 10, 12"
        )
        return

    await update.message.reply_text(report)


# ------------------------------------------------------------
# Histogram
# ------------------------------------------------------------

def parse_histogram_input(text: str) -> Tuple[List[float], int]:
    bins = 10
    data_text = text.strip()

    if "|" in data_text:
        left, right = data_text.split("|", 1)
        left = left.strip().lower()
        data_text = right.strip()

        match = re.search(r"bins\s+(\d+)", left)
        if match:
            bins = int(match.group(1))
    else:
        match = re.search(r"\bbins\s+(\d+)\b", data_text, flags=re.IGNORECASE)
        if match:
            bins = int(match.group(1))
            data_text = data_text[:match.start()] + " " + data_text[match.end():]

    if bins < 2 or bins > 50:
        raise ValueError("Bins must be between 2 and 50.")

    values = parse_numbers_from_text(data_text)
    return values, bins


def create_histogram_image(values: List[float], bins: int) -> BytesIO:
    width, height = 1200, 760
    left, top, right, bottom = 90, 100, 1140, 640
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = load_font(32)
    label_font = load_font(18)

    vmin, vmax = min(values), max(values)
    if abs(vmax - vmin) < 1e-12:
        vmin -= 0.5
        vmax += 0.5

    bin_width = (vmax - vmin) / bins
    counts = [0] * bins

    for value in values:
        index = int((value - vmin) / bin_width)
        if index == bins:
            index -= 1
        counts[index] += 1

    max_count = max(counts) if counts else 1

    draw.text((left, 30), f"Histogram ({len(values)} values, {bins} bins)", fill="black", font=title_font)
    draw.rectangle((left, top, right, bottom), outline="#222222", width=2, fill="#fbfbfb")

    plot_width = right - left
    plot_height = bottom - top
    bar_gap = 3
    bar_width = plot_width / bins

    for i, count in enumerate(counts):
        x1 = left + i * bar_width + bar_gap
        x2 = left + (i + 1) * bar_width - bar_gap
        y1 = bottom - (count / max_count) * (plot_height - 25)
        draw.rectangle((x1, y1, x2, bottom), fill="#4f8cff", outline="#2f5fa8")

        if count > 0:
            draw.text((x1 + 4, y1 - 22), str(count), fill="black", font=label_font)

    for i in range(0, bins + 1, max(1, bins // 8)):
        x = left + i * bar_width
        value = vmin + i * bin_width
        draw.text((x - 20, bottom + 15), nice_number(value, 4), fill="#333333", font=label_font)

    draw.text((left, height - 55), f"min={nice_number(min(values))}, max={nice_number(max(values))}", fill="#555555", font=label_font)
    return image_to_buffer(image, "histogram.png")


async def histogram_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        values, bins = parse_histogram_input(" ".join(context.args))
        image = create_histogram_image(values, bins)
    except Exception as error:
        await update.message.reply_text(
            "Histogram error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/histogram 4,5,5,6,7,8,8,9\n"
            "/histogram bins 5 | 4,5,5,6,7,8,8,9"
        )
        return

    await update.message.reply_photo(photo=InputFile(image, filename="histogram.png"), caption="Histogram 📊")


# ------------------------------------------------------------
# Boxplot
# ------------------------------------------------------------

def boxplot_stats(values: List[float]) -> Dict:
    sorted_values = sorted(values)
    q1 = quantile(sorted_values, 0.25)
    median = quantile(sorted_values, 0.5)
    q3 = quantile(sorted_values, 0.75)
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr
    non_outliers = [v for v in sorted_values if lower_fence <= v <= upper_fence]
    outliers = [v for v in sorted_values if v < lower_fence or v > upper_fence]

    return {
        "min": min(non_outliers) if non_outliers else sorted_values[0],
        "q1": q1,
        "median": median,
        "q3": q3,
        "max": max(non_outliers) if non_outliers else sorted_values[-1],
        "iqr": iqr,
        "outliers": outliers,
        "lower_fence": lower_fence,
        "upper_fence": upper_fence,
    }


def create_boxplot_image(values: List[float]) -> Tuple[BytesIO, Dict]:
    stats = boxplot_stats(values)
    width, height = 1200, 560
    left, top, right, bottom = 100, 170, 1120, 360
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = load_font(32)
    label_font = load_font(20)
    small_font = load_font(18)

    all_values = [stats["min"], stats["q1"], stats["median"], stats["q3"], stats["max"]] + stats["outliers"]
    xmin, xmax = padded_range(all_values)
    mapper = PlotMapper(left, top, right, bottom, xmin, xmax, 0, 1)

    draw.text((left, 35), "Box plot", fill="black", font=title_font)
    draw.line((left, 270, right, 270), fill="#333333", width=2)

    def px(value: float) -> int:
        return mapper.x(value)

    y_mid = 260
    box_top = 215
    box_bottom = 305

    draw.line((px(stats["min"]), y_mid, px(stats["q1"]), y_mid), fill="#333333", width=4)
    draw.line((px(stats["q3"]), y_mid, px(stats["max"]), y_mid), fill="#333333", width=4)
    draw.line((px(stats["min"]), box_top, px(stats["min"]), box_bottom), fill="#333333", width=4)
    draw.line((px(stats["max"]), box_top, px(stats["max"]), box_bottom), fill="#333333", width=4)
    draw.rectangle((px(stats["q1"]), box_top, px(stats["q3"]), box_bottom), fill="#bcd7ff", outline="#1f4f99", width=4)
    draw.line((px(stats["median"]), box_top, px(stats["median"]), box_bottom), fill="#d62728", width=5)

    for outlier in stats["outliers"]:
        x = px(outlier)
        draw.ellipse((x - 7, y_mid - 7, x + 7, y_mid + 7), fill="#ff7f0e", outline="#993f00")

    labels = [
        ("min", stats["min"]),
        ("Q1", stats["q1"]),
        ("median", stats["median"]),
        ("Q3", stats["q3"]),
        ("max", stats["max"]),
    ]

    for name, value in labels:
        x = px(value)
        draw.text((x - 35, 365), f"{name}\n{nice_number(value)}", fill="black", font=small_font)

    draw.text((left, height - 75), f"Outliers: {len(stats['outliers'])} | IQR: {nice_number(stats['iqr'])}", fill="#555555", font=label_font)
    return image_to_buffer(image, "boxplot.png"), stats


async def boxplot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        values = parse_numbers_from_text(" ".join(context.args))
        image, stats = create_boxplot_image(values)
    except Exception as error:
        await update.message.reply_text(
            "Box plot error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/boxplot 3,4,5,5,6,7,8,20"
        )
        return

    caption = (
        "Box plot 📦\n"
        f"Q1={nice_number(stats['q1'])}, median={nice_number(stats['median'])}, Q3={nice_number(stats['q3'])}, "
        f"outliers={len(stats['outliers'])}"
    )
    await update.message.reply_photo(photo=InputFile(image, filename="boxplot.png"), caption=caption)


# ------------------------------------------------------------
# Correlation and regression
# ------------------------------------------------------------

def pearson_correlation(points: List[Tuple[float, float]]) -> float:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx = mean(xs)
    my = mean(ys)
    numerator = sum((x - mx) * (y - my) for x, y in points)
    denom_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - my) ** 2 for y in ys))

    if denom_x == 0 or denom_y == 0:
        raise ValueError("Correlation is undefined when x or y has zero variance.")

    return numerator / (denom_x * denom_y)


def correlation_strength(r: float) -> str:
    abs_r = abs(r)
    direction = "positive" if r > 0 else "negative" if r < 0 else "no"

    if abs_r >= 0.9:
        strength = "very strong"
    elif abs_r >= 0.7:
        strength = "strong"
    elif abs_r >= 0.5:
        strength = "moderate"
    elif abs_r >= 0.3:
        strength = "weak"
    else:
        strength = "very weak"

    if direction == "no":
        return "No linear correlation"

    return f"{strength.capitalize()} {direction} linear correlation"


def linear_regression(points: List[Tuple[float, float]]) -> Dict:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx = mean(xs)
    my = mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)

    if sxx == 0:
        raise ValueError("Regression is undefined when all x values are equal.")

    sxy = sum((x - mx) * (y - my) for x, y in points)
    slope = sxy / sxx
    intercept = my - slope * mx
    predictions = [slope * x + intercept for x in xs]
    ss_res = sum((y - yhat) ** 2 for y, yhat in zip(ys, predictions))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 1.0

    return {
        "slope": slope,
        "intercept": intercept,
        "r2": r2,
        "correlation": pearson_correlation(points),
    }


def create_scatter_regression_image(points: List[Tuple[float, float]], regression: Optional[Dict] = None, title: str = "Scatter plot") -> BytesIO:
    width, height = 1200, 780
    left, top, right, bottom = 95, 95, 1140, 660
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xmin, xmax = padded_range(xs)
    ymin, ymax = padded_range(ys)

    if regression is not None:
        y1 = regression["slope"] * xmin + regression["intercept"]
        y2 = regression["slope"] * xmax + regression["intercept"]
        ymin, ymax = padded_range(ys + [y1, y2])

    mapper = PlotMapper(left, top, right, bottom, xmin, xmax, ymin, ymax)
    draw_plot_frame(draw, mapper, title)

    for x, y in points:
        px = mapper.x(x)
        py = mapper.y(y)
        draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill="#1f77b4", outline="#0d3d66")

    if regression is not None:
        x1, x2 = xmin, xmax
        y1 = regression["slope"] * x1 + regression["intercept"]
        y2 = regression["slope"] * x2 + regression["intercept"]
        draw.line((mapper.x(x1), mapper.y(y1), mapper.x(x2), mapper.y(y2)), fill="#d62728", width=4)
        font = load_font(20)
        draw.text(
            (left, height - 70),
            f"y = {nice_number(regression['slope'])}x + {nice_number(regression['intercept'])} | R² = {nice_number(regression['r2'])}",
            fill="#333333",
            font=font,
        )

    return image_to_buffer(image, "scatter_regression.png")


async def correlation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        points = parse_points(" ".join(context.args), max_points=MAX_POINTS)
        if len(points) < 2:
            raise ValueError("At least 2 points are required.")
        r = pearson_correlation(points)
        image = create_scatter_regression_image(points, None, "Correlation scatter plot")
    except Exception as error:
        await update.message.reply_text(
            "Correlation error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/correlation 1,2; 2,4; 3,5; 4,8; 5,10"
        )
        return

    await update.message.reply_text(
        f"Pearson correlation 📈\n\nr = {nice_number(r)}\n{correlation_strength(r)}"
    )
    await update.message.reply_photo(photo=InputFile(image, filename="correlation.png"), caption="Correlation scatter plot")


async def linear_regression_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        points = parse_points(" ".join(context.args), max_points=MAX_POINTS)
        if len(points) < 2:
            raise ValueError("At least 2 points are required.")
        regression = linear_regression(points)
        image = create_scatter_regression_image(points, regression, "Linear regression")
    except Exception as error:
        await update.message.reply_text(
            "Linear regression error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/linear_regression 1,2; 2,4; 3,5; 4,8; 5,10"
        )
        return

    report = (
        "Linear regression 📈\n\n"
        f"Equation: y = {nice_number(regression['slope'])}x + {nice_number(regression['intercept'])}\n"
        f"Slope: {nice_number(regression['slope'])}\n"
        f"Intercept: {nice_number(regression['intercept'])}\n"
        f"R²: {nice_number(regression['r2'])}\n"
        f"Correlation r: {nice_number(regression['correlation'])}"
    )
    await update.message.reply_text(report)
    await update.message.reply_photo(photo=InputFile(image, filename="linear_regression.png"), caption="Linear regression plot")


# ------------------------------------------------------------
# K-means
# ------------------------------------------------------------

def parse_kmeans_input(text: str) -> Tuple[int, List[Tuple[float, float]]]:
    text = text.strip()

    if "|" not in text:
        raise ValueError("Use: /kmeans k | x,y; x,y; ...")

    left, right = text.split("|", 1)
    k_values = [int(match.group(0)) for match in re.finditer(r"\d+", left)]

    if not k_values:
        raise ValueError("Please provide k.")

    k = k_values[0]

    if k < 1 or k > MAX_KMEANS_K:
        raise ValueError(f"k must be between 1 and {MAX_KMEANS_K}.")

    points = parse_points(right, max_points=MAX_KMEANS_POINTS)

    if k > len(points):
        raise ValueError("k cannot be larger than the number of points.")

    return k, points


def squared_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def run_kmeans(points: List[Tuple[float, float]], k: int, max_iterations: int = 50) -> Dict:
    sorted_points = sorted(points, key=lambda p: (p[0], p[1]))

    if k == 1:
        centroids = [mean([p[0] for p in points]), mean([p[1] for p in points])]

    centroids = []
    for i in range(k):
        index = round(i * (len(sorted_points) - 1) / max(1, k - 1))
        centroids.append(sorted_points[index])

    assignments = [0] * len(points)

    for _ in range(max_iterations):
        changed = False

        for idx, point in enumerate(points):
            cluster = min(range(k), key=lambda c: squared_distance(point, centroids[c]))
            if assignments[idx] != cluster:
                assignments[idx] = cluster
                changed = True

        new_centroids = []
        for cluster in range(k):
            cluster_points = [point for point, assigned in zip(points, assignments) if assigned == cluster]
            if cluster_points:
                new_centroids.append((mean([p[0] for p in cluster_points]), mean([p[1] for p in cluster_points])))
            else:
                new_centroids.append(centroids[cluster])

        if not changed and all(squared_distance(a, b) < 1e-12 for a, b in zip(centroids, new_centroids)):
            centroids = new_centroids
            break

        centroids = new_centroids

    inertia = sum(squared_distance(point, centroids[cluster]) for point, cluster in zip(points, assignments))

    return {
        "centroids": centroids,
        "assignments": assignments,
        "inertia": inertia,
    }


def create_kmeans_image(points: List[Tuple[float, float]], result: Dict) -> BytesIO:
    width, height = 1200, 780
    left, top, right, bottom = 95, 95, 1140, 660
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    xs = [p[0] for p in points] + [c[0] for c in result["centroids"]]
    ys = [p[1] for p in points] + [c[1] for c in result["centroids"]]
    xmin, xmax = padded_range(xs)
    ymin, ymax = padded_range(ys)
    mapper = PlotMapper(left, top, right, bottom, xmin, xmax, ymin, ymax)
    draw_plot_frame(draw, mapper, "K-means clustering")

    colors = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ]

    for point, cluster in zip(points, result["assignments"]):
        px, py = mapper.x(point[0]), mapper.y(point[1])
        color = colors[cluster % len(colors)]
        draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill=color, outline="#333333")

    for idx, centroid in enumerate(result["centroids"]):
        px, py = mapper.x(centroid[0]), mapper.y(centroid[1])
        color = colors[idx % len(colors)]
        draw.rectangle((px - 11, py - 11, px + 11, py + 11), fill=color, outline="black", width=3)
        draw.text((px + 14, py - 10), f"C{idx + 1}", fill="black", font=load_font(18))

    draw.text((left, height - 70), f"Inertia: {nice_number(result['inertia'])}", fill="#333333", font=load_font(20))
    return image_to_buffer(image, "kmeans.png")


async def kmeans_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        k, points = parse_kmeans_input(" ".join(context.args))
        result = run_kmeans(points, k)
        image = create_kmeans_image(points, result)
    except Exception as error:
        await update.message.reply_text(
            "K-means error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/kmeans 2 | 1,1; 1,2; 2,1; 8,8; 9,8; 8,9"
        )
        return

    lines = ["K-means clustering 🤖", ""]
    for idx, centroid in enumerate(result["centroids"], start=1):
        size = sum(1 for assigned in result["assignments"] if assigned == idx - 1)
        lines.append(f"Cluster {idx}: center=({nice_number(centroid[0])}, {nice_number(centroid[1])}), points={size}")
    lines.append(f"Inertia: {nice_number(result['inertia'])}")

    await update.message.reply_text("\n".join(lines))
    await update.message.reply_photo(photo=InputFile(image, filename="kmeans.png"), caption="K-means clustering plot")


# ------------------------------------------------------------
# Outliers and normalization
# ------------------------------------------------------------

def detect_iqr_outliers(values: List[float]) -> Dict:
    stats = boxplot_stats(values)
    return {
        "method": "IQR",
        "outliers": stats["outliers"],
        "lower": stats["lower_fence"],
        "upper": stats["upper_fence"],
        "q1": stats["q1"],
        "q3": stats["q3"],
        "iqr": stats["iqr"],
    }


def detect_zscore_outliers(values: List[float], threshold: float = 3.0) -> Dict:
    avg = mean(values)
    std = math.sqrt(population_variance(values))

    if std == 0:
        return {"method": "z-score", "outliers": [], "mean": avg, "std": std, "threshold": threshold}

    outliers = [value for value in values if abs((value - avg) / std) > threshold]
    return {"method": "z-score", "outliers": outliers, "mean": avg, "std": std, "threshold": threshold}


async def outliers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        method, data_text = split_method_and_data(" ".join(context.args), "iqr")
        values = parse_numbers_from_text(data_text)

        if method == "iqr":
            result = detect_iqr_outliers(values)
            detail = (
                f"Q1: {nice_number(result['q1'])}\n"
                f"Q3: {nice_number(result['q3'])}\n"
                f"IQR: {nice_number(result['iqr'])}\n"
                f"Lower fence: {nice_number(result['lower'])}\n"
                f"Upper fence: {nice_number(result['upper'])}"
            )
        elif method == "zscore":
            result = detect_zscore_outliers(values)
            detail = (
                f"Mean: {nice_number(result['mean'])}\n"
                f"Std dev: {nice_number(result['std'])}\n"
                f"Threshold: |z| > {nice_number(result['threshold'])}"
            )
        else:
            raise ValueError("Method must be iqr or zscore.")

    except Exception as error:
        await update.message.reply_text(
            "Outlier detection error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/outliers iqr | 3,4,5,5,6,7,8,20\n"
            "/outliers zscore | 10,11,12,13,100"
        )
        return

    outlier_text = ", ".join(nice_number(value) for value in result["outliers"]) if result["outliers"] else "None"
    await update.message.reply_text(
        f"Outlier detection — {result['method']}\n\n"
        f"Outliers: {outlier_text}\n\n"
        f"{detail}"
    )


def normalize_values(values: List[float], method: str) -> List[float]:
    if method == "minmax":
        vmin, vmax = min(values), max(values)
        if abs(vmax - vmin) < 1e-12:
            return [0.0 for _ in values]
        return [(value - vmin) / (vmax - vmin) for value in values]

    if method == "zscore":
        avg = mean(values)
        std = math.sqrt(population_variance(values))
        if std == 0:
            return [0.0 for _ in values]
        return [(value - avg) / std for value in values]

    raise ValueError("Method must be minmax or zscore.")


async def normalize_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        method, data_text = split_method_and_data(" ".join(context.args), "minmax")
        values = parse_numbers_from_text(data_text)
        normalized = normalize_values(values, method)
    except Exception as error:
        await update.message.reply_text(
            "Normalize error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/normalize minmax | 10,20,30,40\n"
            "/normalize zscore | 10,20,30,40"
        )
        return

    pairs = [f"{nice_number(v)} → {nice_number(n)}" for v, n in zip(values, normalized)]
    report = f"Normalization — {method}\n\n" + "\n".join(pairs)

    if len(report) <= 3500:
        await update.message.reply_text(report)
    else:
        await update.message.reply_document(document=text_to_file(report, "normalized_values.txt"), caption="Normalized values")


# ------------------------------------------------------------
# Confusion matrix
# ------------------------------------------------------------

def parse_label_pairs(text: str) -> List[Tuple[str, str]]:
    segments = [segment.strip() for segment in text.replace("\n", ";").split(";") if segment.strip()]
    pairs = []

    for segment in segments:
        if "," in segment:
            actual, predicted = [part.strip() for part in segment.split(",", 1)]
        else:
            parts = segment.split()
            if len(parts) != 2:
                raise ValueError(f"Invalid pair: {segment}. Use actual,predicted")
            actual, predicted = parts

        if not actual or not predicted:
            raise ValueError(f"Invalid pair: {segment}")

        pairs.append((actual, predicted))

    if not pairs:
        raise ValueError("No label pairs found.")

    if len(pairs) > MAX_CONFUSION_ITEMS:
        raise ValueError(f"Too many pairs. Maximum is {MAX_CONFUSION_ITEMS}.")

    return pairs


def confusion_metrics(pairs: List[Tuple[str, str]]) -> Dict:
    labels = sorted(set([actual for actual, _ in pairs] + [pred for _, pred in pairs]))
    matrix = {actual: {pred: 0 for pred in labels} for actual in labels}

    for actual, pred in pairs:
        matrix[actual][pred] += 1

    total = len(pairs)
    correct = sum(matrix[label][label] for label in labels)
    accuracy = correct / total if total else 0

    per_label = {}
    precisions = []
    recalls = []
    f1s = []

    for label in labels:
        tp = matrix[label][label]
        fp = sum(matrix[actual][label] for actual in labels if actual != label)
        fn = sum(matrix[label][pred] for pred in labels if pred != label)
        precision = tp / (tp + fp) if tp + fp > 0 else 0.0
        recall = tp / (tp + fn) if tp + fn > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
        per_label[label] = {"precision": precision, "recall": recall, "f1": f1, "support": sum(matrix[label].values())}
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

    return {
        "labels": labels,
        "matrix": matrix,
        "accuracy": accuracy,
        "macro_precision": mean(precisions) if precisions else 0.0,
        "macro_recall": mean(recalls) if recalls else 0.0,
        "macro_f1": mean(f1s) if f1s else 0.0,
        "per_label": per_label,
    }


def create_confusion_matrix_image(metrics: Dict) -> BytesIO:
    labels = metrics["labels"]
    n = len(labels)
    cell = 90 if n <= 6 else 70
    width = max(760, 220 + cell * n)
    height = max(620, 220 + cell * n)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = load_font(30)
    label_font = load_font(18)
    value_font = load_font(22)

    left, top = 160, 140
    draw.text((50, 35), "Confusion matrix", fill="black", font=title_font)
    draw.text((left + cell * n / 2 - 50, 95), "Predicted", fill="black", font=label_font)
    draw.text((45, top + cell * n / 2 - 15), "Actual", fill="black", font=label_font)

    max_value = max(max(row.values()) for row in metrics["matrix"].values()) or 1

    for j, label in enumerate(labels):
        draw.text((left + j * cell + 8, top - 35), label[:8], fill="black", font=label_font)

    for i, actual in enumerate(labels):
        draw.text((left - 95, top + i * cell + 30), actual[:10], fill="black", font=label_font)

        for j, pred in enumerate(labels):
            value = metrics["matrix"][actual][pred]
            intensity = int(245 - 140 * (value / max_value))
            fill = (intensity, intensity + 5 if intensity <= 250 else 255, 255)
            x1 = left + j * cell
            y1 = top + i * cell
            x2 = x1 + cell
            y2 = y1 + cell
            draw.rectangle((x1, y1, x2, y2), fill=fill, outline="#333333")
            draw.text((x1 + cell / 2 - 10, y1 + cell / 2 - 12), str(value), fill="black", font=value_font)

    draw.text((50, height - 70), f"Accuracy: {nice_number(metrics['accuracy'])} | Macro F1: {nice_number(metrics['macro_f1'])}", fill="#333333", font=label_font)
    return image_to_buffer(image, "confusion_matrix.png")


async def confusion_matrix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        pairs = parse_label_pairs(" ".join(context.args))
        metrics = confusion_metrics(pairs)
        image = create_confusion_matrix_image(metrics)
    except Exception as error:
        await update.message.reply_text(
            "Confusion matrix error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/confusion_matrix cat,cat; dog,cat; dog,dog; cat,dog; cat,cat"
        )
        return

    lines = [
        "Classification metrics 🧪",
        "",
        f"Accuracy: {nice_number(metrics['accuracy'])}",
        f"Macro precision: {nice_number(metrics['macro_precision'])}",
        f"Macro recall: {nice_number(metrics['macro_recall'])}",
        f"Macro F1: {nice_number(metrics['macro_f1'])}",
        "",
        "Per label:",
    ]

    for label in metrics["labels"]:
        item = metrics["per_label"][label]
        lines.append(
            f"- {label}: precision={nice_number(item['precision'])}, recall={nice_number(item['recall'])}, F1={nice_number(item['f1'])}, support={item['support']}"
        )

    await update.message.reply_text("\n".join(lines))
    await update.message.reply_photo(photo=InputFile(image, filename="confusion_matrix.png"), caption="Confusion matrix")


# ------------------------------------------------------------
# CSV analysis
# ------------------------------------------------------------

def decode_csv_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode CSV file.")


def try_float(value: str) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        number = float(text)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def analyze_csv_text(text: str) -> str:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except Exception:
        dialect = csv.excel

    reader = csv.DictReader(StringIO(text), dialect=dialect)

    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")

    headers = [header.strip() if header else "" for header in reader.fieldnames]

    if len(headers) > MAX_CSV_COLUMNS:
        raise ValueError(f"Too many columns. Maximum is {MAX_CSV_COLUMNS}.")

    rows = []
    for index, row in enumerate(reader, start=1):
        if index > MAX_CSV_ROWS:
            break
        rows.append(row)

    if not rows:
        raise ValueError("CSV has no data rows.")

    total_rows = len(rows)
    lines = [
        "CSV analysis 📄📊",
        "",
        f"Rows analyzed: {total_rows}",
        f"Columns: {len(headers)}",
        "",
    ]

    numeric_columns = []
    categorical_columns = []
    missing_counts = {}

    for header in headers:
        values = [row.get(header, "") for row in rows]
        missing = sum(1 for value in values if value is None or str(value).strip() == "")
        missing_counts[header] = missing
        numeric_values = [try_float(value) for value in values]
        numeric_real = [value for value in numeric_values if value is not None]

        if len(numeric_real) >= max(2, int(0.8 * (total_rows - missing))):
            numeric_columns.append((header, numeric_real))
        else:
            categorical_columns.append((header, values))

    lines.append("Missing values:")
    for header in headers[:20]:
        lines.append(f"- {header}: {missing_counts[header]}")

    lines.extend(["", "Numeric columns:"])

    if numeric_columns:
        for header, values in numeric_columns[:20]:
            sorted_values = sorted(values)
            lines.append(
                f"- {header}: count={len(values)}, mean={nice_number(mean(values))}, median={nice_number(quantile(sorted_values, 0.5))}, min={nice_number(min(values))}, max={nice_number(max(values))}"
            )
    else:
        lines.append("No numeric columns detected.")

    lines.extend(["", "Categorical columns:"])

    if categorical_columns:
        for header, values in categorical_columns[:15]:
            clean_values = [str(value).strip() for value in values if value is not None and str(value).strip() != ""]
            unique_count = len(set(clean_values))
            top_values = Counter(clean_values).most_common(3)
            top_text = ", ".join(f"{name} ({count})" for name, count in top_values) if top_values else "none"
            lines.append(f"- {header}: unique={unique_count}, top={top_text}")
    else:
        lines.append("No categorical columns detected.")

    if len(numeric_columns) >= 2:
        lines.extend(["", "Strong numeric correlations:"])
        correlations = []
        for i in range(len(numeric_columns)):
            for j in range(i + 1, len(numeric_columns)):
                name_a, values_a = numeric_columns[i]
                name_b, values_b = numeric_columns[j]
                paired = list(zip(values_a, values_b))[:min(len(values_a), len(values_b))]
                if len(paired) >= 3:
                    try:
                        r = pearson_correlation(paired)
                        correlations.append((abs(r), r, name_a, name_b))
                    except Exception:
                        pass
        correlations.sort(reverse=True)
        if correlations:
            for _, r, name_a, name_b in correlations[:5]:
                lines.append(f"- {name_a} vs {name_b}: r={nice_number(r)}")
        else:
            lines.append("No correlations available.")

    return "\n".join(lines)


async def analyze_document_csv(update: Update, document) -> None:
    if not update.message:
        return

    if not document.file_name or not document.file_name.lower().endswith(".csv"):
        await update.message.reply_text("Please send a .csv file.")
        return

    if document.file_size and document.file_size > MAX_CSV_BYTES:
        await update.message.reply_text(f"CSV is too large. Maximum file size is {MAX_CSV_BYTES // 1_000_000} MB.")
        return

    try:
        file = await document.get_file()
        data = await file.download_as_bytearray()

        if len(data) > MAX_CSV_BYTES:
            raise ValueError("CSV is too large.")

        text = decode_csv_bytes(bytes(data))
        report = analyze_csv_text(text)
    except Exception as error:
        await update.message.reply_text(f"CSV analysis error.\n\nError: {error}")
        return

    if len(report) <= 3500:
        await update.message.reply_text(report)
    else:
        await update.message.reply_document(document=text_to_file(report, "csv_analysis.txt"), caption="CSV analysis")


async def csv_analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    reply = update.message.reply_to_message

    if reply and reply.document:
        await analyze_document_csv(update, reply.document)
        return

    if update.message.document:
        await analyze_document_csv(update, update.message.document)
        return

    await update.message.reply_text(
        "CSV analysis usage:\n\n"
        "1. Reply to a CSV file with /csv_analyze\n"
        "2. Or upload a CSV file with caption /csv_analyze\n\n"
        f"Limits: {MAX_CSV_BYTES // 1_000_000} MB, {MAX_CSV_ROWS} rows, {MAX_CSV_COLUMNS} columns"
    )


async def csv_document_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.document:
        return

    caption = update.message.caption or ""

    if not caption.strip().startswith("/csv_analyze"):
        return

    await analyze_document_csv(update, update.message.document)


# ------------------------------------------------------------
# Help and registration
# ------------------------------------------------------------

async def dshelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(ds_help_text())


def register_data_science_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("data_summary", data_summary_command))
    app.add_handler(CommandHandler("datasummary", data_summary_command))
    app.add_handler(CommandHandler("histogram", histogram_command))
    app.add_handler(CommandHandler("boxplot", boxplot_command))
    app.add_handler(CommandHandler("correlation", correlation_command))
    app.add_handler(CommandHandler("linear_regression", linear_regression_command))
    app.add_handler(CommandHandler("linreg", linear_regression_command))
    app.add_handler(CommandHandler("kmeans", kmeans_command))
    app.add_handler(CommandHandler("outliers", outliers_command))
    app.add_handler(CommandHandler("normalize", normalize_command))
    app.add_handler(CommandHandler("confusion_matrix", confusion_matrix_command))
    app.add_handler(CommandHandler("confmatrix", confusion_matrix_command))
    app.add_handler(CommandHandler("csv_analyze", csv_analyze_command))
    app.add_handler(CommandHandler("dshelp", dshelp_command))

    # Only reacts when the document caption starts with /csv_analyze.
    app.add_handler(MessageHandler(filters.Document.ALL, csv_document_message_handler), group=20)
