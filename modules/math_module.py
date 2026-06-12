from typing import List, Tuple, Dict
from collections import Counter
import math

from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, ContextTypes

from config import MAX_INPUT
from utils import text_to_file


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
# Fibonacci logic
# ------------------------------------------------------------

MAX_FIB_INDEX = 5000
MAX_FIB_LIST_COUNT = 2000


def fibonacci_number(n: int) -> int:
    """
    Returns Fibonacci number F(n).

    F(0) = 0
    F(1) = 1
    """
    if n < 0:
        raise ValueError("Please send a non-negative integer. Example: /fib 20")

    if n > MAX_FIB_INDEX:
        raise ValueError(f"Please use n up to {MAX_FIB_INDEX:,} for /fib.")

    a, b = 0, 1

    for _ in range(n):
        a, b = b, a + b

    return a


def fibonacci_list(count: int) -> List[int]:
    """
    Returns the first count Fibonacci numbers.

    Example:
    count = 7 -> [0, 1, 1, 2, 3, 5, 8]
    """
    if count <= 0:
        raise ValueError("Please send a positive integer. Example: /fiblist 30")

    if count > MAX_FIB_LIST_COUNT:
        raise ValueError(f"Please use a count up to {MAX_FIB_LIST_COUNT:,} for /fiblist.")

    seq = []
    a, b = 0, 1

    for _ in range(count):
        seq.append(a)
        a, b = b, a + b

    return seq


def build_fibonacci_list_report(count: int) -> str:
    seq = fibonacci_list(count)

    lines = [
        "Fibonacci series report",
        "",
        f"First {count} Fibonacci numbers",
        "",
        "Definition:",
        "F(0) = 0",
        "F(1) = 1",
        "F(n) = F(n-1) + F(n-2)",
        "",
        "Series:",
        "",
    ]

    for index, value in enumerate(seq):
        lines.append(f"F({index}) = {value}")

    lines.extend(
        [
            "",
            "Raw series:",
            ", ".join(map(str, seq)),
            "",
            f"Last index: F({count - 1})",
            f"Last value: {seq[-1]}",
            f"Digits in last value: {len(str(seq[-1]))}",
        ]
    )

    return "\n".join(lines)


# ------------------------------------------------------------
# Statistics logic
# ------------------------------------------------------------

MAX_STATS_COUNT = 5000


def parse_number_list(args: List[str]) -> List[float]:
    """
    Parses numbers from Telegram command arguments.

    Supports:
    /stats 4 7 9 10
    /stats 4,7,9,10
    /stats 4, 7, 9, 10
    """
    if not args:
        raise ValueError("Please send numbers. Example: /stats 4 7 9 10 10")

    raw_text = " ".join(args)
    raw_text = raw_text.replace(",", " ")

    parts = [part.strip() for part in raw_text.split() if part.strip()]

    if not parts:
        raise ValueError("Please send numbers. Example: /stats 4 7 9 10 10")

    if len(parts) > MAX_STATS_COUNT:
        raise ValueError(f"Please send up to {MAX_STATS_COUNT:,} numbers.")

    numbers = []

    for part in parts:
        try:
            numbers.append(float(part))
        except ValueError:
            raise ValueError(f"Invalid number: {part}")

    return numbers


def format_number(value: float) -> str:
    if isinstance(value, int):
        return str(value)

    if float(value).is_integer():
        return str(int(value))

    return f"{value:.6f}".rstrip("0").rstrip(".")


def calculate_median(sorted_numbers: List[float]) -> float:
    count = len(sorted_numbers)
    middle = count // 2

    if count % 2 == 1:
        return sorted_numbers[middle]

    return (sorted_numbers[middle - 1] + sorted_numbers[middle]) / 2


def calculate_quartiles(sorted_numbers: List[float]) -> Tuple[float, float, float]:
    count = len(sorted_numbers)

    q2 = calculate_median(sorted_numbers)

    if count == 1:
        return sorted_numbers[0], q2, sorted_numbers[0]

    middle = count // 2

    if count % 2 == 0:
        lower_half = sorted_numbers[:middle]
        upper_half = sorted_numbers[middle:]
    else:
        lower_half = sorted_numbers[:middle]
        upper_half = sorted_numbers[middle + 1:]

    q1 = calculate_median(lower_half) if lower_half else sorted_numbers[0]
    q3 = calculate_median(upper_half) if upper_half else sorted_numbers[-1]

    return q1, q2, q3


