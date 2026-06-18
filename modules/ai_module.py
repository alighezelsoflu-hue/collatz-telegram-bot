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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

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
# Persistent per-user AI memory
# ------------------------------------------------------------

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # psycopg is optional for local tests; Render should have psycopg[binary].
    psycopg = None
    dict_row = None


AI_MEMORY_ENABLED = os.getenv("AI_MEMORY_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
AI_MEMORY_MAX_MESSAGES = int(os.getenv("AI_MEMORY_MAX_MESSAGES", "16"))
AI_MEMORY_MAX_MESSAGE_CHARS = int(os.getenv("AI_MEMORY_MAX_MESSAGE_CHARS", "2500"))
AI_MEMORY_MAX_TOTAL_CHARS = int(os.getenv("AI_MEMORY_MAX_TOTAL_CHARS", "12000"))
AI_MEMORY_DB_URL = os.getenv("DATABASE_URL", "").strip()

AI_TOPIC_ALIASES: Dict[str, str] = {
    "general": "general",
    "chat": "general",
    "ai": "general",
    "math": "math",
    "mathematics": "math",
    "data": "data_science",
    "ds": "data_science",
    "data_science": "data_science",
    "datascience": "data_science",
    "stats": "data_science",
    "statistics": "data_science",
    "physics": "physics",
    "phys": "physics",
    "chem": "chemistry",
    "chemistry": "chemistry",
    "astro": "astronomy",
    "astronomy": "astronomy",
    "space": "astronomy",
    "photo": "photo",
    "image": "photo",
    "vision": "photo",
}

AI_TOPIC_LABELS = {
    "general": "General",
    "math": "Math",
    "data_science": "Data science",
    "physics": "Physics",
    "chemistry": "Chemistry",
    "astronomy": "Astronomy",
    "photo": "Photo / vision",
}

# Fallback memory for local runs without DATABASE_URL. Render restarts will reset this.
_LOCAL_AI_MEMORY: Dict[tuple, List[Dict[str, str]]] = defaultdict(list)
_LOCAL_AI_ACTIVE_TOPIC: Dict[tuple, str] = {}
_AI_MEMORY_DB_READY = False


def normalize_ai_topic(topic: Optional[str]) -> str:
    if not topic:
        return "general"
    key = str(topic).strip().lower().replace("-", "_")
    return AI_TOPIC_ALIASES.get(key, key if key in AI_TOPIC_LABELS else "general")


def split_topic_prefix(text: str) -> Tuple[Optional[str], str]:
    """If the first token is a topic, return (topic, text_without_topic)."""
    parts = (text or "").strip().split(maxsplit=1)
    if not parts:
        return None, ""
    maybe = normalize_ai_topic(parts[0])
    raw = parts[0].strip().lower().replace("-", "_")
    if raw in AI_TOPIC_ALIASES or raw in AI_TOPIC_LABELS:
        return maybe, parts[1].strip() if len(parts) > 1 else ""
    return None, text.strip()


def _memory_identity(update: Optional[Update]) -> Tuple[str, str]:
    chat_id = "unknown_chat"
    user_id = "unknown_user"
    try:
        if update and update.effective_chat:
            chat_id = str(update.effective_chat.id)
        if update and update.effective_user:
            user_id = str(update.effective_user.id)
        elif update and update.effective_chat:
            user_id = str(update.effective_chat.id)
    except Exception:
        pass
    return chat_id, user_id


def _truncate_memory_text(text: str) -> str:
    text = (text or "").strip()
    if len(text) > AI_MEMORY_MAX_MESSAGE_CHARS:
        return text[:AI_MEMORY_MAX_MESSAGE_CHARS] + "\n...[truncated]"
    return text


def _db_enabled() -> bool:
    return bool(AI_MEMORY_ENABLED and AI_MEMORY_DB_URL and psycopg is not None)


def _connect_memory_db():
    return psycopg.connect(AI_MEMORY_DB_URL, row_factory=dict_row)


def ensure_ai_memory_tables() -> None:
    global _AI_MEMORY_DB_READY
    if _AI_MEMORY_DB_READY or not _db_enabled():
        return
    with _connect_memory_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_chat_messages (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    topic TEXT NOT NULL DEFAULT 'general',
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_lookup
                ON ai_chat_messages (chat_id, user_id, topic, id DESC)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_chat_state (
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    active_topic TEXT NOT NULL DEFAULT 'general',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (chat_id, user_id)
                )
                """
            )
        conn.commit()
    _AI_MEMORY_DB_READY = True


def set_active_ai_topic(update: Optional[Update], topic: str) -> None:
    topic = normalize_ai_topic(topic)
    chat_id, user_id = _memory_identity(update)
    if _db_enabled():
        ensure_ai_memory_tables()
        with _connect_memory_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_chat_state (chat_id, user_id, active_topic, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (chat_id, user_id)
                    DO UPDATE SET active_topic = EXCLUDED.active_topic, updated_at = NOW()
                    """,
                    (chat_id, user_id, topic),
                )
            conn.commit()
    else:
        _LOCAL_AI_ACTIVE_TOPIC[(chat_id, user_id)] = topic


def get_active_ai_topic(update: Optional[Update]) -> str:
    chat_id, user_id = _memory_identity(update)
    if _db_enabled():
        ensure_ai_memory_tables()
        with _connect_memory_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT active_topic FROM ai_chat_state WHERE chat_id=%s AND user_id=%s",
                    (chat_id, user_id),
                )
                row = cur.fetchone()
                return normalize_ai_topic(row["active_topic"]) if row else "general"
    return _LOCAL_AI_ACTIVE_TOPIC.get((chat_id, user_id), "general")


