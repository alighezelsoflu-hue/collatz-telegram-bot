"""
AI text tools module for AhBashin Telegram Bot.

Free-provider design:
- Default: Groq free tier if GROQ_API_KEY is set.
- Optional: OpenRouter free models if OPENROUTER_API_KEY is set.
- Optional: OpenAI-compatible endpoint if OPENAI_API_KEY is set.
- Offline fallback: /keywords and /sentiment work without any API key.

Required package:
- httpx

Recommended Render env vars for free API mode:
AI_PROVIDER=groq
GROQ_API_KEY=your_groq_key
AI_MODEL=llama-3.1-8b-instant

Alternative OpenRouter free model mode:
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=your_openrouter_key
AI_MODEL=meta-llama/llama-3.3-70b-instruct:free
"""

import os
import re
import math
from collections import Counter
from typing import List, Optional, Tuple

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

try:
    from utils import split_long_text, text_to_file
except Exception:
    from io import BytesIO

    def split_long_text(text: str, limit: int = 3500) -> List[str]:
        if len(text) <= limit:
            return [text]
        chunks = []
        while text:
            chunks.append(text[:limit])
            text = text[limit:]
        return chunks

    def text_to_file(text: str, filename: str) -> BytesIO:
        output = BytesIO()
        output.write(text.encode("utf-8"))
        output.seek(0)
        output.name = filename
        return output


# ------------------------------------------------------------
# Render-safe limits
# ------------------------------------------------------------

MAX_INPUT_CHARS = int(os.getenv("AI_MAX_INPUT_CHARS", "6000"))
MAX_OUTPUT_TOKENS = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "900"))
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "35"))


# ------------------------------------------------------------
# Provider configuration
# ------------------------------------------------------------


def get_ai_provider() -> str:
    configured = os.getenv("AI_PROVIDER", "").strip().lower()
    if configured:
        return configured
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "offline"


def get_ai_model(provider: str) -> str:
    configured = os.getenv("AI_MODEL", "").strip()
    if configured:
        return configured
    if provider == "groq":
        return "llama-3.1-8b-instant"
    if provider == "openrouter":
        # Free OpenRouter model names can change. Override AI_MODEL in Render if needed.
        return "meta-llama/llama-3.3-70b-instruct:free"
    if provider == "openai":
        return "gpt-4o-mini"
    return "offline"


def get_api_config(provider: str) -> Tuple[Optional[str], Optional[str]]:
    if provider == "groq":
        return "https://api.groq.com/openai/v1/chat/completions", os.getenv("GROQ_API_KEY")
    if provider == "openrouter":
        return "https://openrouter.ai/api/v1/chat/completions", os.getenv("OPENROUTER_API_KEY")
    if provider == "openai":
        return "https://api.openai.com/v1/chat/completions", os.getenv("OPENAI_API_KEY")
    return None, None


class AIProviderError(Exception):
    pass


