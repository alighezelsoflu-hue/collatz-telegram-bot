"""
Photo tools + AI vision integration for AhBashin Telegram Bot.

Works with:
- Existing local Pillow photo filters.
- Groq/OpenRouter/OpenAI-compatible vision through modules.ai_module.call_ai_vision.

Recommended Groq vision env vars on Render:
AI_PROVIDER=groq
GROQ_API_KEY=your_key
AI_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct

Visible menu should keep only /photohelp. All other commands are hidden but usable.
"""

from __future__ import annotations

import json
import re
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps
from telegram import InputFile, Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

try:
    from modules.ai_module import AIProviderError, call_ai, call_ai_vision, send_ai_response
except Exception:
    AIProviderError = Exception
    call_ai = None
    call_ai_vision = None
    send_ai_response = None


# ------------------------------------------------------------
# Limits and mode definitions
# ------------------------------------------------------------

MAX_PHOTO_SIDE = 1400
VISION_MAX_PROMPT_CHARS = 3000

PHOTO_MODES = {
    "enhance": "Improve brightness, contrast, color, and sharpness naturally.",
    "clean": "Clean natural photo enhancement.",
    "hdr": "High contrast and detailed HDR-like style.",
    "bw": "Black and white photo.",
    "vintage": "Warm vintage sepia style.",
    "cinematic": "Cinematic contrast and teal-orange color style.",
    "soft": "Soft portrait look.",
    "portrait": "Natural portrait enhancement.",
    "profile": "Profile-picture style crop and enhancement.",
    "cartoon": "Cartoon-like posterized style.",
    "caricature": "Exaggerated colorful cartoon/caricature style.",
    "sticker": "Sticker-style PNG with white border and shadow.",
    "beach": "Warm beach/summer/vacation color style.",
}

MODE_ALIASES = {
    "stiker": "sticker",
    "caricator": "caricature",
    "summer": "beach",
    "vacation": "beach",
    "blackwhite": "bw",
    "black_and_white": "bw",
    "professional": "profile",
    "linkedin": "profile",
}

VISION_COMMANDS = {
    "photo_ai",
    "ask_photo",
    "caption_photo",
    "photo_description",
    "photo_feedback",
    "describe_photo",
    "image_ai",
    "vision",
}


# ------------------------------------------------------------
# General helpers
# ------------------------------------------------------------


def resize_for_telegram(img: Image.Image, max_size: int = MAX_PHOTO_SIDE) -> Image.Image:
    img = img.copy()
    img.thumbnail((max_size, max_size))
    return img


def image_to_bytes(img: Image.Image, image_format: str = "JPEG", filename: str = "edited_photo.jpg") -> BytesIO:
    output = BytesIO()
    if image_format.upper() == "JPEG":
        img.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
    elif image_format.upper() == "PNG":
        img.save(output, format="PNG", optimize=True)
    else:
        raise ValueError("Unsupported image format.")
    output.seek(0)
    output.name = filename
    return output


def normalize_command_name(name: str) -> str:
    name = name.strip().lower()
    if name.startswith("/"):
        name = name[1:]
    if "@" in name:
        name = name.split("@", 1)[0]
    return name


def normalize_caption_command(caption: Optional[str]) -> Tuple[Optional[str], str]:
    if not caption:
        return None, ""
    parts = caption.strip().split(maxsplit=1)
    if not parts or not parts[0].startswith("/"):
        return None, caption.strip()
    cmd = normalize_command_name(parts[0])
    args = parts[1].strip() if len(parts) > 1 else ""
    return cmd, args


def canonical_mode(mode: str) -> Optional[str]:
    mode = normalize_command_name(mode)
    mode = MODE_ALIASES.get(mode, mode)
    return mode if mode in PHOTO_MODES else None


def is_group_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type in {"group", "supergroup"})


async def download_message_photo(update: Update) -> bytes:
    if not update.message or not update.message.photo:
        raise ValueError("No photo found.")
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    data = BytesIO()
    await tg_file.download_to_memory(out=data)
    return data.getvalue()