def save_ai_message(update: Optional[Update], topic: str, role: str, content: str) -> None:
    if not AI_MEMORY_ENABLED:
        return
    topic = normalize_ai_topic(topic)
    role = "assistant" if role == "assistant" else "user"
    content = _truncate_memory_text(content)
    if not content:
        return
    chat_id, user_id = _memory_identity(update)
    if _db_enabled():
        ensure_ai_memory_tables()
        with _connect_memory_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_chat_messages (chat_id, user_id, topic, role, content)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (chat_id, user_id, topic, role, content),
                )
            conn.commit()
    else:
        key = (chat_id, user_id, topic)
        _LOCAL_AI_MEMORY[key].append({"role": role, "content": content})
        _LOCAL_AI_MEMORY[key] = _LOCAL_AI_MEMORY[key][-AI_MEMORY_MAX_MESSAGES * 2:]


def save_ai_turn(update: Optional[Update], topic: str, user_prompt: str, assistant_response: str) -> None:
    topic = normalize_ai_topic(topic)
    save_ai_message(update, topic, "user", user_prompt)
    save_ai_message(update, topic, "assistant", assistant_response)
    set_active_ai_topic(update, topic)


def get_ai_history(update: Optional[Update], topic: str, limit: Optional[int] = None) -> List[Dict[str, str]]:
    topic = normalize_ai_topic(topic)
    limit = int(limit or AI_MEMORY_MAX_MESSAGES)
    chat_id, user_id = _memory_identity(update)
    if not AI_MEMORY_ENABLED:
        return []
    if _db_enabled():
        ensure_ai_memory_tables()
        with _connect_memory_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role, content
                    FROM ai_chat_messages
                    WHERE chat_id=%s AND user_id=%s AND topic=%s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (chat_id, user_id, topic, limit),
                )
                rows = cur.fetchall() or []
                rows = list(reversed(rows))
                return [{"role": row["role"], "content": row["content"]} for row in rows]
    return list(_LOCAL_AI_MEMORY.get((chat_id, user_id, topic), []))[-limit:]


def clear_ai_history(update: Optional[Update], topic: Optional[str] = None, all_topics: bool = False) -> int:
    chat_id, user_id = _memory_identity(update)
    if all_topics:
        if _db_enabled():
            ensure_ai_memory_tables()
            with _connect_memory_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM ai_chat_messages WHERE chat_id=%s AND user_id=%s",
                        (chat_id, user_id),
                    )
                    deleted = cur.rowcount or 0
                    cur.execute(
                        "DELETE FROM ai_chat_state WHERE chat_id=%s AND user_id=%s",
                        (chat_id, user_id),
                    )
                conn.commit()
            return deleted
        deleted = 0
        for key in list(_LOCAL_AI_MEMORY.keys()):
            if key[0] == chat_id and key[1] == user_id:
                deleted += len(_LOCAL_AI_MEMORY[key])
                del _LOCAL_AI_MEMORY[key]
        _LOCAL_AI_ACTIVE_TOPIC.pop((chat_id, user_id), None)
        return deleted

    topic = normalize_ai_topic(topic or get_active_ai_topic(update))
    if _db_enabled():
        ensure_ai_memory_tables()
        with _connect_memory_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ai_chat_messages WHERE chat_id=%s AND user_id=%s AND topic=%s",
                    (chat_id, user_id, topic),
                )
                deleted = cur.rowcount or 0
            conn.commit()
        return deleted
    key = (chat_id, user_id, topic)
    deleted = len(_LOCAL_AI_MEMORY.get(key, []))
    _LOCAL_AI_MEMORY.pop(key, None)
    return deleted


