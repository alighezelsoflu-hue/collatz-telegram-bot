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
# AI integration
# ------------------------------------------------------------

AI_REQUEST_WORDS = {"ai", "explain", "interpret", "summary", "summarize", "insight", "insights"}
AI_SUMMARY_MAX_CHARS = 5200


def extract_ai_request(text: str) -> Tuple[bool, str]:
    """Return (ai_requested, cleaned_text).

    Users can add words like `ai`, `explain`, or `interpret` to a data-science command.
    The cleaned text is sent to the deterministic parser so the AI flag does not break
    column names, numeric parsing, or command options.
    """
    raw = (text or "").strip()
    if not raw:
        return False, ""

    requested = False
    cleaned_tokens = []
    for token in raw.split():
        bare = token.strip().lower().strip(",.;:!?()[]{}")
        if bare in AI_REQUEST_WORDS:
            requested = True
            continue
        cleaned_tokens.append(token)

    return requested, " ".join(cleaned_tokens).strip()


def ai_help_suffix() -> str:
    return (
        "\n\nAI summary: add `ai` or `explain` to most data-science commands, for example:\n"
        "/data_summary 4,7,9,10,10,12 ai\n"
        "/poly_regression degree 2 | 1,2; 2,5; 3,10 explain\n"
        "Reply to a CSV with /dataset_profile ai\n"
        "You can also reply to any result with /ds_ai."
    )


async def send_data_science_ai_summary(
    update: Update,
    title: str,
    result_text: str,
    original_input: str = "",
    extra_context: str = "",
) -> None:
    """Send an AI interpretation of a deterministic data-science result.

    This does not replace the module's calculations. It asks the AI module to explain
    the already-computed result, mention limitations, and suggest next steps.
    """
    if not update.message:
        return

    try:
        from modules.ai_module import call_ai
    except Exception:
        await update.message.reply_text(
            "AI summary is not available because modules/ai_module.py could not be imported.\n"
            "Make sure ai_module.py exists and is registered in main.py."
        )
        return

    safe_result = (result_text or "").strip()
    if len(safe_result) > AI_SUMMARY_MAX_CHARS:
        safe_result = safe_result[:AI_SUMMARY_MAX_CHARS] + "\n\n[Result was truncated before AI summary.]"

    prompt_parts = [
        f"Data-science task: {title}",
    ]
    if original_input.strip():
        prompt_parts.append("User input or command arguments:\n" + original_input.strip()[:1500])
    if extra_context.strip():
        prompt_parts.append("Extra context:\n" + extra_context.strip()[:1500])
    prompt_parts.append("Deterministic bot result:\n" + safe_result)
    prompt_parts.append(
        "Explain the result for a non-expert. Include: 1) key insight, "
        "2) what the numbers mean, 3) limitations/cautions, and 4) one sensible next step. "
        "Do not recompute or contradict the deterministic result."
    )

    system_prompt = (
        "You are AhBashin Bot's data-science tutor. Interpret statistical and ML results clearly, "
        "briefly, and accurately. Do not invent hidden data. Do not replace deterministic calculations. "
        "Mention uncertainty and limitations when relevant."
    )

    try:
        await update.message.chat.send_action(action="typing")
        answer = await call_ai(system_prompt, "\n\n".join(prompt_parts), temperature=0.25)
    except Exception as error:
        await update.message.reply_text(f"AI data-science summary error.\n\n{error}")
        return

    output = "AI data-science summary 🤖📊\n\n" + answer
    if len(output) <= 3500:
        await update.message.reply_text(output)
    elif len(output) <= 10000:
        for chunk in split_long_text(output, limit=3500):
            await update.message.reply_text(chunk)
    else:
        await update.message.reply_document(document=text_to_file(output, "data_science_ai_summary.txt"), caption="AI data-science summary")


async def maybe_send_data_science_ai_summary(
    update: Update,
    ai_requested: bool,
    title: str,
    result_text: str,
    original_input: str = "",
    extra_context: str = "",
) -> None:
    if ai_requested:
        await send_data_science_ai_summary(update, title, result_text, original_input, extra_context)



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

# Advanced feature limits
MAX_ADVANCED_CSV_NUMERIC_COLUMNS = 12
MAX_PAIRPLOT_COLUMNS = 4
MAX_PAIRPLOT_ROWS = 1000
MAX_POLY_DEGREE = 5
MAX_REGRESSION_POINTS = 1000
MAX_MULTI_FEATURES = 8
MAX_LOGISTIC_ITERATIONS = 2500
MAX_FORECAST_STEPS = 100
MAX_TTEST_VALUES = 5000
MAX_CHISQUARE_CATEGORIES = 50


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
        "Relationships and regression:\n"
        "/correlation 1,2; 2,4; 3,5; 4,8 - Pearson correlation\n"
        "/linear_regression 1,2; 2,4; 3,5; 4,8 - simple linear regression\n"
        "/poly_regression degree 2 | 1,2; 2,5; 3,10 - polynomial regression\n"
        "/multiple_regression target=price features=size,rooms - CSV multiple regression\n"
        "/logistic_regression 1,0; 2,0; 4,1; 5,1 - binary logistic regression\n\n"
        "Clustering and dimension reduction:\n"
        "/kmeans 2 | 1,1; 1,2; 8,8; 9,8 - k-means clustering\n"
        "/kmeans_auto maxk 6 | 1,1; 1,2; 8,8; 9,8 - elbow curve\n"
        "/pca 1,2; 2,3; 3,5; 4,6 - 2D principal component analysis\n\n"
        "Time series:\n"
        "/moving_average window 3 | 10,12,13,15,14 - moving average plot\n"
        "/forecast steps 5 | 10,12,13,15,18 - simple trend forecast\n\n"
        "Data cleaning and transforms:\n"
        "/outliers iqr | 3,4,5,5,6,7,8,20 - IQR outliers\n"
        "/outliers zscore | 10,11,12,13,100 - z-score outliers\n"
        "/normalize minmax | 10,20,30,40 - min-max scaling\n"
        "/normalize zscore | 10,20,30,40 - z-score normalization\n\n"
        "Classification and statistics:\n"
        "/confusion_matrix cat,cat; dog,cat; dog,dog - metrics and matrix\n"
        "/ttest one_sample mean=10 | 9,10,11,12,8 - t-test\n"
        "/ttest two_sample | 9,10,11,12 ; 14,15,13,16 - Welch two-sample t-test\n"
        "/chisquare 20,30,25,25 - chi-square goodness-of-fit\n"
        "/chisquare observed 18,22,30 expected 20,20,30 - custom expected counts\n\n"
        "CSV tools:\n"
        "/csv_analyze - basic CSV report\n"
        "/dataset_profile - advanced CSV profile report\n"
        "/corr_matrix - CSV correlation heatmap\n"
        "/pairplot col1 col2 col3 - CSV scatter matrix, max 4 columns\n\n"
        "CSV usage: reply to a CSV file with the command, or upload a CSV with the command as caption.\n\n"
        "AI summaries:\n"
        "Add ai or explain to most commands for an AI interpretation after the deterministic result.\n"
        "/data_summary 4,7,9,10,10,12 ai\n"
        "/forecast steps 5 | 10,12,13,15,18 explain\n"
        "Reply to a CSV with /dataset_profile ai\n"
        "/ds_ai - summarize a replied-to data-science result\n\n"
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

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        values = parse_numbers_from_text(clean_text)
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
    await maybe_send_data_science_ai_summary(update, ai_requested, "Data summary", report, clean_text)


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

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        values, bins = parse_histogram_input(clean_text)
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

    caption = "Histogram 📊"
    await update.message.reply_photo(photo=InputFile(image, filename="histogram.png"), caption=caption)
    histogram_report = (
        f"Histogram\nCount: {len(values)}\nBins: {bins}\n"
        f"Minimum: {nice_number(min(values))}\nMaximum: {nice_number(max(values))}\n"
        f"Mean: {nice_number(mean(values))}"
    )
    await maybe_send_data_science_ai_summary(update, ai_requested, "Histogram", histogram_report, clean_text)


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

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        values = parse_numbers_from_text(clean_text)
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
    boxplot_report = (
        "Box plot\n"
        f"Count: {len(values)}\n"
        f"Q1: {nice_number(stats['q1'])}\n"
        f"Median: {nice_number(stats['median'])}\n"
        f"Q3: {nice_number(stats['q3'])}\n"
        f"IQR: {nice_number(stats['iqr'])}\n"
        f"Outliers: {', '.join(nice_number(v) for v in stats['outliers']) if stats['outliers'] else 'None'}"
    )
    await maybe_send_data_science_ai_summary(update, ai_requested, "Box plot", boxplot_report, clean_text)


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

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        points = parse_points(clean_text, max_points=MAX_POINTS)
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

    report = f"Pearson correlation 📈\n\nr = {nice_number(r)}\n{correlation_strength(r)}"
    await update.message.reply_text(report)
    await update.message.reply_photo(photo=InputFile(image, filename="correlation.png"), caption="Correlation scatter plot")
    await maybe_send_data_science_ai_summary(update, ai_requested, "Pearson correlation", report, clean_text)


