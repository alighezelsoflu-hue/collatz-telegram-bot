import math
import re
from collections import defaultdict
from fractions import Fraction
from io import BytesIO
from typing import Dict, List, Tuple, Optional

from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, ContextTypes


# ------------------------------------------------------------
# Limits for Render Free safety
# ------------------------------------------------------------

MAX_FORMULA_LENGTH = 120
MAX_COMPOUNDS = 20
MAX_ELEMENTS_IN_EQUATION = 35
MAX_GAS_POINTS = 500


# ------------------------------------------------------------
# Optional AI explanation integration
# ------------------------------------------------------------

CHEMISTRY_AI_TRIGGER_WORDS = {"ai", "explain", "explanation", "interpret", "tutor"}


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


def split_chemistry_ai_request(args: List[str]) -> Tuple[List[str], bool, str]:
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
        if normalized in CHEMISTRY_AI_TRIGGER_WORDS or normalized in {"teach", "lesson"}:
            wants_ai = True
            if normalized in {"tutor", "teach", "lesson"} and index + 1 < len(args):
                selected_language = language_from_token(args[index + 1])
                if selected_language:
                    language = selected_language
                    skip_next = True
            continue

        cleaned.append(arg)

    return cleaned, wants_ai, language


async def send_chemistry_ai_explanation(
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
            "You are AhBashin Bot's dedicated Chemistry AI Tutor. Teach chemistry like a patient, "
            "expert human tutor. Build conceptual understanding before calculations. For problems, identify "
            "knowns/unknowns, write the relevant formula or balanced equation, show units, mole ratios, and steps. "
            "Explain common mistakes such as wrong units, unbalanced equations, or confusing moles and grams. "
            "Be safety-aware: for hazardous chemicals, reactions, drugs, explosives, or dangerous procedures, give "
            "high-level educational safety guidance only and do not provide operational instructions. If the chemistry "
            "module provides a deterministic result, treat it as the source of truth and explain it."
        )
        final_instruction = (
            "Tutor the user on this chemistry topic/problem. Structure the answer as:\n"
            "1) Big concept\n2) Given/unknown or formula setup\n3) Step-by-step explanation\n"
            "4) Common mistake or safety note\n5) Quick practice question."
        )
        title = "AI chemistry tutor 🧑‍🏫🧪\n\n"
        temperature = 0.35
    else:
        system_prompt = (
            "You are AhBashin Bot's chemistry tutor. Explain chemistry calculator results clearly, briefly, "
            "and accurately for a student. The deterministic chemistry module already performed the "
            "calculation, so do not override or contradict it. Explain formulas, units, assumptions, "
            "and safety/limitations when relevant. Keep the answer concise."
        )
        final_instruction = (
            "Explain what this chemistry result means, which formula or concept is involved, "
            "and how the user should interpret it. For plots, explain the axes and relationship shown."
        )
        title = "AI chemistry explanation 🧠🧪\n\n"
        temperature = 0.25

    system_prompt += f"\n\nRespond in {language}."

    prompt_parts = [
        f"Chemistry command: /{command_name}",
        f"User input: {user_input or '(no input)'}",
    ]

    if deterministic_context:
        prompt_parts.append(f"Result/context from the chemistry module:\n{deterministic_context}")

    prompt_parts.append(final_instruction)

    try:
        explanation = await call_ai(system_prompt, "\n\n".join(prompt_parts), temperature=temperature)
    except Exception as error:
        label = "tutor" if is_tutor else "explanation"
        await update.message.reply_text(f"AI chemistry {label} error.\n\nError: {error}")
        return

    text = title + explanation
    for chunk in split_long_text(text, limit=3500):
        await update.message.reply_text(chunk)


def detect_chemistry_ai_mode(args: List[str]) -> str:
    for arg in args:
        normalized = arg.strip().lower().strip(".,!?:;()[]{}")
        if normalized in {"tutor", "teach", "lesson"}:
            return "tutor"
    return "explain"
def chemistry_ai_wrapper(command_name: str, handler):
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        original_args = list(getattr(context, "args", []) or [])
        cleaned_args, wants_ai, ai_language = split_chemistry_ai_request(original_args)
        ai_mode = detect_chemistry_ai_mode(original_args)
        context.args = cleaned_args

        try:
            await handler(update, context)
        finally:
            context.args = original_args

        if wants_ai:
            await send_chemistry_ai_explanation(
                update,
                command_name=command_name,
                user_input=" ".join(cleaned_args),
                mode=ai_mode,
                language=ai_language,
            )

    return wrapped
async def chemistry_ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain a chemistry request/result using AI.

    Usage:
    /chem_ai explain molarity
    or reply to a chemistry result/plot caption with /chem_ai
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
            "Chemistry AI usage:\n\n"
            "Add ai/explain to a chemistry command:\n"
            "/molar_mass Ca(OH)2 explain\n"
            "/balance C3H8 + O2 -> CO2 + H2O ai\n\n"
            "Or reply to a chemistry result with:\n"
            "/chem_ai"
        )
        return

    await send_chemistry_ai_explanation(
        update,
        command_name="chem_ai",
        user_input=text,
        deterministic_context=text,
    )