def ai_memory_status_text(update: Optional[Update]) -> str:
    chat_id, user_id = _memory_identity(update)
    active = get_active_ai_topic(update)
    storage = "Postgres/Neon" if _db_enabled() else "local memory fallback"
    lines = [
        "AI chat memory 🧠",
        "",
        f"Storage: {storage}",
        f"Active topic: {AI_TOPIC_LABELS.get(active, active)}",
        "",
        "Messages by topic:",
    ]
    counts = {topic: 0 for topic in AI_TOPIC_LABELS}
    if _db_enabled():
        ensure_ai_memory_tables()
        with _connect_memory_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT topic, COUNT(*) AS count
                    FROM ai_chat_messages
                    WHERE chat_id=%s AND user_id=%s
                    GROUP BY topic
                    ORDER BY topic
                    """,
                    (chat_id, user_id),
                )
                for row in cur.fetchall() or []:
                    counts[normalize_ai_topic(row["topic"])] = int(row["count"])
    else:
        for (c, u, topic), items in _LOCAL_AI_MEMORY.items():
            if c == chat_id and u == user_id:
                counts[normalize_ai_topic(topic)] = len(items)
    for topic, label in AI_TOPIC_LABELS.items():
        lines.append(f"- {label}: {counts.get(topic, 0)}")
    lines.append("")
    lines.append("Use /clear_chat to clear the active topic, or /clear_chat all to clear everything.")
    return "\n".join(lines)


def ai_history_preview_text(update: Optional[Update], topic: Optional[str] = None) -> str:
    topic = normalize_ai_topic(topic or get_active_ai_topic(update))
    history = get_ai_history(update, topic, limit=10)
    label = AI_TOPIC_LABELS.get(topic, topic)
    if not history:
        return f"No AI history yet for topic: {label}."
    lines = [f"Recent AI history — {label} 🧠", ""]
    for item in history:
        role = "You" if item["role"] == "user" else "AhBashin"
        content = item["content"].replace("\n", " ").strip()
        if len(content) > 220:
            content = content[:220] + "..."
        lines.append(f"{role}: {content}")
        lines.append("")
    return "\n".join(lines).strip()

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


async def call_ai_messages(
    system_prompt: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.4,
    max_tokens: Optional[int] = None,
) -> str:
    """Call the configured OpenAI-compatible text model with a message list."""
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

    safe_messages: List[Dict[str, str]] = []
    total_chars = 0
    for item in messages:
        role = item.get("role", "user")
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if len(content) > MAX_INPUT_CHARS:
            content = content[:MAX_INPUT_CHARS] + "\n\n[Input was truncated for safety.]"
        total_chars += len(content)
        safe_messages.append({"role": role, "content": content})

    # Keep the newest useful context if the total gets too large.
    while safe_messages and total_chars > AI_MEMORY_MAX_TOTAL_CHARS:
        removed = safe_messages.pop(0)
        total_chars -= len(removed.get("content", ""))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if provider == "openrouter":
        site_url = os.getenv("OPENROUTER_SITE_URL", "https://collatz-telegram-bot.onrender.com")
        app_name = os.getenv("OPENROUTER_APP_NAME", "AhBashin Telegram Bot")
        headers["HTTP-Referer"] = site_url
        headers["X-Title"] = app_name

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}] + safe_messages,
        "temperature": temperature,
        "max_tokens": int(max_tokens or MAX_OUTPUT_TOKENS),
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


async def call_ai(system_prompt: str, user_prompt: str, temperature: float = 0.4) -> str:
    """One-shot AI call without persistent memory. Existing modules can still use this."""
    return await call_ai_messages(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=temperature,
    )


async def call_ai_with_history(
    update: Optional[Update],
    system_prompt: str,
    user_prompt: str,
    topic: Optional[str] = None,
    temperature: float = 0.4,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Persistent per-user chat call.
    Memory key: chat_id + user_id + topic, so Ali and Sara in the same group never mix.
    """
    selected_topic = normalize_ai_topic(topic or get_active_ai_topic(update))
    history = get_ai_history(update, selected_topic, limit=AI_MEMORY_MAX_MESSAGES)
    messages = history + [{"role": "user", "content": user_prompt}]
    answer = await call_ai_messages(system_prompt, messages, temperature=temperature, max_tokens=max_tokens)
    save_ai_turn(update, selected_topic, user_prompt, answer)
    return answer