async def linear_regression_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        points = parse_points(clean_text, max_points=MAX_POINTS)
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
    await maybe_send_data_science_ai_summary(update, ai_requested, "Linear regression", report, clean_text)


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

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        k, points = parse_kmeans_input(clean_text)
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

    report = "\n".join(lines)
    await update.message.reply_text(report)
    await update.message.reply_photo(photo=InputFile(image, filename="kmeans.png"), caption="K-means clustering plot")
    await maybe_send_data_science_ai_summary(update, ai_requested, "K-means clustering", report, clean_text)


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

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        method, data_text = split_method_and_data(clean_text, "iqr")
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
    report = (
        f"Outlier detection — {result['method']}\n\n"
        f"Outliers: {outlier_text}\n\n"
        f"{detail}"
    )
    await update.message.reply_text(report)
    await maybe_send_data_science_ai_summary(update, ai_requested, "Outlier detection", report, clean_text)


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

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        method, data_text = split_method_and_data(clean_text, "minmax")
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
    await maybe_send_data_science_ai_summary(update, ai_requested, "Normalization", report, clean_text)


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

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        pairs = parse_label_pairs(clean_text)
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

    report = "\n".join(lines)
    await update.message.reply_text(report)
    await update.message.reply_photo(photo=InputFile(image, filename="confusion_matrix.png"), caption="Confusion matrix")
    await maybe_send_data_science_ai_summary(update, ai_requested, "Confusion matrix and classification metrics", report, clean_text)


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


async def analyze_document_csv(update: Update, document, ai_requested: bool = False, original_input: str = "") -> None:
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
    await maybe_send_data_science_ai_summary(update, ai_requested, "CSV analysis", report, original_input)


async def csv_analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)
    reply = update.message.reply_to_message

    if reply and reply.document:
        await analyze_document_csv(update, reply.document, ai_requested=ai_requested, original_input=clean_text)
        return

    if update.message.document:
        await analyze_document_csv(update, update.message.document, ai_requested=ai_requested, original_input=clean_text)
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

    caption = (update.message.caption or "").strip()
    if not caption.startswith("/"):
        return

    command_token = caption.split(maxsplit=1)[0]
    command = command_token.split("@", 1)[0].lower()
    args_text = caption[len(command_token):].strip()

    # CommandHandler usually handles text commands, while this handler makes
    # CSV commands work when the command is used as a document caption.
    try:
        context.args = args_text.split()
    except Exception:
        pass

    if command == "/csv_analyze":
        ai_requested, clean_args_text = extract_ai_request(args_text)
        await analyze_document_csv(update, update.message.document, ai_requested=ai_requested, original_input=clean_args_text)
    elif command in {"/corr_matrix", "/corrmatrix"}:
        await corr_matrix_command(update, context)
    elif command == "/pairplot":
        await pairplot_command(update, context)
    elif command in {"/multiple_regression", "/multireg"}:
        await multiple_regression_command(update, context)
    elif command in {"/dataset_profile", "/profile_csv"}:
        await dataset_profile_command(update, context)



# ------------------------------------------------------------
# Advanced CSV helpers
# ------------------------------------------------------------

def get_csv_document(update: Update):
    if not update.message:
        return None

    if update.message.document:
        return update.message.document

    reply = update.message.reply_to_message
    if reply and reply.document:
        return reply.document

    return None


async def download_csv_text(update: Update) -> str:
    document = get_csv_document(update)

    if document is None:
        raise ValueError("Reply to a CSV file with this command, or upload a CSV with the command as caption.")

    if not document.file_name or not document.file_name.lower().endswith(".csv"):
        raise ValueError("Please use a .csv file.")

    if document.file_size and document.file_size > MAX_CSV_BYTES:
        raise ValueError(f"CSV is too large. Maximum file size is {MAX_CSV_BYTES // 1_000_000} MB.")

    file = await document.get_file()
    data = await file.download_as_bytearray()

    if len(data) > MAX_CSV_BYTES:
        raise ValueError("CSV is too large.")

    return decode_csv_bytes(bytes(data))


def load_csv_table(text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except Exception:
        dialect = csv.excel

    reader = csv.DictReader(StringIO(text), dialect=dialect)

    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")

    headers = [header.strip() if header else "" for header in reader.fieldnames]
    original_headers = reader.fieldnames

    if len(headers) > MAX_CSV_COLUMNS:
        raise ValueError(f"Too many columns. Maximum is {MAX_CSV_COLUMNS}.")

    rows = []
    for index, row in enumerate(reader, start=1):
        if index > MAX_CSV_ROWS:
            break
        clean_row = {}
        for original, clean in zip(original_headers, headers):
            clean_row[clean] = row.get(original, "")
        rows.append(clean_row)

    if not rows:
        raise ValueError("CSV has no data rows.")

    return headers, rows


def resolve_column_name(headers: List[str], requested: str) -> str:
    requested = requested.strip()
    if requested in headers:
        return requested

    requested_lower = requested.lower()
    matches = [header for header in headers if header.lower() == requested_lower]
    if matches:
        return matches[0]

    contains = [header for header in headers if requested_lower in header.lower()]
    if len(contains) == 1:
        return contains[0]

    raise ValueError(f"Column not found: {requested}")


def numeric_columns(headers: List[str], rows: List[Dict[str, str]], min_fraction: float = 0.75) -> Dict[str, List[float]]:
    result = {}

    for header in headers:
        values = []
        non_missing = 0

        for row in rows:
            raw = row.get(header, "")
            if raw is not None and str(raw).strip() != "":
                non_missing += 1
            value = try_float(raw)
            if value is not None:
                values.append(value)

        if non_missing > 0 and len(values) >= 3 and len(values) / non_missing >= min_fraction:
            result[header] = values

    return result


def paired_numeric_values(rows: List[Dict[str, str]], column_a: str, column_b: str, max_rows: Optional[int] = None) -> List[Tuple[float, float]]:
    points = []
    for row in rows:
        a = try_float(row.get(column_a, ""))
        b = try_float(row.get(column_b, ""))
        if a is not None and b is not None:
            points.append((a, b))
            if max_rows is not None and len(points) >= max_rows:
                break
    return points


def paired_features_target(rows: List[Dict[str, str]], features: List[str], target: str) -> Tuple[List[List[float]], List[float]]:
    x_rows = []
    y_values = []

    for row in rows:
        x = []
        valid = True
        for feature in features:
            value = try_float(row.get(feature, ""))
            if value is None:
                valid = False
                break
            x.append(value)

        target_value = try_float(row.get(target, ""))
        if target_value is None:
            valid = False

        if valid:
            x_rows.append(x)
            y_values.append(target_value)

    return x_rows, y_values


# ------------------------------------------------------------
# Linear algebra helpers
# ------------------------------------------------------------

def solve_linear_system(matrix: List[List[float]], vector: List[float]) -> List[float]:
    n = len(matrix)
    if n == 0 or any(len(row) != n for row in matrix) or len(vector) != n:
        raise ValueError("Invalid linear system dimensions.")

    augmented = [row[:] + [value] for row, value in zip(matrix, vector)]

    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            raise ValueError("System is singular or ill-conditioned.")

        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        pivot_value = augmented[col][col]

        for j in range(col, n + 1):
            augmented[col][j] /= pivot_value

        for row in range(n):
            if row == col:
                continue
            factor = augmented[row][col]
            if abs(factor) < 1e-18:
                continue
            for j in range(col, n + 1):
                augmented[row][j] -= factor * augmented[col][j]

    return [augmented[i][n] for i in range(n)]


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def rmse(actual: List[float], predicted: List[float]) -> float:
    return math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual))