async def get_photo_from_update_or_reply(update: Update) -> Optional[bytes]:
    """Return photo bytes from current message or replied-to photo."""
    msg = update.message
    if not msg:
        return None

    target = msg
    if not target.photo and target.reply_to_message and target.reply_to_message.photo:
        target = target.reply_to_message

    if not target.photo:
        return None

    photo = target.photo[-1]
    tg_file = await photo.get_file()
    data = BytesIO()
    await tg_file.download_to_memory(out=data)
    return data.getvalue()


async def reply_long_text(update: Update, text: str) -> None:
    if not update.message:
        return
    if send_ai_response:
        await send_ai_response(update, text, filename="photo_ai_response.txt")
        return
    if len(text) <= 3500:
        await update.message.reply_text(text)
    else:
        for i in range(0, len(text), 3500):
            await update.message.reply_text(text[i:i + 3500])


# ------------------------------------------------------------
# Local photo filters
# ------------------------------------------------------------


def apply_enhance_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGB"))
    img = ImageEnhance.Brightness(img).enhance(1.04)
    img = ImageEnhance.Contrast(img).enhance(1.14)
    img = ImageEnhance.Color(img).enhance(1.10)
    img = ImageEnhance.Sharpness(img).enhance(1.25)
    return img


def apply_clean_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGB"))
    img = img.filter(ImageFilter.SMOOTH_MORE)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Color(img).enhance(1.06)
    img = ImageEnhance.Sharpness(img).enhance(1.12)
    return img


def apply_hdr_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGB"))
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Contrast(img).enhance(1.35)
    img = ImageEnhance.Color(img).enhance(1.18)
    img = ImageEnhance.Sharpness(img).enhance(1.55)
    return img


def apply_bw_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGB"))
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray)
    return gray.convert("RGB")


def apply_vintage_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGB"))
    img = ImageEnhance.Color(img).enhance(0.58)
    img = ImageEnhance.Contrast(img).enhance(1.14)
    img = ImageEnhance.Brightness(img).enhance(1.03)
    sepia = ImageOps.colorize(ImageOps.grayscale(img), "#3b2614", "#f2d6a2")
    img = Image.blend(img, sepia, 0.60).filter(ImageFilter.GaussianBlur(radius=0.25))
    w, h = img.size
    small = 280
    mask = Image.new("L", (small, small), 0)
    cx = cy = small / 2
    for y in range(small):
        for x in range(small):
            dx = (x - cx) / cx
            dy = (y - cy) / cy
            d = (dx * dx + dy * dy) ** 0.5
            mask.putpixel((x, y), int(255 * max(0, 1 - d * 0.9)))
    mask = mask.resize((w, h), Image.Resampling.LANCZOS)
    dark = Image.new("RGB", (w, h), "#1f1308")
    return Image.composite(img, dark, mask)


def apply_cinematic_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGB"))
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Contrast(img).enhance(1.22)
    img = ImageEnhance.Color(img).enhance(1.10)
    teal = Image.new("RGB", img.size, "#0b5d6b")
    warm = Image.new("RGB", img.size, "#f0a35d")
    shadows = Image.blend(img, teal, 0.10)
    img = Image.blend(shadows, warm, 0.06)
    return ImageEnhance.Sharpness(img).enhance(1.20)


def apply_soft_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGB"))
    soft = img.filter(ImageFilter.GaussianBlur(radius=1.4))
    img = Image.blend(img, soft, 0.28)
    img = ImageEnhance.Brightness(img).enhance(1.06)
    img = ImageEnhance.Contrast(img).enhance(0.96)
    img = ImageEnhance.Color(img).enhance(1.05)
    return img


def apply_portrait_filter(img: Image.Image) -> Image.Image:
    img = apply_clean_filter(img)
    img = ImageEnhance.Brightness(img).enhance(1.03)
    img = ImageEnhance.Contrast(img).enhance(1.05)
    img = ImageEnhance.Sharpness(img).enhance(1.18)
    return img


