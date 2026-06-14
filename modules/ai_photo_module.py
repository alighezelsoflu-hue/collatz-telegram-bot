from io import BytesIO
from typing import Callable, Dict, Optional

from PIL import (
    Image,
    ImageChops,
    ImageEnhance,
    ImageFilter,
    ImageOps,
    ImageStat,
)
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

MAX_IMAGE_SIZE = 1600
PROFILE_SIZE = 1080


# ------------------------------------------------------------
# General helpers
# ------------------------------------------------------------

def resize_for_telegram(img: Image.Image, max_size: int = MAX_IMAGE_SIZE) -> Image.Image:
    img = img.copy()
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return img


def image_to_bytes(
    img: Image.Image,
    image_format: str = "JPEG",
    filename: Optional[str] = None,
) -> BytesIO:
    output = BytesIO()
    image_format = image_format.upper()

    if image_format == "JPEG":
        img = img.convert("RGB")
        img.save(output, format="JPEG", quality=95, optimize=True)
        output.name = filename or "ai_photo.jpg"

    elif image_format == "PNG":
        img.save(output, format="PNG", optimize=True)
        output.name = filename or "ai_photo.png"

    else:
        raise ValueError("Unsupported image format. Use JPEG or PNG.")

    output.seek(0)
    return output


def normalize_caption_command(caption: Optional[str]) -> Optional[str]:
    if not caption:
        return None

    parts = caption.strip().split()

    if not parts:
        return None

    first = parts[0].strip().lower()

    if not first.startswith("/"):
        return None

    first = first[1:]

    if "@" in first:
        first = first.split("@", 1)[0]

    return first


def crop_center_square(img: Image.Image) -> Image.Image:
    width, height = img.size
    side = min(width, height)

    left = (width - side) // 2
    top = (height - side) // 2
    right = left + side
    bottom = top + side

    return img.crop((left, top, right, bottom))


def estimate_brightness(img: Image.Image) -> float:
    gray = ImageOps.grayscale(img.convert("RGB"))
    stat = ImageStat.Stat(gray)
    return float(stat.mean[0])


