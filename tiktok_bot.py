#!/usr/bin/env python3
"""
TikTok Downloader Telegram Bot
--------------------------------
Downloads TikTok videos WITHOUT watermark and sends them via Telegram.

Requirements:
    pip install python-telegram-bot yt-dlp httpx[socks]

Usage:
    1. Get your bot token from @BotFather on Telegram
    2. Set your BOT_TOKEN below (or use an environment variable)
    3. Run: python tiktok_bot.py

VPN / Proxy notes:
    - If you're behind a VPN that routes all traffic, no proxy config needed.
    - If you use a LOCAL proxy (Clash, V2Ray, etc.) set PROXY_URL below.
      Examples:
        PROXY_URL = "socks5://127.0.0.1:1080"   # SOCKS5 local proxy
        PROXY_URL = "http://127.0.0.1:7890"      # HTTP local proxy
    - Leave PROXY_URL = None if your VPN handles everything system-wide.
"""

import os
import re
import glob
import logging
import tempfile
import asyncio
import yt_dlp

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.request import HTTPXRequest

# ─────────────────────────────────────────────
#  CONFIG  —  edit this section
# ─────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8633370052:AAHggDZqRAEnYz3KLkSTOXBe4D2ZO4v61gU")

# Set to your local proxy if needed, otherwise leave as None
# Examples:
#   PROXY_URL = "socks5://127.0.0.1:1080"
#   PROXY_URL = "http://127.0.0.1:7890"
PROXY_URL = os.getenv("PROXY_URL", None)

# Connection / read timeouts in seconds (increase if on a slow VPN)
CONNECT_TIMEOUT = 30.0
READ_TIMEOUT    = 60.0
WRITE_TIMEOUT   = 60.0

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
TIKTOK_REGEX = re.compile(
    r"(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/\S+",
    re.IGNORECASE,
)


def extract_tiktok_url(text: str) -> str | None:
    """Return the first TikTok URL found in a message, or None."""
    match = TIKTOK_REGEX.search(text)
    return match.group(0) if match else None


def find_downloaded_file(output_template: str) -> str | None:
    """
    yt-dlp may produce files like 'video.mp4', 'video.webm', etc.
    Glob for whatever it created.
    """
    # Try common extensions
    for ext in ("mp4", "webm", "mkv", "mov", "avi"):
        path = f"{output_template}.{ext}"
        if os.path.exists(path):
            return path
    # Fallback: glob anything that starts with the template name
    matches = glob.glob(f"{output_template}*")
    return matches[0] if matches else None


def download_tiktok(url: str, output_template: str) -> str:
    """
    Download a TikTok video without watermark using yt-dlp.
    Returns the path to the downloaded file.
    Raises yt_dlp.utils.DownloadError on failure.
    """
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": output_template + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        # Retries
        "retries": 3,
        "fragment_retries": 3,
        # Some TikTok regions require cookies; uncomment & point to your file:
        # "cookiefile": "cookies.txt",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)

    result = find_downloaded_file(output_template)
    if not result:
        raise FileNotFoundError("yt-dlp finished but no output file was found.")
    return result


# ─────────────────────────────────────────────
#  HANDLERS
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when the user sends /start."""
    await update.message.reply_text(
        "👋 *TikTok Downloader Bot*\n\n"
        "Send me any TikTok link and I'll send back the video "
        "*without a watermark*! 🎬\n\n"
        "Supported links:\n"
        "`https://www.tiktok.com/@user/video/...`\n"
        "`https://vm.tiktok.com/...`\n"
        "`https://vt.tiktok.com/...`\n\n"
        "Type /help for more info.",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help info when the user sends /help."""
    await update.message.reply_text(
        "ℹ️ *How to use this bot:*\n\n"
        "1️⃣ Copy a TikTok video link\n"
        "2️⃣ Paste it here and send\n"
        "3️⃣ Wait a few seconds — I'll download and send the video!\n\n"
        "*Limits:*\n"
        "• Videos must be under 50 MB (Telegram limit)\n"
        "• Private or deleted videos cannot be downloaded\n\n"
        "If anything goes wrong, just try again! 🔁",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main handler: detect TikTok URL → download → send video."""
    message = update.message
    text = message.text or ""

    url = extract_tiktok_url(text)

    if not url:
        await message.reply_text(
            "❓ I couldn't find a TikTok link in your message.\n"
            "Please send a valid TikTok URL!"
        )
        return

    status_msg = await message.reply_text("⏳ Downloading your video, please wait…")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_template = os.path.join(tmpdir, "video")

            loop = asyncio.get_event_loop()
            downloaded_path = await loop.run_in_executor(
                None, download_tiktok, url, output_template
            )

            file_size_mb = os.path.getsize(downloaded_path) / (1024 * 1024)
            logger.info("Downloaded %.1f MB → %s", file_size_mb, downloaded_path)

            if file_size_mb > 50:
                await status_msg.edit_text(
                    "⚠️ This video is too large to send via Telegram (> 50 MB).\n"
                    "Try a shorter TikTok video!"
                )
                return

            await status_msg.edit_text("📤 Uploading to Telegram…")

            with open(downloaded_path, "rb") as video_file:
                await message.reply_video(
                    video=video_file,
                    caption="✅ Here's your TikTok video — no watermark! 🎬",
                    supports_streaming=True,
                    read_timeout=READ_TIMEOUT,
                    write_timeout=WRITE_TIMEOUT,
                )

            await status_msg.delete()

    except yt_dlp.utils.DownloadError as e:
        logger.error("yt-dlp error: %s", e)
        await status_msg.edit_text(
            "❌ Failed to download the video.\n\n"
            "Possible reasons:\n"
            "• The video is private or deleted\n"
            "• The link is invalid or expired\n"
            "• TikTok temporarily blocked the request\n\n"
            "Please try again in a moment!"
        )
    except FileNotFoundError as e:
        logger.error("File not found after download: %s", e)
        await status_msg.edit_text(
            "❌ Download finished but the file couldn't be found.\n"
            "Please try again!"
        )
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        await status_msg.edit_text(
            "⚠️ Something went wrong. Please try again later."
        )


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def main() -> None:
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise ValueError(
            "❌ Please set your BOT_TOKEN!\n"
            "  Option 1: Edit BOT_TOKEN at the top of this file\n"
            "  Option 2: Run with:  BOT_TOKEN=xxx python tiktok_bot.py"
        )

    logger.info("Starting TikTok Downloader Bot…")
    if PROXY_URL:
        logger.info("Using proxy: %s", PROXY_URL)

    # Build an HTTPXRequest with raised timeouts (and optional proxy)
    request_kwargs = dict(
        connect_timeout=CONNECT_TIMEOUT,
        read_timeout=READ_TIMEOUT,
        write_timeout=WRITE_TIMEOUT,
    )
    if PROXY_URL:
        request_kwargs["proxy"] = PROXY_URL

    http_request = HTTPXRequest(**request_kwargs)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(http_request)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running! Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()