def apply_profile_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGB"), max_size=900)
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((900, 900), Image.Resampling.LANCZOS)
    img = apply_portrait_filter(img)
    return img


def apply_cartoon_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGB"))
    base = img.filter(ImageFilter.MedianFilter(size=5)).filter(ImageFilter.SMOOTH_MORE)
    base = ImageEnhance.Color(base).enhance(1.65)
    base = ImageEnhance.Contrast(base).enhance(1.25)
    base = ImageEnhance.Brightness(base).enhance(1.04)
    base = ImageOps.posterize(base, bits=4)
    edges = ImageOps.grayscale(img).filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.autocontrast(edges)
    edges = ImageOps.invert(edges)
    edges = edges.point(lambda p: 255 if p > 80 else 0)
    return ImageEnhance.Sharpness(ImageChops.multiply(base, edges.convert("RGB"))).enhance(1.4)


def apply_caricature_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGB"))
    base = img.filter(ImageFilter.MedianFilter(size=7)).filter(ImageFilter.SMOOTH_MORE)
    base = ImageEnhance.Color(base).enhance(2.0)
    base = ImageEnhance.Contrast(base).enhance(1.45)
    base = ImageEnhance.Brightness(base).enhance(1.05)
    base = ImageOps.posterize(base, bits=3)
    edges = ImageOps.grayscale(img).filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.autocontrast(edges)
    edges = ImageOps.invert(edges)
    edges = edges.point(lambda p: 255 if p > 90 else 0)
    return ImageEnhance.Sharpness(ImageChops.multiply(base, edges.convert("RGB"))).enhance(1.8)


def apply_sticker_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGBA"), max_size=512)
    rgb = img.convert("RGB")
    rgb = ImageEnhance.Color(rgb).enhance(1.35)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.18)
    img = rgb.convert("RGBA")
    border = 24
    shadow_offset = 10
    bordered = Image.new("RGBA", (img.width + border * 2, img.height + border * 2), (255, 255, 255, 255))
    bordered.paste(img, (border, border), img)
    final = Image.new("RGBA", (bordered.width + shadow_offset, bordered.height + shadow_offset), (0, 0, 0, 0))
    shadow = Image.new("RGBA", bordered.size, (0, 0, 0, 85)).filter(ImageFilter.GaussianBlur(radius=5))
    final.paste(shadow, (shadow_offset, shadow_offset), shadow)
    final.paste(bordered, (0, 0), bordered)
    return final


def apply_beach_filter(img: Image.Image) -> Image.Image:
    img = resize_for_telegram(img.convert("RGB"))
    img = ImageEnhance.Color(img).enhance(1.30)
    img = ImageEnhance.Contrast(img).enhance(1.10)
    img = ImageEnhance.Brightness(img).enhance(1.10)
    overlay = Image.new("RGB", img.size, "#ffd89a")
    img = Image.blend(img, overlay, 0.10)
    return ImageEnhance.Sharpness(img).enhance(1.15)


def apply_photo_mode(img: Image.Image, mode: str) -> Tuple[Image.Image, str, str]:
    mode = canonical_mode(mode) or mode
    if mode == "enhance":
        return apply_enhance_filter(img), "JPEG", "enhanced.jpg"
    if mode == "clean":
        return apply_clean_filter(img), "JPEG", "clean.jpg"
    if mode == "hdr":
        return apply_hdr_filter(img), "JPEG", "hdr.jpg"
    if mode == "bw":
        return apply_bw_filter(img), "JPEG", "black_white.jpg"
    if mode == "vintage":
        return apply_vintage_filter(img), "JPEG", "vintage.jpg"
    if mode == "cinematic":
        return apply_cinematic_filter(img), "JPEG", "cinematic.jpg"
    if mode == "soft":
        return apply_soft_filter(img), "JPEG", "soft.jpg"
    if mode == "portrait":
        return apply_portrait_filter(img), "JPEG", "portrait.jpg"
    if mode == "profile":
        return apply_profile_filter(img), "JPEG", "profile.jpg"
    if mode == "cartoon":
        return apply_cartoon_filter(img), "JPEG", "cartoon.jpg"
    if mode == "caricature":
        return apply_caricature_filter(img), "JPEG", "caricature.jpg"
    if mode == "sticker":
        return apply_sticker_filter(img), "PNG", "sticker_style.png"
    if mode == "beach":
        return apply_beach_filter(img), "JPEG", "beach.jpg"
    raise ValueError(f"Unknown photo mode: {mode}")


