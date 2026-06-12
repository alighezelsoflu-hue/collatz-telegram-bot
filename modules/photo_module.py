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

MAX_TELEGRAM_SIZE = 1600
PROFILE_SIZE = 1080
STICKER_SIZE = 512


# ------------------------------------------------------------
# General helpers
# ------------------------------------------------------------

def resize_for_telegram(img: Image.Image, max_size: int = MAX_TELEGRAM_SIZE) -> Image.Image:
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
        output.name = filename or "edited_photo.jpg"

    elif image_format == "PNG":
        img.save(output, format="PNG", optimize=True)
        output.name = filename or "edited_photo.png"

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


def safe_autocontrast(img: Image.Image, cutoff: int = 1) -> Image.Image:
    return ImageOps.autocontrast(img.convert("RGB"), cutoff=cutoff)


def safe_sharpen(img: Image.Image, factor: float = 1.20) -> Image.Image:
    return ImageEnhance.Sharpness(img).enhance(factor)


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


def add_soft_border(img: Image.Image, border_size: int = 18) -> Image.Image:
    img = img.convert("RGB")
    bordered = ImageOps.expand(img, border=border_size, fill="white")
    bordered = ImageOps.expand(bordered, border=2, fill="#dddddd")
    return bordered


def add_sticker_border(img: Image.Image, border_size: int = 24, shadow_offset: int = 12) -> Image.Image:
    img = img.convert("RGBA")

    bordered = Image.new(
        "RGBA",
        (img.width + border_size * 2, img.height + border_size * 2),
        (255, 255, 255, 255),
    )
    bordered.paste(img, (border_size, border_size), img)

    final_img = Image.new(
        "RGBA",
        (bordered.width + shadow_offset, bordered.height + shadow_offset),
        (0, 0, 0, 0),
    )

    shadow = Image.new("RGBA", bordered.size, (0, 0, 0, 85))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=7))

    final_img.paste(shadow, (shadow_offset, shadow_offset), shadow)
    final_img.paste(bordered, (0, 0), bordered)

    return final_img


def soft_denoise(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    smoothed = img.filter(ImageFilter.MedianFilter(size=3))
    return Image.blend(img, smoothed, 0.18)


def professional_base_enhance(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = safe_autocontrast(img, cutoff=1)

    brightness = estimate_brightness(img)

    if brightness < 95:
        img = ImageEnhance.Brightness(img).enhance(1.14)
    elif brightness < 120:
        img = ImageEnhance.Brightness(img).enhance(1.07)
    elif brightness > 205:
        img = ImageEnhance.Brightness(img).enhance(0.95)

    img = ImageEnhance.Contrast(img).enhance(1.13)
    img = ImageEnhance.Color(img).enhance(1.08)
    img = soft_denoise(img)
    img = safe_sharpen(img, 1.18)

    return img


# ------------------------------------------------------------
# Filters
# ------------------------------------------------------------

def apply_enhance_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img)
    return professional_base_enhance(img)


def apply_vintage_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img)
    img = professional_base_enhance(img)

    img = ImageEnhance.Color(img).enhance(0.65)
    img = ImageEnhance.Contrast(img).enhance(1.12)

    gray = ImageOps.grayscale(img)
    sepia = ImageOps.colorize(gray, "#35200f", "#f3d4a3")

    img = Image.blend(img, sepia, 0.55)

    warm = Image.new("RGB", img.size, "#c28b55")
    img = Image.blend(img, warm, 0.08)

    img = add_vignette(img, strength=0.50)
    img = safe_sharpen(img, 1.08)

    return img


def apply_bw_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img)
    img = professional_base_enhance(img)

    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.30)
    gray = ImageEnhance.Sharpness(gray).enhance(1.16)

    return gray.convert("RGB")


def apply_cinematic_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img)
    img = professional_base_enhance(img)

    img = ImageEnhance.Contrast(img).enhance(1.23)
    img = ImageEnhance.Color(img).enhance(0.95)

    teal = Image.new("RGB", img.size, "#244f5f")
    orange = Image.new("RGB", img.size, "#ffb36b")

    img = Image.blend(img, teal, 0.055)
    img = Image.blend(img, orange, 0.055)

    img = add_vignette(img, strength=0.40)
    img = safe_sharpen(img, 1.16)

    return img