def mae(actual: List[float], predicted: List[float]) -> float:
    return sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)


def r2_score(actual: List[float], predicted: List[float]) -> float:
    avg = mean(actual)
    ss_res = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    ss_tot = sum((a - avg) ** 2 for a in actual)
    return 1 - ss_res / ss_tot if ss_tot != 0 else 1.0


# ------------------------------------------------------------
# Correlation matrix
# ------------------------------------------------------------

def build_correlation_matrix(headers: List[str], rows: List[Dict[str, str]], selected_columns: Optional[List[str]] = None) -> Tuple[List[str], List[List[Optional[float]]]]:
    numeric = numeric_columns(headers, rows)

    if selected_columns:
        columns = [resolve_column_name(headers, col) for col in selected_columns]
        missing_numeric = [col for col in columns if col not in numeric]
        if missing_numeric:
            raise ValueError("These columns are not numeric enough: " + ", ".join(missing_numeric))
    else:
        columns = list(numeric.keys())

    if len(columns) < 2:
        raise ValueError("At least 2 numeric columns are required.")

    if len(columns) > MAX_ADVANCED_CSV_NUMERIC_COLUMNS:
        columns = columns[:MAX_ADVANCED_CSV_NUMERIC_COLUMNS]

    matrix: List[List[Optional[float]]] = []
    for col_a in columns:
        row_values: List[Optional[float]] = []
        for col_b in columns:
            if col_a == col_b:
                row_values.append(1.0)
                continue
            points = paired_numeric_values(rows, col_a, col_b)
            if len(points) < 3:
                row_values.append(None)
            else:
                try:
                    row_values.append(pearson_correlation(points))
                except Exception:
                    row_values.append(None)
        matrix.append(row_values)

    return columns, matrix


def corr_color(value: Optional[float]) -> Tuple[int, int, int]:
    if value is None:
        return (230, 230, 230)

    value = max(-1.0, min(1.0, value))
    if value >= 0:
        intensity = int(255 - 145 * value)
        return (intensity, intensity, 255)

    intensity = int(255 + 145 * value)
    return (255, intensity, intensity)


def create_correlation_matrix_image(columns: List[str], matrix: List[List[Optional[float]]]) -> BytesIO:
    n = len(columns)
    cell = 82 if n <= 8 else 68
    width = max(900, 260 + n * cell)
    height = max(760, 250 + n * cell)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(30)
    label_font = load_font(16)
    value_font = load_font(17)

    left, top = 190, 150
    draw.text((45, 35), "Correlation matrix heatmap", fill="black", font=title_font)
    draw.text((45, 78), "Pearson r. Blue = positive, red = negative.", fill="#444444", font=label_font)

    for j, col in enumerate(columns):
        draw.text((left + j * cell + 6, top - 38), col[:10], fill="black", font=label_font)

    for i, col in enumerate(columns):
        draw.text((left - 145, top + i * cell + 28), col[:16], fill="black", font=label_font)
        for j, value in enumerate(matrix[i]):
            x1 = left + j * cell
            y1 = top + i * cell
            x2 = x1 + cell
            y2 = y1 + cell
            draw.rectangle((x1, y1, x2, y2), fill=corr_color(value), outline="#333333")
            label = "NA" if value is None else nice_number(value, 3)
            draw.text((x1 + 13, y1 + 28), label, fill="black", font=value_font)

    return image_to_buffer(image, "correlation_matrix.png")


async def corr_matrix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        csv_text = await download_csv_text(update)
        headers, rows = load_csv_table(csv_text)
        selected = [part.strip() for part in re.split(r"[,\s]+", clean_text.strip()) if part.strip()]
        columns, matrix = build_correlation_matrix(headers, rows, selected if selected else None)
        image = create_correlation_matrix_image(columns, matrix)
    except Exception as error:
        await update.message.reply_text(
            "Correlation matrix error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "Reply to a CSV file with /corr_matrix\n"
            "Optional: /corr_matrix column1 column2 column3"
        )
        return

    await update.message.reply_photo(photo=InputFile(image, filename="correlation_matrix.png"), caption="CSV correlation matrix")
    matrix_lines = ["CSV correlation matrix", "Columns: " + ", ".join(columns)]
    for col, row in zip(columns, matrix):
        values = ", ".join("NA" if v is None else nice_number(v, 3) for v in row)
        matrix_lines.append(f"{col}: {values}")
    await maybe_send_data_science_ai_summary(update, ai_requested, "CSV correlation matrix", "\n".join(matrix_lines), clean_text)


# ------------------------------------------------------------
# Pairplot
# ------------------------------------------------------------

def draw_small_scatter(draw: ImageDraw.ImageDraw, points: List[Tuple[float, float]], box: Tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    draw.rectangle(box, outline="#444444", fill="#fbfbfb")
    if not points:
        return

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xmin, xmax = padded_range(xs)
    ymin, ymax = padded_range(ys)

    for x, y in points:
        px = int(x1 + 8 + (x - xmin) / (xmax - xmin) * max(1, (x2 - x1 - 16)))
        py = int(y2 - 8 - (y - ymin) / (ymax - ymin) * max(1, (y2 - y1 - 16)))
        draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill="#1f77b4")


def create_pairplot_image(columns: List[str], rows: List[Dict[str, str]]) -> BytesIO:
    n = len(columns)
    cell = 245
    margin_left = 120
    margin_top = 110
    width = margin_left + n * cell + 70
    height = margin_top + n * cell + 70
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(30)
    label_font = load_font(18)
    small_font = load_font(16)

    draw.text((45, 35), "Pairplot scatter matrix", fill="black", font=title_font)

    for i, y_col in enumerate(columns):
        draw.text((25, margin_top + i * cell + 100), y_col[:12], fill="black", font=label_font)
        for j, x_col in enumerate(columns):
            box = (
                margin_left + j * cell,
                margin_top + i * cell,
                margin_left + (j + 1) * cell - 15,
                margin_top + (i + 1) * cell - 15,
            )
            if i == j:
                draw.rectangle(box, outline="#444444", fill="#f4f4f4")
                draw.text((box[0] + 30, box[1] + 95), x_col[:16], fill="black", font=label_font)
            else:
                points = paired_numeric_values(rows, x_col, y_col, max_rows=MAX_PAIRPLOT_ROWS)
                draw_small_scatter(draw, points, box)

            if i == 0:
                draw.text((box[0] + 12, margin_top - 30), x_col[:12], fill="black", font=small_font)

    return image_to_buffer(image, "pairplot.png")


async def pairplot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        csv_text = await download_csv_text(update)
        headers, rows = load_csv_table(csv_text)
        numeric = numeric_columns(headers, rows)
        requested = [part.strip() for part in re.split(r"[,\s]+", clean_text.strip()) if part.strip()]

        if requested:
            columns = [resolve_column_name(headers, col) for col in requested]
            missing_numeric = [col for col in columns if col not in numeric]
            if missing_numeric:
                raise ValueError("These columns are not numeric enough: " + ", ".join(missing_numeric))
        else:
            columns = list(numeric.keys())[:MAX_PAIRPLOT_COLUMNS]

        if len(columns) < 2:
            raise ValueError("At least 2 numeric columns are required.")
        if len(columns) > MAX_PAIRPLOT_COLUMNS:
            raise ValueError(f"Pairplot supports maximum {MAX_PAIRPLOT_COLUMNS} columns.")

        image = create_pairplot_image(columns, rows)
    except Exception as error:
        await update.message.reply_text(
            "Pairplot error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "Reply to a CSV with /pairplot\n"
            "or /pairplot column1 column2 column3"
        )
        return

    await update.message.reply_photo(photo=InputFile(image, filename="pairplot.png"), caption="CSV pairplot")
    pairplot_report = (
        "CSV pairplot scatter matrix\n"
        f"Columns: {', '.join(columns)}\n"
        f"Rows available: {len(rows)}\n"
        "Use the plots to inspect linear/nonlinear relationships, clusters, and outliers."
    )
    await maybe_send_data_science_ai_summary(update, ai_requested, "CSV pairplot", pairplot_report, clean_text)