async def chemistry_tutor_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dedicated chemistry tutor mode.

    Usage:
    /chem_tutor explain stoichiometry
    /chem_tutor teach me pH
    or reply to a chemistry result/problem with /chem_tutor
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
            "Chemistry tutor usage:\n\nDefault language is English. Add fa, de, it, fr, es, or ar after the tutor command.\n\nLanguage examples:\n/chem_tutor fa explain stoichiometry\n/chem_tutor de teach me molarity\n/chem_tutor it why do we balance equations?\n\n"
            "/chem_tutor explain stoichiometry\n"
            "/chem_tutor teach me molarity\n"
            "/chem_tutor why do we balance equations?\n\n"
            "Or reply to a chemistry result/problem with /chem_tutor"
        )
        return

    await send_chemistry_ai_explanation(
        update,
        command_name="chem_tutor",
        user_input=text,
        deterministic_context=text,
        mode="tutor",
        language=tutor_language,
    )


# ------------------------------------------------------------
# Periodic table data
# atomic number, symbol, name, atomic mass, group, period, category
# Atomic masses are standard approximate values, enough for calculator use.
# ------------------------------------------------------------

ELEMENTS = [
    (1, "H", "Hydrogen", 1.008, 1, 1, "nonmetal"),
    (2, "He", "Helium", 4.0026, 18, 1, "noble gas"),
    (3, "Li", "Lithium", 6.94, 1, 2, "alkali metal"),
    (4, "Be", "Beryllium", 9.0122, 2, 2, "alkaline earth metal"),
    (5, "B", "Boron", 10.81, 13, 2, "metalloid"),
    (6, "C", "Carbon", 12.011, 14, 2, "nonmetal"),
    (7, "N", "Nitrogen", 14.007, 15, 2, "nonmetal"),
    (8, "O", "Oxygen", 15.999, 16, 2, "nonmetal"),
    (9, "F", "Fluorine", 18.998, 17, 2, "halogen"),
    (10, "Ne", "Neon", 20.180, 18, 2, "noble gas"),
    (11, "Na", "Sodium", 22.990, 1, 3, "alkali metal"),
    (12, "Mg", "Magnesium", 24.305, 2, 3, "alkaline earth metal"),
    (13, "Al", "Aluminium", 26.982, 13, 3, "post-transition metal"),
    (14, "Si", "Silicon", 28.085, 14, 3, "metalloid"),
    (15, "P", "Phosphorus", 30.974, 15, 3, "nonmetal"),
    (16, "S", "Sulfur", 32.06, 16, 3, "nonmetal"),
    (17, "Cl", "Chlorine", 35.45, 17, 3, "halogen"),
    (18, "Ar", "Argon", 39.948, 18, 3, "noble gas"),
    (19, "K", "Potassium", 39.098, 1, 4, "alkali metal"),
    (20, "Ca", "Calcium", 40.078, 2, 4, "alkaline earth metal"),
    (21, "Sc", "Scandium", 44.956, 3, 4, "transition metal"),
    (22, "Ti", "Titanium", 47.867, 4, 4, "transition metal"),
    (23, "V", "Vanadium", 50.942, 5, 4, "transition metal"),
    (24, "Cr", "Chromium", 51.996, 6, 4, "transition metal"),
    (25, "Mn", "Manganese", 54.938, 7, 4, "transition metal"),
    (26, "Fe", "Iron", 55.845, 8, 4, "transition metal"),
    (27, "Co", "Cobalt", 58.933, 9, 4, "transition metal"),
    (28, "Ni", "Nickel", 58.693, 10, 4, "transition metal"),
    (29, "Cu", "Copper", 63.546, 11, 4, "transition metal"),
    (30, "Zn", "Zinc", 65.38, 12, 4, "transition metal"),
    (31, "Ga", "Gallium", 69.723, 13, 4, "post-transition metal"),
    (32, "Ge", "Germanium", 72.630, 14, 4, "metalloid"),
    (33, "As", "Arsenic", 74.922, 15, 4, "metalloid"),
    (34, "Se", "Selenium", 78.971, 16, 4, "nonmetal"),
    (35, "Br", "Bromine", 79.904, 17, 4, "halogen"),
    (36, "Kr", "Krypton", 83.798, 18, 4, "noble gas"),
    (37, "Rb", "Rubidium", 85.468, 1, 5, "alkali metal"),
    (38, "Sr", "Strontium", 87.62, 2, 5, "alkaline earth metal"),
    (39, "Y", "Yttrium", 88.906, 3, 5, "transition metal"),
    (40, "Zr", "Zirconium", 91.224, 4, 5, "transition metal"),
    (41, "Nb", "Niobium", 92.906, 5, 5, "transition metal"),
    (42, "Mo", "Molybdenum", 95.95, 6, 5, "transition metal"),
    (43, "Tc", "Technetium", 98.0, 7, 5, "transition metal"),
    (44, "Ru", "Ruthenium", 101.07, 8, 5, "transition metal"),
    (45, "Rh", "Rhodium", 102.91, 9, 5, "transition metal"),
    (46, "Pd", "Palladium", 106.42, 10, 5, "transition metal"),
    (47, "Ag", "Silver", 107.87, 11, 5, "transition metal"),
    (48, "Cd", "Cadmium", 112.41, 12, 5, "transition metal"),
    (49, "In", "Indium", 114.82, 13, 5, "post-transition metal"),
    (50, "Sn", "Tin", 118.71, 14, 5, "post-transition metal"),
    (51, "Sb", "Antimony", 121.76, 15, 5, "metalloid"),
    (52, "Te", "Tellurium", 127.60, 16, 5, "metalloid"),
    (53, "I", "Iodine", 126.90, 17, 5, "halogen"),
    (54, "Xe", "Xenon", 131.29, 18, 5, "noble gas"),
    (55, "Cs", "Caesium", 132.91, 1, 6, "alkali metal"),
    (56, "Ba", "Barium", 137.33, 2, 6, "alkaline earth metal"),
    (57, "La", "Lanthanum", 138.91, 3, 6, "lanthanide"),
    (58, "Ce", "Cerium", 140.12, None, 6, "lanthanide"),
    (59, "Pr", "Praseodymium", 140.91, None, 6, "lanthanide"),
    (60, "Nd", "Neodymium", 144.24, None, 6, "lanthanide"),
    (61, "Pm", "Promethium", 145.0, None, 6, "lanthanide"),
    (62, "Sm", "Samarium", 150.36, None, 6, "lanthanide"),
    (63, "Eu", "Europium", 151.96, None, 6, "lanthanide"),
    (64, "Gd", "Gadolinium", 157.25, None, 6, "lanthanide"),
    (65, "Tb", "Terbium", 158.93, None, 6, "lanthanide"),
    (66, "Dy", "Dysprosium", 162.50, None, 6, "lanthanide"),
    (67, "Ho", "Holmium", 164.93, None, 6, "lanthanide"),
    (68, "Er", "Erbium", 167.26, None, 6, "lanthanide"),
    (69, "Tm", "Thulium", 168.93, None, 6, "lanthanide"),
    (70, "Yb", "Ytterbium", 173.05, None, 6, "lanthanide"),
    (71, "Lu", "Lutetium", 174.97, 3, 6, "lanthanide"),
    (72, "Hf", "Hafnium", 178.49, 4, 6, "transition metal"),
    (73, "Ta", "Tantalum", 180.95, 5, 6, "transition metal"),
    (74, "W", "Tungsten", 183.84, 6, 6, "transition metal"),
    (75, "Re", "Rhenium", 186.21, 7, 6, "transition metal"),
    (76, "Os", "Osmium", 190.23, 8, 6, "transition metal"),
    (77, "Ir", "Iridium", 192.22, 9, 6, "transition metal"),
    (78, "Pt", "Platinum", 195.08, 10, 6, "transition metal"),
    (79, "Au", "Gold", 196.97, 11, 6, "transition metal"),
    (80, "Hg", "Mercury", 200.59, 12, 6, "transition metal"),
    (81, "Tl", "Thallium", 204.38, 13, 6, "post-transition metal"),
    (82, "Pb", "Lead", 207.2, 14, 6, "post-transition metal"),
    (83, "Bi", "Bismuth", 208.98, 15, 6, "post-transition metal"),
    (84, "Po", "Polonium", 209.0, 16, 6, "post-transition metal"),
    (85, "At", "Astatine", 210.0, 17, 6, "halogen"),
    (86, "Rn", "Radon", 222.0, 18, 6, "noble gas"),
    (87, "Fr", "Francium", 223.0, 1, 7, "alkali metal"),
    (88, "Ra", "Radium", 226.0, 2, 7, "alkaline earth metal"),
    (89, "Ac", "Actinium", 227.0, 3, 7, "actinide"),
    (90, "Th", "Thorium", 232.04, None, 7, "actinide"),
    (91, "Pa", "Protactinium", 231.04, None, 7, "actinide"),
    (92, "U", "Uranium", 238.03, None, 7, "actinide"),
    (93, "Np", "Neptunium", 237.0, None, 7, "actinide"),
    (94, "Pu", "Plutonium", 244.0, None, 7, "actinide"),
    (95, "Am", "Americium", 243.0, None, 7, "actinide"),
    (96, "Cm", "Curium", 247.0, None, 7, "actinide"),
    (97, "Bk", "Berkelium", 247.0, None, 7, "actinide"),
    (98, "Cf", "Californium", 251.0, None, 7, "actinide"),
    (99, "Es", "Einsteinium", 252.0, None, 7, "actinide"),
    (100, "Fm", "Fermium", 257.0, None, 7, "actinide"),
    (101, "Md", "Mendelevium", 258.0, None, 7, "actinide"),
    (102, "No", "Nobelium", 259.0, None, 7, "actinide"),
    (103, "Lr", "Lawrencium", 266.0, 3, 7, "actinide"),
    (104, "Rf", "Rutherfordium", 267.0, 4, 7, "transition metal"),
    (105, "Db", "Dubnium", 268.0, 5, 7, "transition metal"),
    (106, "Sg", "Seaborgium", 269.0, 6, 7, "transition metal"),
    (107, "Bh", "Bohrium", 270.0, 7, 7, "transition metal"),
    (108, "Hs", "Hassium", 269.0, 8, 7, "transition metal"),
    (109, "Mt", "Meitnerium", 278.0, 9, 7, "unknown"),
    (110, "Ds", "Darmstadtium", 281.0, 10, 7, "unknown"),
    (111, "Rg", "Roentgenium", 282.0, 11, 7, "unknown"),
    (112, "Cn", "Copernicium", 285.0, 12, 7, "transition metal"),
    (113, "Nh", "Nihonium", 286.0, 13, 7, "unknown"),
    (114, "Fl", "Flerovium", 289.0, 14, 7, "post-transition metal"),
    (115, "Mc", "Moscovium", 290.0, 15, 7, "unknown"),
    (116, "Lv", "Livermorium", 293.0, 16, 7, "unknown"),
    (117, "Ts", "Tennessine", 294.0, 17, 7, "halogen"),
    (118, "Og", "Oganesson", 294.0, 18, 7, "noble gas"),
]