def apply_clean_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img)

    img = img.convert("RGB")
    img = ImageOps.autocontrast(img, cutoff=2)
    img = ImageEnhance.Brightness(img).enhance(1.04)
    img = ImageEnhance.Contrast(img).enhance(1.28)
    img = ImageEnhance.Color(img).enhance(0.96)
    img = soft_denoise(img)
    img = safe_sharpen(img, 1.38)

    return img


def apply_profile_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = crop_center_square(img)
    img = resize_for_telegram(img, max_size=PROFILE_SIZE)

    img = professional_base_enhance(img)
    img = ImageEnhance.Contrast(img).enhance(1.06)
    img = ImageEnhance.Color(img).enhance(1.05)
    img = safe_sharpen(img, 1.16)

    return img


def apply_beach_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img)
    img = professional_base_enhance(img)

    img = ImageEnhance.Brightness(img).enhance(1.08)
    img = ImageEnhance.Color(img).enhance(1.28)
    img = ImageEnhance.Contrast(img).enhance(1.08)

    warm = Image.new("RGB", img.size, "#ffd69b")
    sky = Image.new("RGB", img.size, "#8fdcff")

    img = Image.blend(img, warm, 0.10)
    img = Image.blend(img, sky, 0.035)
    img = safe_sharpen(img, 1.10)

    return img


def apply_cartoon_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img)
    img = img.convert("RGB")

    base = img.filter(ImageFilter.MedianFilter(size=5))
    base = base.filter(ImageFilter.SMOOTH_MORE)
    base = ImageEnhance.Color(base).enhance(1.55)
    base = ImageEnhance.Contrast(base).enhance(1.20)
    base = ImageEnhance.Brightness(base).enhance(1.03)
    base = ImageOps.posterize(base, bits=4)

    gray = ImageOps.grayscale(img)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.autocontrast(edges)
    edges = edges.filter(ImageFilter.MedianFilter(size=3))
    edges = edges.point(lambda p: 255 if p > 64 else 0)
    edges = ImageOps.invert(edges)

    cartoon = ImageChops.multiply(base, edges.convert("RGB"))
    cartoon = safe_sharpen(cartoon, 1.45)

    return cartoon


def apply_caricature_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img)
    img = img.convert("RGB")

    base = img.filter(ImageFilter.SMOOTH_MORE)
    base = base.filter(ImageFilter.SMOOTH_MORE)
    base = ImageEnhance.Color(base).enhance(1.85)
    base = ImageEnhance.Contrast(base).enhance(1.34)
    base = ImageEnhance.Brightness(base).enhance(1.04)
    base = ImageOps.posterize(base, bits=3)

    gray = ImageOps.grayscale(img)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.autocontrast(edges)
    edges = edges.filter(ImageFilter.MedianFilter(size=3))
    edges = edges.point(lambda p: 255 if p > 72 else 0)
    edges = ImageOps.invert(edges)

    caricature = ImageChops.multiply(base, edges.convert("RGB"))
    caricature = safe_sharpen(caricature, 1.70)

    return caricature


def apply_sticker_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    img = crop_center_square(img)
    img = resize_for_telegram(img, max_size=STICKER_SIZE)

    rgb = img.convert("RGB")
    rgb = professional_base_enhance(rgb)
    rgb = ImageEnhance.Color(rgb).enhance(1.18)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.10)
    rgb = safe_sharpen(rgb, 1.18)

    rgba = rgb.convert("RGBA")
    return add_sticker_border(rgba)


def apply_portrait_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img)
    img = img.convert("RGB")

    sharp = professional_base_enhance(img)
    blurred = img.filter(ImageFilter.GaussianBlur(radius=5))

    width, height = img.size
    mask = Image.new("L", (width, height), 0)

    center_w = int(width * 0.58)
    center_h = int(height * 0.72)
    left = (width - center_w) // 2
    top = (height - center_h) // 2
    right = left + center_w
    bottom = top + center_h

    center_mask = Image.new("L", (center_w, center_h), 255)
    center_mask = center_mask.filter(ImageFilter.GaussianBlur(radius=45))
    mask.paste(center_mask, (left, top))

    portrait = Image.composite(sharp, blurred, mask)
    portrait = add_vignette(portrait, strength=0.48)

    return portrait