# ------------------------------------------------------------
# Vision / image understanding helpers
# ------------------------------------------------------------

import base64
from io import BytesIO

try:
    from PIL import Image
except Exception:  # Pillow is normally installed for photo tools.
    Image = None


MAX_VISION_IMAGE_BYTES = int(os.getenv("AI_VISION_MAX_IMAGE_BYTES", "3500000"))
MAX_VISION_SIDE = int(os.getenv("AI_VISION_MAX_SIDE", "1280"))


def get_ai_vision_provider() -> str:
    configured = os.getenv("AI_VISION_PROVIDER", "").strip().lower()
    if configured:
        return configured
    return get_ai_provider()


def get_ai_vision_model(provider: str) -> str:
    configured = os.getenv("AI_VISION_MODEL", "").strip()
    if configured:
        return configured
    if provider == "groq":
        # Current Groq vision-capable model. Override AI_VISION_MODEL in Render if Groq changes model names.
        return "meta-llama/llama-4-scout-17b-16e-instruct"
    if provider == "openrouter":
        # OpenRouter free vision model names can change. Set AI_VISION_MODEL in Render for best results.
        return os.getenv("AI_MODEL", "qwen/qwen2.5-vl-32b-instruct:free")
    if provider == "openai":
        return os.getenv("AI_MODEL", "gpt-4o-mini")
    return "offline"


def _prepare_image_for_vision(image_bytes: bytes, mime_type: str = "image/jpeg") -> Tuple[bytes, str]:
    """Compress/resize image so it is safe for vision APIs and Telegram downloads."""
    if Image is None:
        if len(image_bytes) > MAX_VISION_IMAGE_BYTES:
            raise AIProviderError("Pillow is not available and the image is too large for vision upload.")
        return image_bytes, mime_type

    try:
        image = Image.open(BytesIO(image_bytes))
        image = image.convert("RGB")
        image.thumbnail((MAX_VISION_SIDE, MAX_VISION_SIDE))
    except Exception as error:
        raise AIProviderError(f"Could not read image for AI vision: {error}")

    quality = 88
    while quality >= 45:
        output = BytesIO()
        image.save(output, format="JPEG", quality=quality, optimize=True)
        prepared = output.getvalue()
        if len(prepared) <= MAX_VISION_IMAGE_BYTES:
            return prepared, "image/jpeg"
        quality -= 8

    raise AIProviderError(
        "Image is too large for AI vision after compression. Try sending a smaller photo."
    )


