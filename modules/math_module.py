from typing import List, Tuple, Dict, Any
from collections import Counter
import ast
import math
import operator

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
    if n < 0:
        raise ValueError("Please send a non-negative integer. Example: /fib 20")

    if n > MAX_FIB_INDEX:
        raise ValueError(f"Please use n up to {MAX_FIB_INDEX:,} for /fib.")

    a, b = 0, 1

    for _ in range(n):
        a, b = b, a + b

    return a


def fibonacci_list(count: int) -> List[int]:
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


def format_number(value: Any, max_digits: int = 12) -> str:
    if value is None:
        return "N/A"

    if isinstance(value, int):
        return str(value)

    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "∞" if value > 0 else "-∞"
        if value.is_integer():
            return str(int(value))
        return f"{value:.{max_digits}g}"

    return str(value)


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
    frequencies = list(counter.values())

    highest_frequency = max(frequencies)

    if highest_frequency == 1:
        return []

    # Your requested rule:
    # If all distinct values appear the same number of times,
    # the data set has no mode: Mo = ∅
    if len(set(frequencies)) == 1:
        return []

    modes = [
        number
        for number, frequency in counter.items()
        if frequency == highest_frequency
    ]

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
        mode_text = "Mo = ∅"

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
        "Mode rule in this bot:",
        "If all distinct values have the same frequency, Mode = Mo = ∅.",
    ]

    return "\n".join(lines)


def build_statistics_short_summary(numbers: List[float]) -> str:
    stats = calculate_statistics(numbers)

    modes = stats["modes"]

    if modes:
        mode_text = ", ".join(format_number(mode) for mode in modes)
    else:
        mode_text = "Mo = ∅"

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
# Scientific calculator logic
# ------------------------------------------------------------

MAX_CALC_EXPRESSION_LENGTH = 500
MAX_CALC_ABS_RESULT = 10**100


def calc_mean(*values: float) -> float:
    if not values:
        raise ValueError("mean() needs at least one number.")
    return sum(values) / len(values)


def calc_median(*values: float) -> float:
    if not values:
        raise ValueError("median() needs at least one number.")
    return calculate_median(sorted(float(v) for v in values))


def calc_mode(*values: float) -> Any:
    if not values:
        raise ValueError("mode() needs at least one number.")
    modes = calculate_modes([float(v) for v in values])
    if not modes:
        return "Mo = ∅"
    if len(modes) == 1:
        return modes[0]
    return modes


def calc_variance(*values: float) -> float:
    if not values:
        raise ValueError("variance() needs at least one number.")
    values = [float(v) for v in values]
    mean_value = calc_mean(*values)
    return sum((x - mean_value) ** 2 for x in values) / len(values)


def calc_sample_variance(*values: float) -> float:
    if len(values) < 2:
        raise ValueError("sample_variance() needs at least two numbers.")
    values = [float(v) for v in values]
    mean_value = calc_mean(*values)
    return sum((x - mean_value) ** 2 for x in values) / (len(values) - 1)


def calc_std(*values: float) -> float:
    return math.sqrt(calc_variance(*values))


def calc_sample_std(*values: float) -> float:
    return math.sqrt(calc_sample_variance(*values))


def calc_range(*values: float) -> float:
    if not values:
        raise ValueError("range() needs at least one number.")
    return max(values) - min(values)


def calc_percent(value: float, percent: float) -> float:
    return value * percent / 100


def calc_factorial(value: float) -> int:
    if not float(value).is_integer():
        raise ValueError("factorial() only accepts whole numbers.")
    value = int(value)
    if value < 0:
        raise ValueError("factorial() does not accept negative numbers.")
    if value > 1000:
        raise ValueError("factorial() accepts values up to 1000.")
    return math.factorial(value)


def calc_ncr(n: float, r: float) -> int:
    if not float(n).is_integer() or not float(r).is_integer():
        raise ValueError("ncr() accepts whole numbers only.")
    n = int(n)
    r = int(r)
    if n < 0 or r < 0:
        raise ValueError("ncr() does not accept negative numbers.")
    return math.comb(n, r)


def calc_npr(n: float, r: float) -> int:
    if not float(n).is_integer() or not float(r).is_integer():
        raise ValueError("npr() accepts whole numbers only.")
    n = int(n)
    r = int(r)
    if n < 0 or r < 0:
        raise ValueError("npr() does not accept negative numbers.")
    return math.perm(n, r)


def deg(value: float) -> float:
    return math.degrees(value)


