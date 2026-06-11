import os
from io import BytesIO
from typing import List, Optional

from fastapi import FastAPI, Request, HTTPException
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageChops
from telegram import Update, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


MAX_INPUT = 10**12
MAX_RETURNED_SEQUENCE_ITEMS = 120

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Example: https://your-app-name.onrender.com
SECRET_PATH = os.getenv("SECRET_PATH", "telegram-webhook")

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")

telegram_app = Application.builder().token(TOKEN).build()
api = FastAPI(title="Collatz Multi Tool Telegram Bot")


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


def summarize_sequence(n: int) -> str:
    if n > MAX_INPUT:
        raise ValueError(f"Please use a number up to {MAX_INPUT:,}.")

    seq = collatz_sequence(n)
    steps = len(seq) - 1
    max_value = max(seq)
    peak_index = seq.index(max_value)

    if len(seq) <= MAX_RETURNED_SEQUENCE_ITEMS:
        sequence_text = " → ".join(map(str, seq))
    else:
        head = " → ".join(map(str, seq[:60]))
        tail = " → ".join(map(str, seq[-20:]))
        sequence_text = f"{head} → ... → {tail}"

    return (
        f"Collatz result for n = {n}\n\n"
        f"Steps to reach 1: {steps}\n"
        f"Maximum value reached: {max_value}\n"
        f"Peak reached at step: {peak_index}\n"
        f"Sequence length: {len(seq)} numbers\n\n"
        f"Sequence:\n{sequence_text}"
    )


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def resize_for_telegram(img: Image.Image, max_size: int = 1400) -> Image.Image:
    img = img.copy()
    img.thumbnail((max_size, max_size))
    return img


def image_to_bytes(img: Image.Image, image_format: str = "JPEG") -> BytesIO:
    output = BytesIO()

    if image_format.upper() == "JPEG":
        img = img.convert("RGB")
        img.save(output, format="JPEG", quality=92, optimize=True)
        output.name = "edited_photo.jpg"
    elif image_format.upper() == "PNG":
        img.save(output, format="PNG", optimize=True)
        output.name = "edited_photo.png"
    else:
        raise ValueError("Unsupported image format.")

    output.seek(0)
    return output


def normalize_caption_command(caption: Optional[str]) -> Optional[str]:
    """
    Converts:
    /vintage
    /vintage@MyBot
    into:
    vintage
    """
    if not caption:
        return None

    first = caption.strip().split()[0].lower()
    if not first.startswith("/"):
        return None

    first = first[1:]
    if "@" in first:
        first = first.split("@", 1)[0]

    return first


# ------------------------------------------------------------
# Filters
# ------------------------------------------------------------

def apply_vintage_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = resize_for_telegram(img)

    img = ImageEnhance.Color(img).enhance(0.58)
    img = ImageEnhance.Contrast(img).enhance(1.14)
    img = ImageEnhance.Brightness(img).enhance(1.03)

    sepia = ImageOps.grayscale(img)
    sepia = ImageOps.colorize(sepia, "#3b2614", "#f2d6a2")
    img = Image.blend(img, sepia, 0.60)

    img = img.filter(ImageFilter.GaussianBlur(radius=0.25))

    # Soft vignette
    width, height = img.size
    small = 280
    mask = Image.new("L", (small, small), 0)
    cx, cy = small / 2, small / 2

    for y in range(small):
        for x in range(small):
            dx = (x - cx) / cx
            dy = (y - cy) / cy
            distance = (dx * dx + dy * dy) ** 0.5
            value = int(255 * max(0, 1 - distance * 0.9))
            mask.putpixel((x, y), value)

    mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    dark = Image.new("RGB", (width, height), "#1f1308")
    img = Image.composite(img, dark, mask)

    return img


def apply_cartoon_filter(img: Image.Image) -> Image.Image:
    """
    Improved cartoon filter:
    - smooths flat regions
    - boosts colors
    - posterizes
    - overlays black edges
    """
    img = img.convert("RGB")
    img = resize_for_telegram(img)

    base = img.filter(ImageFilter.MedianFilter(size=5))
    base = base.filter(ImageFilter.SMOOTH_MORE)
    base = ImageEnhance.Color(base).enhance(1.7)
    base = ImageEnhance.Contrast(base).enhance(1.3)
    base = ImageOps.posterize(base, bits=4)

    # Edge mask: white background with black edges
    gray = ImageOps.grayscale(img)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageEnhance.Contrast(edges).enhance(2.0)
    edges = ImageOps.invert(edges)
    edges = edges.point(lambda p: 255 if p > 110 else 0)

    # Multiply with edge mask so black edges are kept and non-edges stay intact
    edge_rgb = edges.convert("RGB")
    cartoon = ImageChops.multiply(base, edge_rgb)

    cartoon = ImageEnhance.Sharpness(cartoon).enhance(1.5)
    return cartoon