# ------------------------------------------------------------
# Help text
# ------------------------------------------------------------


def photo_help_text() -> str:
    return (
        "AhBashin photo tools 📸🤖\n\n"
        "Local photo editing:\n"
        "/enhance - natural enhancement\n"
        "/clean - clean photo\n"
        "/hdr - stronger detail and contrast\n"
        "/bw - black and white\n"
        "/vintage - vintage warm style\n"
        "/cinematic - cinematic look\n"
        "/soft - soft portrait look\n"
        "/portrait - portrait enhancement\n"
        "/profile - square profile photo\n"
        "/cartoon - cartoon style\n"
        "/caricature - caricature style\n"
        "/sticker - sticker-style PNG\n"
        "/beach - beach/summer style\n\n"
        "AI smart photo tools:\n"
        "/smart_photo your goal - AI chooses a filter, then you send a photo\n"
        "/photo_suggest your goal - AI recommends photo commands\n\n"
        "AI vision tools, reply to a photo or send the command then a photo:\n"
        "/photo_ai - describe and understand the photo\n"
        "/ask_photo question - ask something about the photo\n"
        "/caption_photo style - write captions\n"
        "/photo_description - concise image description\n"
        "/photo_feedback - composition/profile feedback\n\n"
        "Examples:\n"
        "/smart_photo make it professional for LinkedIn\n"
        "/ask_photo is this good for a profile picture?\n"
        "/caption_photo instagram\n"
        "/photo_feedback\n\n"
        "AI vision needs a vision model env var, for Groq for example:\n"
        "AI_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct"
    )


# ------------------------------------------------------------
# AI prompts
# ------------------------------------------------------------


def photo_vision_system_prompt(kind: str = "general") -> str:
    base = (
        "You are AhBashin Bot's AI photo assistant. "
        "Analyze the image carefully and answer the user clearly. "
        "Do not identify real people by name. Do not claim a person's identity. "
        "Do not infer sensitive traits such as religion, ethnicity, politics, health, or private identity. "
        "You may describe visible objects, setting, composition, lighting, colors, mood, and text visible in the image. "
        "If asked for photo improvement, give practical editing suggestions and suggest AhBashin photo commands when useful."
    )
    if kind == "caption":
        return base + " Write useful captions. Give 5 options unless the user asks otherwise."
    if kind == "feedback":
        return base + " Focus on constructive photography feedback: lighting, framing, background, sharpness, crop, and best filter."
    if kind == "description":
        return base + " Give a concise but informative image description."
    return base


async def call_photo_vision(image_bytes: bytes, prompt: str, kind: str = "general") -> str:
    if call_ai_vision is None:
        raise RuntimeError("AI vision helper is unavailable. Update modules/ai_module.py first.")
    return await call_ai_vision(
        system_prompt=photo_vision_system_prompt(kind),
        user_prompt=prompt[:VISION_MAX_PROMPT_CHARS],
        image_bytes=image_bytes,
        mime_type="image/jpeg",
        temperature=0.25,
        max_tokens=900,
    )


# ------------------------------------------------------------
# Smart photo mode selection
# ------------------------------------------------------------


def fallback_mode_from_goal(goal: str) -> str:
    text = goal.lower()
    if any(word in text for word in ["linkedin", "professional", "profile", "passport", "cv", "resume"]):
        return "profile"
    if any(word in text for word in ["cinematic", "movie", "film"]):
        return "cinematic"
    if any(word in text for word in ["black", "white", "bw", "monochrome"]):
        return "bw"
    if any(word in text for word in ["vintage", "old", "retro"]):
        return "vintage"
    if any(word in text for word in ["cartoon", "anime", "drawing"]):
        return "cartoon"
    if any(word in text for word in ["sticker", "telegram sticker"]):
        return "sticker"
    if any(word in text for word in ["beach", "summer", "vacation", "warm"]):
        return "beach"
    if any(word in text for word in ["soft", "gentle", "portrait"]):
        return "portrait"
    if any(word in text for word in ["sharp", "detail", "strong", "hdr"]):
        return "hdr"
    return "enhance"