# ------------------------------------------------------------
# Polynomial regression
# ------------------------------------------------------------

def parse_degree_points_input(text: str, default_degree: int = 2) -> Tuple[int, str]:
    degree = default_degree
    data_text = text.strip()

    if "|" in data_text:
        left, right = data_text.split("|", 1)
        match = re.search(r"degree\s*(?:=)?\s*(\d+)", left, flags=re.IGNORECASE)
        if match:
            degree = int(match.group(1))
        else:
            nums = re.findall(r"\d+", left)
            if nums:
                degree = int(nums[0])
        data_text = right.strip()
    else:
        match = re.search(r"degree\s*(?:=)?\s*(\d+)", data_text, flags=re.IGNORECASE)
        if match:
            degree = int(match.group(1))
            data_text = data_text[:match.start()] + " " + data_text[match.end():]

    if degree < 1 or degree > MAX_POLY_DEGREE:
        raise ValueError(f"Degree must be between 1 and {MAX_POLY_DEGREE}.")

    return degree, data_text


def fit_polynomial_regression(points: List[Tuple[float, float]], degree: int) -> Dict:
    if len(points) <= degree:
        raise ValueError("Number of points must be greater than the polynomial degree.")

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    size = degree + 1

    matrix = []
    vector = []
    for row_power in range(size):
        matrix_row = []
        for col_power in range(size):
            matrix_row.append(sum(x ** (row_power + col_power) for x in xs))
        matrix.append(matrix_row)
        vector.append(sum(y * (x ** row_power) for x, y in points))

    coeffs = solve_linear_system(matrix, vector)
    predicted = [sum(coeffs[p] * (x ** p) for p in range(size)) for x in xs]

    return {
        "degree": degree,
        "coeffs": coeffs,
        "r2": r2_score(ys, predicted),
        "rmse": rmse(ys, predicted),
        "predicted": predicted,
    }


def polynomial_to_text(coeffs: List[float]) -> str:
    terms = []
    for power, coeff in enumerate(coeffs):
        if abs(coeff) < 1e-10:
            continue
        sign = "+" if coeff >= 0 else "-"
        value = abs(coeff)
        if power == 0:
            term = nice_number(value)
        elif power == 1:
            term = f"{nice_number(value)}x"
        else:
            term = f"{nice_number(value)}x^{power}"
        terms.append((sign, term))

    if not terms:
        return "y = 0"

    first_sign, first_term = terms[0]
    expression = ("-" if first_sign == "-" else "") + first_term
    for sign, term in terms[1:]:
        expression += f" {sign} {term}"
    return "y = " + expression


def create_polynomial_regression_image(points: List[Tuple[float, float]], result: Dict) -> BytesIO:
    width, height = 1200, 780
    left, top, right, bottom = 95, 95, 1140, 660
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xmin, xmax = padded_range(xs)

    curve = []
    for i in range(300):
        x = xmin + i * (xmax - xmin) / 299
        y = sum(result["coeffs"][p] * (x ** p) for p in range(len(result["coeffs"])))
        curve.append((x, y))

    ymin, ymax = padded_range(ys + [p[1] for p in curve])
    mapper = PlotMapper(left, top, right, bottom, xmin, xmax, ymin, ymax)
    draw_plot_frame(draw, mapper, f"Polynomial regression degree {result['degree']}")

    for x, y in points:
        px, py = mapper.x(x), mapper.y(y)
        draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill="#1f77b4", outline="#0d3d66")

    curve_pixels = [(mapper.x(x), mapper.y(y)) for x, y in curve if math.isfinite(y)]
    if len(curve_pixels) >= 2:
        draw.line(curve_pixels, fill="#d62728", width=4)

    draw.text((left, height - 70), f"{polynomial_to_text(result['coeffs'])} | R²={nice_number(result['r2'])}", fill="#333333", font=load_font(18))
    return image_to_buffer(image, "polynomial_regression.png")


async def poly_regression_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        degree, data_text = parse_degree_points_input(clean_text)
        points = parse_points(data_text, max_points=MAX_REGRESSION_POINTS)
        result = fit_polynomial_regression(points, degree)
        image = create_polynomial_regression_image(points, result)
    except Exception as error:
        await update.message.reply_text(
            "Polynomial regression error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/poly_regression degree 2 | 1,2; 2,5; 3,10; 4,17; 5,26"
        )
        return

    report = (
        "Polynomial regression 📈\n\n"
        f"{polynomial_to_text(result['coeffs'])}\n"
        f"Degree: {result['degree']}\n"
        f"R²: {nice_number(result['r2'])}\n"
        f"RMSE: {nice_number(result['rmse'])}"
    )
    await update.message.reply_text(report)
    await update.message.reply_photo(photo=InputFile(image, filename="polynomial_regression.png"), caption="Polynomial regression plot")
    await maybe_send_data_science_ai_summary(update, ai_requested, "Polynomial regression", report, clean_text)


# ------------------------------------------------------------
# Multiple linear regression
# ------------------------------------------------------------

def parse_multiple_regression_args(text: str) -> Tuple[str, List[str]]:
    target_match = re.search(r"target\s*=\s*([^|\n]+?)(?=\s+features\s*=|$)", text, flags=re.IGNORECASE)
    features_match = re.search(r"features\s*=\s*([^|\n]+)$", text, flags=re.IGNORECASE)

    if not target_match or not features_match:
        raise ValueError("Use: /multiple_regression target=target_column features=feature1,feature2")

    target = target_match.group(1).strip().strip(",")
    features = [feature.strip() for feature in features_match.group(1).split(",") if feature.strip()]

    if not target:
        raise ValueError("Target column is missing.")
    if not features:
        raise ValueError("At least one feature column is required.")
    if len(features) > MAX_MULTI_FEATURES:
        raise ValueError(f"Maximum features: {MAX_MULTI_FEATURES}.")

    return target, features


def fit_multiple_regression(x_rows: List[List[float]], y_values: List[float]) -> Dict:
    if len(x_rows) < 3:
        raise ValueError("At least 3 complete numeric rows are required.")

    p = len(x_rows[0]) + 1
    if len(x_rows) <= p:
        raise ValueError("More rows than coefficients are required.")

    design = [[1.0] + row[:] for row in x_rows]
    matrix = [[0.0 for _ in range(p)] for _ in range(p)]
    vector = [0.0 for _ in range(p)]

    for row, y in zip(design, y_values):
        for i in range(p):
            vector[i] += row[i] * y
            for j in range(p):
                matrix[i][j] += row[i] * row[j]

    coeffs = solve_linear_system(matrix, vector)
    predicted = [sum(c * value for c, value in zip(coeffs, row)) for row in design]

    return {
        "coeffs": coeffs,
        "predicted": predicted,
        "r2": r2_score(y_values, predicted),
        "rmse": rmse(y_values, predicted),
        "mae": mae(y_values, predicted),
        "rows": len(y_values),
    }


def create_predicted_actual_image(actual: List[float], predicted: List[float], title: str) -> BytesIO:
    points = list(zip(actual, predicted))
    width, height = 1200, 780
    left, top, right, bottom = 95, 95, 1140, 660
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    all_values = actual + predicted
    xmin, xmax = padded_range(all_values)
    ymin, ymax = xmin, xmax
    mapper = PlotMapper(left, top, right, bottom, xmin, xmax, ymin, ymax)
    draw_plot_frame(draw, mapper, title, "actual", "predicted")

    draw.line((mapper.x(xmin), mapper.y(xmin), mapper.x(xmax), mapper.y(xmax)), fill="#d62728", width=3)
    for x, y in points[:1000]:
        px, py = mapper.x(x), mapper.y(y)
        draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill="#1f77b4", outline="#0d3d66")

    return image_to_buffer(image, "predicted_vs_actual.png")