def add_vignette(img: Image.Image, strength: float = 0.45) -> Image.Image:
    img = img.convert("RGB")
    width, height = img.size

    small_w = max(100, width // 8)
    small_h = max(100, height // 8)

    mask = Image.new("L", (small_w, small_h), 0)
    cx, cy = small_w / 2, small_h / 2

    for y in range(small_h):
        for x in range(small_w):
            dx = (x - cx) / cx
            dy = (y - cy) / cy
            distance = (dx * dx + dy * dy) ** 0.5
            value = int(255 * max(0, 1 - distance * (1.35 - strength)))
            mask.putpixel((x, y), value)

    mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    dark = Image.new("RGB", (width, height), "#101010")

    return Image.composite(img, dark, mask)


def add_glow(img: Image.Image, strength: float = 0.25, radius: float = 8.0) -> Image.Image:
    img = img.convert("RGB")
    glow = img.filter(ImageFilter.GaussianBlur(radius=radius))
    glow = ImageEnhance.Brightness(glow).enhance(1.12)
    return Image.blend(img, glow, strength)


def local_ai_base_enhance(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = resize_for_telegram(img)

    img = ImageOps.autocontrast(img, cutoff=1)

    brightness = estimate_brightness(img)

    if brightness < 95:
        img = ImageEnhance.Brightness(img).enhance(1.16)
    elif brightness < 120:
        img = ImageEnhance.Brightness(img).enhance(1.08)
    elif brightness > 205:
        img = ImageEnhance.Brightness(img).enhance(0.95)

    img = ImageEnhance.Contrast(img).enhance(1.14)
    img = ImageEnhance.Color(img).enhance(1.08)

    denoise = img.filter(ImageFilter.MedianFilter(size=3))
    img = Image.blend(img, denoise, 0.16)

    img = ImageEnhance.Sharpness(img).enhance(1.22)

    return img


def make_edge_mask(img: Image.Image, threshold: int = 70) -> Image.Image:
    gray = ImageOps.grayscale(img.convert("RGB"))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.autocontrast(edges)
    edges = edges.filter(ImageFilter.MedianFilter(size=3))
    edges = edges.point(lambda p: 255 if p > threshold else 0)
    edges = ImageOps.invert(edges)
    return edges.convert("RGB")


def center_subject_mask(width: int, height: int, blur_radius: int = 55) -> Image.Image:
    mask = Image.new("L", (width, height), 0)

    center_w = int(width * 0.58)
    center_h = int(height * 0.74)

    left = (width - center_w) // 2
    top = (height - center_h) // 2

    center = Image.new("L", (center_w, center_h), 255)
    center = center.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    mask.paste(center, (left, top))
    return mask


# ------------------------------------------------------------
# Free local AI-style effects
# ------------------------------------------------------------

def apply_ai_enhance(img: Image.Image) -> Image.Image:
    img = local_ai_base_enhance(img)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.16)
    return img


def apply_ai_portrait(img: Image.Image) -> Image.Image:
    img = local_ai_base_enhance(img)

    width, height = img.size

    background = img.filter(ImageFilter.GaussianBlur(radius=7))
    foreground = img.filter(ImageFilter.SMOOTH_MORE)
    foreground = Image.blend(img, foreground, 0.18)
    foreground = ImageEnhance.Brightness(foreground).enhance(1.03)
    foreground = ImageEnhance.Contrast(foreground).enhance(1.08)
    foreground = ImageEnhance.Sharpness(foreground).enhance(1.18)

    mask = center_subject_mask(width, height, blur_radius=55)

    result = Image.composite(foreground, background, mask)
    result = add_vignette(result, strength=0.50)

    return result


def apply_ai_cartoon(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img).convert("RGB")

    base = img.filter(ImageFilter.MedianFilter(size=5))
    base = base.filter(ImageFilter.SMOOTH_MORE)
    base = base.filter(ImageFilter.SMOOTH_MORE)

    base = ImageEnhance.Color(base).enhance(1.60)
    base = ImageEnhance.Contrast(base).enhance(1.22)
    base = ImageEnhance.Brightness(base).enhance(1.03)
    base = ImageOps.posterize(base, bits=4)

    edges = make_edge_mask(img, threshold=65)

    result = ImageChops.multiply(base, edges)
    result = ImageEnhance.Sharpness(result).enhance(1.45)

    return result


def apply_ai_anime(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img).convert("RGB")

    base = img.filter(ImageFilter.MedianFilter(size=5))
    base = base.filter(ImageFilter.SMOOTH_MORE)
    base = ImageEnhance.Color(base).enhance(1.90)
    base = ImageEnhance.Contrast(base).enhance(1.30)
    base = ImageEnhance.Brightness(base).enhance(1.06)
    base = ImageOps.posterize(base, bits=4)

    pink = Image.new("RGB", base.size, "#ffd7f0")
    blue = Image.new("RGB", base.size, "#c7e8ff")

    base = Image.blend(base, pink, 0.06)
    base = Image.blend(base, blue, 0.04)

    edges = make_edge_mask(img, threshold=58)

    result = ImageChops.multiply(base, edges)
    result = add_glow(result, strength=0.12, radius=5)
    result = ImageEnhance.Sharpness(result).enhance(1.35)

    return result


def apply_ai_studio(img: Image.Image) -> Image.Image:
    img = local_ai_base_enhance(img)

    width, height = img.size

    background = Image.new("RGB", (width, height), "#20242b")
    blurred = img.filter(ImageFilter.GaussianBlur(radius=8))
    background = Image.blend(background, blurred, 0.35)

    foreground = ImageEnhance.Brightness(img).enhance(1.06)
    foreground = ImageEnhance.Contrast(foreground).enhance(1.16)
    foreground = ImageEnhance.Sharpness(foreground).enhance(1.22)

    mask = center_subject_mask(width, height, blur_radius=60)

    result = Image.composite(foreground, background, mask)
    result = add_vignette(result, strength=0.44)

    return result


def apply_ai_background(img: Image.Image) -> Image.Image:
    img = local_ai_base_enhance(img)

    width, height = img.size

    background = img.filter(ImageFilter.GaussianBlur(radius=12))
    background = ImageEnhance.Brightness(background).enhance(0.88)
    background = ImageEnhance.Color(background).enhance(0.85)

    foreground = ImageEnhance.Sharpness(img).enhance(1.22)
    foreground = ImageEnhance.Contrast(foreground).enhance(1.08)

    mask = center_subject_mask(width, height, blur_radius=70)

    result = Image.composite(foreground, background, mask)
    result = add_vignette(result, strength=0.50)

    return result


def apply_ai_magic(img: Image.Image) -> Image.Image:
    img = local_ai_base_enhance(img)

    img = ImageEnhance.Color(img).enhance(1.45)
    img = ImageEnhance.Contrast(img).enhance(1.20)

    purple = Image.new("RGB", img.size, "#8c5cff")
    gold = Image.new("RGB", img.size, "#ffc15a")

    img = Image.blend(img, purple, 0.07)
    img = Image.blend(img, gold, 0.06)

    img = add_glow(img, strength=0.20, radius=8)
    img = add_vignette(img, strength=0.42)
    img = ImageEnhance.Sharpness(img).enhance(1.18)

    return img


def apply_ai_profile(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = crop_center_square(img)
    img = resize_for_telegram(img, max_size=PROFILE_SIZE)

    img = local_ai_base_enhance(img)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Color(img).enhance(1.08)

    return img


# ------------------------------------------------------------
# Mode system
# ------------------------------------------------------------

AI_MODE_MESSAGES = {
    "ai_enhance": "Free AI-style enhance mode selected. Now send me a photo ✨",
    "ai_portrait": "Free AI-style portrait mode selected. Now send me a photo 👤",
    "ai_cartoon": "Free AI-style cartoon mode selected. Now send me a photo 🎨",
    "ai_anime": "Free AI-style anime mode selected. Now send me a photo 🌸",
    "ai_studio": "Free AI-style studio mode selected. Now send me a photo 📷",
    "ai_background": "Free AI-style background mode selected. Now send me a photo 🖼️",
    "ai_magic": "Free AI-style magic mode selected. Now send me a photo 🪄",
    "ai_profile": "Free AI-style profile mode selected. Now send me a photo 👤",
}


AI_FILTERS: Dict[str, Callable[[Image.Image], Image.Image]] = {
    "ai_enhance": apply_ai_enhance,
    "ai_portrait": apply_ai_portrait,
    "ai_cartoon": apply_ai_cartoon,
    "ai_anime": apply_ai_anime,
    "ai_studio": apply_ai_studio,
    "ai_background": apply_ai_background,
    "ai_magic": apply_ai_magic,
    "ai_profile": apply_ai_profile,
}


AI_CAPTIONS = {
    "ai_enhance": "Your free AI-style enhanced photo is ready ✨",
    "ai_portrait": "Your free AI-style portrait photo is ready 👤",
    "ai_cartoon": "Your free AI-style cartoon photo is ready 🎨",
    "ai_anime": "Your free AI-style anime photo is ready 🌸",
    "ai_studio": "Your free AI-style studio photo is ready 📷",
    "ai_background": "Your free AI-style background photo is ready 🖼️",
    "ai_magic": "Your free AI-style magic photo is ready 🪄",
    "ai_profile": "Your free AI-style profile photo is ready 👤",
}


def available_ai_photo_commands_text() -> str:
    return (
        "Free AI-style photo commands:\n\n"
        "/ai_enhance - local AI-style photo enhancement\n"
        "/ai_portrait - portrait look with soft background\n"
        "/ai_cartoon - cartoon style\n"
        "/ai_anime - anime-inspired style\n"
        "/ai_studio - studio portrait look\n"
        "/ai_background - blur and improve background style\n"
        "/ai_magic - colorful artistic transformation\n"
        "/ai_profile - square profile-style AI enhancement\n"
        "/ai_reset - reset AI photo mode\n\n"
        "Note: This is free local AI-style editing with Pillow. "
        "It does not use paid cloud AI."
    )


def normalize_ai_mode_name(mode: str) -> str:
    mode = mode.lower().strip()

    aliases = {
        "ai_bg": "ai_background",
        "ai_back": "ai_background",
        "ai_art": "ai_magic",
        "ai_avatar": "ai_profile",
    }

    return aliases.get(mode, mode)


async def set_ai_photo_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    if not update.message:
        return

    mode = normalize_ai_mode_name(mode)
    context.user_data["ai_photo_mode"] = mode
    context.user_data.pop("photo_mode", None)

    await update.message.reply_text(
        AI_MODE_MESSAGES.get(mode, "Free AI-style mode selected. Now send me a photo.")
    )


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

async def ai_enhance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_ai_photo_mode(update, context, "ai_enhance")


async def ai_portrait_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_ai_photo_mode(update, context, "ai_portrait")


async def ai_cartoon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_ai_photo_mode(update, context, "ai_cartoon")


async def ai_anime_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_ai_photo_mode(update, context, "ai_anime")


async def ai_studio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_ai_photo_mode(update, context, "ai_studio")


async def ai_background_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_ai_photo_mode(update, context, "ai_background")


async def ai_magic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_ai_photo_mode(update, context, "ai_magic")


async def ai_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_ai_photo_mode(update, context, "ai_profile")


async def ai_prompt_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "This free local AI-style module does not use text prompts.\n\n"
        "Use one of these modes instead:\n\n"
        + available_ai_photo_commands_text()
    )


async def ai_reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    context.user_data.pop("ai_photo_mode", None)

    await update.message.reply_text("AI photo mode was reset.")


async def ai_photohelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(available_ai_photo_commands_text())


# ------------------------------------------------------------
# Photo handler
# ------------------------------------------------------------

async def ai_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    if not message or not message.photo:
        return

    mode = context.user_data.get("ai_photo_mode")
    caption_command = normalize_caption_command(message.caption)

    # If photo caption contains an AI command like /ai_enhance,
    # use that directly.
    if caption_command and caption_command.startswith("ai_"):
        mode = normalize_ai_mode_name(caption_command)

    # If no AI mode is selected, do nothing.
    if not mode:
        return

    mode = normalize_ai_mode_name(mode)

    if mode not in AI_FILTERS:
        await message.reply_text(
            "Unknown AI photo mode.\n\n" + available_ai_photo_commands_text()
        )
        context.user_data.pop("ai_photo_mode", None)
        return

    await message.reply_text("Processing your free AI-style photo...")

    try:
        photo = message.photo[-1]
        telegram_file = await photo.get_file()

        input_bytes = BytesIO()
        await telegram_file.download_to_memory(out=input_bytes)
        input_bytes.seek(0)

        img = Image.open(input_bytes)

        edited = AI_FILTERS[mode](img)

        filename = f"{mode}.jpg"
        output = image_to_bytes(edited, "JPEG", filename)

        await message.reply_photo(
            photo=InputFile(output, filename=filename),
            caption=AI_CAPTIONS.get(mode, "Your free AI-style photo is ready."),
        )

    except Exception as error:
        await message.reply_text(
            f"AI-style photo processing failed.\n\nError: {error}"
        )

    finally:
        context.user_data.pop("ai_photo_mode", None)


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

def register_ai_photo_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("ai_enhance", ai_enhance_command))
    app.add_handler(CommandHandler("ai_portrait", ai_portrait_command))
    app.add_handler(CommandHandler("ai_cartoon", ai_cartoon_command))
    app.add_handler(CommandHandler("ai_anime", ai_anime_command))
    app.add_handler(CommandHandler("ai_studio", ai_studio_command))
    app.add_handler(CommandHandler("ai_background", ai_background_command))
    app.add_handler(CommandHandler("ai_bg", ai_background_command))
    app.add_handler(CommandHandler("ai_magic", ai_magic_command))
    app.add_handler(CommandHandler("ai_profile", ai_profile_command))
    app.add_handler(CommandHandler("ai_avatar", ai_profile_command))

    app.add_handler(CommandHandler("ai_prompt", ai_prompt_command))
    app.add_handler(CommandHandler("ai_reset", ai_reset_command))
    app.add_handler(CommandHandler("ai_photohelp", ai_photohelp_command))

    app.add_handler(MessageHandler(filters.PHOTO, ai_photo_handler), group=2)