ELEMENT_BY_SYMBOL = {item[1]: item for item in ELEMENTS}
ELEMENT_BY_NAME = {item[2].lower(): item for item in ELEMENTS}
ELEMENT_BY_NUMBER = {str(item[0]): item for item in ELEMENTS}
ATOMIC_MASS = {item[1]: item[3] for item in ELEMENTS}


# ------------------------------------------------------------
# Help text
# ------------------------------------------------------------

def chemistry_help_text() -> str:
    return (
        "Chemistry tools 🧪\n\n"
        "/element O - element lookup by symbol\n"
        "/element oxygen - element lookup by name\n"
        "/element 8 - element lookup by atomic number\n"
        "/molar_mass H2O - molar mass of formula\n"
        "/molar_mass Ca(OH)2 - supports parentheses\n"
        "/balance H2 + O2 -> H2O - balance equation\n"
        "/balance C3H8 + O2 -> CO2 + H2O - combustion example\n"
        "/idealgas P=1 V=22.4 n=1 - solve missing T with PV=nRT\n"
        "/molarity moles=0.5 volume=2 - molarity M=n/V\n"
        "/molarity mass=58.44 formula=NaCl volume=1 - molarity from mass\n"
        "/dilution M1=2 V1=0.5 M2=1 - solve dilution variable\n"
        "/ph H=1e-7 - pH from H+ concentration\n"
        "/ph OH=1e-3 - pH from OH- concentration\n"
        "/gasplot P V n=1 T=300 - ideal gas P vs V plot\n\n"
        "AI explanation:\n"
        "Add ai/explain to any chemistry command, example:\n"
        "/molar_mass Ca(OH)2 explain\n"
        "/chem_ai - explain a replied chemistry result\n\n"
        "Units used by default:\n"
        "P = atm, V = L, n = mol, T = K, R = 0.082057 L·atm/(mol·K)\n\n"
        "Tip: keep formulas compact, example: C6H12O6, Fe2(SO4)3, Ca(OH)2"
    )