async def ai_choose_photo_mode(goal: str) -> Tuple[str, str]:
    fallback = fallback_mode_from_goal(goal)
    if call_ai is None:
        return fallback, "AI text helper unavailable, so I used keyword matching."

    system = (
        "You choose one local photo editing mode for AhBashin Bot. "
        "Available modes: enhance, clean, hdr, bw, vintage, cinematic, soft, portrait, profile, cartoon, caricature, sticker, beach. "
        "Return strict JSON only with keys mode and reason. Choose exactly one mode."
    )
    user = f"User goal: {goal}\nChoose the best mode."
    try:
        answer = await call_ai(system, user, temperature=0.1)
        match = re.search(r"\{.*\}", answer, flags=re.DOTALL)
        data = json.loads(match.group(0) if match else answer)
        mode = canonical_mode(str(data.get("mode", ""))) or fallback
        reason = str(data.get("reason", "AI selected this mode."))
        return mode, reason
    except Exception:
        return fallback, "AI mode selection failed, so I used keyword matching."


# ------------------------------------------------------------
# Command handlers: local modes
# ------------------------------------------------------------


async def set_photo_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    if not update.message:
        return
    mode = canonical_mode(mode)
    if not mode:
        await update.message.reply_text("Unknown photo mode. Use /photohelp.")
        return
    context.user_data["photo_mode"] = mode
    await update.message.reply_text(
        f"{mode} mode selected. Now send me a photo 📸\n\n"
        "Tip: You can also send a photo with the command as caption."
    )


async def enhance_command(update, context): await set_photo_mode(update, context, "enhance")
async def clean_command(update, context): await set_photo_mode(update, context, "clean")
async def hdr_command(update, context): await set_photo_mode(update, context, "hdr")
async def bw_command(update, context): await set_photo_mode(update, context, "bw")
async def vintage_command(update, context): await set_photo_mode(update, context, "vintage")
async def cinematic_command(update, context): await set_photo_mode(update, context, "cinematic")
async def soft_command(update, context): await set_photo_mode(update, context, "soft")
async def portrait_command(update, context): await set_photo_mode(update, context, "portrait")
async def profile_command(update, context): await set_photo_mode(update, context, "profile")
async def cartoon_command(update, context): await set_photo_mode(update, context, "cartoon")
async def caricature_command(update, context): await set_photo_mode(update, context, "caricature")
async def sticker_command(update, context): await set_photo_mode(update, context, "sticker")
async def beach_command(update, context): await set_photo_mode(update, context, "beach")


async def photohelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(photo_help_text())


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    context.user_data.pop("photo_mode", None)
    context.user_data.pop("photo_vision_mode", None)
    await update.message.reply_text("Cancelled photo mode and AI photo mode.")


async def photoinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    image_bytes = await get_photo_from_update_or_reply(update)
    if not image_bytes:
        await update.message.reply_text("Reply to a photo with /photoinfo, or send a photo with caption /photoinfo.")
        return
    image = Image.open(BytesIO(image_bytes))
    await update.message.reply_text(
        "Photo info 🖼️\n\n"
        f"Format: {image.format or 'unknown'}\n"
        f"Size: {image.width} × {image.height}\n"
        f"Mode: {image.mode}\n"
        f"File bytes: {len(image_bytes):,}"
    )


# ------------------------------------------------------------
# Command handlers: AI smart and vision
# ------------------------------------------------------------