def calculate_modes(numbers: List[float]) -> List[float]:
    counter = Counter(numbers)
    highest_frequency = max(counter.values())

    if highest_frequency == 1:
        return []

    modes = [number for number, frequency in counter.items() if frequency == highest_frequency]
    modes.sort()

    return modes


def calculate_statistics(numbers: List[float]) -> Dict[str, object]:
    if not numbers:
        raise ValueError("Please send at least one number.")

    count = len(numbers)
    sorted_numbers = sorted(numbers)

    total = sum(numbers)
    mean = total / count
    median = calculate_median(sorted_numbers)
    minimum = sorted_numbers[0]
    maximum = sorted_numbers[-1]
    data_range = maximum - minimum

    q1, q2, q3 = calculate_quartiles(sorted_numbers)
    iqr = q3 - q1

    modes = calculate_modes(numbers)

    population_variance = sum((x - mean) ** 2 for x in numbers) / count
    population_std_dev = math.sqrt(population_variance)

    if count > 1:
        sample_variance = sum((x - mean) ** 2 for x in numbers) / (count - 1)
        sample_std_dev = math.sqrt(sample_variance)
    else:
        sample_variance = None
        sample_std_dev = None

    return {
        "count": count,
        "sum": total,
        "mean": mean,
        "median": median,
        "modes": modes,
        "minimum": minimum,
        "maximum": maximum,
        "range": data_range,
        "q1": q1,
        "q2": q2,
        "q3": q3,
        "iqr": iqr,
        "population_variance": population_variance,
        "population_std_dev": population_std_dev,
        "sample_variance": sample_variance,
        "sample_std_dev": sample_std_dev,
        "sorted_numbers": sorted_numbers,
    }


def build_statistics_report(numbers: List[float]) -> str:
    stats = calculate_statistics(numbers)

    modes = stats["modes"]

    if modes:
        mode_text = ", ".join(format_number(mode) for mode in modes)
    else:
        mode_text = "No mode. All values appear only once."

    sample_variance = stats["sample_variance"]
    sample_std_dev = stats["sample_std_dev"]

    if sample_variance is None:
        sample_variance_text = "Not available. Need at least 2 numbers."
        sample_std_text = "Not available. Need at least 2 numbers."
    else:
        sample_variance_text = format_number(sample_variance)
        sample_std_text = format_number(sample_std_dev)

    lines = [
        "Statistics report",
        "",
        "Input data:",
        ", ".join(format_number(number) for number in numbers),
        "",
        "Sorted data:",
        ", ".join(format_number(number) for number in stats["sorted_numbers"]),
        "",
        "Basic statistics:",
        f"Count: {stats['count']}",
        f"Sum: {format_number(stats['sum'])}",
        f"Mean: {format_number(stats['mean'])}",
        f"Median: {format_number(stats['median'])}",
        f"Mode: {mode_text}",
        f"Minimum: {format_number(stats['minimum'])}",
        f"Maximum: {format_number(stats['maximum'])}",
        f"Range: {format_number(stats['range'])}",
        "",
        "Quartiles:",
        f"Q1: {format_number(stats['q1'])}",
        f"Q2 / Median: {format_number(stats['q2'])}",
        f"Q3: {format_number(stats['q3'])}",
        f"IQR: {format_number(stats['iqr'])}",
        "",
        "Population statistics:",
        f"Population variance: {format_number(stats['population_variance'])}",
        f"Population standard deviation: {format_number(stats['population_std_dev'])}",
        "",
        "Sample statistics:",
        f"Sample variance: {sample_variance_text}",
        f"Sample standard deviation: {sample_std_text}",
        "",
        "Notes:",
        "Population variance divides by n.",
        "Sample variance divides by n - 1.",
    ]

    return "\n".join(lines)


