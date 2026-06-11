import os
from typing import List

from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)


MAX_INPUT = 10**12
MAX_RETURNED_SEQUENCE_ITEMS = 120

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Example: https://your-app-name.onrender.com
SECRET_PATH = os.getenv("SECRET_PATH", "telegram-webhook")

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")

telegram_app = Application.builder().token(TOKEN).build()
api = FastAPI(title="Collatz Telegram Bot")


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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hello! I calculate Collatz sequences.\n\n"
        "Use:\n"
        "/collatz 26\n"
        "/collatz 27\n\n"
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


telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(CommandHandler("collatz", collatz_command))


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
        "message": "Collatz Telegram Bot is running.",
        "usage": "/collatz 27",
    }


@api.post("/{path}")
async def telegram_webhook(path: str, request: Request):
    if path != SECRET_PATH:
        raise HTTPException(status_code=404, detail="Not found")

    data = await request.json()
    update = Update.de_json(data=data, bot=telegram_app.bot)

    await telegram_app.process_update(update)

    return {"ok": True}