async def multiple_regression_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        args_text = clean_text
        csv_text = await download_csv_text(update)
        headers, rows = load_csv_table(csv_text)
        target_raw, features_raw = parse_multiple_regression_args(args_text)
        target = resolve_column_name(headers, target_raw)
        features = [resolve_column_name(headers, feature) for feature in features_raw]
        x_rows, y_values = paired_features_target(rows, features, target)
        result = fit_multiple_regression(x_rows, y_values)
        image = create_predicted_actual_image(y_values, result["predicted"], "Multiple regression: predicted vs actual")
    except Exception as error:
        await update.message.reply_text(
            "Multiple regression error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "Reply to a CSV with:\n"
            "/multiple_regression target=price features=size,rooms,age"
        )
        return

    lines = [
        "Multiple linear regression 📈",
        "",
        f"Target: {target}",
        f"Rows used: {result['rows']}",
        f"R²: {nice_number(result['r2'])}",
        f"RMSE: {nice_number(result['rmse'])}",
        f"MAE: {nice_number(result['mae'])}",
        "",
        "Coefficients:",
        f"Intercept: {nice_number(result['coeffs'][0])}",
    ]
    for feature, coeff in zip(features, result["coeffs"][1:]):
        lines.append(f"{feature}: {nice_number(coeff)}")

    report = "\n".join(lines)
    await update.message.reply_text(report)
    await update.message.reply_photo(photo=InputFile(image, filename="multiple_regression.png"), caption="Predicted vs actual")
    await maybe_send_data_science_ai_summary(update, ai_requested, "Multiple linear regression", report, clean_text)


# ------------------------------------------------------------
# Logistic regression
# ------------------------------------------------------------

def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
    return z / (1 + z)


def fit_logistic_regression(points: List[Tuple[float, float]]) -> Dict:
    if len(points) < 4:
        raise ValueError("At least 4 points are required.")

    xs = [p[0] for p in points]
    ys = [int(p[1]) for p in points]

    if any(y not in (0, 1) for y in ys):
        raise ValueError("Labels must be 0 or 1.")

    x_mean = mean(xs)
    x_std = math.sqrt(population_variance(xs))
    if x_std == 0:
        raise ValueError("x must have non-zero variance.")

    zs = [(x - x_mean) / x_std for x in xs]
    w = 0.0
    b = 0.0
    learning_rate = 0.15

    for _ in range(MAX_LOGISTIC_ITERATIONS):
        grad_w = 0.0
        grad_b = 0.0
        for z, y in zip(zs, ys):
            p = sigmoid(w * z + b)
            grad_w += (p - y) * z
            grad_b += (p - y)
        w -= learning_rate * grad_w / len(zs)
        b -= learning_rate * grad_b / len(zs)

    probabilities = [sigmoid(w * z + b) for z in zs]
    predictions = [1 if p >= 0.5 else 0 for p in probabilities]
    accuracy = sum(1 for y, pred in zip(ys, predictions) if y == pred) / len(ys)

    return {
        "w": w,
        "b": b,
        "x_mean": x_mean,
        "x_std": x_std,
        "probabilities": probabilities,
        "predictions": predictions,
        "accuracy": accuracy,
    }


def create_logistic_regression_image(points: List[Tuple[float, float]], result: Dict) -> BytesIO:
    width, height = 1200, 780
    left, top, right, bottom = 95, 95, 1140, 660
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    xs = [p[0] for p in points]
    xmin, xmax = padded_range(xs)
    mapper = PlotMapper(left, top, right, bottom, xmin, xmax, -0.08, 1.08)
    draw_plot_frame(draw, mapper, "Logistic regression", "x", "P(y=1)")

    for x, y in points:
        px, py = mapper.x(x), mapper.y(y)
        color = "#2ca02c" if int(y) == 1 else "#d62728"
        draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=color, outline="#333333")

    curve = []
    for i in range(300):
        x = xmin + i * (xmax - xmin) / 299
        z = (x - result["x_mean"]) / result["x_std"]
        y = sigmoid(result["w"] * z + result["b"])
        curve.append((mapper.x(x), mapper.y(y)))
    draw.line(curve, fill="#1f77b4", width=4)
    draw.line((mapper.x(xmin), mapper.y(0.5), mapper.x(xmax), mapper.y(0.5)), fill="#888888", width=2)

    draw.text((left, height - 70), f"accuracy={nice_number(result['accuracy'])} | z=(x-{nice_number(result['x_mean'])})/{nice_number(result['x_std'])}", fill="#333333", font=load_font(18))
    return image_to_buffer(image, "logistic_regression.png")


async def logistic_regression_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        points = parse_points(clean_text, max_points=MAX_REGRESSION_POINTS)
        result = fit_logistic_regression(points)
        image = create_logistic_regression_image(points, result)
    except Exception as error:
        await update.message.reply_text(
            "Logistic regression error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/logistic_regression 1,0; 2,0; 3,0; 4,1; 5,1; 6,1"
        )
        return

    report = (
        "Logistic regression 🤖\n\n"
        f"Model: P(y=1) = sigmoid({nice_number(result['w'])}z + {nice_number(result['b'])})\n"
        f"z = (x - {nice_number(result['x_mean'])}) / {nice_number(result['x_std'])}\n"
        f"Accuracy at threshold 0.5: {nice_number(result['accuracy'])}"
    )
    await update.message.reply_text(report)
    await update.message.reply_photo(photo=InputFile(image, filename="logistic_regression.png"), caption="Logistic regression plot")
    await maybe_send_data_science_ai_summary(update, ai_requested, "Logistic regression", report, clean_text)


# ------------------------------------------------------------
# PCA
# ------------------------------------------------------------

def run_pca_2d(points: List[Tuple[float, float]]) -> Dict:
    if len(points) < 2:
        raise ValueError("At least 2 points are required.")

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx = mean(xs)
    my = mean(ys)
    centered = [(x - mx, y - my) for x, y in points]

    a = sum(x * x for x, _ in centered) / len(points)
    b = sum(x * y for x, y in centered) / len(points)
    c = sum(y * y for _, y in centered) / len(points)

    term = math.sqrt((a - c) ** 2 + 4 * b * b)
    lambda1 = (a + c + term) / 2
    lambda2 = (a + c - term) / 2

    if abs(b) > 1e-12:
        vx, vy = b, lambda1 - a
    elif a >= c:
        vx, vy = 1.0, 0.0
    else:
        vx, vy = 0.0, 1.0

    norm = math.sqrt(vx * vx + vy * vy)
    vx, vy = vx / norm, vy / norm
    explained = lambda1 / (lambda1 + lambda2) if lambda1 + lambda2 > 0 else 1.0
    scores = [x * vx + y * vy for x, y in centered]

    return {
        "mean": (mx, my),
        "pc1": (vx, vy),
        "eigenvalues": (lambda1, lambda2),
        "explained": explained,
        "scores": scores,
    }


def create_pca_image(points: List[Tuple[float, float]], result: Dict) -> BytesIO:
    width, height = 1200, 780
    left, top, right, bottom = 95, 95, 1140, 660
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx, my = result["mean"]
    vx, vy = result["pc1"]
    scale = max(max(abs(score) for score in result["scores"]), 1.0)
    line_points = [(mx - vx * scale, my - vy * scale), (mx + vx * scale, my + vy * scale)]
    xmin, xmax = padded_range(xs + [p[0] for p in line_points])
    ymin, ymax = padded_range(ys + [p[1] for p in line_points])
    mapper = PlotMapper(left, top, right, bottom, xmin, xmax, ymin, ymax)
    draw_plot_frame(draw, mapper, "PCA first principal component")

    for x, y in points:
        px, py = mapper.x(x), mapper.y(y)
        draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill="#1f77b4", outline="#0d3d66")

    draw.line((mapper.x(line_points[0][0]), mapper.y(line_points[0][1]), mapper.x(line_points[1][0]), mapper.y(line_points[1][1])), fill="#d62728", width=4)
    draw.ellipse((mapper.x(mx) - 8, mapper.y(my) - 8, mapper.x(mx) + 8, mapper.y(my) + 8), fill="#ff7f0e", outline="#333333")
    draw.text((left, height - 70), f"PC1=({nice_number(vx)}, {nice_number(vy)}) | explained variance={nice_number(result['explained'])}", fill="#333333", font=load_font(18))
    return image_to_buffer(image, "pca.png")