def rad(value: float) -> float:
    return math.radians(value)


SAFE_CONSTANTS = {
    "pi": math.pi,
    "π": math.pi,
    "e": math.e,
    "tau": math.tau,
    "τ": math.tau,
    "phi": (1 + math.sqrt(5)) / 2,
    "golden": (1 + math.sqrt(5)) / 2,
    "inf": math.inf,
    "infinity": math.inf,
    "nan": math.nan,
}

SAFE_FUNCTIONS = {
    # Basic
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": lambda *values: sum(values),

    # Roots and powers
    "sqrt": math.sqrt,
    "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
    "pow": pow,

    # Exponential and logarithms
    "exp": math.exp,
    "ln": math.log,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,

    # Trigonometry, radians
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,

    # Trigonometry, degrees
    "sind": lambda x: math.sin(math.radians(x)),
    "cosd": lambda x: math.cos(math.radians(x)),
    "tand": lambda x: math.tan(math.radians(x)),
    "asind": lambda x: math.degrees(math.asin(x)),
    "acosd": lambda x: math.degrees(math.acos(x)),
    "atand": lambda x: math.degrees(math.atan(x)),

    # Hyperbolic
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,

    # Angle conversion
    "deg": deg,
    "degrees": deg,
    "rad": rad,
    "radians": rad,

    # Number theory / combinatorics
    "factorial": calc_factorial,
    "fact": calc_factorial,
    "gcd": math.gcd,
    "lcm": math.lcm,
    "ncr": calc_ncr,
    "comb": calc_ncr,
    "npr": calc_npr,
    "perm": calc_npr,

    # Statistics
    "mean": calc_mean,
    "avg": calc_mean,
    "average": calc_mean,
    "median": calc_median,
    "mode": calc_mode,
    "variance": calc_variance,
    "var": calc_variance,
    "sample_variance": calc_sample_variance,
    "sample_var": calc_sample_variance,
    "std": calc_std,
    "stdev": calc_std,
    "sample_std": calc_sample_std,
    "sample_stdev": calc_sample_std,
    "range": calc_range,

    # Other useful math
    "ceil": math.ceil,
    "floor": math.floor,
    "trunc": math.trunc,
    "percent": calc_percent,
    "fib": fibonacci_number,
    "fibonacci": fibonacci_number,
}

SAFE_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

SAFE_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class SafeMathEvaluator(ast.NodeVisitor):
    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Only numbers are allowed.")

    def visit_Name(self, node: ast.Name) -> Any:
        name = node.id.lower()

        if name in SAFE_CONSTANTS:
            return SAFE_CONSTANTS[name]

        raise ValueError(f"Unknown name: {node.id}")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = self.visit(node.left)
        right = self.visit(node.right)

        operator_type = type(node.op)

        if operator_type not in SAFE_BINARY_OPERATORS:
            raise ValueError("This operator is not allowed.")

        if operator_type is ast.Pow:
            if abs(right) > 1000:
                raise ValueError("Power is too large.")
            if abs(left) > 10**10:
                raise ValueError("Base is too large.")

        result = SAFE_BINARY_OPERATORS[operator_type](left, right)
        self.check_result(result)
        return result

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operator_type = type(node.op)

        if operator_type not in SAFE_UNARY_OPERATORS:
            raise ValueError("This unary operator is not allowed.")

        value = self.visit(node.operand)
        result = SAFE_UNARY_OPERATORS[operator_type](value)
        self.check_result(result)
        return result

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only direct function calls are allowed.")

        function_name = node.func.id.lower()

        if function_name not in SAFE_FUNCTIONS:
            raise ValueError(f"Unknown function: {node.func.id}")

        if node.keywords:
            raise ValueError("Keyword arguments are not allowed.")

        if len(node.args) > 100:
            raise ValueError("Too many function arguments.")

        args = [self.visit(arg) for arg in node.args]
        result = SAFE_FUNCTIONS[function_name](*args)

        self.check_result(result)
        return result

    def visit_List(self, node: ast.List) -> Any:
        raise ValueError("Lists are not allowed. Use mean(1,2,3), not mean([1,2,3]).")

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        raise ValueError("Tuples are not allowed. Use mean(1,2,3), not mean((1,2,3)).")

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"Unsupported expression: {type(node).__name__}")

    @staticmethod
    def check_result(result: Any) -> None:
        if isinstance(result, (int, float)):
            if isinstance(result, float) and (math.isnan(result) or math.isinf(result)):
                return

            if abs(result) > MAX_CALC_ABS_RESULT:
                raise ValueError("Result is too large.")


