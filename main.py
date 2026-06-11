import os
from io import BytesIO
from typing import List

from fastapi import FastAPI, Request, HTTPException
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
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


# -------------------------
# Collatz logic
# -------------------------

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


# -------------------------
# Image filter logic
# -------------------------

def resize_for_telegram(img: Image.Image, max_size: int = 1600) -> Image.Image:
    img = img.copy()
    img.thumbnail((max_size, max_size))
    return img


def apply_vintage_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = resize_for_telegram(img)

    # Fade colors
    img = ImageEnhance.Color(img).enhance(0.55)

    # Slight contrast
    img = ImageEnhance.Contrast(img).enhance(1.18)

    # Slight warm brightness
    img = ImageEnhance.Brightness(img).enhance(1.02)

    # Sepia effect
    sepia = ImageOps.grayscale(img)
    sepia = ImageOps.colorize(sepia, "#3b2614", "#f2d6a2")

    # Blend original and sepia
    img = Image.blend(img, sepia, 0.65)

    # Soft old-photo blur
    img = img.filter(ImageFilter.GaussianBlur(radius=0.35))

    # Vignette
    width, height = img.size
    vignette = Image.new("L", (width, height), 0)

    for y in range(height):
        for x in range(width):
            dx = (x - width / 2) / (width / 2)
            dy = (y - height / 2) / (height / 2)
            distance = (dx * dx + dy * dy) ** 0.5
            value = int(255 * max(0, min(1, 1 - distance * 0.75)))
            vignette.putpixel((x, y), value)

    dark = Image.new("RGB", (width, height), "#1f1308")
    img = Image.composite(img, dark, vignette)

    return img


def apply_cartoon_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = resize_for_telegram(img)

    # Smooth colors
    smooth = img.filter(ImageFilter.MedianFilter(size=5))

    # Boost color and contrast
    smooth = ImageEnhance.Color(smooth).enhance(1.6)
    smooth = ImageEnhance.Contrast(smooth).enhance(1.25)

    # Posterize for cartoon look
    cartoon = ImageOps.posterize(smooth, bits=4)

    # Detect edges
    gray = ImageOps.grayscale(img)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.invert(edges)
    edges = edges.point(lambda p: 255 if p > 120 else 0)

    # Apply edges as mask
    cartoon = Image.composite(cartoon, Image.new("RGB", cartoon.size, "black"), ImageOps.invert(edges))

    return cartoon


def apply_sticker_filter(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    img = resize_for_telegram(img, max_size=512)

    # Add playful contrast/color
    rgb = img.convert("RGB")
    rgb = ImageEnhance.Color(rgb).enhance(1.4)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.2)
    img = rgb.convert("RGBA")

    # Add white border
    border_size = 24
    white_bg = Image.new(
        "RGBA",
        (img.width + border_size * 2, img.height + border_size * 2),
        (255, 255, 255, 255),
    )
    white_bg.paste(img, (border_size, border_size), img)

    # Add small shadow background
    shadow_offset = 10
    final_img = Image.new(
        "RGBA",
        (white_bg.width + shadow_offset, white_bg.height + shadow_offset),
        (0, 0, 0, 0),
    )

    shadow = Image.new("RGBA", white_bg.size, (0, 0, 0, 80))
    final_img.paste(shadow, (shadow_offset, shadow_offset), shadow)
    final_img.paste(white_bg, (0, 0), white_bg)

    return final_img


def image_to_bytes(img: Image.Image, image_format: str = "JPEG") -> BytesIO:
    output = BytesIO()

    if image_format.upper() == "JPEG":
        img = img.convert("RGB")
        img.save(output, format="JPEG", quality=92)
        output.name = "edited_photo.jpg"
    else:
        img.save(output, format="PNG")
        output.name = "sticker_style.png"

    output.seek(0)
    return output