def apply_soft_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img)
    img = professional_base_enhance(img)

    soft = img.filter(ImageFilter.GaussianBlur(radius=1.2))
    img = Image.blend(img, soft, 0.22)
    img = ImageEnhance.Brightness(img).enhance(1.03)
    img = ImageEnhance.Color(img).enhance(1.04)

    return img


def apply_hdr_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img)
    img = safe_autocontrast(img, cutoff=1)

    img = ImageEnhance.Contrast(img).enhance(1.35)
    img = ImageEnhance.Color(img).enhance(1.18)
    img = safe_sharpen(img, 1.55)

    return img


def get_photo_info(img: Image.Image) -> str:
    width, height = img.size
    mode = img.mode
    image_format = img.format or "Unknown"

    return (
        "Photo info\n\n"
        f"Width: {width}px\n"
        f"Height: {height}px\n"
        f"Mode: {mode}\n"
        f"Format: {image_format}"
    )


# ------------------------------------------------------------
# Mode system
# ------------------------------------------------------------

PHOTO_MODE_MESSAGES = {
    "enhance": "Enhance mode selected. Now send me a photo ✨",
    "vintage": "Vintage mode selected. Now send me a photo 📸",
    "bw": "Black and white mode selected. Now send me a photo 🖤",
    "cinematic": "Cinematic mode selected. Now send me a photo 🎬",
    "clean": "Clean mode selected. Now send me a photo 🧼",
    "profile": "Profile mode selected. Now send me a photo 👤",
    "cartoon": "Cartoon mode selected. Now send me a photo 🎨",
    "caricature": "Caricature mode selected. Now send me a photo 😄",
    "sticker": "Sticker mode selected. Now send me a photo 🖼️",
    "beach": "Beach mode selected. Now send me a photo 🌴",
    "portrait": "Portrait mode selected. Now send me a photo 👔",
    "soft": "Soft mode selected. Now send me a photo 🌙",
    "hdr": "HDR mode selected. Now send me a photo 🔆",
    "photoinfo": "Photo info mode selected. Now send me a photo ℹ️",
}


MODE_ALIASES = {
    "blackwhite": "bw",
    "black_white": "bw",
    "b&w": "bw",
    "mono": "bw",
    "monochrome": "bw",

    "summer": "beach",
    "vacation": "beach",

    "stiker": "sticker",

    "caricator": "caricature",
    "funny": "caricature",

    "photo_info": "photoinfo",
    "info": "photoinfo",

    "auto": "enhance",
    "improve": "enhance",

    "document": "clean",
    "scan": "clean",

    "cinema": "cinematic",
}


def normalize_mode_name(mode: str) -> str:
    mode = mode.lower().strip()
    return MODE_ALIASES.get(mode, mode)


def available_photo_commands_text() -> str:
    return (
        "Available photo commands:\n\n"
        "/enhance - improve brightness, contrast, color, and sharpness\n"
        "/vintage - vintage photo effect\n"
        "/bw - black and white photo\n"
        "/cinematic - cinematic photo look\n"
        "/clean - clean and sharpen photo\n"
        "/profile - square profile-style crop\n"
        "/cartoon - cartoon photo style\n"
        "/caricature - stronger caricature style\n"
        "/sticker - sticker-style PNG\n"
        "/beach - summer/beach filter\n"
        "/portrait - soft portrait focus effect\n"
        "/soft - soft dreamy filter\n"
        "/hdr - strong detail and contrast\n"
        "/photoinfo - show photo information\n"
        "/cancel - cancel current mode"
    )


async def set_photo_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    if not update.message:
        return

    mode = normalize_mode_name(mode)
    context.user_data["photo_mode"] = mode

    await update.message.reply_text(
        PHOTO_MODE_MESSAGES.get(mode, "Mode selected. Now send me a photo.")
    )


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

async def enhance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "enhance")


async def vintage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "vintage")


async def bw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "bw")


async def cinematic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "cinematic")


async def clean_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "clean")


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "profile")


async def cartoon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "cartoon")


async def caricature_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "caricature")


async def sticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "sticker")


async def beach_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "beach")


async def portrait_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "portrait")


async def soft_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "soft")


async def hdr_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "hdr")


async def photoinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "photoinfo")


async def photohelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(available_photo_commands_text())


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    context.user_data.pop("photo_mode", None)
    await update.message.reply_text("Cancelled.\n\n" + available_photo_commands_text())


# ------------------------------------------------------------
# Processing
# ------------------------------------------------------------

