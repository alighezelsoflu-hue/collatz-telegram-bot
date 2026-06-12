import html
import re
import time
from typing import Any, Tuple
from urllib.parse import quote_plus

import feedparser
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TRUMP_NEWS_QUERY, TRUMP_NEWS_ITEMS
from utils import split_long_text


# ------------------------------------------------------------
# News helpers
# ------------------------------------------------------------

def clean_rss_text(text: str) -> str:
    if not text:
        return ""

    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def summarize_news_entry(entry: Any) -> Tuple[str, str, str]:
    title = clean_rss_text(getattr(entry, "title", ""))
    summary = clean_rss_text(getattr(entry, "summary", ""))

    # Google News RSS often includes the source at the end:
    # Example: "Some headline - Reuters"
    if " - " in title:
        headline, source = title.rsplit(" - ", 1)
    else:
        headline, source = title, "Unknown source"

    if summary and summary != title:
        short_summary = summary
    else:
        short_summary = headline

    if len(short_summary) > 350:
        short_summary = short_summary[:347] + "..."

    return headline, source, short_summary


def translate_to_farsi(text: str) -> str:
    if not text:
        return ""

    try:
        # Keep text shorter to reduce translation errors.
        text = text[:450]
        return GoogleTranslator(source="auto", target="fa").translate(text)
    except Exception:
        return "ترجمه در دسترس نیست."


# ------------------------------------------------------------
# Telegram command
# ------------------------------------------------------------

async def trump_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        query = quote_plus(TRUMP_NEWS_QUERY)
        rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

        feed = feedparser.parse(rss_url)
        entries = list(feed.entries)

        if not entries:
            await update.message.reply_text("I could not find recent Trump-related news right now.")
            return

        # Chronological order: newest first.
        entries.sort(
            key=lambda entry: time.mktime(entry.published_parsed)
            if hasattr(entry, "published_parsed") and entry.published_parsed
            else 0,
            reverse=True,
        )

        count = max(1, min(TRUMP_NEWS_ITEMS, 10))
        entries = entries[:count]

        lines = [
            "Latest Trump-related news summary",
            "Sorted chronologically, newest first",
            "English + Farsi translation",
            "Source: Google News RSS",
            "",
        ]

        for index, entry in enumerate(entries, start=1):
            headline, source, short_summary = summarize_news_entry(entry)
            published = clean_rss_text(getattr(entry, "published", "time unavailable"))

            headline_fa = translate_to_farsi(headline)
            summary_fa = translate_to_farsi(short_summary)

            lines.append(f"{index}. {headline}")
            lines.append(f"Source: {source}")
            lines.append(f"Published: {published}")
            lines.append(f"Summary: {short_summary}")
            lines.append("")
            lines.append("ترجمه فارسی:")
            lines.append(f"عنوان: {headline_fa}")
            lines.append(f"خلاصه: {summary_fa}")
            lines.append("")
            lines.append("-" * 40)
            lines.append("")

        text = "\n".join(lines)

        for chunk in split_long_text(text):
            await update.message.reply_text(chunk)

    except Exception as error:
        await update.message.reply_text(
            f"Could not load Trump-related news summary.\n\nError: {error}"
        )


def register_news_handlers(app: Application) -> None:
    app.add_handler(CommandHandler(["trump", "Trump"], trump_command))