# -------------------------
# Telegram commands
# -------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hello! I can calculate Collatz sequences and edit photos.\n\n"
        "Commands:\n"
        "/collatz 27 - calculate Collatz sequence\n"
        "/vintage - send a photo and I make it vintage\n"
        "/cartoon - send a photo and I make it cartoon style\n"
        "/sticker - send a photo and I make it sticker style\n"
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


async def vintage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["photo_mode"] = "vintage"
    await update.message.reply_text("Vintage mode selected. Now send me a photo 📸")


async def cartoon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["photo_mode"] = "cartoon"
    await update.message.reply_text("Cartoon mode selected. Now send me a photo 🎨")


async def sticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["photo_mode"] = "sticker"
    await update.message.reply_text("Sticker mode selected. Now send me a photo 😄")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("photo_mode", None)
    await update.message.reply_text("Cancelled. Send /vintage, /cartoon, /sticker, or /collatz 27.")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    if not message or not message.photo:
        return

    mode = context.user_data.get("photo_mode")

    # Also allow users to send a photo with caption:
    # /vintage
    # /cartoon
    # /sticker
    caption = message.caption or ""
    caption_command = caption.strip().split()[0].lower() if caption.strip() else ""

    if caption_command in ["/vintage", "/vintage@yourbot"]:
        mode = "vintage"
    elif caption_command in ["/cartoon", "/cartoon@yourbot"]:
        mode = "cartoon"
    elif caption_command in ["/sticker", "/stiker", "/sticker@yourbot", "/stiker@yourbot"]:
        mode = "sticker"

    if not mode:
        await message.reply_text(
            "Please choose a photo mode first:\n\n"
            "/vintage\n"
            "/cartoon\n"
            "/sticker"
        )
        return

    await message.reply_text("Processing your photo...")

    try:
        # Get highest resolution photo Telegram provides
        photo = message.photo[-1]
        telegram_file = await photo.get_file()

        input_bytes = BytesIO()
        await telegram_file.download_to_memory(out=input_bytes)
        input_bytes.seek(0)

        img = Image.open(input_bytes)

        if mode == "vintage":
            edited = apply_vintage_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(photo=InputFile(output), caption="Your vintage photo is ready 📸")

        elif mode == "cartoon":
            edited = apply_cartoon_filter(img)
            output = image_to_bytes(edited, "JPEG")
            await message.reply_photo(photo=InputFile(output), caption="Your cartoon photo is ready 🎨")

        elif mode == "sticker":
            edited = apply_sticker_filter(img)
            output = image_to_bytes(edited, "PNG")
            await message.reply_document(document=InputFile(output), caption="Your sticker-style image is ready 😄")

        else:
            await message.reply_text("Unknown mode. Please use /vintage, /cartoon, or /sticker.")

    except Exception as error:
        await message.reply_text(f"Sorry, I could not process that photo.\n\nError: {error}")

    finally:
        # Remove mode after one photo.
        # If you want mode to stay active, delete this line.
        context.user_data.pop("photo_mode", None)


# -------------------------
# Register handlers
# -------------------------

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(CommandHandler("collatz", collatz_command))
telegram_app.add_handler(CommandHandler("vintage", vintage_command))
telegram_app.add_handler(CommandHandler("cartoon", cartoon_command))
telegram_app.add_handler(CommandHandler("sticker", sticker_command))
telegram_app.add_handler(CommandHandler("stiker", sticker_command))
telegram_app.add_handler(CommandHandler("cancel", cancel_command))
telegram_app.add_handler(MessageHandler(filters.PHOTO, photo_handler))


# -------------------------
# FastAPI webhook
# -------------------------

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
            "/sticker",
        ],
    }


@api.post("/{path}")
async def telegram_webhook(path: str, request: Request):
    if path != SECRET_PATH:
        raise HTTPException(status_code=404, detail="Not found")

    data = await request.json()
    update = Update.de_json(data=data, bot=telegram_app.bot)

    await telegram_app.process_update(update)

    return {"ok": True}