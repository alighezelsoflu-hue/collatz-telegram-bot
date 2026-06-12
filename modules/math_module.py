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


def register_math_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("collatz", collatz_command))