async def pca_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        points = parse_points(clean_text, max_points=MAX_REGRESSION_POINTS)
        result = run_pca_2d(points)
        image = create_pca_image(points, result)
    except Exception as error:
        await update.message.reply_text(
            "PCA error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/pca 1,2; 2,3; 3,5; 4,6; 5,8"
        )
        return

    report = (
        "Principal component analysis 🧭\n\n"
        f"Mean point: ({nice_number(result['mean'][0])}, {nice_number(result['mean'][1])})\n"
        f"PC1 direction: ({nice_number(result['pc1'][0])}, {nice_number(result['pc1'][1])})\n"
        f"Eigenvalues: {nice_number(result['eigenvalues'][0])}, {nice_number(result['eigenvalues'][1])}\n"
        f"Explained variance by PC1: {nice_number(result['explained'])}"
    )
    await update.message.reply_text(report)
    await update.message.reply_photo(photo=InputFile(image, filename="pca.png"), caption="PCA plot")
    await maybe_send_data_science_ai_summary(update, ai_requested, "PCA", report, clean_text)


# ------------------------------------------------------------
# K-means auto / elbow
# ------------------------------------------------------------

def parse_kmeans_auto_input(text: str) -> Tuple[int, List[Tuple[float, float]]]:
    if "|" not in text:
        raise ValueError("Use: /kmeans_auto maxk 6 | x,y; x,y; ...")

    left, right = text.split("|", 1)
    match = re.search(r"maxk\s*(?:=)?\s*(\d+)", left, flags=re.IGNORECASE)
    if match:
        max_k = int(match.group(1))
    else:
        nums = re.findall(r"\d+", left)
        max_k = int(nums[0]) if nums else 6

    if max_k < 2 or max_k > MAX_KMEANS_K:
        raise ValueError(f"maxk must be between 2 and {MAX_KMEANS_K}.")

    points = parse_points(right, max_points=MAX_KMEANS_POINTS)
    max_k = min(max_k, len(points))
    return max_k, points


def create_elbow_image(inertias: List[Tuple[int, float]]) -> BytesIO:
    width, height = 1100, 720
    left, top, right, bottom = 90, 95, 1040, 600
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    ks = [k for k, _ in inertias]
    vals = [v for _, v in inertias]
    ymin, ymax = padded_range(vals, include_zero=True)
    mapper = PlotMapper(left, top, right, bottom, min(ks), max(ks), ymin, ymax)
    draw_plot_frame(draw, mapper, "K-means elbow curve", "k", "inertia")

    pixels = [(mapper.x(k), mapper.y(v)) for k, v in inertias]
    if len(pixels) >= 2:
        draw.line(pixels, fill="#1f77b4", width=4)
    for k, v in inertias:
        px, py = mapper.x(k), mapper.y(v)
        draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill="#ff7f0e", outline="#333333")
        draw.text((px + 8, py - 10), str(k), fill="black", font=load_font(16))

    return image_to_buffer(image, "kmeans_elbow.png")


def recommend_k_from_inertias(inertias: List[Tuple[int, float]]) -> int:
    if len(inertias) <= 2:
        return inertias[-1][0]

    best_k = inertias[1][0]
    best_score = -float("inf")
    values = [v for _, v in inertias]
    for i in range(1, len(values) - 1):
        previous_drop = values[i - 1] - values[i]
        next_drop = values[i] - values[i + 1]
        score = previous_drop - next_drop
        if score > best_score:
            best_score = score
            best_k = inertias[i][0]
    return best_k


async def kmeans_auto_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        max_k, points = parse_kmeans_auto_input(clean_text)
        inertias = []
        for k in range(1, max_k + 1):
            result = run_kmeans(points, k)
            inertias.append((k, result["inertia"]))
        recommended = recommend_k_from_inertias(inertias)
        image = create_elbow_image(inertias)
    except Exception as error:
        await update.message.reply_text(
            "K-means auto error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/kmeans_auto maxk 6 | 1,1; 1,2; 8,8; 9,8; 20,20; 21,20"
        )
        return

    lines = ["K-means elbow analysis 🤖", "", f"Suggested k: {recommended}", "", "Inertia by k:"]
    for k, inertia in inertias:
        lines.append(f"k={k}: {nice_number(inertia)}")

    report = "\n".join(lines)
    await update.message.reply_text(report)
    await update.message.reply_photo(photo=InputFile(image, filename="kmeans_elbow.png"), caption="K-means elbow curve")
    await maybe_send_data_science_ai_summary(update, ai_requested, "K-means elbow analysis", report, clean_text)


# ------------------------------------------------------------
# Moving average and forecast
# ------------------------------------------------------------

def parse_window_values_input(text: str, default_window: int = 3) -> Tuple[int, List[float]]:
    window = default_window
    data_text = text.strip()

    if "|" in data_text:
        left, right = data_text.split("|", 1)
        match = re.search(r"window\s*(?:=)?\s*(\d+)", left, flags=re.IGNORECASE)
        if match:
            window = int(match.group(1))
        else:
            nums = re.findall(r"\d+", left)
            if nums:
                window = int(nums[0])
        data_text = right.strip()

    values = parse_numbers_from_text(data_text, max_count=MAX_NUMBERS)
    if window < 1 or window > len(values):
        raise ValueError("Window must be between 1 and the number of values.")

    return window, values


def moving_average(values: List[float], window: int) -> List[float]:
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        result.append(mean(values[start:i + 1]))
    return result


def create_line_series_image(series: List[Tuple[str, List[float]]], title: str, filename: str) -> BytesIO:
    width, height = 1200, 780
    left, top, right, bottom = 95, 95, 1140, 660
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    all_values = []
    max_len = 0
    for _, values in series:
        all_values.extend(values)
        max_len = max(max_len, len(values))

    mapper = PlotMapper(left, top, right, bottom, 1, max(2, max_len), *padded_range(all_values))
    draw_plot_frame(draw, mapper, title, "index", "value")

    colors = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e"]
    for idx, (name, values) in enumerate(series):
        pixels = [(mapper.x(i + 1), mapper.y(value)) for i, value in enumerate(values)]
        if len(pixels) >= 2:
            draw.line(pixels, fill=colors[idx % len(colors)], width=4)
        for px, py in pixels:
            draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=colors[idx % len(colors)])
        draw.text((left + idx * 220, height - 68), name, fill=colors[idx % len(colors)], font=load_font(20))

    return image_to_buffer(image, filename)


async def moving_average_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        window, values = parse_window_values_input(clean_text)
        ma_values = moving_average(values, window)
        image = create_line_series_image([("Original", values), (f"MA window={window}", ma_values)], "Moving average", "moving_average.png")
    except Exception as error:
        await update.message.reply_text(
            "Moving average error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/moving_average window 3 | 10,12,13,15,14,18,20"
        )
        return

    preview = ", ".join(nice_number(v) for v in ma_values[:20])
    if len(ma_values) > 20:
        preview += ", ..."
    report = f"Moving average 📉\n\nWindow: {window}\nValues: {preview}"
    await update.message.reply_text(report)
    await update.message.reply_photo(photo=InputFile(image, filename="moving_average.png"), caption="Moving average plot")
    await maybe_send_data_science_ai_summary(update, ai_requested, "Moving average", report, clean_text)


def parse_forecast_input(text: str) -> Tuple[int, List[float]]:
    steps = 5
    data_text = text.strip()

    if "|" in data_text:
        left, right = data_text.split("|", 1)
        match = re.search(r"steps\s*(?:=)?\s*(\d+)", left, flags=re.IGNORECASE)
        if match:
            steps = int(match.group(1))
        else:
            nums = re.findall(r"\d+", left)
            if nums:
                steps = int(nums[0])
        data_text = right.strip()

    if steps < 1 or steps > MAX_FORECAST_STEPS:
        raise ValueError(f"Steps must be between 1 and {MAX_FORECAST_STEPS}.")

    values = parse_numbers_from_text(data_text, max_count=MAX_NUMBERS)
    if len(values) < 2:
        raise ValueError("At least 2 values are required.")

    return steps, values


