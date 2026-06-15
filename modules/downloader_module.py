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

DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("DOWNLOADER_TIMEOUT_SECONDS", "240"))

# Optional Instagram cookies file.
# On Render, set:
# INSTAGRAM_COOKIES_FILE=/etc/secrets/instagram_cookies.txt
INSTAGRAM_COOKIES_FILE = os.getenv("INSTAGRAM_COOKIES_FILE", "").strip()

# Set this to 1 on Render only for debugging.
# DOWNLOADER_SHOW_TECHNICAL_ERRORS=1
SHOW_TECHNICAL_ERRORS = os.getenv("DOWNLOADER_SHOW_TECHNICAL_ERRORS", "0") == "1"


ALLOWED_DOMAINS = (
    "instagram.com",
    "www.instagram.com",

    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def downloader_help_text() -> str:
    instagram_status = (
        "Instagram cookies: configured"
        if INSTAGRAM_COOKIES_FILE
        else "Instagram cookies: not configured"
    )

    return (
        "Downloader commands:\n\n"
        "/download <link> - download public video\n"
        "/dl <link> - same as /download\n"
        "/audio <link> - download audio only\n"
        "/mp3 <link> - same as /audio\n"
        "/downloader_help - show this help\n\n"
        "Supported links:\n"
        "- X/Twitter public posts\n"
        "- Instagram reels/posts if cookies are configured\n\n"
        f"{instagram_status}\n"
        f"Max file size: {MAX_DOWNLOAD_MB} MB\n\n"
        "Examples:\n"
        "/dl https://x.com/user/status/...\n"
        "/dl https://www.instagram.com/reel/...\n"
    )


def extract_url_from_args(args) -> Optional[str]:
    if not args:
        return None

    text = " ".join(args).strip()
    match = re.search(r"https?://\S+", text)

    if not match:
        return None

    url = match.group(0).strip()
    url = url.rstrip(").,]}>\"'")

    return url


def get_host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def is_instagram_url(url: str) -> bool:
    host = get_host(url)
    return host == "instagram.com" or host.endswith(".instagram.com")


def is_x_url(url: str) -> bool:
    host = get_host(url)
    return (
        host == "x.com"
        or host.endswith(".x.com")
        or host == "twitter.com"
        or host.endswith(".twitter.com")
    )


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


def get_cookies_file_for_url(url: str) -> Optional[str]:
    """
    Uses cookies only for Instagram links when INSTAGRAM_COOKIES_FILE is set.

    The file must be Netscape cookies.txt format.
    Example Render path:
    /etc/secrets/instagram_cookies.txt
    """
    if not is_instagram_url(url):
        return None

    if not INSTAGRAM_COOKIES_FILE:
        return None

    cookies_path = Path(INSTAGRAM_COOKIES_FILE)

    if cookies_path.exists() and cookies_path.is_file():
        return str(cookies_path)

    return None


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


def common_ytdlp_options(download_dir: Path, url: str) -> dict:
    options = {
        "outtmpl": str(download_dir / "%(title).80s_%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_DOWNLOAD_BYTES,
        "socket_timeout": 40,
        "retries": 3,
        "fragment_retries": 3,
        "restrictfilenames": False,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    cookies_file = get_cookies_file_for_url(url)

    if cookies_file:
        options["cookiefile"] = cookies_file

    return options


def build_video_options(download_dir: Path, url: str) -> dict:
    options = common_ytdlp_options(download_dir, url)

    options.update(
        {
            "format": (
                "best[ext=mp4][acodec!=none][vcodec!=none][filesize<45M]/"
                "best[acodec!=none][vcodec!=none][filesize<45M]/"
                "best[ext=mp4][acodec!=none][vcodec!=none]/"
                "best[acodec!=none][vcodec!=none]/"
                "worst[ext=mp4][acodec!=none][vcodec!=none]/"
                "worst[acodec!=none][vcodec!=none]"
            ),
            "merge_output_format": "mp4",
        }
    )

    return options


def build_audio_options(download_dir: Path, url: str) -> dict:
    options = common_ytdlp_options(download_dir, url)

    options.update(
        {
            "format": (
                "bestaudio[ext=m4a][filesize<45M]/"
                "bestaudio[filesize<45M]/"
                "bestaudio/best"
            ),
        }
    )

    return options


def clean_error_message(error: Exception, mode: str, url: str) -> str:
    error_text = str(error)

    if is_instagram_url(url):
        if not INSTAGRAM_COOKIES_FILE:
            return (
                "Instagram download needs cookies.\n\n"
                "You must add this Render environment variable:\n"
                "INSTAGRAM_COOKIES_FILE=/etc/secrets/instagram_cookies.txt"
            )

        if get_cookies_file_for_url(url) is None:
            return (
                "Instagram cookies file is configured, but the file was not found.\n\n"
                f"Current path:\n{INSTAGRAM_COOKIES_FILE}\n\n"
                "Check Render Secret Files and env var."
            )

        if (
            "empty media response" in error_text.lower()
            or "login" in error_text.lower()
            or "cookies" in error_text.lower()
            or "private" in error_text.lower()
        ):
            return (
                "Instagram blocked this download even with cookies.\n\n"
                "Possible reasons:\n"
                "- Cookies are expired\n"
                "- Instagram security check is needed\n"
                "- The reel/post is private or restricted\n"
                "- Instagram blocked the Render server\n\n"
                "Export fresh Instagram cookies from Chrome and update the Render Secret File."
            )

        return (
            "Instagram download failed.\n\n"
            "Possible reasons:\n"
            "- Cookies are expired\n"
            "- The reel/post is private or restricted\n"
            "- Instagram blocked the server\n"
            "- The file is too large"
        )

    if "File is larger than max-filesize" in error_text or "too large" in error_text.lower():
        return (
            f"This file is too large.\n\n"
            f"Current limit: {MAX_DOWNLOAD_MB} MB"
        )

    if "Requested format is not available" in error_text:
        if mode == "video":
            return (
                "Video format was not available in a Telegram-friendly file.\n\n"
                "Try /audio with the same link."
            )

        return "Audio format was not available for this link."

    if "Private video" in error_text or "private" in error_text.lower():
        return "This post/video is private or restricted."

    if "unavailable" in error_text.lower():
        return "This post/video is unavailable or restricted."

    base = (
        "Download failed.\n\n"
        "Possible reasons:\n"
        "- The post is private or restricted\n"
        "- The video is too large\n"
        "- The website blocked the request\n"
        "- The link is not supported"
    )

    if SHOW_TECHNICAL_ERRORS:
        return base + "\n\nTechnical error:\n" + error_text[:1200]

    return base


def run_ytdlp_download(url: str, mode: str) -> Tuple[Path, str, str]:
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed. Add yt-dlp to requirements.txt and redeploy.")

    temp_dir = Path(tempfile.mkdtemp(prefix="laklak_download_"))

    try:
        if mode == "audio":
            options = build_audio_options(temp_dir, url)
        else:
            options = build_video_options(temp_dir, url)

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
        f"Size: {size_mb:.1f} MB"
    )

    with file_path.open("rb") as file_obj:
        input_file = InputFile(file_obj, filename=file_path.name)

        if mode == "audio":
            try:
                await update.message.reply_audio(
                    audio=input_file,
                    caption=caption,
                    title=title,
                )
            except Exception:
                file_obj.seek(0)
                input_file = InputFile(file_obj, filename=file_path.name)

                await update.message.reply_document(
                    document=input_file,
                    caption=caption,
                )

        elif suffix in (".mp4", ".mov", ".m4v", ".webm", ".mkv"):
            try:
                await update.message.reply_video(
                    video=input_file,
                    caption=caption,
                    supports_streaming=True,
                )
            except Exception:
                file_obj.seek(0)
                input_file = InputFile(file_obj, filename=file_path.name)

                await update.message.reply_document(
                    document=input_file,
                    caption=caption,
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
            "Please send a link.\n\n" + downloader_help_text()
        )
        return

    if not is_allowed_url(url):
        await update.message.reply_text(
            "This link is not supported now.\n\n"
            "Supported links:\n"
            "- X/Twitter\n"
            "- Instagram"
        )
        return

    if is_instagram_url(url) and not INSTAGRAM_COOKIES_FILE:
        await update.message.reply_text(
            "Instagram download needs cookies.\n\n"
            "You logged in with Chrome. Now export Instagram cookies and add them to Render.\n\n"
            "Required Render env var:\n"
            "INSTAGRAM_COOKIES_FILE=/etc/secrets/instagram_cookies.txt"
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

        await status_message.edit_text("Uploading to Telegram...")

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
            "Download timed out.\n\n"
            "Try a shorter or smaller link."
        )

    except Exception as error:
        clean_error = clean_error_message(error, mode, url)
        await status_message.edit_text(clean_error)

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