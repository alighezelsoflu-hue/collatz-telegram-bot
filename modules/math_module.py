from typing import List, Tuple

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

    Uses:
    F(0) = 0
    F(1) = 1
    F(2) = 1
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


def build_fibonacci_number_report(n: int) -> str:
    value = fibonacci_number(n)

    lines = [
        f"Fibonacci number report",
        "",
        f"Requested index: n = {n}",
        "",
        "Definition:",
        "F(0) = 0",
        "F(1) = 1",
        "F(n) = F(n-1) + F(n-2)",
        "",
        f"Result:",
        f"F({n}) = {value}",
        "",
        f"Number of digits: {len(str(value))}",
    ]

    return "\n".join(lines)


def build_fibonacci_list_report(count: int) -> str:
    seq = fibonacci_list(count)

    lines = [
        f"Fibonacci series report",
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


def register_math_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("collatz", collatz_command))

    app.add_handler(CommandHandler("fib", fib_command))
    app.add_handler(CommandHandler("fibonacci", fib_command))
    app.add_handler(CommandHandler("fiblist", fiblist_command))