def safe_calculate(expression: str) -> Any:
    if not expression or not expression.strip():
        raise ValueError("Please send an expression. Example: /calc sin(pi / 2)")

    expression = expression.strip()

    if len(expression) > MAX_CALC_EXPRESSION_LENGTH:
        raise ValueError(f"Expression is too long. Maximum {MAX_CALC_EXPRESSION_LENGTH} characters.")

    expression = expression.replace("^", "**")
    expression = expression.replace("×", "*")
    expression = expression.replace("÷", "/")

    parsed = ast.parse(expression, mode="eval")
    evaluator = SafeMathEvaluator()

    return evaluator.visit(parsed)


def build_math_help_text() -> str:
    return (
        "Scientific calculator help\n\n"
        "Constants:\n"
        "pi, π, e, tau, τ, phi\n\n"
        "Basic examples:\n"
        "/calc 2 + 3 * 4\n"
        "/calc 2^10\n"
        "/calc sqrt(144)\n"
        "/calc factorial(5)\n\n"
        "Logarithms:\n"
        "/calc ln(e)\n"
        "/calc log(100, 10)\n"
        "/calc log10(1000)\n"
        "/calc log2(1024)\n\n"
        "Trigonometry in radians:\n"
        "/calc sin(pi / 2)\n"
        "/calc cos(pi)\n"
        "/calc tan(pi / 4)\n\n"
        "Trigonometry in degrees:\n"
        "/calc sind(90)\n"
        "/calc cosd(180)\n"
        "/calc tand(45)\n\n"
        "Statistics inside /calc:\n"
        "/calc mean(4,7,4,2,7,4,2,2,7)\n"
        "/calc median(4,7,4,2,7,4,2,2,7)\n"
        "/calc mode(4,7,4,2,7,4,2,2,7)\n"
        "/calc std(4,7,4,2,7,4,2,2,7)\n\n"
        "Combinatorics:\n"
        "/calc ncr(5, 2)\n"
        "/calc npr(5, 2)\n\n"
        "Fibonacci:\n"
        "/calc fib(20)\n\n"
        "Separate commands:\n"
        "/pi\n"
        "/e\n"
        "/fib 20\n"
        "/fiblist 30\n"
        "/stats 4 7 9 10 10\n"
        "/statsfile 4 7 9 10 10"
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


async def calc_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "/calc sin(pi / 2)\n"
            "/calc log(100, 10)\n"
            "/calc sqrt(144)\n\n"
            "Use /mathhelp for examples."
        )
        return

    expression = " ".join(context.args)

    try:
        result = safe_calculate(expression)

        if isinstance(result, list):
            result_text = ", ".join(format_number(item) for item in result)
        else:
            result_text = format_number(result, max_digits=15)

        await update.message.reply_text(
            f"Calculator result\n\n"
            f"Expression:\n{expression}\n\n"
            f"Result:\n{result_text}"
        )

    except Exception as error:
        await update.message.reply_text(
            f"Could not calculate this expression.\n\n"
            f"Error: {error}\n\n"
            "Try:\n"
            "/calc sin(pi / 2)\n"
            "/calc log(100, 10)\n"
            "/calc sqrt(144)\n"
            "/mathhelp"
        )


async def pi_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "Pi number\n\n"
        f"π = {math.pi:.50f}\n\n"
        "Examples:\n"
        "/calc pi\n"
        "/calc 2 * pi\n"
        "/calc sin(pi / 2)"
    )


async def e_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "Euler's number\n\n"
        f"e = {math.e:.50f}\n\n"
        "Examples:\n"
        "/calc e\n"
        "/calc ln(e)\n"
        "/calc exp(1)"
    )


async def mathhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(build_math_help_text())


def register_math_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("collatz", collatz_command))

    app.add_handler(CommandHandler("fib", fib_command))
    app.add_handler(CommandHandler("fibonacci", fib_command))
    app.add_handler(CommandHandler("fiblist", fiblist_command))

    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("statistics", stats_command))
    app.add_handler(CommandHandler("statsfile", statsfile_command))

    app.add_handler(CommandHandler("calc", calc_command))
    app.add_handler(CommandHandler("calculate", calc_command))
    app.add_handler(CommandHandler("calculator", calc_command))

    app.add_handler(CommandHandler("pi", pi_command))
    app.add_handler(CommandHandler("e", e_command))
    app.add_handler(CommandHandler("mathhelp", mathhelp_command))