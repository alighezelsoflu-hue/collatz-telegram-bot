import html
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

import feedparser
import httpx
from deep_translator import GoogleTranslator
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TRUMP_NEWS_QUERY, TRUMP_NEWS_ITEMS
from utils import split_long_text, text_to_file


# ------------------------------------------------------------
# Text cleaning helpers
# ------------------------------------------------------------

def clean_rss_text(text: str) -> str:
    if not text:
        return ""

    text = html.unescape(str(text))
    text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def clean_article_text(text: str) -> str:
    text = clean_rss_text(text)

    junk_patterns = [
        r"Subscribe now.*",
        r"Sign up.*",
        r"Create your free account.*",
        r"Advertisement.*",
        r"Read more.*",
        r"Continue reading.*",
    ]

    for pattern in junk_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

    return text


def shorten_text(text: str, max_length: int = 750) -> str:
    text = clean_article_text(text)

    if len(text) <= max_length:
        return text

    shortened = text[:max_length].rsplit(" ", 1)[0]
    return shortened + "..."


def remove_duplicate_sentences(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    seen = set()
    unique = []

    for sentence in sentences:
        key = sentence.lower().strip()

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        unique.append(sentence.strip())

    return " ".join(unique).strip()


# ------------------------------------------------------------
# Translation helpers
# ------------------------------------------------------------

def translate_to_farsi(text: str) -> str:
    if not text:
        return ""

    try:
        # GoogleTranslator works better with smaller chunks.
        text = text.strip()

        if len(text) <= 3500:
            return GoogleTranslator(source="auto", target="fa").translate(text)

        chunks = []
        current = ""

        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if len(current) + len(sentence) + 1 > 3000:
                if current:
                    chunks.append(current)
                current = sentence
            else:
                current += (" " if current else "") + sentence

        if current:
            chunks.append(current)

        translated_chunks = []

        for chunk in chunks:
            translated_chunks.append(
                GoogleTranslator(source="auto", target="fa").translate(chunk)
            )

        return "\n".join(translated_chunks)

    except Exception:
        return "ترجمه در دسترس نیست."


def translate_optional(text: str, fallback: str = "نامشخص") -> str:
    if not text:
        return fallback

    translated = translate_to_farsi(text)

    if not translated or translated == "ترجمه در دسترس نیست.":
        return fallback

    return translated


# ------------------------------------------------------------
# Article metadata extraction
# ------------------------------------------------------------

def extract_meta_content(html_text: str, meta_name: str) -> Optional[str]:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(meta_name)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(meta_name)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(meta_name)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(meta_name)}["\']',
    ]

    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)

        if match:
            return clean_article_text(match.group(1))

    return None


def extract_article_description_from_html(html_text: str) -> Optional[str]:
    candidates = [
        extract_meta_content(html_text, "og:description"),
        extract_meta_content(html_text, "twitter:description"),
        extract_meta_content(html_text, "description"),
    ]

    for candidate in candidates:
        if candidate and len(candidate) > 40:
            return candidate

    return None