def apply_sticker_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    img = resize_for_telegram(img, max_size=512)

    rgb = img.convert("RGB")
    rgb = ImageEnhance.Color(rgb).enhance(1.35)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.18)
    img = rgb.convert("RGBA")

    border_size = 24
    shadow_offset = 10

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
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=5))

    final_img.paste(shadow, (shadow_offset, shadow_offset), shadow)
    final_img.paste(bordered, (0, 0), bordered)

    return final_img


def apply_beach_filter(img: Image.Image) -> Image.Image:
    """
    Summer / beach style as a clean photo filter only.
    No sunglasses, no stickers, no icons.
    """
    img = img.convert("RGB")
    img = resize_for_telegram(img)

    img = ImageEnhance.Color(img).enhance(1.30)
    img = ImageEnhance.Contrast(img).enhance(1.10)
    img = ImageEnhance.Brightness(img).enhance(1.10)

    warm_overlay = Image.new("RGB", img.size, "#ffd89a")
    img = Image.blend(img, warm_overlay, 0.10)

    img = ImageEnhance.Sharpness(img).enhance(1.15)
    return img


def apply_caricature_filter(img: Image.Image) -> Image.Image:
    """
    Fun caricature mood:
    more exaggerated than cartoon:
    - stronger saturation
    - stronger contrast
    - heavier posterization
    - darker outlines
    """
    img = img.convert("RGB")
    img = resize_for_telegram(img)

    base = img.filter(ImageFilter.MedianFilter(size=7))
    base = base.filter(ImageFilter.SMOOTH_MORE)
    base = ImageEnhance.Color(base).enhance(2.0)
    base = ImageEnhance.Contrast(base).enhance(1.45)
    base = ImageEnhance.Brightness(base).enhance(1.05)
    base = ImageOps.posterize(base, bits=3)

    gray = ImageOps.grayscale(img)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageEnhance.Contrast(edges).enhance(2.6)
    edges = ImageOps.invert(edges)
    edges = edges.point(lambda p: 255 if p > 120 else 0)

    edge_rgb = edges.convert("RGB")
    caricature = ImageChops.multiply(base, edge_rgb)
    caricature = ImageEnhance.Sharpness(caricature).enhance(1.8)

    return caricature


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hello! I can calculate Collatz sequences and edit photos.\n\n"
        "Commands:\n"
        "/collatz 27 - calculate Collatz sequence\n"
        "/vintage - send a photo and I make it vintage\n"
        "/cartoon - send a photo and I make it cartoon style\n"
        "/caricature - send a photo and I make it fun caricature style\n"
        "/caricator - same as /caricature\n"
        "/sticker - send a photo and I make it sticker style\n"
        "/stiker - same as /sticker\n"
        "/beach - send a photo and I make it summer/beach style\n"
        "/summer - same as /beach\n"
        "/vacation - same as /beach\n"
        "/cancel - cancel current photo mode\n\n"
        "In a group, commands are the most reliable way to talk to me."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def collatz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /collatz 27")
        return

    try:
        n = int(context.args[0])
        await update.message.reply_text(summarize_sequence(n))
    except ValueError as error:
        await update.message.reply_text(
            f"{error}\n\nPlease send a positive whole number, for example:\n/collatz 27"
        )


async def set_photo_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    context.user_data["photo_mode"] = mode

    messages = {
        "vintage": "Vintage mode selected. Now send me a photo 📸",
        "cartoon": "Cartoon mode selected. Now send me a photo 🎨",
        "caricature": "Caricature mode selected. Now send me a photo 😄",
        "sticker": "Sticker mode selected. Now send me a photo 🖼️",
        "beach": "Beach mode selected. Now send me a photo 🌴",
    }

    await update.message.reply_text(messages.get(mode, "Mode selected. Now send me a photo."))


async def vintage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "vintage")


async def cartoon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "cartoon")


async def caricature_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "caricature")


async def sticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "sticker")


