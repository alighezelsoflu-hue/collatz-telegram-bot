import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, ContextTypes

try:
    import yt_dlp
except Exception:
    yt_dlp = None


# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

MAX_DOWNLOAD_MB = int(os.getenv("DOWNLOADER_MAX_MB", "45"))
MAX_DOWNLOAD_BYTES = MAX_DOWNLOAD_MB * 1024 * 1024

DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("DOWNLOADER_TIMEOUT_SECONDS", "180"))

ALLOWED_DOMAINS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "instagram.com",
    "www.instagram.com",
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "tiktok.com",
    "www.tiktok.com",
    "vm.tiktok.com",
)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def downloader_help_text() -> str:
    return (
        "Downloader commands:\n\n"
        "/download <link> - download public video\n"
        "/dl <link> - same as /download\n"
        "/audio <link> - download audio only\n"
        "/mp3 <link> - same as /audio\n"
        "/downloader_help - show this help\n\n"
        "Examples:\n"
        "/download https://www.youtube.com/watch?v=...\n"
        "/download https://youtube.com/shorts/...\n"
        "/download https://www.instagram.com/reel/...\n"
        "/download https://x.com/user/status/...\n\n"
        "Notes:\n"
        "- Only public links are supported.\n"
        "- Private Instagram/X/Twitter links may fail.\n"
        f"- Max file size is {MAX_DOWNLOAD_MB} MB.\n"
        "- Download only content you have permission to use."
    )


def extract_url_from_args(args) -> Optional[str]:
    if not args:
        return None

    text = " ".join(args).strip()

    match = re.search(r"https?://\S+", text)

    if not match:
        return None

    url = match.group(0).strip()

    # Remove common trailing punctuation from copied messages.
    url = url.rstrip(").,]}>\"'")

    return url


def is_allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        if not parsed.scheme.startswith("http"):
            return False

        if not host:
            return False

        return any(host == domain or host.endswith("." + domain) for domain in ALLOWED_DOMAINS)

    except Exception:
        return False


def safe_title(text: str, max_length: int = 70) -> str:
    text = re.sub(r"[^\w\s.\-()\[\]]+", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return "download"

    return text[:max_length].strip()


def get_file_size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def find_downloaded_file(directory: Path) -> Optional[Path]:
    files = [p for p in directory.rglob("*") if p.is_file()]

    if not files:
        return None

    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return files[0]


def build_video_options(download_dir: Path) -> dict:
    return {
        "outtmpl": str(download_dir / "%(title).80s_%(id)s.%(ext)s"),
        "format": (
            "best[filesize<45M][ext=mp4]/"
            "best[filesize<45M]/"
            "best[ext=mp4]/"
            "best"
        ),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_DOWNLOAD_BYTES,
        "merge_output_format": "mp4",
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
        "restrictfilenames": False,
    }


def build_audio_options(download_dir: Path) -> dict:
    # This downloads audio-only. It does not force mp3 conversion,
    # because mp3 conversion needs ffmpeg on the server.
    return {
        "outtmpl": str(download_dir / "%(title).80s_%(id)s.%(ext)s"),
        "format": (
            "bestaudio[filesize<45M]/"
            "bestaudio/best"
        ),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_DOWNLOAD_BYTES,
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
        "restrictfilenames": False,
    }


def run_ytdlp_download(url: str, mode: str) -> Tuple[Path, str, str]:
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed. Add yt-dlp to requirements.txt and redeploy.")

    temp_dir = Path(tempfile.mkdtemp(prefix="laklak_download_"))

    try:
        if mode == "audio":
            options = build_audio_options(temp_dir)
        else:
            options = build_video_options(temp_dir)

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

        downloaded_file = find_downloaded_file(temp_dir)

        if downloaded_file is None:
            raise RuntimeError("Download finished, but no file was found.")

        file_size = downloaded_file.stat().st_size

        if file_size > MAX_DOWNLOAD_BYTES:
            raise RuntimeError(
                f"Downloaded file is too large: {get_file_size_mb(downloaded_file):.1f} MB. "
                f"Limit is {MAX_DOWNLOAD_MB} MB."
            )

        title = safe_title(info.get("title") or "download")
        webpage_url = info.get("webpage_url") or url

        return downloaded_file, title, webpage_url

    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


async def download_with_timeout(url: str, mode: str) -> Tuple[Path, str, str]:
    return await asyncio.wait_for(
        asyncio.to_thread(run_ytdlp_download, url, mode),
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )


async def send_downloaded_file(
    update: Update,
    file_path: Path,
    title: str,
    source_url: str,
    mode: str,
) -> None:
    if not update.message:
        return

    suffix = file_path.suffix.lower()
    size_mb = get_file_size_mb(file_path)

    caption = (
        f"{title}\n\n"
        f"Size: {size_mb:.1f} MB\n"
        f"Source: {source_url}"
    )

    with file_path.open("rb") as file_obj:
        input_file = InputFile(file_obj, filename=file_path.name)

        if mode == "audio":
            await update.message.reply_audio(
                audio=input_file,
                caption=caption,
                title=title,
            )

        elif suffix in (".mp4", ".mov", ".m4v", ".webm", ".mkv"):
            await update.message.reply_video(
                video=input_file,
                caption=caption,
                supports_streaming=True,
            )

        else:
            await update.message.reply_document(
                document=input_file,
                caption=caption,
            )


async def handle_download_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str,
) -> None:
    if not update.message:
        return

    url = extract_url_from_args(context.args)

    if not url:
        await update.message.reply_text(
            "Please send a link.\n\n"
            + downloader_help_text()
        )
        return

    if not is_allowed_url(url):
        await update.message.reply_text(
            "This link is not supported yet.\n\n"
            "Supported public links:\n"
            "- YouTube\n"
            "- Instagram\n"
            "- X/Twitter\n"
            "- TikTok"
        )
        return

    if yt_dlp is None:
        await update.message.reply_text(
            "yt-dlp is not installed.\n\n"
            "Add this to requirements.txt:\n"
            "yt-dlp"
        )
        return

    status_message = await update.message.reply_text(
        "Downloading... please wait.\n\n"
        f"Limit: {MAX_DOWNLOAD_MB} MB"
    )

    file_path = None

    try:
        file_path, title, source_url = await download_with_timeout(url, mode)

        await status_message.edit_text("Upload to Telegram started...")

        await send_downloaded_file(
            update=update,
            file_path=file_path,
            title=title,
            source_url=source_url,
            mode=mode,
        )

        try:
            await status_message.delete()
        except Exception:
            pass

    except asyncio.TimeoutError:
        await status_message.edit_text(
            "Download timed out. Try a shorter or smaller video."
        )

    except Exception as error:
        await status_message.edit_text(
            "Download failed.\n\n"
            f"Error: {error}\n\n"
            "Possible reasons:\n"
            "- The post is private\n"
            "- The video is too large\n"
            "- The website blocked the request\n"
            "- The link is not supported by yt-dlp"
        )

    finally:
        if file_path:
            shutil.rmtree(file_path.parent, ignore_errors=True)


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_download_command(update, context, mode="video")


async def audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_download_command(update, context, mode="audio")


async def downloader_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(downloader_help_text())


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

def register_downloader_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("download", download_command))
    app.add_handler(CommandHandler("dl", download_command))

    app.add_handler(CommandHandler("audio", audio_command))
    app.add_handler(CommandHandler("mp3", audio_command))

    app.add_handler(CommandHandler("downloader_help", downloader_help_command))
    app.add_handler(CommandHandler("downloadhelp", downloader_help_command))