async def call_ai(system_prompt: str, user_prompt: str, temperature: float = 0.4) -> str:
    provider = get_ai_provider()
    model = get_ai_model(provider)
    url, api_key = get_api_config(provider)

    if provider == "offline" or not url or not api_key:
        raise AIProviderError(
            "AI API is not configured. Set one free-provider key in Render, for example:\n"
            "AI_PROVIDER=groq\n"
            "GROQ_API_KEY=your_key\n"
            "AI_MODEL=llama-3.1-8b-instant\n\n"
            "Offline commands still work: /keywords and /sentiment"
        )

    user_prompt = user_prompt.strip()
    if len(user_prompt) > MAX_INPUT_CHARS:
        user_prompt = user_prompt[:MAX_INPUT_CHARS] + "\n\n[Input was truncated for safety.]"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if provider == "openrouter":
        site_url = os.getenv("OPENROUTER_SITE_URL", "https://collatz-telegram-bot.onrender.com")
        app_name = os.getenv("OPENROUTER_APP_NAME", "LakLak Telegram Bot")
        headers["HTTP-Referer"] = site_url
        headers["X-Title"] = app_name

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": MAX_OUTPUT_TOKENS,
    }

    try:
        async with httpx.AsyncClient(timeout=AI_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        raise AIProviderError("The AI provider timed out. Try a shorter message.")
    except Exception as error:
        raise AIProviderError(f"Could not contact AI provider: {error}")

    if response.status_code >= 400:
        error_text = response.text[:900]
        raise AIProviderError(
            f"AI provider error {response.status_code}.\n\n"
            f"Provider: {provider}\n"
            f"Model: {model}\n"
            f"Message: {error_text}"
        )

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except Exception:
        raise AIProviderError("AI provider returned an unexpected response format.")

    return str(content).strip()


# ------------------------------------------------------------
# Text extraction helpers
# ------------------------------------------------------------


def get_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    args_text = " ".join(context.args).strip()
    if args_text:
        return args_text

    if update.message and update.message.reply_to_message:
        reply = update.message.reply_to_message
        if reply.text:
            return reply.text.strip()
        if reply.caption:
            return reply.caption.strip()

    return ""


def split_with_mode(text: str, default_mode: str = "default") -> Tuple[str, str]:
    text = text.strip()
    if "|" in text:
        left, right = text.split("|", 1)
        mode = left.strip().lower() or default_mode
        content = right.strip()
        return mode, content
    parts = text.split(maxsplit=1)
    if len(parts) >= 2 and parts[0].lower() in {
        "formal", "friendly", "short", "simple", "professional", "casual",
        "fa", "en", "de", "fr", "es", "ar", "it", "tr",
    }:
        return parts[0].lower(), parts[1].strip()
    return default_mode, text


async def send_ai_response(update: Update, text: str, filename: str = "ai_response.txt") -> None:
    if not update.message:
        return
    if len(text) <= 3500:
        await update.message.reply_text(text)
    elif len(text) <= 10000:
        for chunk in split_long_text(text, limit=3500):
            await update.message.reply_text(chunk)
    else:
        await update.message.reply_document(document=text_to_file(text, filename), caption="AI response")


async def run_ai_command(update: Update, system_prompt: str, user_prompt: str, usage: str, temperature: float = 0.4) -> None:
    if not update.message:
        return

    if not user_prompt.strip():
        await update.message.reply_text(usage)
        return

    try:
        await update.message.chat.send_action(action="typing")
        answer = await call_ai(system_prompt, user_prompt, temperature=temperature)
    except Exception as error:
        await update.message.reply_text(f"AI error.\n\n{error}")
        return

    await send_ai_response(update, answer)


# ------------------------------------------------------------
# Help
# ------------------------------------------------------------


def ai_help_text() -> str:
    provider = get_ai_provider()
    model = get_ai_model(provider)
    configured = provider != "offline"
    status = "configured" if configured else "offline fallback only"

    return (
        "AI text tools 🤖\n\n"
        f"Status: {status}\n"
        f"Provider: {provider}\n"
        f"Model: {model}\n\n"
        "Commands using AI API:\n"
        "/askai your question - general AI assistant\n"
        "/summarize long text - summarize text\n"
        "/rewrite formal | text - rewrite in a tone\n"
        "/explain difficult text - simple explanation\n"
        "/translate_ai fa | text - translate with context\n"
        "/quiz text/topic - generate quiz questions\n"
        "/flashcards text/topic - generate flashcards\n"
        "/code_explain code - explain code\n"
        "/code_fix error/code - suggest a fix\n"
        "/regex request - generate regex\n"
        "/sql request - generate SQL\n\n"
        "Offline commands, no API key needed:\n"
        "/keywords text - extract keywords\n"
        "/sentiment text - simple sentiment detection\n\n"
        "Examples:\n"
        "/askai explain black holes simply\n"
        "/rewrite professional | send me the file now\n"
        "/translate_ai fa | Hello, how are you?\n"
        "/code_fix TypeError: unsupported operand type(s) for +: int and str\n\n"
        "Free API setup example on Render:\n"
        "AI_PROVIDER=groq\n"
        "GROQ_API_KEY=your_key\n"
        "AI_MODEL=llama-3.1-8b-instant"
    )


async def aihelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(ai_help_text())


# ------------------------------------------------------------
# API-backed commands
# ------------------------------------------------------------


async def askai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = get_message_text(update, context)
    await run_ai_command(
        update,
        "You are AhBashin Bot, a helpful, concise Telegram assistant. Give accurate, practical answers.",
        text,
        "Usage:\n/askai explain black holes simply\n\nYou can also reply to a message with /askai",
        temperature=0.5,
    )


async def summarize_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = get_message_text(update, context)
    await run_ai_command(
        update,
        "Summarize the user's text clearly. Include key points and keep it concise unless the text is complex.",
        text,
        "Usage:\n/summarize long text here\n\nYou can also reply to a long message with /summarize",
        temperature=0.2,
    )


async def rewrite_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = get_message_text(update, context)
    mode, text = split_with_mode(raw, "professional")
    await run_ai_command(
        update,
        f"Rewrite the user's text in a {mode} tone. Preserve the original meaning. Return only the rewritten text.",
        text,
        "Usage:\n/rewrite formal | hey bro I need the report today\n/rewrite short | your long text",
        temperature=0.4,
    )


async def explain_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = get_message_text(update, context)
    await run_ai_command(
        update,
        "Explain the user's text simply and clearly. Use examples when helpful. Avoid unnecessary jargon.",
        text,
        "Usage:\n/explain Quantum entanglement is...\n\nYou can also reply to text with /explain",
        temperature=0.3,
    )


async def translate_ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = get_message_text(update, context)
    lang, text = split_with_mode(raw, "fa")
    await run_ai_command(
        update,
        f"Translate the user's text to {lang}. Preserve tone and context. Return only the translation.",
        text,
        "Usage:\n/translate_ai fa | Hello, how are you?\n/translate_ai en | سلام خوبی؟",
        temperature=0.2,
    )


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = get_message_text(update, context)
    await run_ai_command(
        update,
        "Create a short quiz from the user's topic or text. Make 5 questions. Include answers at the end.",
        text,
        "Usage:\n/quiz photosynthesis\n/quiz paste lesson text here",
        temperature=0.5,
    )


async def flashcards_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = get_message_text(update, context)
    await run_ai_command(
        update,
        "Create useful study flashcards from the user's topic or text. Format as Q: ... A: ...",
        text,
        "Usage:\n/flashcards Newton laws\n/flashcards paste study text here",
        temperature=0.4,
    )


async def code_explain_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = get_message_text(update, context)
    await run_ai_command(
        update,
        "Explain the code clearly. Describe what it does, important lines, and possible issues.",
        text,
        "Usage:\n/code_explain print([x*x for x in range(10)])\n\nYou can also reply to code with /code_explain",
        temperature=0.2,
    )


async def code_fix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = get_message_text(update, context)
    await run_ai_command(
        update,
        "Help fix the user's programming error or code. Explain the cause and provide corrected code when possible.",
        text,
        "Usage:\n/code_fix TypeError: unsupported operand type(s) for +: 'int' and 'str'",
        temperature=0.2,
    )


async def regex_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = get_message_text(update, context)
    await run_ai_command(
        update,
        "Generate a regex for the user's request. Include the regex, explanation, and 2 examples. Be careful with escaping.",
        text,
        "Usage:\n/regex extract emails from text\n/regex match Iranian phone numbers",
        temperature=0.2,
    )


async def sql_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = get_message_text(update, context)
    await run_ai_command(
        update,
        "Generate SQL for the user's request. Prefer standard SQL. Include a short explanation. Do not invent table names unless given.",
        text,
        "Usage:\n/sql table users columns id,name,age. Find users older than 30",
        temperature=0.2,
    )


# ------------------------------------------------------------
# Offline commands
# ------------------------------------------------------------


STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "you", "your", "have",
    "has", "had", "but", "not", "can", "will", "would", "there", "their", "about", "into", "than",
    "then", "they", "them", "our", "out", "all", "any", "because", "been", "being", "what", "when",
    "where", "which", "who", "how", "why", "is", "am", "be", "to", "of", "in", "on", "a", "an",
    "it", "as", "at", "or", "by", "if", "we", "he", "she", "his", "her", "i", "me", "my",
}