async def forecast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        steps, values = parse_forecast_input(clean_text)
        points = [(i + 1, value) for i, value in enumerate(values)]
        reg = linear_regression(points)
        forecast_values = [reg["slope"] * (len(values) + i + 1) + reg["intercept"] for i in range(steps)]
        combined_forecast = values + forecast_values
        image = create_line_series_image([("Actual", values), ("Trend + forecast", combined_forecast)], "Simple linear forecast", "forecast.png")
    except Exception as error:
        await update.message.reply_text(
            "Forecast error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/forecast steps 5 | 10,12,13,15,18,21"
        )
        return

    report = (
        "Simple trend forecast 🔮\n\n"
        f"Model: y = {nice_number(reg['slope'])}t + {nice_number(reg['intercept'])}\n"
        f"R² on history: {nice_number(reg['r2'])}\n"
        f"Next {steps}: " + ", ".join(nice_number(v) for v in forecast_values)
    )
    await update.message.reply_text(report)
    await update.message.reply_photo(photo=InputFile(image, filename="forecast.png"), caption="Forecast plot")
    await maybe_send_data_science_ai_summary(update, ai_requested, "Simple trend forecast", report, clean_text)


# ------------------------------------------------------------
# Hypothesis tests
# ------------------------------------------------------------

def student_t_pdf(x: float, df: int) -> float:
    return math.exp(
        math.lgamma((df + 1) / 2) - math.lgamma(df / 2)
        - 0.5 * math.log(df * math.pi)
        - ((df + 1) / 2) * math.log(1 + (x * x) / df)
    )


def student_t_two_tailed_p(t_value: float, df: int) -> float:
    t_abs = abs(t_value)
    if df <= 0:
        return float("nan")
    if t_abs > 40:
        return 0.0

    intervals = 1000
    if intervals % 2 == 1:
        intervals += 1
    h = t_abs / intervals if intervals else 0
    area = student_t_pdf(0.0, df) + student_t_pdf(t_abs, df)
    for i in range(1, intervals):
        x = i * h
        area += (4 if i % 2 else 2) * student_t_pdf(x, df)
    integral = area * h / 3
    cdf = 0.5 + integral
    return max(0.0, min(1.0, 2 * (1 - cdf)))


def parse_ttest_input(text: str) -> Dict:
    if "|" not in text:
        raise ValueError("Use | before the data values.")

    left, right = text.split("|", 1)
    left_lower = left.lower()

    if "two_sample" in left_lower or "two-sample" in left_lower or "welch" in left_lower:
        groups = [part.strip() for part in right.split(";", 1)]
        if len(groups) != 2:
            raise ValueError("Two-sample t-test needs two groups separated by ;")
        values_a = parse_numbers_from_text(groups[0], max_count=MAX_TTEST_VALUES)
        values_b = parse_numbers_from_text(groups[1], max_count=MAX_TTEST_VALUES)
        return {"kind": "two_sample", "a": values_a, "b": values_b}

    mean_match = re.search(r"mean\s*=\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)", left, flags=re.IGNORECASE)
    if not mean_match:
        if "mean" in left_lower:
            nums = parse_numbers_from_text(left, max_count=1)
            test_mean = nums[0]
        else:
            raise ValueError("One-sample t-test needs mean=VALUE.")
    else:
        test_mean = float(mean_match.group(1))

    values = parse_numbers_from_text(right, max_count=MAX_TTEST_VALUES)
    return {"kind": "one_sample", "mean": test_mean, "values": values}


def one_sample_ttest(values: List[float], test_mean: float) -> Dict:
    if len(values) < 2:
        raise ValueError("At least 2 values are required.")
    avg = mean(values)
    sd = math.sqrt(sample_variance(values))
    if sd == 0:
        raise ValueError("Sample standard deviation is zero.")
    t_value = (avg - test_mean) / (sd / math.sqrt(len(values)))
    df = len(values) - 1
    return {"mean": avg, "sd": sd, "t": t_value, "df": df, "p": student_t_two_tailed_p(t_value, df)}


def two_sample_welch_ttest(a: List[float], b: List[float]) -> Dict:
    if len(a) < 2 or len(b) < 2:
        raise ValueError("Each group needs at least 2 values.")
    ma, mb = mean(a), mean(b)
    va, vb = sample_variance(a), sample_variance(b)
    se2 = va / len(a) + vb / len(b)
    if se2 <= 0:
        raise ValueError("Standard error is zero.")
    t_value = (ma - mb) / math.sqrt(se2)
    df_num = se2 ** 2
    df_den = ((va / len(a)) ** 2) / (len(a) - 1) + ((vb / len(b)) ** 2) / (len(b) - 1)
    df = max(1, int(round(df_num / df_den))) if df_den > 0 else min(len(a), len(b)) - 1
    return {"mean_a": ma, "mean_b": mb, "t": t_value, "df": df, "p": student_t_two_tailed_p(t_value, df)}


async def ttest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        parsed = parse_ttest_input(clean_text)
        if parsed["kind"] == "one_sample":
            result = one_sample_ttest(parsed["values"], parsed["mean"])
            report = (
                "One-sample t-test 🧪\n\n"
                f"Hypothesized mean: {nice_number(parsed['mean'])}\n"
                f"Sample mean: {nice_number(result['mean'])}\n"
                f"Sample std dev: {nice_number(result['sd'])}\n"
                f"t: {nice_number(result['t'])}\n"
                f"df: {result['df']}\n"
                f"Approx. two-tailed p-value: {nice_number(result['p'])}"
            )
        else:
            result = two_sample_welch_ttest(parsed["a"], parsed["b"])
            report = (
                "Welch two-sample t-test 🧪\n\n"
                f"Group A mean: {nice_number(result['mean_a'])}\n"
                f"Group B mean: {nice_number(result['mean_b'])}\n"
                f"Difference: {nice_number(result['mean_a'] - result['mean_b'])}\n"
                f"t: {nice_number(result['t'])}\n"
                f"df: {result['df']}\n"
                f"Approx. two-tailed p-value: {nice_number(result['p'])}"
            )
    except Exception as error:
        await update.message.reply_text(
            "t-test error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/ttest one_sample mean=10 | 9,10,11,12,8,10\n"
            "/ttest two_sample | 9,10,11,12 ; 14,15,13,16"
        )
        return

    await update.message.reply_text(report)
    await maybe_send_data_science_ai_summary(update, ai_requested, "t-test", report, clean_text)


