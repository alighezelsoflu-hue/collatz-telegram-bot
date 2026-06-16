from typing import List, Tuple, Dict, Any
from collections import Counter
import ast
import math
import operator
import cmath
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, ContextTypes
from utils import split_long_text, text_to_file
from config import MAX_INPUT
from utils import text_to_file

from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from telegram import InputFile

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


def parse_number_list(args: List[str]) -> List[float]:
    """
    Simple parser for plain numbers.

    Supports:
    /stats 4 7 9 10
    /stats 4,7,9,10
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

    # If every value appears only once, there is no mode.
    if highest_frequency == 1:
        return []

    # User-requested rule:
    # If all distinct values have exactly the same frequency,
    # this bot treats the data set as having no mode.
    #
    # Example:
    # 2, 4, 7 each appear 3 times
    # Mode: Mo = ∅
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

    # Trigonometry in radians
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,

    # Trigonometry in degrees
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

    # Number theory and combinatorics
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
            if abs(left) > 1000 and abs(right) > 20:
                raise ValueError("Power result would be too large.")

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


def split_top_level_commas(text: str) -> List[str]:
    """
    Splits by commas, but ignores commas inside parentheses.

    Example:
    4, pi, sin(pi / 2), log(100, 10)
    becomes:
    ["4", "pi", "sin(pi / 2)", "log(100, 10)"]
    """
    items = []
    current = []
    depth = 0

    for char in text:
        if char == "(":
            depth += 1
            current.append(char)

        elif char == ")":
            depth -= 1

            if depth < 0:
                raise ValueError("Unbalanced parentheses.")

            current.append(char)

        elif char == "," and depth == 0:
            item = "".join(current).strip()

            if item:
                items.append(item)

            current = []

        else:
            current.append(char)

    if depth != 0:
        raise ValueError("Unbalanced parentheses.")

    item = "".join(current).strip()

    if item:
        items.append(item)

    return items


def parse_math_number_list(args: List[str]) -> List[float]:
    """
    Parses numbers or math expressions for /stats.

    Supports:
    /stats 4 7 9 10
    /stats 4, 7, 9, 10
    /stats 4, pi, 4, sin(pi / 2), 7, 4, 2, 2, log(100, 10)
    """
    if not args:
        raise ValueError(
            "Please send numbers or expressions. Example:\n"
            "/stats 4, pi, sin(pi / 2), log(100, 10)"
        )

    raw_text = " ".join(args).strip()

    if not raw_text:
        raise ValueError("Please send numbers or expressions.")

    if "," in raw_text:
        parts = split_top_level_commas(raw_text)
    else:
        parts = raw_text.split()

    if not parts:
        raise ValueError("Please send numbers or expressions.")

    if len(parts) > MAX_STATS_COUNT:
        raise ValueError(f"Please send up to {MAX_STATS_COUNT:,} values.")

    numbers = []

    for part in parts:
        try:
            result = safe_calculate(part)

            if not isinstance(result, (int, float)):
                raise ValueError(f"Expression did not return a number: {part}")

            if isinstance(result, float) and (math.isnan(result) or math.isinf(result)):
                raise ValueError(f"Expression returned invalid number: {part}")

            numbers.append(float(result))

        except Exception as error:
            raise ValueError(f"Invalid value: {part}\nReason: {error}")

    return numbers


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
        "Statistics command with expressions:\n"
        "/stats 4, pi, 4, sin(pi / 2), 7, 4, 2, 2, log(100, 10)\n\n"
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
        numbers = parse_math_number_list(context.args)
        summary = build_statistics_short_summary(numbers)

        await update.message.reply_text(summary)

    except ValueError as error:
        await update.message.reply_text(
            f"{error}\n\n"
            "Examples:\n"
            "/stats 4 7 9 10 10\n"
            "/stats 4, 7, 9, 10, 10\n"
            "/stats 4, pi, sin(pi / 2), log(100, 10)"
        )


async def statsfile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        numbers = parse_math_number_list(context.args)
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
            "/statsfile 4, 7, 9, 10, 10\n"
            "/statsfile 4, pi, sin(pi / 2), log(100, 10)"
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

# ------------------------------------------------------------
# Polynomial roots
# ------------------------------------------------------------

def parse_polynomial_coefficients(args):
    """
    Parses coefficients from:
    /polyroots 1 -5 6
    /polyroots 1, -5, 6

    Coefficients must be from highest degree to constant term.
    Example:
    1 -5 6 means x^2 - 5x + 6
    """
    if not args:
        raise ValueError("Please provide polynomial coefficients.")

    text = " ".join(args).replace(",", " ")
    parts = [part.strip() for part in text.split() if part.strip()]

    if len(parts) < 2:
        raise ValueError("A polynomial needs at least 2 coefficients.")

    coefficients = []

    for part in parts:
        try:
            coefficients.append(float(part))
        except Exception:
            raise ValueError(f"Invalid coefficient: {part}")

    # Remove leading zero coefficients.
    while coefficients and abs(coefficients[0]) < 1e-12:
        coefficients.pop(0)

    if len(coefficients) < 2:
        raise ValueError("Leading coefficient cannot be zero.")

    return coefficients


def format_real_number(value: float, digits: int = 10) -> str:
    if abs(value) < 1e-10:
        value = 0.0

    if abs(value - round(value)) < 1e-10:
        return str(int(round(value)))

    return f"{value:.{digits}g}"


def format_complex_number(value: complex) -> str:
    real = value.real
    imag = value.imag

    if abs(real) < 1e-10:
        real = 0.0

    if abs(imag) < 1e-10:
        imag = 0.0

    if imag == 0:
        return format_real_number(real)

    if real == 0:
        return f"{format_real_number(imag)}i"

    sign = "+" if imag > 0 else "-"
    return f"{format_real_number(real)} {sign} {format_real_number(abs(imag))}i"


def polynomial_to_text(coefficients) -> str:
    degree = len(coefficients) - 1
    terms = []

    for index, coefficient in enumerate(coefficients):
        power = degree - index

        if abs(coefficient) < 1e-12:
            continue

        abs_coefficient = abs(coefficient)

        if power == 0:
            term = format_real_number(abs_coefficient)
        elif power == 1:
            if abs(abs_coefficient - 1) < 1e-12:
                term = "x"
            else:
                term = f"{format_real_number(abs_coefficient)}x"
        else:
            if abs(abs_coefficient - 1) < 1e-12:
                term = f"x^{power}"
            else:
                term = f"{format_real_number(abs_coefficient)}x^{power}"

        if not terms:
            if coefficient < 0:
                terms.append("-" + term)
            else:
                terms.append(term)
        else:
            if coefficient < 0:
                terms.append("- " + term)
            else:
                terms.append("+ " + term)

    if not terms:
        return "0"

    return " ".join(terms)


def evaluate_polynomial_complex(coefficients, x: complex) -> complex:
    result = 0j

    for coefficient in coefficients:
        result = result * x + coefficient

    return result


def solve_polynomial_roots(coefficients):
    """
    Degree 1 and 2 are solved directly.
    Degree 3+ uses Durand-Kerner numerical method.
    """
    degree = len(coefficients) - 1

    if degree < 1:
        raise ValueError("This is not a polynomial equation.")

    if degree == 1:
        a, b = coefficients
        return [complex(-b / a)]

    if degree == 2:
        a, b, c = coefficients
        discriminant = complex(b * b - 4 * a * c)
        sqrt_discriminant = cmath.sqrt(discriminant)

        root1 = (-b + sqrt_discriminant) / (2 * a)
        root2 = (-b - sqrt_discriminant) / (2 * a)

        return sorted([root1, root2], key=lambda z: (z.real, z.imag))

    # Normalize polynomial so leading coefficient is 1.
    leading = coefficients[0]
    normalized = [complex(coefficient / leading) for coefficient in coefficients]

    # Cauchy-style radius.
    radius = 1 + max(abs(coefficient) for coefficient in normalized[1:])

    roots = [
        radius * cmath.exp(2j * cmath.pi * index / degree)
        for index in range(degree)
    ]

    max_iterations = 2000
    tolerance = 1e-12

    for _ in range(max_iterations):
        new_roots = []

        for i, root in enumerate(roots):
            denominator = 1j * 0 + 1

            for j, other_root in enumerate(roots):
                if i == j:
                    continue

                difference = root - other_root

                if abs(difference) < 1e-14:
                    difference = complex(1e-14, 1e-14)

                denominator *= difference

            new_root = root - evaluate_polynomial_complex(normalized, root) / denominator
            new_roots.append(new_root)

        max_change = max(abs(new_roots[i] - roots[i]) for i in range(degree))
        roots = new_roots

        if max_change < tolerance:
            break

    return sorted(roots, key=lambda z: (z.real, z.imag))


def build_polynomial_roots_report(coefficients, roots) -> str:
    degree = len(coefficients) - 1
    polynomial_text = polynomial_to_text(coefficients)

    lines = [
        "Polynomial roots",
        "",
        f"Polynomial:",
        f"{polynomial_text} = 0",
        "",
        f"Degree: {degree}",
        "",
        "Roots:",
    ]

    for index, root in enumerate(roots, start=1):
        lines.append(f"x{index} = {format_complex_number(root)}")

    if degree >= 3:
        lines.extend(
            [
                "",
                "Note:",
                "Roots for degree 3 and higher are numerical approximations.",
            ]
        )

    return "\n".join(lines)


async def polyroots_command(update, context) -> None:
    if not update.message:
        return

    try:
        coefficients = parse_polynomial_coefficients(context.args)
        roots = solve_polynomial_roots(coefficients)
        report = build_polynomial_roots_report(coefficients, roots)

    except Exception as error:
        await update.message.reply_text(
            "Polynomial roots error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/polyroots 1 -5 6\n"
            "/polyroots 1 0 -4\n"
            "/polyroots 1 0 0 -1\n\n"
            "Coefficients must be from highest degree to constant term.\n"
            "Example: /polyroots 1 -5 6 means x² - 5x + 6 = 0"
        )
        return

    for chunk in split_long_text(report):
        await update.message.reply_text(chunk)


# ------------------------------------------------------------
# Prime numbers
# ------------------------------------------------------------

MAX_PRIME_LIMIT = 1_000_000


def parse_prime_limit(args) -> int:
    if not args:
        raise ValueError("Please provide a limit.")

    text = "".join(args).replace(",", "").replace("_", "").strip()

    if not text.isdigit():
        raise ValueError("Limit must be a positive integer.")

    limit = int(text)

    if limit < 2:
        raise ValueError("Limit must be at least 2.")

    if limit > MAX_PRIME_LIMIT:
        raise ValueError(f"Limit is too large. Maximum allowed is {MAX_PRIME_LIMIT}.")

    return limit


def primes_less_than(limit: int):
    if limit <= 2:
        return []

    sieve = bytearray(b"\x01") * limit
    sieve[0:2] = b"\x00\x00"

    max_check = int(limit ** 0.5) + 1

    for number in range(2, max_check):
        if sieve[number]:
            start = number * number
            step = number
            count = ((limit - 1 - start) // step) + 1
            sieve[start:limit:step] = b"\x00" * count

    return [number for number in range(limit) if sieve[number]]


def build_primes_report(limit: int, primes) -> str:
    lines = [
        f"Prime numbers less than {limit}",
        "",
        f"Count: {len(primes)}",
        "",
    ]

    if primes:
        lines.append(", ".join(str(prime) for prime in primes))
    else:
        lines.append("No prime numbers found.")

    return "\n".join(lines)


async def primes_command(update, context) -> None:
    if not update.message:
        return

    try:
        limit = parse_prime_limit(context.args)
        primes = primes_less_than(limit)
        report = build_primes_report(limit, primes)

    except Exception as error:
        await update.message.reply_text(
            "Prime numbers error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/primes 100\n"
            "/primes 1000\n"
            "/primesfile 100000"
        )
        return

    if len(report) <= 3500:
        await update.message.reply_text(report)
    else:
        await update.message.reply_document(
            document=text_to_file(report, f"primes_less_than_{limit}.txt"),
            caption=f"Prime numbers less than {limit}",
        )


async def primesfile_command(update, context) -> None:
    if not update.message:
        return

    try:
        limit = parse_prime_limit(context.args)
        primes = primes_less_than(limit)
        report = build_primes_report(limit, primes)

    except Exception as error:
        await update.message.reply_text(
            "Prime file error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/primesfile 10000"
        )
        return

    await update.message.reply_document(
        document=text_to_file(report, f"primes_less_than_{limit}.txt"),
        caption=f"Prime numbers less than {limit}",
    )



# ------------------------------------------------------------
# Polynomial plot
# ------------------------------------------------------------

def parse_polyplot_args(args):
    """
    Usage:
    /polyplot 1 -5 6
    /polyplot 1 -5 6 range -2 8

    Coefficients are from highest degree to constant term.
    """
    if not args:
        raise ValueError("Please provide polynomial coefficients.")

    lowered = [arg.lower() for arg in args]

    xmin = None
    xmax = None

    if "range" in lowered:
        range_index = lowered.index("range")
        coefficient_args = args[:range_index]
        range_args = args[range_index + 1:]

        if len(range_args) != 2:
            raise ValueError("Range must be: range xmin xmax")

        xmin = float(range_args[0])
        xmax = float(range_args[1])

    else:
        coefficient_args = args

    coefficients = parse_polynomial_coefficients(coefficient_args)

    if xmin is None or xmax is None:
        degree = len(coefficients) - 1

        if degree <= 2:
            xmin, xmax = -10.0, 10.0
        else:
            xmin, xmax = -5.0, 5.0

    if xmin >= xmax:
        raise ValueError("xmin must be smaller than xmax.")

    if xmax - xmin > 1_000_000:
        raise ValueError("Range is too large.")

    return coefficients, xmin, xmax


def evaluate_polynomial_real(coefficients, x: float) -> float:
    result = 0.0

    for coefficient in coefficients:
        result = result * x + coefficient

    return result


def load_plot_font(size: int = 22):
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


def nice_number(value: float) -> str:
    if abs(value) < 1e-10:
        value = 0.0

    if abs(value - round(value)) < 1e-10:
        return str(int(round(value)))

    return f"{value:.4g}"


def create_polynomial_plot_image(coefficients, xmin: float, xmax: float) -> BytesIO:
    width = 1400
    height = 900

    margin_left = 110
    margin_right = 50
    margin_top = 90
    margin_bottom = 110

    plot_left = margin_left
    plot_right = width - margin_right
    plot_top = margin_top
    plot_bottom = height - margin_bottom

    plot_width = plot_right - plot_left
    plot_height = plot_bottom - plot_top

    samples = 700
    points = []

    for i in range(samples + 1):
        x = xmin + (xmax - xmin) * i / samples
        y = evaluate_polynomial_real(coefficients, x)

        if abs(y) > 1e100:
            continue

        points.append((x, y))

    if not points:
        raise ValueError("Could not evaluate polynomial in this range.")

    y_values = [y for _, y in points]
    sorted_y = sorted(y_values)

    # Robust y-range: ignore extreme spikes so graph stays readable.
    low_index = max(0, int(len(sorted_y) * 0.02))
    high_index = min(len(sorted_y) - 1, int(len(sorted_y) * 0.98))

    ymin = sorted_y[low_index]
    ymax = sorted_y[high_index]

    # Include x-axis if possible.
    ymin = min(ymin, 0)
    ymax = max(ymax, 0)

    if abs(ymax - ymin) < 1e-12:
        ymin -= 1
        ymax += 1

    y_padding = (ymax - ymin) * 0.10
    ymin -= y_padding
    ymax += y_padding

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = load_plot_font(34)
    label_font = load_plot_font(22)
    small_font = load_plot_font(18)

    polynomial_text = polynomial_to_text(coefficients)

    draw.text(
        (margin_left, 30),
        f"Polynomial plot: {polynomial_text}",
        fill="black",
        font=title_font,
    )

    def map_x(x: float) -> int:
        return int(plot_left + (x - xmin) / (xmax - xmin) * plot_width)

    def map_y(y: float) -> int:
        return int(plot_bottom - (y - ymin) / (ymax - ymin) * plot_height)

    # Background
    draw.rectangle(
        (plot_left, plot_top, plot_right, plot_bottom),
        outline="#222222",
        width=2,
        fill="#fbfbfb",
    )

    # Grid
    grid_lines = 10

    for i in range(grid_lines + 1):
        gx = plot_left + i * plot_width / grid_lines
        gy = plot_top + i * plot_height / grid_lines

        draw.line((gx, plot_top, gx, plot_bottom), fill="#dddddd", width=1)
        draw.line((plot_left, gy, plot_right, gy), fill="#dddddd", width=1)

    # Axes
    if xmin <= 0 <= xmax:
        x0 = map_x(0)
        draw.line((x0, plot_top, x0, plot_bottom), fill="#333333", width=3)

    if ymin <= 0 <= ymax:
        y0 = map_y(0)
        draw.line((plot_left, y0, plot_right, y0), fill="#333333", width=3)

    # Axis labels
    for i in range(grid_lines + 1):
        x_value = xmin + i * (xmax - xmin) / grid_lines
        x_pixel = plot_left + i * plot_width / grid_lines

        draw.text(
            (x_pixel - 25, plot_bottom + 18),
            nice_number(x_value),
            fill="#333333",
            font=small_font,
        )

        y_value = ymax - i * (ymax - ymin) / grid_lines
        y_pixel = plot_top + i * plot_height / grid_lines

        draw.text(
            (15, y_pixel - 10),
            nice_number(y_value),
            fill="#333333",
            font=small_font,
        )

    # Function curve
    pixel_points = []

    for x, y in points:
        if y < ymin or y > ymax:
            pixel_points.append(None)
            continue

        pixel_points.append((map_x(x), map_y(y)))

    current_segment = []

    for point in pixel_points:
        if point is None:
            if len(current_segment) >= 2:
                draw.line(current_segment, fill="#1f77b4", width=4)
            current_segment = []
        else:
            current_segment.append(point)

    if len(current_segment) >= 2:
        draw.line(current_segment, fill="#1f77b4", width=4)

    # Real roots
    try:
        roots = solve_polynomial_roots(coefficients)
        real_roots = [
            root.real
            for root in roots
            if abs(root.imag) < 1e-7 and xmin <= root.real <= xmax
        ]

        for root in real_roots:
            rx = map_x(root)
            ry = map_y(0)
            draw.ellipse((rx - 8, ry - 8, rx + 8, ry + 8), fill="#d62728")
            draw.text(
                (rx + 10, ry - 28),
                f"x={nice_number(root)}",
                fill="#d62728",
                font=small_font,
            )

    except Exception:
        pass

    draw.text(
        (margin_left, height - 55),
        f"x range: [{nice_number(xmin)}, {nice_number(xmax)}] | y range: [{nice_number(ymin)}, {nice_number(ymax)}]",
        fill="#555555",
        font=label_font,
    )

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = "polynomial_plot.png"

    return output


async def polyplot_command(update, context) -> None:
    if not update.message:
        return

    try:
        coefficients, xmin, xmax = parse_polyplot_args(context.args)
        polynomial_text = polynomial_to_text(coefficients)
        image = create_polynomial_plot_image(coefficients, xmin, xmax)

    except Exception as error:
        await update.message.reply_text(
            "Polynomial plot error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/polyplot 1 -5 6\n"
            "/polyplot 1 0 -4\n"
            "/polyplot 1 0 0 -1\n"
            "/polyplot 1 -5 6 range -2 8\n\n"
            "Coefficients must be from highest degree to constant term.\n"
            "Example: /polyplot 1 -5 6 means x² - 5x + 6"
        )
        return

    await update.message.reply_photo(
        photo=InputFile(image, filename="polynomial_plot.png"),
        caption=f"Plot of {polynomial_text}",
    )    

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

    app.add_handler(CommandHandler("polyroots", polyroots_command))
    app.add_handler(CommandHandler("roots", polyroots_command))

    app.add_handler(CommandHandler("primes", primes_command))
    app.add_handler(CommandHandler("primesfile", primesfile_command))
    app.add_handler(CommandHandler("polyplot", polyplot_command))
    app.add_handler(CommandHandler("plotpoly", polyplot_command))