async def smart_photo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    goal = " ".join(context.args).strip()
    if not goal:
        await update.message.reply_text(
            "Usage:\n"
            "/smart_photo make this professional for LinkedIn\n"
            "/smart_photo make it cinematic\n"
            "/smart_photo make it black and white"
        )
        return
    await update.message.chat.send_action(action=ChatAction.TYPING)
    mode, reason = await ai_choose_photo_mode(goal)
    context.user_data["photo_mode"] = mode
    await update.message.reply_text(
        "Smart photo mode 🤖📸\n\n"
        f"Selected mode: /{mode}\n"
        f"Reason: {reason}\n\n"
        "Now send me a photo."
    )


async def photo_suggest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    goal = " ".join(context.args).strip()
    if not goal:
        await update.message.reply_text(
            "Usage:\n"
            "/photo_suggest I want a professional profile picture\n"
            "/photo_suggest I want a warm vacation look"
        )
        return
    mode, reason = await ai_choose_photo_mode(goal)
    await update.message.reply_text(
        "Photo suggestion 🤖\n\n"
        f"Best command: /{mode}\n"
        f"Reason: {reason}\n\n"
        "You can run that command, or use /smart_photo with the same request."
    )


def build_vision_prompt(command: str, args_text: str) -> Tuple[str, str]:
    command = canonical_mode(command) or normalize_command_name(command)
    args_text = args_text.strip()

    if command in {"caption_photo"}:
        style = args_text or "useful social media"
        return f"Write 5 {style} captions for this image. Keep them natural and not too long.", "caption"

    if command in {"photo_feedback"}:
        prompt = args_text or (
            "Give constructive feedback on this photo. Discuss lighting, framing, background, sharpness, crop, "
            "and which AhBashin photo command would improve it most."
        )
        return prompt, "feedback"

    if command in {"photo_description", "describe_photo"}:
        prompt = args_text or "Describe this image clearly and concisely."
        return prompt, "description"

    if command in {"ask_photo"}:
        prompt = args_text or "What is in this image?"
        return prompt, "general"

    prompt = args_text or (
        "Describe this photo. Include visible objects, scene, colors, composition, lighting, mood, "
        "and practical improvement suggestions."
    )
    return prompt, "general"


async def run_vision_on_photo(update: Update, image_bytes: bytes, command: str, args_text: str) -> None:
    if not update.message:
        return
    prompt, kind = build_vision_prompt(command, args_text)
    try:
        await update.message.chat.send_action(action=ChatAction.TYPING)
        answer = await call_photo_vision(image_bytes=image_bytes, prompt=prompt, kind=kind)
    except Exception as error:
        await update.message.reply_text(f"AI photo error.\n\n{error}")
        return
    await reply_long_text(update, answer)


async def set_or_run_vision_command(update: Update, context: ContextTypes.DEFAULT_TYPE, command: str) -> None:
    if not update.message:
        return
    args_text = " ".join(context.args).strip()
    image_bytes = await get_photo_from_update_or_reply(update)
    if image_bytes:
        await run_vision_on_photo(update, image_bytes, command, args_text)
        return

    context.user_data["photo_vision_mode"] = {"command": command, "args": args_text}
    await update.message.reply_text(
        "AI photo mode selected 🤖📸\n\n"
        "Now send me a photo, or reply to a photo with the command directly."
    )


async def photo_ai_command(update, context): await set_or_run_vision_command(update, context, "photo_ai")
async def ask_photo_command(update, context): await set_or_run_vision_command(update, context, "ask_photo")
async def caption_photo_command(update, context): await set_or_run_vision_command(update, context, "caption_photo")
async def photo_description_command(update, context): await set_or_run_vision_command(update, context, "photo_description")
async def photo_feedback_command(update, context): await set_or_run_vision_command(update, context, "photo_feedback")


# ------------------------------------------------------------
# Photo message handler
# ------------------------------------------------------------