POSITIVE_WORDS = {
    "good", "great", "excellent", "amazing", "happy", "love", "like", "best", "perfect", "nice", "awesome",
    "wonderful", "beautiful", "success", "successful", "fast", "helpful", "enjoy", "enjoyed", "positive",
}

NEGATIVE_WORDS = {
    "bad", "terrible", "awful", "sad", "hate", "worst", "broken", "slow", "angry", "problem", "error",
    "failed", "fail", "failure", "negative", "poor", "ugly", "annoying", "hard", "difficult", "pain",
}


def tokenize_words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9_'-]{2,}", text.lower())


async def keywords_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = get_message_text(update, context)
    if not text:
        await update.message.reply_text("Usage:\n/keywords paste your text here")
        return

    words = [w for w in tokenize_words(text) if w not in STOPWORDS]
    if not words:
        await update.message.reply_text("No useful keywords found.")
        return

    counts = Counter(words)
    top = counts.most_common(15)
    lines = ["Keywords 🔑", ""]
    for word, count in top:
        lines.append(f"- {word}: {count}")
    await update.message.reply_text("\n".join(lines))


async def sentiment_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = get_message_text(update, context)
    if not text:
        await update.message.reply_text("Usage:\n/sentiment I am very happy today")
        return

    words = tokenize_words(text)
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    score = pos - neg

    if score > 0:
        label = "Positive 🙂"
    elif score < 0:
        label = "Negative 🙁"
    else:
        label = "Neutral 😐"

    confidence = min(1.0, abs(score) / max(1, math.sqrt(len(words)))) if words else 0.0
    await update.message.reply_text(
        "Sentiment analysis 🧭\n\n"
        f"Result: {label}\n"
        f"Positive words: {pos}\n"
        f"Negative words: {neg}\n"
        f"Score: {score}\n"
        f"Confidence: {confidence:.2f}\n\n"
        "Note: this offline sentiment tool is simple and keyword-based."
    )


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------


def register_ai_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("aihelp", aihelp_command))
    app.add_handler(CommandHandler("askai", askai_command))
    app.add_handler(CommandHandler("ai", askai_command))
    app.add_handler(CommandHandler("summarize", summarize_command))
    app.add_handler(CommandHandler("rewrite", rewrite_command))
    app.add_handler(CommandHandler("explain", explain_command))
    app.add_handler(CommandHandler("translate_ai", translate_ai_command))
    app.add_handler(CommandHandler("aitranslate", translate_ai_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("flashcards", flashcards_command))
    app.add_handler(CommandHandler("code_explain", code_explain_command))
    app.add_handler(CommandHandler("codefix", code_fix_command))
    app.add_handler(CommandHandler("code_fix", code_fix_command))
    app.add_handler(CommandHandler("regex", regex_command))
    app.add_handler(CommandHandler("sql", sql_command))
    app.add_handler(CommandHandler("keywords", keywords_command))
    app.add_handler(CommandHandler("sentiment", sentiment_command))