async def call_ai_vision(
    system_prompt: str,
    user_prompt: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    temperature: float = 0.25,
    max_tokens: Optional[int] = None,
) -> str:
    """Call an OpenAI-compatible vision model with one image and text prompt."""
    provider = get_ai_vision_provider()
    model = get_ai_vision_model(provider)
    url, api_key = get_api_config(provider)

    if provider == "offline" or not url or not api_key:
        raise AIProviderError(
            "AI vision is not configured. For Groq, set these Render env vars:\n"
            "AI_PROVIDER=groq\n"
            "GROQ_API_KEY=your_key\n"
            "AI_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct"
        )

    user_prompt = (user_prompt or "What is in this image?").strip()
    if len(user_prompt) > MAX_INPUT_CHARS:
        user_prompt = user_prompt[:MAX_INPUT_CHARS] + "\n\n[Prompt was truncated for safety.]"

    prepared_bytes, prepared_mime = _prepare_image_for_vision(image_bytes, mime_type=mime_type)
    base64_image = base64.b64encode(prepared_bytes).decode("utf-8")
    data_url = f"data:{prepared_mime};base64,{base64_image}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if provider == "openrouter":
        site_url = os.getenv("OPENROUTER_SITE_URL", "https://collatz-telegram-bot.onrender.com")
        app_name = os.getenv("OPENROUTER_APP_NAME", "AhBashin Telegram Bot")
        headers["HTTP-Referer"] = site_url
        headers["X-Title"] = app_name

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "temperature": temperature,
        "max_tokens": int(max_tokens or MAX_OUTPUT_TOKENS),
    }

    try:
        async with httpx.AsyncClient(timeout=AI_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        raise AIProviderError("The AI vision provider timed out. Try a smaller image or shorter prompt.")
    except Exception as error:
        raise AIProviderError(f"Could not contact AI vision provider: {error}")

    if response.status_code >= 400:
        error_text = response.text[:1200]
        raise AIProviderError(
            f"AI vision provider error {response.status_code}.\n\n"
            f"Provider: {provider}\n"
            f"Model: {model}\n"
            f"Message: {error_text}"
        )

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except Exception:
        raise AIProviderError("AI vision provider returned an unexpected response format.")

    return str(content).strip()


async def ask_ai_text(
    user_prompt: str,
    system_prompt: str = "You are AhBashin Bot, a helpful assistant.",
    max_tokens: int = 900,
    temperature: float = 0.3,
) -> str:
    """Shared helper used by other modules."""
    old_max = os.environ.get("AI_MAX_OUTPUT_TOKENS")
    try:
        # call_ai reads the module-level MAX_OUTPUT_TOKENS, so max_tokens is advisory for callers.
        return await call_ai(system_prompt=system_prompt, user_prompt=user_prompt, temperature=temperature)
    finally:
        if old_max is not None:
            os.environ["AI_MAX_OUTPUT_TOKENS"] = old_max


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
        "/askai your question - AI assistant with your active topic memory\n"
        "/chat math your question - continue a specific topic memory\n"
        "/newchat - clear active topic memory\n"
        "/clear_chat all - clear all your AI memory in this chat\n"
        "/chat_status - show your private memory status\n"
        "/chat_history - preview recent memory\n"
        "/summarize long text - summarize text\n"
        "/rewrite formal | text - rewrite in a tone\n"
        "/explain difficult text - simple explanation\n"
        "/translate_ai fa | text - translate with context\n"
        "/quiz text/topic - generate quiz questions\n"
        "/flashcards text/topic - generate flashcards\n"
        "/code_explain code - explain code\n"
        "/code_fix error/code - suggest a fix\n"
        "/regex request - generate regex\n"
        "/sql request - generate SQL\n"
        "/photo_ai - understand a photo when used with photo module\n"
        "/ask_photo question - ask about a photo\n"
        "/caption_photo style - caption a photo\n"
        "/photo_feedback - composition/profile feedback\n\n"
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
    await chat_command(update, context)


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
# Persistent chat commands
# ------------------------------------------------------------

async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    raw = get_message_text(update, context)
    selected_topic, text = split_topic_prefix(raw)
    topic = selected_topic or get_active_ai_topic(update)
    if not text:
        await update.message.reply_text(
            "Usage:\n"
            "/chat your message\n"
            "/chat math continue with another example\n"
            "/chat data_science explain that result more simply\n\n"
            "Topics: general, math, data_science, physics, chemistry, astronomy, photo"
        )
        return
    system_prompt = (
        "You are AhBashin Bot, a helpful Telegram assistant with per-user memory. "
        "Continue naturally from the user's previous context when it is relevant. "
        "If previous context is not relevant, answer the new request directly. "
        "Be clear, practical, and concise."
    )
    try:
        await update.message.chat.send_action(action="typing")
        answer = await call_ai_with_history(
            update=update,
            system_prompt=system_prompt,
            user_prompt=text,
            topic=topic,
            temperature=0.5,
        )
    except Exception as error:
        await update.message.reply_text(f"AI chat error.\n\n{error}")
        return
    await send_ai_response(update, answer)


async def clear_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    raw = " ".join(context.args).strip()
    if raw.lower() in {"all", "everything", "*"}:
        deleted = clear_ai_history(update, all_topics=True)
        await update.message.reply_text(f"Cleared all your AI chat history for this chat. Deleted {deleted} messages.")
        return
    topic = normalize_ai_topic(raw) if raw else get_active_ai_topic(update)
    deleted = clear_ai_history(update, topic=topic)
    await update.message.reply_text(
        f"Cleared your {AI_TOPIC_LABELS.get(topic, topic)} AI history in this chat. Deleted {deleted} messages."
    )


async def newchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clear_chat_command(update, context)


async def chat_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(ai_memory_status_text(update))


async def chat_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    raw = " ".join(context.args).strip()
    topic = normalize_ai_topic(raw) if raw else get_active_ai_topic(update)
    await update.message.reply_text(ai_history_preview_text(update, topic))

# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------


def register_ai_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("aihelp", aihelp_command))
    app.add_handler(CommandHandler("askai", askai_command))
    app.add_handler(CommandHandler("ai", askai_command))
    app.add_handler(CommandHandler("chat", chat_command))
    app.add_handler(CommandHandler("continue", chat_command))
    app.add_handler(CommandHandler("newchat", newchat_command))
    app.add_handler(CommandHandler("clear_chat", clear_chat_command))
    app.add_handler(CommandHandler("chat_status", chat_status_command))
    app.add_handler(CommandHandler("chat_history", chat_history_command))
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