PHOTO_FILTERS: Dict[str, Callable[[Image.Image], Image.Image]] = {
    "enhance": apply_enhance_filter,
    "vintage": apply_vintage_filter,
    "bw": apply_bw_filter,
    "cinematic": apply_cinematic_filter,
    "clean": apply_clean_filter,
    "profile": apply_profile_filter,
    "cartoon": apply_cartoon_filter,
    "caricature": apply_caricature_filter,
    "sticker": apply_sticker_filter,
    "beach": apply_beach_filter,
    "portrait": apply_portrait_filter,
    "soft": apply_soft_filter,
    "hdr": apply_hdr_filter,
}


PHOTO_CAPTIONS = {
    "enhance": "Your enhanced photo is ready ✨",
    "vintage": "Your vintage photo is ready 📸",
    "bw": "Your black-and-white photo is ready 🖤",
    "cinematic": "Your cinematic photo is ready 🎬",
    "clean": "Your cleaned photo is ready 🧼",
    "profile": "Your profile-style photo is ready 👤",
    "cartoon": "Your cartoon photo is ready 🎨",
    "caricature": "Your caricature photo is ready 😄",
    "sticker": "Your sticker-style image is ready 🖼️",
    "beach": "Your beach photo is ready 🌴",
    "portrait": "Your portrait-style photo is ready 👔",
    "soft": "Your soft-style photo is ready 🌙",
    "hdr": "Your HDR-style photo is ready 🔆",
}


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    if not message or not message.photo:
        return

    mode = context.user_data.get("photo_mode")
    caption_command = normalize_caption_command(message.caption)

    if caption_command:
        mode = normalize_mode_name(caption_command)

    if not mode:
        await message.reply_text(
            "Please choose a photo mode first.\n\n" + available_photo_commands_text()
        )
        return

    mode = normalize_mode_name(mode)

    await message.reply_text("Processing your photo...")

    try:
        photo = message.photo[-1]
        telegram_file = await photo.get_file()

        input_bytes = BytesIO()
        await telegram_file.download_to_memory(out=input_bytes)
        input_bytes.seek(0)

        img = Image.open(input_bytes)

        if mode == "photoinfo":
            await message.reply_text(get_photo_info(img))
            return

        if mode not in PHOTO_FILTERS:
            await message.reply_text(
                "Unknown photo mode.\n\n" + available_photo_commands_text()
            )
            return

        edited = PHOTO_FILTERS[mode](img)

        if mode == "sticker":
            filename = "sticker_style.png"
            output = image_to_bytes(edited, "PNG", filename)

            await message.reply_document(
                document=InputFile(output, filename=filename),
                caption=PHOTO_CAPTIONS.get(mode, "Your edited photo is ready."),
            )

        else:
            filename = f"{mode}_photo.jpg"
            output = image_to_bytes(edited, "JPEG", filename)

            await message.reply_photo(
                photo=InputFile(output, filename=filename),
                caption=PHOTO_CAPTIONS.get(mode, "Your edited photo is ready."),
            )

    except Exception as error:
        await message.reply_text(
            f"Sorry, I could not process that photo.\n\nError: {error}"
        )

    finally:
        context.user_data.pop("photo_mode", None)


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

def register_photo_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("enhance", enhance_command))
    app.add_handler(CommandHandler("vintage", vintage_command))
    app.add_handler(CommandHandler("bw", bw_command))
    app.add_handler(CommandHandler("cinematic", cinematic_command))
    app.add_handler(CommandHandler("clean", clean_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("cartoon", cartoon_command))
    app.add_handler(CommandHandler("caricature", caricature_command))
    app.add_handler(CommandHandler("caricator", caricature_command))
    app.add_handler(CommandHandler("sticker", sticker_command))
    app.add_handler(CommandHandler("stiker", sticker_command))
    app.add_handler(CommandHandler("beach", beach_command))
    app.add_handler(CommandHandler("summer", beach_command))
    app.add_handler(CommandHandler("vacation", beach_command))
    app.add_handler(CommandHandler("portrait", portrait_command))
    app.add_handler(CommandHandler("soft", soft_command))
    app.add_handler(CommandHandler("hdr", hdr_command))
    app.add_handler(CommandHandler("photoinfo", photoinfo_command))
    app.add_handler(CommandHandler("photo_info", photoinfo_command))
    app.add_handler(CommandHandler("photohelp", photohelp_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))