def chi_square_survival_approx(chi2: float, df: int) -> float:
    if df <= 0:
        return float("nan")
    if chi2 <= 0:
        return 1.0
    z = ((chi2 / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    return max(0.0, min(1.0, 1 - normal_cdf(z)))


def parse_chisquare_input(text: str) -> Tuple[List[float], Optional[List[float]]]:
    lower = text.lower()
    if "expected" in lower:
        parts = re.split(r"expected", text, maxsplit=1, flags=re.IGNORECASE)
        observed_text = re.sub(r"observed", "", parts[0], flags=re.IGNORECASE)
        expected_text = parts[1]
        observed = parse_numbers_from_text(observed_text, max_count=MAX_CHISQUARE_CATEGORIES)
        expected = parse_numbers_from_text(expected_text, max_count=MAX_CHISQUARE_CATEGORIES)
    else:
        observed_text = re.sub(r"observed", "", text, flags=re.IGNORECASE)
        observed = parse_numbers_from_text(observed_text, max_count=MAX_CHISQUARE_CATEGORIES)
        expected = None

    if len(observed) < 2:
        raise ValueError("At least 2 categories are required.")
    if any(value < 0 for value in observed):
        raise ValueError("Observed counts must be non-negative.")

    if expected is not None:
        if len(expected) != len(observed):
            raise ValueError("Observed and expected lists must have the same length.")
        if any(value <= 0 for value in expected):
            raise ValueError("Expected counts must be positive.")
    else:
        avg = sum(observed) / len(observed)
        expected = [avg for _ in observed]

    return observed, expected


async def chisquare_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        observed, expected = parse_chisquare_input(clean_text)
        chi2 = sum((o - e) ** 2 / e for o, e in zip(observed, expected))
        df = len(observed) - 1
        p = chi_square_survival_approx(chi2, df)
    except Exception as error:
        await update.message.reply_text(
            "Chi-square error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/chisquare 20,30,25,25\n"
            "/chisquare observed 18,22,30 expected 20,20,30"
        )
        return

    rows_text = "\n".join(
        f"Category {i + 1}: observed={nice_number(o)}, expected={nice_number(e)}"
        for i, (o, e) in enumerate(zip(observed, expected))
    )
    report = (
        "Chi-square goodness-of-fit test 🧪\n\n"
        f"χ²: {nice_number(chi2)}\n"
        f"df: {df}\n"
        f"Approx. p-value: {nice_number(p)}\n\n"
        f"{rows_text}"
    )
    await update.message.reply_text(report)
    await maybe_send_data_science_ai_summary(update, ai_requested, "Chi-square goodness-of-fit test", report, clean_text)


# ------------------------------------------------------------
# Dataset profile
# ------------------------------------------------------------

def dataset_profile_report(headers: List[str], rows: List[Dict[str, str]]) -> str:
    total_rows = len(rows)
    numeric = numeric_columns(headers, rows)
    row_tuples = [tuple(str(row.get(header, "")).strip() for header in headers) for row in rows]
    duplicate_rows = total_rows - len(set(row_tuples))

    lines = [
        "Advanced dataset profile 📄📊",
        "",
        f"Rows analyzed: {total_rows}",
        f"Columns: {len(headers)}",
        f"Duplicate rows: {duplicate_rows}",
        f"Numeric columns: {len(numeric)}",
        f"Categorical/text columns: {len(headers) - len(numeric)}",
        "",
        "Column overview:",
    ]

    constant_columns = []
    likely_id_columns = []
    high_cardinality_columns = []

    for header in headers:
        values = [str(row.get(header, "")).strip() for row in rows]
        non_missing = [value for value in values if value != ""]
        missing = total_rows - len(non_missing)
        unique = len(set(non_missing))
        missing_pct = missing / total_rows if total_rows else 0
        unique_ratio = unique / len(non_missing) if non_missing else 0
        col_type = "numeric" if header in numeric else "categorical/text"

        if unique <= 1:
            constant_columns.append(header)
        if len(non_missing) >= max(10, int(0.8 * total_rows)) and unique_ratio >= 0.95:
            likely_id_columns.append(header)
        if col_type != "numeric" and unique_ratio >= 0.5 and unique >= 20:
            high_cardinality_columns.append(header)

        lines.append(
            f"- {header}: {col_type}, missing={missing} ({nice_number(missing_pct * 100)}%), unique={unique}"
        )

    lines.extend(["", "Quality checks:"])
    lines.append("Constant columns: " + (", ".join(constant_columns) if constant_columns else "none"))
    lines.append("Possible ID columns: " + (", ".join(likely_id_columns) if likely_id_columns else "none"))
    lines.append("High-cardinality categorical columns: " + (", ".join(high_cardinality_columns) if high_cardinality_columns else "none"))

    lines.extend(["", "Numeric summaries:"])
    if numeric:
        for header, values in list(numeric.items())[:25]:
            sorted_values = sorted(values)
            lines.append(
                f"- {header}: count={len(values)}, mean={nice_number(mean(values))}, median={nice_number(quantile(sorted_values, 0.5))}, std={nice_number(math.sqrt(population_variance(values)))}, min={nice_number(min(values))}, max={nice_number(max(values))}"
            )
    else:
        lines.append("No numeric columns detected.")

    lines.extend(["", "Categorical summaries:"])
    for header in headers:
        if header in numeric:
            continue
        values = [str(row.get(header, "")).strip() for row in rows if str(row.get(header, "")).strip() != ""]
        top_values = Counter(values).most_common(5)
        top_text = ", ".join(f"{name} ({count})" for name, count in top_values) if top_values else "none"
        lines.append(f"- {header}: top={top_text}")

    if len(numeric) >= 2:
        lines.extend(["", "Top numeric correlations:"])
        correlations = []
        cols = list(numeric.keys())
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                points = paired_numeric_values(rows, cols[i], cols[j])
                if len(points) >= 3:
                    try:
                        r = pearson_correlation(points)
                        correlations.append((abs(r), r, cols[i], cols[j], len(points)))
                    except Exception:
                        pass
        correlations.sort(reverse=True)
        if correlations:
            for _, r, a, b, n in correlations[:10]:
                lines.append(f"- {a} vs {b}: r={nice_number(r)}, n={n}")
        else:
            lines.append("No correlations available.")

    return "\n".join(lines)


async def dataset_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = " ".join(context.args)
    ai_requested, clean_text = extract_ai_request(raw_text)

    try:
        csv_text = await download_csv_text(update)
        headers, rows = load_csv_table(csv_text)
        report = dataset_profile_report(headers, rows)
    except Exception as error:
        await update.message.reply_text(
            "Dataset profile error.\n\n"
            f"Error: {error}\n\n"
            "Usage: reply to a CSV file with /dataset_profile"
        )
        return

    if len(report) <= 3500:
        await update.message.reply_text(report)
    else:
        await update.message.reply_document(document=text_to_file(report, "dataset_profile.txt"), caption="Advanced dataset profile")
    await maybe_send_data_science_ai_summary(update, ai_requested, "Advanced dataset profile", report, clean_text)

# ------------------------------------------------------------
# Help and registration
# ------------------------------------------------------------

async def ds_ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            "Usage:\n"
            "Reply to a data-science result with /ds_ai\n"
            "or use /ds_ai paste a data-science result here"
        )
        return

    await send_data_science_ai_summary(
        update,
        title="User-provided data-science result",
        result_text=text,
        original_input="/ds_ai",
    )


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

    # Advanced regression and ML
    app.add_handler(CommandHandler("poly_regression", poly_regression_command))
    app.add_handler(CommandHandler("polyreg", poly_regression_command))
    app.add_handler(CommandHandler("multiple_regression", multiple_regression_command))
    app.add_handler(CommandHandler("multireg", multiple_regression_command))
    app.add_handler(CommandHandler("logistic_regression", logistic_regression_command))
    app.add_handler(CommandHandler("logreg", logistic_regression_command))
    app.add_handler(CommandHandler("pca", pca_command))

    app.add_handler(CommandHandler("kmeans", kmeans_command))
    app.add_handler(CommandHandler("kmeans_auto", kmeans_auto_command))
    app.add_handler(CommandHandler("kauto", kmeans_auto_command))
    app.add_handler(CommandHandler("outliers", outliers_command))
    app.add_handler(CommandHandler("normalize", normalize_command))

    # Time series
    app.add_handler(CommandHandler("moving_average", moving_average_command))
    app.add_handler(CommandHandler("movingavg", moving_average_command))
    app.add_handler(CommandHandler("forecast", forecast_command))

    # Classification and hypothesis tests
    app.add_handler(CommandHandler("confusion_matrix", confusion_matrix_command))
    app.add_handler(CommandHandler("confmatrix", confusion_matrix_command))
    app.add_handler(CommandHandler("ttest", ttest_command))
    app.add_handler(CommandHandler("chisquare", chisquare_command))

    # CSV tools
    app.add_handler(CommandHandler("csv_analyze", csv_analyze_command))
    app.add_handler(CommandHandler("corr_matrix", corr_matrix_command))
    app.add_handler(CommandHandler("corrmatrix", corr_matrix_command))
    app.add_handler(CommandHandler("pairplot", pairplot_command))
    app.add_handler(CommandHandler("dataset_profile", dataset_profile_command))
    app.add_handler(CommandHandler("profile_csv", dataset_profile_command))

    app.add_handler(CommandHandler("ds_ai", ds_ai_command))
    app.add_handler(CommandHandler("dsai", ds_ai_command))
    app.add_handler(CommandHandler("dshelp", dshelp_command))

    # Only reacts when the document caption starts with a supported CSV command.
    app.add_handler(MessageHandler(filters.Document.ALL, csv_document_message_handler), group=20)