def build_statistics_short_summary(numbers: List[float]) -> str:
    stats = calculate_statistics(numbers)

    modes = stats["modes"]

    if modes:
        mode_text = ", ".join(format_number(mode) for mode in modes)
    else:
        mode_text = "No mode"

    sample_std_dev = stats["sample_std_dev"]

    if sample_std_dev is None:
        sample_std_text = "N/A"
    else:
        sample_std_text = format_number(sample_std_dev)

    return (
        "Statistics result\n\n"
        f"Count: {stats['count']}\n"
        f"Sum: {format_number(stats['sum'])}\n"
        f"Mean: {format_number(stats['mean'])}\n"
        f"Median: {format_number(stats['median'])}\n"
        f"Mode: {mode_text}\n"
        f"Min: {format_number(stats['minimum'])}\n"
        f"Max: {format_number(stats['maximum'])}\n"
        f"Range: {format_number(stats['range'])}\n"
        f"Q1: {format_number(stats['q1'])}\n"
        f"Q3: {format_number(stats['q3'])}\n"
        f"IQR: {format_number(stats['iqr'])}\n"
        f"Population std dev: {format_number(stats['population_std_dev'])}\n"
        f"Sample std dev: {sample_std_text}"
    )


# ------------------------------------------------------------
# Telegram commands
# ------------------------------------------------------------

async def collatz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

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


async def fib_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage: /fib 20")
        return

    try:
        n = int(context.args[0])
        value = fibonacci_number(n)

        await update.message.reply_text(
            f"Fibonacci result\n\n"
            f"F({n}) = {value}\n\n"
            f"Number of digits: {len(str(value))}"
        )

    except ValueError as error:
        await update.message.reply_text(
            f"{error}\n\nExamples:\n/fib 20\n/fibonacci 50"
        )


async def fiblist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage: /fiblist 30")
        return

    try:
        count = int(context.args[0])
        report_text = build_fibonacci_list_report(count)

        filename = f"fibonacci_first_{count}_numbers.txt"
        file_output = text_to_file(report_text, filename)

        seq = fibonacci_list(count)
        last_index = count - 1
        last_value = seq[-1]

        await update.message.reply_text(
            f"Fibonacci series is ready.\n\n"
            f"First {count} Fibonacci numbers were calculated.\n"
            f"Last item: F({last_index}) = {last_value}\n"
            f"Digits in last value: {len(str(last_value))}\n\n"
            f"I attached the full series as a text file."
        )

        await update.message.reply_document(
            document=InputFile(file_output, filename=filename),
            caption=f"First {count} Fibonacci numbers",
        )

    except ValueError as error:
        await update.message.reply_text(
            f"{error}\n\nExamples:\n/fiblist 30\n/fiblist 100"
        )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        numbers = parse_number_list(context.args)
        summary = build_statistics_short_summary(numbers)

        await update.message.reply_text(summary)

    except ValueError as error:
        await update.message.reply_text(
            f"{error}\n\n"
            "Examples:\n"
            "/stats 4 7 9 10 10\n"
            "/stats 4, 7, 9, 10, 10"
        )


async def statsfile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        numbers = parse_number_list(context.args)
        report_text = build_statistics_report(numbers)

        filename = "statistics_report.txt"
        file_output = text_to_file(report_text, filename)

        await update.message.reply_text(
            "Statistics report is ready.\n"
            "I attached the complete report as a text file."
        )

        await update.message.reply_document(
            document=InputFile(file_output, filename=filename),
            caption="Complete statistics report",
        )

    except ValueError as error:
        await update.message.reply_text(
            f"{error}\n\n"
            "Examples:\n"
            "/statsfile 4 7 9 10 10\n"
            "/statsfile 4, 7, 9, 10, 10"
        )


def register_math_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("collatz", collatz_command))

    app.add_handler(CommandHandler("fib", fib_command))
    app.add_handler(CommandHandler("fibonacci", fib_command))
    app.add_handler(CommandHandler("fiblist", fiblist_command))

    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("statistics", stats_command))
    app.add_handler(CommandHandler("statsfile", statsfile_command))