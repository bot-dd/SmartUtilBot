# Copyright @ISmartDevs
# Channel t.me/TheSmartDev
import os
import re
import asyncio
import time
import aiohttp
import aiofiles
from pathlib import Path
from typing import Optional
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from config import COMMAND_PREFIX
from utils import LOGGER, progress_bar, notify_admin  # Import LOGGER, progress_bar, and notify_admin from utils
from core import banned_users  # Check if user is banned

# Use the imported LOGGER
logger = LOGGER

# Configuration
class Config:
    TEMP_DIR = Path("temp")

Config.TEMP_DIR.mkdir(exist_ok=True)

class FacebookDownloader:
    def __init__(self, temp_dir: Path):
        self.temp_dir = temp_dir

    async def sanitize_filename(self, title: str) -> str:
        """Sanitize file name by removing invalid characters."""
        title = re.sub(r'[<>:"/\\|?*]', '', title[:50]).strip()
        return f"{title.replace(' ', '_')}_{int(time.time())}"

    async def download_video(self, url: str, downloading_message: Message) -> Optional[dict]:
        self.temp_dir.mkdir(exist_ok=True)
        api_url = f"https://smartfbdl.vercel.app/dl?url={url}"
        
        try:
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit_per_host=10),
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                async with session.get(api_url) as response:
                    logger.info(f"API request to {api_url} returned status {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"API response: {data}")
                        # Find HD quality video URL
                        video_url = next(
                            (link["url"] for link in data.get("links", []) if link.get("quality") == "HD"),
                            None
                        )
                        if not video_url:
                            logger.error("No HD video URL found in API response")
                            await downloading_message.edit_text("**Unable To Extract Video URL**", parse_mode=ParseMode.MARKDOWN)
                            return None
                        await downloading_message.edit_text("**Found ☑️ Downloading...**", parse_mode=ParseMode.MARKDOWN)
                        title = data.get("title", "Facebook Video")
                        safe_title = await self.sanitize_filename(title)
                        filename = self.temp_dir / f"{safe_title}.mp4"
                        await self._download_file(session, video_url, filename)
                        return {
                            'title': title,
                            'filename': str(filename),
                            'webpage_url': url
                        }
                    logger.error(f"API request failed: HTTP status {response.status}")
                    return None
        except aiohttp.ClientError as e:
            logger.error(f"Facebook download error: {e}")
            # Notify admins
            await notify_admin(downloading_message._client, f"{COMMAND_PREFIX}fb", e, downloading_message)
            return None
        except asyncio.TimeoutError:
            logger.error("Request to Facebook API timed out")
            # Notify admins
            await notify_admin(downloading_message._client, f"{COMMAND_PREFIX}fb", asyncio.TimeoutError("Request to Facebook API timed out"), downloading_message)
            return None
        except Exception as e:
            logger.error(f"Facebook download error: {e}")
            # Notify admins
            await notify_admin(downloading_message._client, f"{COMMAND_PREFIX}fb", e, downloading_message)
            return None

    async def _download_file(self, session: aiohttp.ClientSession, url: str, dest: Path):
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    logger.info(f"Downloading video from {url} to {dest}")
                    async with aiofiles.open(dest, mode='wb') as f:
                        async for chunk in response.content.iter_chunked(1024 * 1024):  # 1MB chunks
                            await f.write(chunk)
                    logger.info(f"Video downloaded successfully to {dest}")
                else:
                    logger.error(f"Failed to download file: HTTP status {response.status}")
                    raise Exception(f"Failed to download file: HTTP status {response.status}")
        except aiohttp.ClientError as e:
            logger.error(f"Error downloading file from {url}: {e}")
            # Notify admins
            await notify_admin(None, f"{COMMAND_PREFIX}fb", e, None)
            raise

def setup_fb_handlers(app: Client):
    fb_downloader = FacebookDownloader(Config.TEMP_DIR)

    # Create a regex pattern from the COMMAND_PREFIX list
    command_prefix_regex = f"[{''.join(map(re.escape, COMMAND_PREFIX))}]"

    @app.on_message(filters.regex(rf"^{command_prefix_regex}fb(\s+https?://\S+)?$") & (filters.private | filters.group))
    async def fb_handler(client: Client, message: Message):
        # Check if user is banned
        user_id = message.from_user.id if message.from_user else None
        if user_id and banned_users.find_one({"user_id": user_id}):
            await client.send_message(message.chat.id, "**✘Sorry You're Banned From Using Me↯**", parse_mode=ParseMode.MARKDOWN)
            return

        url = None
        # Check if URL from reply
        if message.reply_to_message and message.reply_to_message.text:
            match = re.search(r"https?://(www\.facebook\.com|fb\.watch|m\.facebook\.com)/\S+", message.reply_to_message.text)
            if match:
                url = match.group(0)
        # Check if URL from command
        if not url:
            command_parts = message.text.split(maxsplit=1)
            if len(command_parts) > 1:
                match = re.search(r"https?://(www\.facebook\.com|fb\.watch|m\.facebook\.com)/\S+", command_parts[1])
                if match:
                    url = match.group(0)

        if not url:
            await client.send_message(
                chat_id=message.chat.id,
                text="**Please provide a valid Facebook video link **",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.warning(f"No Facebook URL provided, user: {user_id or 'unknown'}, chat: {message.chat.id}")
            return

        logger.info(f"Facebook URL received: {url}, user: {user_id or 'unknown'}, chat: {message.chat.id}")
        downloading_message = await client.send_message(
            chat_id=message.chat.id,
            text="**Searching The Video**",
            parse_mode=ParseMode.MARKDOWN
        )

        try:
            video_info = await fb_downloader.download_video(url, downloading_message)
            if not video_info:
                await downloading_message.edit_text("**Invalid Video URL or Video is Private**", parse_mode=ParseMode.MARKDOWN)
                logger.error(f"Failed to download video for URL: {url}")
                return

            title = video_info['title']
            filename = video_info['filename']
            webpage_url = video_info['webpage_url']

            if message.from_user:
                user_full_name = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
                user_info = f"[{user_full_name}](tg://user?id={user_id})"
            else:
                group_name = message.chat.title or "this group"
                group_url = f"https://t.me/{message.chat.username}" if message.chat.username else "this group"
                user_info = f"[{group_name}]({group_url})"

            caption = (
                f"🎥 **Title**: `{title}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔗 **Link**: [Watch on Facebook]({webpage_url})\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Downloaded By**: {user_info}"
            )

            async with aiofiles.open(filename, 'rb'):
                start_time = time.time()
                last_update_time = [start_time]
                await client.send_video(
                    chat_id=message.chat.id,
                    video=filename,
                    supports_streaming=True,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    progress=progress_bar,
                    progress_args=(downloading_message, start_time, last_update_time)
                )

            await downloading_message.delete()
            if os.path.exists(filename):
                os.remove(filename)
                logger.info(f"Deleted video file: {filename}")

        except Exception as e:
            logger.error(f"Error processing Facebook video: {e}")
            # Notify admins
            await notify_admin(client, f"{COMMAND_PREFIX}fb", e, downloading_message)
            # Send user-facing error message
            await downloading_message.edit_text("**Facebook Downloader API Dead**", parse_mode=ParseMode.MARKDOWN)