async def fetch_article_details(url: str) -> Optional[str]:
    if not url:
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; LakLakBot/1.0; +https://telegram.org)"
        )
    }

    try:
        async with httpx.AsyncClient(
            timeout=8.0,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(url)

        if response.status_code >= 400:
            return None

        content_type = response.headers.get("content-type", "").lower()

        if "text/html" not in content_type:
            return None

        description = extract_article_description_from_html(response.text)

        if description:
            return shorten_text(description, 900)

    except Exception:
        return None

    return None


# ------------------------------------------------------------
# RSS parsing helpers
# ------------------------------------------------------------

def get_entry_source(entry: Any, title: str) -> str:
    try:
        source_title = getattr(entry, "source", {}).get("title", "")
        source_title = clean_rss_text(source_title)

        if source_title:
            return source_title
    except Exception:
        pass

    if " - " in title:
        possible_source = title.rsplit(" - ", 1)[1].strip()

        if possible_source:
            return clean_rss_text(possible_source)

    return "Unknown source"


def get_entry_headline(entry: Any) -> str:
    title = clean_rss_text(getattr(entry, "title", ""))

    if " - " in title:
        headline = title.rsplit(" - ", 1)[0].strip()
    else:
        headline = title.strip()

    return headline or "Untitled article"


def get_entry_rss_summary(entry: Any, headline: str) -> str:
    summary_parts = []

    summary = clean_rss_text(getattr(entry, "summary", ""))
    description = clean_rss_text(getattr(entry, "description", ""))

    if summary:
        summary_parts.append(summary)

    if description and description != summary:
        summary_parts.append(description)

    try:
        content_items = getattr(entry, "content", [])

        for item in content_items:
            value = clean_rss_text(item.get("value", ""))

            if value:
                summary_parts.append(value)
    except Exception:
        pass

    combined = remove_duplicate_sentences(" ".join(summary_parts))

    if not combined:
        return ""

    combined_lower = combined.lower()
    headline_lower = headline.lower()

    if combined_lower == headline_lower:
        return ""

    if headline_lower in combined_lower and len(combined) < len(headline) + 80:
        return ""

    return shorten_text(combined, 750)


def build_key_details_en(headline: str, summary: str, source: str, published: str) -> str:
    details = []

    if headline:
        details.append(f"Main point: {headline}")

    if source and source != "Unknown source":
        details.append(f"Reported by: {source}")

    if published and published != "time unavailable":
        details.append(f"Published: {published}")

    if summary and not summary.startswith("A detailed article summary was not available"):
        first_sentence = re.split(r"(?<=[.!?])\s+", summary)[0].strip()

        if first_sentence and first_sentence.lower() not in headline.lower():
            details.append(f"Extra detail: {first_sentence}")

    return "\n".join(f"- {item}" for item in details)


def build_key_details_fa(headline_fa: str, summary_fa: str, source_fa: str, published_fa: str) -> str:
    details = []

    if headline_fa:
        details.append(f"نکته اصلی: {headline_fa}")

    if source_fa:
        details.append(f"گزارش‌شده توسط: {source_fa}")

    if published_fa:
        details.append(f"زمان انتشار: {published_fa}")

    if summary_fa and summary_fa != "جزئیات بیشتری از این خبر در دسترس نیست.":
        first_sentence = re.split(r"(?<=[.!?؟])\s+", summary_fa)[0].strip()

        if first_sentence:
            details.append(f"جزئیات بیشتر: {first_sentence}")

    return "\n".join(f"- {item}" for item in details)


async def summarize_news_entry(entry: Any) -> Dict[str, str]:
    headline = get_entry_headline(entry)
    title = clean_rss_text(getattr(entry, "title", ""))
    source = get_entry_source(entry, title)

    published = clean_rss_text(getattr(entry, "published", "time unavailable"))
    link = clean_rss_text(getattr(entry, "link", ""))

    rss_summary = get_entry_rss_summary(entry, headline)
    article_details = await fetch_article_details(link)

    if article_details:
        detailed_summary = article_details
        summary_source = "Article metadata"
    elif rss_summary:
        detailed_summary = rss_summary
        summary_source = "Google News RSS"
    else:
        detailed_summary = (
            "A detailed article summary was not available from the RSS feed. "
            "Open the source link for the full report."
        )
        summary_source = "Fallback"

    key_details = build_key_details_en(headline, detailed_summary, source, published)

    return {
        "headline": headline,
        "source": source,
        "published": published,
        "link": link,
        "summary": detailed_summary,
        "summary_source": summary_source,
        "key_details": key_details,
    }


# ------------------------------------------------------------
# Report builders
# ------------------------------------------------------------

def build_news_item_text(index: int, item: Dict[str, str]) -> str:
    headline = item["headline"]
    source = item["source"]
    published = item["published"]
    summary = item["summary"]
    summary_source = item["summary_source"]
    key_details = item["key_details"]
    link = item["link"]

    headline_fa = translate_optional(headline)
    source_fa = translate_optional(source)
    published_fa = translate_optional(published)
    summary_source_fa = translate_optional(summary_source)
    summary_fa = translate_optional(summary, fallback="جزئیات بیشتری از این خبر در دسترس نیست.")
    key_details_fa = build_key_details_fa(
        headline_fa=headline_fa,
        summary_fa=summary_fa,
        source_fa=source_fa,
        published_fa=published_fa,
    )

    lines = [
        f"{index}. {headline}",
        f"Source: {source}",
        f"Published: {published}",
        f"Summary source: {summary_source}",
        "",
        "Detailed summary:",
        summary,
        "",
        "Key details:",
        key_details,
    ]

    if link:
        lines.extend(
            [
                "",
                f"Link: {link}",
            ]
        )

    lines.extend(
        [
            "",
            "ترجمه کامل فارسی:",
            "",
            f"{index}. {headline_fa}",
            f"منبع: {source_fa}",
            f"زمان انتشار: {published_fa}",
            f"منبع خلاصه: {summary_source_fa}",
            "",
            "خلاصه تفصیلی:",
            summary_fa,
            "",
            "جزئیات کلیدی:",
            key_details_fa,
        ]
    )

    if link:
        lines.extend(
            [
                "",
                f"لینک: {link}",
            ]
        )

    lines.extend(
        [
            "",
            "-" * 50,
            "",
        ]
    )

    return "\n".join(lines)


async def build_trump_news_report() -> str:
    query = quote_plus(TRUMP_NEWS_QUERY)
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    feed = feedparser.parse(rss_url)
    entries = list(feed.entries)

    if not entries:
        raise ValueError("I could not find recent Trump-related news right now.")

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
        "English + full Farsi translation",
        "Source: Google News RSS, with article metadata when available",
        "",
        "خلاصه آخرین خبرهای مرتبط با ترامپ",
        "مرتب‌شده بر اساس زمان، از جدیدترین به قدیمی‌ترین",
        "انگلیسی + ترجمه کامل فارسی",
        "منبع: Google News RSS، همراه با متادیتای مقاله در صورت دسترسی",
        "",
    ]

    for index, entry in enumerate(entries, start=1):
        item = await summarize_news_entry(entry)
        lines.append(build_news_item_text(index, item))

    return "\n".join(lines)


# ------------------------------------------------------------
# Telegram commands
# ------------------------------------------------------------

async def trump_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        await update.message.reply_text(
            "Loading latest Trump-related news with full Farsi translation..."
        )

        text = await build_trump_news_report()

        for chunk in split_long_text(text, limit=3500):
            await update.message.reply_text(chunk)

    except Exception as error:
        await update.message.reply_text(
            f"Could not load Trump-related news summary.\n\nError: {error}"
        )


async def trumpfile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        await update.message.reply_text(
            "Creating detailed bilingual Trump-related news report file..."
        )

        text = await build_trump_news_report()
        filename = "trump_news_bilingual_report.txt"
        file_output = text_to_file(text, filename)

        await update.message.reply_document(
            document=InputFile(file_output, filename=filename),
            caption="Detailed bilingual Trump-related news report",
        )

    except Exception as error:
        await update.message.reply_text(
            f"Could not create Trump-related news report.\n\nError: {error}"
        )


def register_news_handlers(app: Application) -> None:
    app.add_handler(CommandHandler(["trump", "Trump"], trump_command))
    app.add_handler(CommandHandler(["trumpfile", "Trumpfile"], trumpfile_command))