async def beach_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_photo_mode(update, context, "beach")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("photo_mode", None)
    await update.message.reply_text(
        "Cancelled. Send /vintage, /cartoon, /caricature, /sticker, /beach, or /collatz 27."
    )


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.photo:
        return

    mode = context.user_data.get("photo_mode")
    caption_command = normalize_caption_command(message.caption)

    if caption_command == "vintage":
        mode = "vintage"
    elif caption_command == "cartoon":
        mode = "cartoon"
    elif caption_command in ["caricature", "caricator"]:
        mode = "caricature"
    elif caption_command in ["sticker", "stiker"]:
        mode = "sticker"
    elif caption_command in ["beach", "summer", "vacation"]:
        mode = "beach"

    if not mode:
        await message.reply_text(
            "Please choose a photo mode first:\n\n"
            "/vintage\n"
            "/cartoon\n"
            "/caricature\n"
            "/sticker\n"
            "/beach"
        )
        return

    await message.reply_text("Processing your photo...")

    try:
        photo = message.photo[-1]
        telegram_file = await photo.get_file()

        input_bytes = BytesIO()
        await telegram_file.download_to_memory(out=input_bytes)
        input_bytes.seek(0)

        img = Image.open(input_bytes)

        if mode == "vintage":
            edited = apply_vintage_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(
                photo=InputFile(output),
                caption="Your vintage photo is ready 📸",
            )

        elif mode == "cartoon":
            edited = apply_cartoon_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(
                photo=InputFile(output),
                caption="Your cartoon photo is ready 🎨",
            )

        elif mode == "caricature":
            edited = apply_caricature_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(
                photo=InputFile(output),
                caption="Your caricature photo is ready 😄",
            )

        elif mode == "sticker":
            edited = apply_sticker_filter(img)
            output = image_to_bytes(edited, "PNG")
            await message.reply_document(
                document=InputFile(output),
                caption="Your sticker-style image is ready 🖼️",
            )

        elif mode == "beach":
            edited = apply_beach_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(
                photo=InputFile(output),
                caption="Your beach photo is ready 🌴",
            )

        else:
            await message.reply_text(
                "Unknown mode. Use /vintage, /cartoon, /caricature, /sticker, or /beach."
            )

    except Exception as error:
        await message.reply_text(f"Sorry, I could not process that photo.\n\nError: {error}")

    finally:
        # Remove mode after one photo
        context.user_data.pop("photo_mode", None)


# ------------------------------------------------------------
# Register handlers
# ------------------------------------------------------------

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(CommandHandler("collatz", collatz_command))
telegram_app.add_handler(CommandHandler("vintage", vintage_command))
telegram_app.add_handler(CommandHandler("cartoon", cartoon_command))
telegram_app.add_handler(CommandHandler("caricature", caricature_command))
telegram_app.add_handler(CommandHandler("caricator", caricature_command))
telegram_app.add_handler(CommandHandler("sticker", sticker_command))
telegram_app.add_handler(CommandHandler("stiker", sticker_command))
telegram_app.add_handler(CommandHandler("beach", beach_command))
telegram_app.add_handler(CommandHandler("summer", beach_command))
telegram_app.add_handler(CommandHandler("vacation", beach_command))
telegram_app.add_handler(CommandHandler("cancel", cancel_command))
telegram_app.add_handler(MessageHandler(filters.PHOTO, photo_handler))


# ------------------------------------------------------------
# FastAPI webhook
# ------------------------------------------------------------

@api.on_event("startup")
async def startup() -> None:
    await telegram_app.initialize()
    await telegram_app.start()

    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{SECRET_PATH}"
        await telegram_app.bot.set_webhook(url=webhook_url)
        print(f"Webhook set to: {webhook_url}")
    else:
        print("WEBHOOK_URL is not set. App is running, but Telegram webhook was not configured.")


@api.on_event("shutdown")
async def shutdown() -> None:
    await telegram_app.stop()
    await telegram_app.shutdown()


@api.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Collatz multi-tool Telegram bot is running.",
        "usage": [
            "/collatz 27",
            "/vintage",
            "/cartoon",
            "/caricature",
            "/sticker",
            "/beach",
        ],
    }


@api.head("/")
async def head_root():
    return {}


@api.post("/{path}")
async def telegram_webhook(path: str, request: Request):
    if path != SECRET_PATH:
        raise HTTPException(status_code=404, detail="Not found")

    data = await request.json()
    update = Update.de_json(data=data, bot=telegram_app.bot)

    await telegram_app.process_update(update)

    return {"ok": True}