# ------------------------------------------------------------
# General helpers
# ------------------------------------------------------------

def fmt(value: float, digits: int = 6) -> str:
    if isinstance(value, int):
        return str(value)
    if abs(value) < 1e-12:
        value = 0.0
    if abs(value - round(value)) < 1e-12:
        return str(int(round(value)))
    return f"{value:.{digits}g}"


def parse_key_values(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key, value in re.findall(r"([A-Za-z][A-Za-z0-9_]*)\s*=\s*([^\s]+)", text):
        result[key.lower()] = value.strip()
    return result


def get_float(params: Dict[str, str], *names: str) -> Optional[float]:
    for name in names:
        if name.lower() in params:
            return float(params[name.lower()])
    return None


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


# ------------------------------------------------------------
# Formula parsing and molar mass
# ------------------------------------------------------------

def normalize_formula(formula: str) -> str:
    formula = formula.strip()
    formula = formula.replace("[", "(").replace("]", ")")
    formula = formula.replace("{", "(").replace("}", ")")
    return formula


def parse_number_at(text: str, index: int) -> Tuple[int, int]:
    start = index
    while index < len(text) and text[index].isdigit():
        index += 1
    if start == index:
        return 1, index
    return int(text[start:index]), index


def merge_counts(base: Dict[str, int], extra: Dict[str, int], multiplier: int = 1) -> None:
    for symbol, count in extra.items():
        base[symbol] += count * multiplier


def parse_formula_segment(formula: str) -> Dict[str, int]:
    formula = normalize_formula(formula)
    if not formula or len(formula) > MAX_FORMULA_LENGTH:
        raise ValueError("Formula is empty or too long.")

    index = 0

    def parse_group(stop_char: Optional[str] = None) -> Dict[str, int]:
        nonlocal index
        counts: Dict[str, int] = defaultdict(int)

        while index < len(formula):
            char = formula[index]

            if stop_char and char == stop_char:
                index += 1
                return counts

            if char == "(":
                index += 1
                inner_counts = parse_group(")")
                multiplier, index = parse_number_at(formula, index)
                merge_counts(counts, inner_counts, multiplier)
                continue

            if char == ")":
                raise ValueError("Unmatched closing parenthesis.")

            if char.isupper():
                symbol = char
                index += 1
                if index < len(formula) and formula[index].islower():
                    symbol += formula[index]
                    index += 1

                if symbol not in ATOMIC_MASS:
                    raise ValueError(f"Unknown element symbol: {symbol}")

                multiplier, index = parse_number_at(formula, index)
                counts[symbol] += multiplier
                continue

            raise ValueError(f"Invalid formula character: {char}")

        if stop_char:
            raise ValueError("Unmatched opening parenthesis.")

        return counts

    return dict(parse_group())


def split_hydrate_formula(formula: str) -> List[str]:
    # Supports CuSO4·5H2O and simple dot notation CuSO4.5H2O.
    formula = formula.replace("·", ".")
    return [part.strip() for part in formula.split(".") if part.strip()]


def parse_formula(formula: str) -> Dict[str, int]:
    total: Dict[str, int] = defaultdict(int)

    for part in split_hydrate_formula(formula):
        match = re.match(r"^(\d+)([A-Z].*)$", part)
        if match:
            multiplier = int(match.group(1))
            part_formula = match.group(2)
        else:
            multiplier = 1
            part_formula = part

        counts = parse_formula_segment(part_formula)
        merge_counts(total, counts, multiplier)

    return dict(total)


def molar_mass_from_counts(counts: Dict[str, int]) -> Tuple[float, List[str]]:
    total = 0.0
    lines: List[str] = []

    for symbol in sorted(counts.keys()):
        count = counts[symbol]
        mass = ATOMIC_MASS[symbol]
        subtotal = count * mass
        total += subtotal
        lines.append(f"{symbol}: {count} × {fmt(mass)} = {fmt(subtotal)} g/mol")

    return total, lines


# ------------------------------------------------------------
# Equation balancing
# ------------------------------------------------------------

def parse_compound_with_coefficient(text: str) -> Tuple[int, str]:
    text = text.strip()
    match = re.match(r"^(\d+)\s*([A-Za-z(\[].*)$", text)
    if match:
        return int(match.group(1)), match.group(2).strip()
    return 1, text


def split_equation(equation: str) -> Tuple[List[str], List[str]]:
    equation = equation.replace("=>", "->").replace("=", "->")
    if "->" not in equation:
        raise ValueError("Equation must contain ->")

    left_text, right_text = equation.split("->", 1)
    left = [part.strip() for part in left_text.split("+") if part.strip()]
    right = [part.strip() for part in right_text.split("+") if part.strip()]

    if not left or not right:
        raise ValueError("Equation must have reactants and products.")

    compounds = left + right
    if len(compounds) > MAX_COMPOUNDS:
        raise ValueError(f"Too many compounds. Maximum is {MAX_COMPOUNDS}.")

    return left, right


def rref(matrix: List[List[Fraction]]) -> Tuple[List[List[Fraction]], List[int]]:
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    pivot_cols: List[int] = []
    r = 0

    for c in range(cols):
        pivot = None
        for i in range(r, rows):
            if matrix[i][c] != 0:
                pivot = i
                break

        if pivot is None:
            continue

        matrix[r], matrix[pivot] = matrix[pivot], matrix[r]
        pivot_value = matrix[r][c]
        matrix[r] = [value / pivot_value for value in matrix[r]]

        for i in range(rows):
            if i != r and matrix[i][c] != 0:
                factor = matrix[i][c]
                matrix[i] = [matrix[i][j] - factor * matrix[r][j] for j in range(cols)]

        pivot_cols.append(c)
        r += 1
        if r == rows:
            break

    return matrix, pivot_cols


def lcm(a: int, b: int) -> int:
    return abs(a * b) // math.gcd(a, b) if a and b else abs(a or b)


def balance_equation(equation: str) -> Tuple[List[int], List[str], List[str]]:
    left, right = split_equation(equation)

    # Remove existing leading coefficients while parsing.
    left_formulas = [parse_compound_with_coefficient(item)[1] for item in left]
    right_formulas = [parse_compound_with_coefficient(item)[1] for item in right]
    compounds = left_formulas + right_formulas

    compound_counts = [parse_formula(compound) for compound in compounds]
    elements = sorted({symbol for counts in compound_counts for symbol in counts})

    if len(elements) > MAX_ELEMENTS_IN_EQUATION:
        raise ValueError(f"Too many different elements. Maximum is {MAX_ELEMENTS_IN_EQUATION}.")

    matrix: List[List[Fraction]] = []
    for element in elements:
        row: List[Fraction] = []
        for i, counts in enumerate(compound_counts):
            sign = 1 if i < len(left_formulas) else -1
            row.append(Fraction(sign * counts.get(element, 0)))
        matrix.append(row)

    matrix, pivot_cols = rref(matrix)
    cols = len(compounds)
    free_cols = [col for col in range(cols) if col not in pivot_cols]
    if not free_cols:
        raise ValueError("Could not find a balancing solution.")

    solution = [Fraction(0) for _ in range(cols)]
    solution[free_cols[-1]] = Fraction(1)

    for row_index, pivot_col in enumerate(pivot_cols):
        value = Fraction(0)
        for free_col in free_cols:
            value -= matrix[row_index][free_col] * solution[free_col]
        solution[pivot_col] = value

    denominator_lcm = 1
    for value in solution:
        denominator_lcm = lcm(denominator_lcm, value.denominator)

    coefficients = [int(value * denominator_lcm) for value in solution]

    if all(value <= 0 for value in coefficients):
        coefficients = [-value for value in coefficients]
    elif any(value < 0 for value in coefficients):
        # Try flipping. If still mixed, equation likely parsed into an unusual null vector.
        flipped = [-value for value in coefficients]
        if all(value >= 0 for value in flipped):
            coefficients = flipped

    gcd_value = 0
    for value in coefficients:
        gcd_value = math.gcd(gcd_value, abs(value))
    if gcd_value > 1:
        coefficients = [value // gcd_value for value in coefficients]

    if any(value <= 0 for value in coefficients):
        raise ValueError("Could not create positive integer coefficients.")

    return coefficients, left_formulas, right_formulas


def format_balanced_equation(coefficients: List[int], left: List[str], right: List[str]) -> str:
    formulas = left + right

    def item(coef: int, formula: str) -> str:
        return formula if coef == 1 else f"{coef} {formula}"

    left_items = [item(coefficients[i], left[i]) for i in range(len(left))]
    offset = len(left)
    right_items = [item(coefficients[offset + i], right[i]) for i in range(len(right))]
    return " + ".join(left_items) + " -> " + " + ".join(right_items)


# ------------------------------------------------------------
# Plot helpers
# ------------------------------------------------------------

def create_xy_plot(
    title: str,
    x_label: str,
    y_label: str,
    points: List[Tuple[float, float]],
    filename: str = "chemistry_plot.png",
) -> BytesIO:
    width, height = 1200, 760
    left, right, top, bottom = 105, 45, 85, 95
    plot_left, plot_right = left, width - right
    plot_top, plot_bottom = top, height - bottom
    plot_width = plot_right - plot_left
    plot_height = plot_bottom - plot_top

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    if abs(xmax - xmin) < 1e-12:
        xmin -= 1
        xmax += 1
    if abs(ymax - ymin) < 1e-12:
        ymin -= 1
        ymax += 1

    xpad = (xmax - xmin) * 0.05
    ypad = (ymax - ymin) * 0.10
    xmin -= xpad
    xmax += xpad
    ymin -= ypad
    ymax += ypad

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(34)
    label_font = load_font(21)
    small_font = load_font(17)

    draw.text((left, 25), title, fill="black", font=title_font)
    draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), outline="#222222", width=2, fill="#fbfbfb")

    def map_x(x: float) -> int:
        return int(plot_left + (x - xmin) / (xmax - xmin) * plot_width)

    def map_y(y: float) -> int:
        return int(plot_bottom - (y - ymin) / (ymax - ymin) * plot_height)

    grid = 10
    for i in range(grid + 1):
        gx = plot_left + i * plot_width / grid
        gy = plot_top + i * plot_height / grid
        draw.line((gx, plot_top, gx, plot_bottom), fill="#dddddd", width=1)
        draw.line((plot_left, gy, plot_right, gy), fill="#dddddd", width=1)

        x_val = xmin + i * (xmax - xmin) / grid
        y_val = ymax - i * (ymax - ymin) / grid
        draw.text((gx - 24, plot_bottom + 15), fmt(x_val, 4), fill="#333333", font=small_font)
        draw.text((15, gy - 10), fmt(y_val, 4), fill="#333333", font=small_font)

    pixel_points = [(map_x(x), map_y(y)) for x, y in points]
    if len(pixel_points) >= 2:
        draw.line(pixel_points, fill="#1f77b4", width=4)

    draw.text((plot_left + plot_width // 2 - 30, height - 50), x_label, fill="black", font=label_font)
    draw.text((20, top - 35), y_label, fill="black", font=label_font)

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = filename
    return output


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

async def chemhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(chemistry_help_text())


async def element_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/element oxygen\n/element O\n/element 8")
        return

    query = " ".join(context.args).strip()
    item = None

    if query in ELEMENT_BY_SYMBOL:
        item = ELEMENT_BY_SYMBOL[query]
    elif query.capitalize() in ELEMENT_BY_SYMBOL:
        item = ELEMENT_BY_SYMBOL[query.capitalize()]
    elif query.lower() in ELEMENT_BY_NAME:
        item = ELEMENT_BY_NAME[query.lower()]
    elif query in ELEMENT_BY_NUMBER:
        item = ELEMENT_BY_NUMBER[query]

    if not item:
        await update.message.reply_text(f"Element not found: {query}")
        return

    number, symbol, name, mass, group, period, category = item
    group_text = str(group) if group is not None else "lanthanide/actinide block"

    await update.message.reply_text(
        f"{name} ({symbol})\n\n"
        f"Atomic number: {number}\n"
        f"Atomic mass: {fmt(mass)} u\n"
        f"Group: {group_text}\n"
        f"Period: {period}\n"
        f"Category: {category}"
    )


async def molar_mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/molar_mass H2O\n/molar_mass C6H12O6\n/molar_mass Ca(OH)2")
        return

    formula = "".join(context.args).strip()

    try:
        counts = parse_formula(formula)
        total, lines = molar_mass_from_counts(counts)
    except Exception as error:
        await update.message.reply_text(f"Molar mass error.\n\nError: {error}")
        return

    await update.message.reply_text(
        f"Molar mass of {formula}\n\n"
        + "\n".join(lines)
        + f"\n\nTotal: {fmt(total, 8)} g/mol"
    )


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    equation = " ".join(context.args).strip()
    if not equation:
        await update.message.reply_text(
            "Usage:\n"
            "/balance H2 + O2 -> H2O\n"
            "/balance Fe + O2 -> Fe2O3\n"
            "/balance C3H8 + O2 -> CO2 + H2O"
        )
        return

    try:
        coefficients, left, right = balance_equation(equation)
        balanced = format_balanced_equation(coefficients, left, right)
    except Exception as error:
        await update.message.reply_text(f"Balance error.\n\nError: {error}")
        return

    await update.message.reply_text(
        "Balanced equation ⚖️\n\n"
        f"Input:\n{equation}\n\n"
        f"Balanced:\n{balanced}"
    )


async def idealgas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    text = " ".join(context.args)
    params = parse_key_values(text)
    R = get_float(params, "R") or 0.082057

    values = {
        "P": get_float(params, "P", "pressure"),
        "V": get_float(params, "V", "volume"),
        "n": get_float(params, "n", "moles", "mol"),
        "T": get_float(params, "T", "temp", "temperature"),
    }

    missing = [key for key, value in values.items() if value is None]
    if len(missing) != 1:
        await update.message.reply_text(
            "Usage: provide exactly 3 of P, V, n, T.\n\n"
            "Examples:\n"
            "/idealgas P=1 V=22.4 n=1\n"
            "/idealgas P=1 n=1 T=273.15\n"
            "Default R = 0.082057 L·atm/(mol·K)"
        )
        return

    missing_key = missing[0]
    P, V, n, T = values["P"], values["V"], values["n"], values["T"]

    try:
        if missing_key == "P":
            result = n * R * T / V
            unit = "atm"
        elif missing_key == "V":
            result = n * R * T / P
            unit = "L"
        elif missing_key == "n":
            result = P * V / (R * T)
            unit = "mol"
        else:
            result = P * V / (n * R)
            unit = "K"
    except Exception as error:
        await update.message.reply_text(f"Ideal gas calculation error.\n\nError: {error}")
        return

    await update.message.reply_text(
        "Ideal gas law: PV = nRT\n\n"
        f"P = {fmt(P) if P is not None else '?'} atm\n"
        f"V = {fmt(V) if V is not None else '?'} L\n"
        f"n = {fmt(n) if n is not None else '?'} mol\n"
        f"T = {fmt(T) if T is not None else '?'} K\n"
        f"R = {fmt(R)} L·atm/(mol·K)\n\n"
        f"Solved: {missing_key} = {fmt(result, 8)} {unit}"
    )


async def molarity_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    params = parse_key_values(" ".join(context.args))
    volume = get_float(params, "volume", "v", "L")
    moles = get_float(params, "moles", "mol", "n")
    mass = get_float(params, "mass", "g")
    formula = params.get("formula")

    if volume is None or volume <= 0:
        await update.message.reply_text(
            "Usage:\n"
            "/molarity moles=0.5 volume=2\n"
            "/molarity mass=58.44 formula=NaCl volume=1"
        )
        return

    try:
        if moles is None:
            if mass is None or not formula:
                raise ValueError("Provide moles, or provide mass and formula.")
            counts = parse_formula(formula)
            molar_mass, _ = molar_mass_from_counts(counts)
            moles = mass / molar_mass
        else:
            molar_mass = None

        M = moles / volume
    except Exception as error:
        await update.message.reply_text(f"Molarity error.\n\nError: {error}")
        return

    extra = ""
    if mass is not None and formula:
        extra = f"Mass: {fmt(mass)} g\nFormula: {formula}\nMolar mass: {fmt(molar_mass, 8)} g/mol\n"

    await update.message.reply_text(
        "Molarity calculation\n\n"
        f"{extra}"
        f"Moles: {fmt(moles, 8)} mol\n"
        f"Volume: {fmt(volume)} L\n\n"
        f"M = {fmt(M, 8)} mol/L"
    )


async def dilution_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    params = parse_key_values(" ".join(context.args))
    values = {
        "M1": get_float(params, "M1"),
        "V1": get_float(params, "V1"),
        "M2": get_float(params, "M2"),
        "V2": get_float(params, "V2"),
    }
    missing = [key for key, value in values.items() if value is None]

    if len(missing) != 1:
        await update.message.reply_text(
            "Usage: provide exactly 3 of M1, V1, M2, V2.\n\n"
            "Examples:\n"
            "/dilution M1=2 V1=0.5 M2=1\n"
            "/dilution M1=2 V1=0.25 V2=1"
        )
        return

    try:
        M1, V1, M2, V2 = values["M1"], values["V1"], values["M2"], values["V2"]
        missing_key = missing[0]
        if missing_key == "M1":
            result = M2 * V2 / V1
        elif missing_key == "V1":
            result = M2 * V2 / M1
        elif missing_key == "M2":
            result = M1 * V1 / V2
        else:
            result = M1 * V1 / M2
    except Exception as error:
        await update.message.reply_text(f"Dilution error.\n\nError: {error}")
        return

    await update.message.reply_text(
        "Dilution equation: M1V1 = M2V2\n\n"
        f"M1 = {fmt(M1) if M1 is not None else '?'}\n"
        f"V1 = {fmt(V1) if V1 is not None else '?'}\n"
        f"M2 = {fmt(M2) if M2 is not None else '?'}\n"
        f"V2 = {fmt(V2) if V2 is not None else '?'}\n\n"
        f"Solved: {missing_key} = {fmt(result, 8)}"
    )


async def ph_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    params = parse_key_values(" ".join(context.args))

    try:
        if get_float(params, "ph") is not None:
            pH = get_float(params, "ph")
            H = 10 ** (-pH)
            pOH = 14 - pH
            OH = 10 ** (-pOH)
        elif get_float(params, "poh") is not None:
            pOH = get_float(params, "poh")
            OH = 10 ** (-pOH)
            pH = 14 - pOH
            H = 10 ** (-pH)
        elif get_float(params, "H", "h") is not None:
            H = get_float(params, "H", "h")
            if H <= 0:
                raise ValueError("H concentration must be positive.")
            pH = -math.log10(H)
            pOH = 14 - pH
            OH = 10 ** (-pOH)
        elif get_float(params, "OH", "oh") is not None:
            OH = get_float(params, "OH", "oh")
            if OH <= 0:
                raise ValueError("OH concentration must be positive.")
            pOH = -math.log10(OH)
            pH = 14 - pOH
            H = 10 ** (-pH)
        else:
            raise ValueError("Provide pH, pOH, H, or OH.")
    except Exception as error:
        await update.message.reply_text(
            "pH error.\n\n"
            f"Error: {error}\n\n"
            "Examples:\n"
            "/ph H=1e-7\n"
            "/ph OH=1e-3\n"
            "/ph pOH=5"
        )
        return

    if pH < 7:
        nature = "acidic"
    elif pH > 7:
        nature = "basic"
    else:
        nature = "neutral"

    await update.message.reply_text(
        "pH calculation\n\n"
        f"[H+] = {fmt(H, 8)} M\n"
        f"[OH-] = {fmt(OH, 8)} M\n"
        f"pH = {fmt(pH, 8)}\n"
        f"pOH = {fmt(pOH, 8)}\n"
        f"Solution is {nature}."
    )


async def gasplot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "/gasplot P V n=1 T=300\n"
            "/gasplot V T n=1 P=1\n"
            "/gasplot P T n=1 V=10"
        )
        return

    xvar = context.args[0].upper()
    yvar = context.args[1].upper()
    params = parse_key_values(" ".join(context.args[2:]))
    R = get_float(params, "R") or 0.082057
    n = get_float(params, "n") or 1.0
    T = get_float(params, "T") or 300.0
    P = get_float(params, "P") or 1.0
    V = get_float(params, "V") or 10.0

    try:
        points: List[Tuple[float, float]] = []

        if xvar == "V" and yvar == "P":
            xmin, xmax = 0.5, 50.0
            for i in range(1, 301):
                x = xmin + (xmax - xmin) * i / 300
                y = n * R * T / x
                points.append((x, y))
            x_label, y_label = "V (L)", "P (atm)"
            title = f"Ideal gas: P vs V, n={fmt(n)} mol, T={fmt(T)} K"

        elif xvar == "P" and yvar == "V":
            xmin, xmax = 0.1, 10.0
            for i in range(1, 301):
                x = xmin + (xmax - xmin) * i / 300
                y = n * R * T / x
                points.append((x, y))
            x_label, y_label = "P (atm)", "V (L)"
            title = f"Ideal gas: V vs P, n={fmt(n)} mol, T={fmt(T)} K"

        elif xvar == "T" and yvar == "V":
            xmin, xmax = 100.0, 600.0
            for i in range(301):
                x = xmin + (xmax - xmin) * i / 300
                y = n * R * x / P
                points.append((x, y))
            x_label, y_label = "T (K)", "V (L)"
            title = f"Charles-style plot: V vs T, n={fmt(n)} mol, P={fmt(P)} atm"

        elif xvar == "T" and yvar == "P":
            xmin, xmax = 100.0, 600.0
            for i in range(301):
                x = xmin + (xmax - xmin) * i / 300
                y = n * R * x / V
                points.append((x, y))
            x_label, y_label = "T (K)", "P (atm)"
            title = f"Ideal gas: P vs T, n={fmt(n)} mol, V={fmt(V)} L"

        else:
            raise ValueError("Supported pairs: P V, V P, T V, T P")

        image = create_xy_plot(title, x_label, y_label, points, filename="gasplot.png")
    except Exception as error:
        await update.message.reply_text(f"Gas plot error.\n\nError: {error}")
        return

    await update.message.reply_photo(
        photo=InputFile(image, filename="gasplot.png"),
        caption=title,
    )


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

def register_chemistry_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("chemhelp", chemhelp_command))
    app.add_handler(CommandHandler("chem_ai", chemistry_ai_command))
    app.add_handler(CommandHandler("chemai", chemistry_ai_command))
    app.add_handler(CommandHandler("chem_tutor", chemistry_tutor_command))
    app.add_handler(CommandHandler("chemtutor", chemistry_tutor_command))
    app.add_handler(CommandHandler("chemistry_tutor", chemistry_tutor_command))
    app.add_handler(CommandHandler("tutor_chem", chemistry_tutor_command))
    app.add_handler(CommandHandler("tutor_chemistry", chemistry_tutor_command))

    def add(names: List[str], handler, command_name: str) -> None:
        wrapped = chemistry_ai_wrapper(command_name, handler)
        for name in names:
            app.add_handler(CommandHandler(name, wrapped))

    add(["element"], element_command, "element")
    add(["molar_mass", "molarmass"], molar_mass_command, "molar_mass")
    add(["balance"], balance_command, "balance")
    add(["idealgas"], idealgas_command, "idealgas")
    add(["molarity"], molarity_command, "molarity")
    add(["dilution"], dilution_command, "dilution")
    add(["ph"], ph_command, "ph")
    add(["gasplot"], gasplot_command, "gasplot")