async def process_local_photo_mode(update: Update, image_bytes: bytes, mode: str) -> None:
    if not update.message:
        return
    try:
        image = Image.open(BytesIO(image_bytes))
        edited, image_format, filename = apply_photo_mode(image, mode)
        out = image_to_bytes(edited, image_format=image_format, filename=filename)
    except Exception as error:
        await update.message.reply_text(f"Sorry, I could not process that photo.\n\nError: {error}")
        return

    caption = f"Your /{mode} photo is ready 📸"
    if image_format.upper() == "PNG" and mode == "sticker":
        await update.message.reply_document(document=InputFile(out, filename=filename), caption=caption)
    else:
        await update.message.reply_photo(photo=InputFile(out, filename=filename), caption=caption)


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.photo:
        return

    caption_cmd, caption_args = normalize_caption_command(msg.caption)

    image_bytes = await download_message_photo(update)

    # AI vision command in caption, for example photo caption: /ask_photo what is this?
    if caption_cmd in VISION_COMMANDS:
        await run_vision_on_photo(update, image_bytes, caption_cmd, caption_args)
        context.user_data.pop("photo_vision_mode", None)
        return

    # Pending AI vision mode from /photo_ai, /ask_photo, etc.
    pending_vision = context.user_data.get("photo_vision_mode")
    if isinstance(pending_vision, dict):
        command = pending_vision.get("command", "photo_ai")
        args_text = pending_vision.get("args", "")
        await run_vision_on_photo(update, image_bytes, command, args_text)
        context.user_data.pop("photo_vision_mode", None)
        return

    # Local filter mode from caption command or previous command.
    mode = None
    if caption_cmd:
        mode = canonical_mode(caption_cmd)
    if not mode:
        mode = context.user_data.get("photo_mode")

    if mode:
        await msg.reply_text("Processing your photo...")
        await process_local_photo_mode(update, image_bytes, mode)
        context.user_data.pop("photo_mode", None)
        return

    # Do not nag groups for random photos.
    if is_group_chat(update):
        return

    await msg.reply_text(
        "Please choose a photo mode first.\n\n"
        "Editing: /enhance, /cinematic, /profile, /cartoon, /sticker\n"
        "AI vision: /photo_ai, /ask_photo, /caption_photo, /photo_feedback\n"
        "Help: /photohelp"
    )


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------


def register_photo_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("photohelp", photohelp_command))

    # Local photo filters
    app.add_handler(CommandHandler("enhance", enhance_command))
    app.add_handler(CommandHandler("clean", clean_command))
    app.add_handler(CommandHandler("hdr", hdr_command))
    app.add_handler(CommandHandler("bw", bw_command))
    app.add_handler(CommandHandler("vintage", vintage_command))
    app.add_handler(CommandHandler("cinematic", cinematic_command))
    app.add_handler(CommandHandler("soft", soft_command))
    app.add_handler(CommandHandler("portrait", portrait_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("cartoon", cartoon_command))
    app.add_handler(CommandHandler("caricature", caricature_command))
    app.add_handler(CommandHandler("caricator", caricature_command))
    app.add_handler(CommandHandler("sticker", sticker_command))
    app.add_handler(CommandHandler("stiker", sticker_command))
    app.add_handler(CommandHandler("beach", beach_command))
    app.add_handler(CommandHandler("summer", beach_command))
    app.add_handler(CommandHandler("vacation", beach_command))
    app.add_handler(CommandHandler("photoinfo", photoinfo_command))
    app.add_handler(CommandHandler("photo_info", photoinfo_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    # AI smart + vision commands
    app.add_handler(CommandHandler("smart_photo", smart_photo_command))
    app.add_handler(CommandHandler("photo_suggest", photo_suggest_command))
    app.add_handler(CommandHandler("photo_ai", photo_ai_command))
    app.add_handler(CommandHandler("image_ai", photo_ai_command))
    app.add_handler(CommandHandler("vision", photo_ai_command))
    app.add_handler(CommandHandler("ask_photo", ask_photo_command))
    app.add_handler(CommandHandler("caption_photo", caption_photo_command))
    app.add_handler(CommandHandler("photo_description", photo_description_command))
    app.add_handler(CommandHandler("describe_photo", photo_description_command))
    app.add_handler(CommandHandler("photo_feedback", photo_feedback_command))

    # Only handles photos. Random group photos are ignored unless a mode/caption command is present.
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler), group=1)
