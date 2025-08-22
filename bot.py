import os
import glob
import time
import requests
import asyncio
import json
from functools import wraps
from PIL import Image, ImageDraw, ImageFont
from yt_dlp import YoutubeDL
from pyrogram import Client
from pymediainfo import MediaInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# === Configuration (FILL THESE OUT) ===
BOT_TOKEN = '8275155826:AAH1iiq7p1mDZ2gw_UDUc5nUAIi3rc_-VB8'                  # 👈 PASTE YOUR TELEGRAM BOT TOKEN HERE
API_ID = 27409928                             # 👈 PASTE YOUR TELEGRAM API ID HERE
API_HASH = '5bb178e8905d57f05954c5d5ff263785'               # 👈 PASTE YOUR TELEGRAM API HASH HERE
ADMIN_CHAT_ID = 7962617461                     # 👈 PASTE YOUR NUMERIC CHAT ID HERE

# === Global State & File Paths (Do not change) ===
user_settings = {}
download_process_active = False
source_thumb_jpg = 'source_thumbnail.jpg'
final_thumb_jpg = 'final_thumbnail.jpg'
font_path = 'arial.ttf'  # Make sure this font file is in the same directory
proxy_settings_file = 'proxy_settings.json'


# === Authorization Decorator ===
def restricted(func):
    """Restricts usage of the command to the ADMIN_CHAT_ID."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id != ADMIN_CHAT_ID:
            await update.message.reply_text("🚫 Sorry, you are not authorized to use this bot.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


# === Proxy Management ===
def load_proxy_settings():
    if os.path.exists(proxy_settings_file):
        with open(proxy_settings_file, 'r') as f:
            return json.load(f)
    return {"url": None, "enabled": False}

def save_proxy_settings(settings):
    with open(proxy_settings_file, 'w') as f:
        json.dump(settings, f)

proxy_config = load_proxy_settings()


# === Helper Functions ===
def get_user_settings(chat_id):
    """Initializes and retrieves settings for the admin user."""
    if chat_id not in user_settings:
        user_settings[chat_id] = {
            'caption': "Default Caption - Set yours with /caption",
            'caption_enabled': True,
            'watermark_text': "@default_watermark",
            'watermark_enabled': False,  # Watermark is OFF by default
            'target_chat_id': chat_id  # Default to sending back to the user
        }
    return user_settings[chat_id]

def find_downloaded_video():
    for ext in ('mp4', 'mkv', 'webm'):
        files = glob.glob(f"*.{ext}")
        if files:
            return files[0]
    return None

def cleanup_files():
    print("🧹 Cleaning up local files...")
    video_file = find_downloaded_video()
    for file_path in [source_thumb_jpg, final_thumb_jpg, video_file]:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"   - Removed: {file_path}")
            except OSError as e:
                print(f"   - Error removing {file_path}: {e}")
    print("✨ Cleanup done.")


# === Core Media Processing Logic ===
def download_high_quality_thumbnail(url, proxy_url_if_enabled):
    print("ℹ️  Fetching video info for thumbnail...")
    ydl_opts = {'quiet': True, 'cookiefile': 'cookies.txt'}
    if proxy_url_if_enabled:
        ydl_opts['proxy'] = proxy_url_if_enabled
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        video_id = info.get('id')
    max_res_url = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
    hq_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    proxies = {'http': proxy_url_if_enabled, 'https': proxy_url_if_enabled} if proxy_url_if_enabled else None
    response = requests.get(max_res_url, proxies=proxies)
    if response.status_code != 200:
        response = requests.get(hq_url, proxies=proxies)
        if response.status_code != 200:
            raise ConnectionError("❌ Failed to download any high-quality thumbnail.")
    with open(source_thumb_jpg, 'wb') as f:
        f.write(response.content)

def prepare_thumbnail(source_path, watermark_text, watermark_enabled):
    if not watermark_enabled:
        print("💧 Watermark is disabled. Using original thumbnail.")
        os.rename(source_path, final_thumb_jpg)
        return
    with Image.open(source_path) as img:
        img = img.convert("RGB")
        draw = ImageDraw.Draw(img)
        try:
            font_size = int(img.height * 0.1)
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            font = ImageFont.load_default()
        text_bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width, text_height = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
        x = img.width - text_width - int(img.width * 0.03)
        y = (img.height - text_height) / 2
        outline_color = "black"
        for i in range(-2, 3):
            for j in range(-2, 3):
                draw.text((x + i, y + j), watermark_text, font=font, fill=outline_color)
        draw.text((x, y), watermark_text, font=font, fill="white")
        print("💧 Watermark added.")
        img.save(final_thumb_jpg, "jpeg", quality=95, optimize=True)

# === Telegram Bot Command Handlers ===
@restricted
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user_settings(update.effective_chat.id)
    help_text = (
        "👋 *Welcome to your Video Downloader Bot!* 🚀\n\n"
        "Here's the workflow:\n\n"
        "1️⃣ *Set Target Chat* (Where to send the video):\n"
        "   `/send_to @your_channel`\n"
        "   `/send_to me` (for your Saved Messages)\n\n"
        "2️⃣ *Set Caption*:\n"
        "   `/caption Your amazing caption here!`\n"
        "   `/caption off` (to send with no caption)\n\n"
        "3️⃣ *Configure Watermark* (Off by default):\n"
        "   `/watermark @your_channel`\n"
        "   `/watermark off`\n\n"
        "4️⃣ *Set Proxy* (Optional):\n"
        "   `/set_proxy http://user:pass@host:port`\n"
        "   `/proxy on` or `/proxy off`\n\n"
        "5️⃣ **Download the video:**\n"
        "   `/dl https://youtu.be/some_video_id`\n\n"
        "ℹ️ **Other Commands:**\n"
        "   `/cancel` - Stops the current process.\n"
        "   `/status` - Shows your current settings.\n"
        "   `/help` - Shows this message again."
    )
    await update.message.reply_markdown(help_text)

@restricted
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = get_user_settings(update.effective_chat.id)
    proxy_status = "Enabled ✅" if proxy_config['enabled'] else "Disabled ❌"
    proxy_url_display = proxy_config['url'] if proxy_config['url'] else "Not Set"
    caption_status = "Enabled ✅" if settings['caption_enabled'] else "Disabled ❌"
    caption_text_display = f"'{settings['caption']}'" if settings['caption_enabled'] else "N/A"
    watermark_status = "Enabled ✅" if settings['watermark_enabled'] else "Disabled ❌"
    watermark_text_display = f"'{settings['watermark_text']}'" if settings['watermark_enabled'] else "N/A"
    status_text = (
        f"⚙️ *Current Bot Settings*\n\n"
        f"**📤 Target Chat:** `{settings['target_chat_id']}`\n\n"
        f"**✍️ Caption:** {caption_status}\n"
        f"   - Text: `{caption_text_display}`\n\n"
        f"**💧 Watermark:** {watermark_status}\n"
        f"   - Text: `{watermark_text_display}`\n\n"
        f"**🔒 Proxy:** {proxy_status}\n"
        f"   - URL: `{proxy_url_display}`"
    )
    await update.message.reply_markdown(status_text)

@restricted
async def send_to_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("📤 Usage: `/send_to @channel_name` or `/send_to me`")
        return
    target = context.args[0]
    settings = get_user_settings(update.effective_chat.id)
    if target.lower() == 'me':
        settings['target_chat_id'] = update.effective_chat.id
        await update.message.reply_text("✅ Success! Videos will now be sent here.")
    else:
        settings['target_chat_id'] = target
        await update.message.reply_text(f"✅ Success! Videos will now be sent to `{target}`.", parse_mode='Markdown')

@restricted
async def set_caption_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption_input = " ".join(context.args)
    if not caption_input:
        await update.message.reply_text("✍️ Usage: `/caption My text` or `/caption off`")
        return
    settings = get_user_settings(update.effective_chat.id)
    if caption_input.lower() == 'off':
        settings['caption_enabled'] = False
        await update.message.reply_text("❌ Caption has been disabled.")
    else:
        settings['caption_enabled'] = True
        settings['caption'] = caption_input
        await update.message.reply_text(f"✅ Caption has been set to:\n`{caption_input}`", parse_mode='Markdown')

@restricted
async def set_watermark_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    watermark_input = " ".join(context.args)
    if not watermark_input:
        await update.message.reply_text("💧 Usage: `/watermark @my_channel` or `/watermark off`")
        return
    settings = get_user_settings(update.effective_chat.id)
    if watermark_input.lower() == 'off':
        settings['watermark_enabled'] = False
        await update.message.reply_text("❌ Watermark has been disabled.")
    else:
        settings['watermark_enabled'] = True
        settings['watermark_text'] = watermark_input
        await update.message.reply_text(f"✅ Watermark text has been set to: `{watermark_input}`", parse_mode='Markdown')

@restricted
async def set_proxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/set_proxy http://user:pass@host:port`")
        return
    proxy_config['url'] = context.args[0]
    save_proxy_settings(proxy_config)
    await update.message.reply_text(f"✅ Proxy URL saved! Enable it with `/proxy on`.")

@restricted
async def proxy_toggle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in ['on', 'off']:
        await update.message.reply_text("⚠️ Usage: `/proxy on` or `/proxy off`.")
        return
    if not proxy_config['url']:
        await update.message.reply_text("‼️ No proxy URL is set. Use `/set_proxy` first.")
        return
    action = context.args[0].lower()
    proxy_config['enabled'] = (action == 'on')
    save_proxy_settings(proxy_config)
    status = "enabled ✅" if proxy_config['enabled'] else "disabled ❌"
    await update.message.reply_text(f"🔒 Proxy is now **{status}**.")

@restricted
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global download_process_active
    if not download_process_active:
        await update.message.reply_text("🤷 No active process to cancel.")
        return
    download_process_active = False
    await update.message.reply_text("🛑 Cancel command received! Stopping process...")

@restricted
async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global download_process_active
    if download_process_active:
        await update.message.reply_text("⏳ A process is already running. Please wait or use /cancel.")
        return
    if not context.args:
        await update.message.reply_text("🔗 Usage: `/dl <video_url>`")
        return

    video_url = context.args[0]
    download_process_active = True
    cleanup_files()
    settings = get_user_settings(update.effective_chat.id)
    status_msg = await update.message.reply_text("🚀 Starting process...")
    last_update_time = 0

    async def progress_hook(d, status_prefix, status_verb):
        nonlocal last_update_time
        if not download_process_active:
            raise Exception("Process cancelled by user.")
        current_time = time.time()
        if current_time - last_update_time < 2:
            return
        
        percent = d.get('percent', 0)
        speed = d.get('speed', "N/A")
        eta = d.get('eta', "N/A")

        try:
            await status_msg.edit_text(
                f"{status_prefix} **{status_verb}...**\n\n"
                f"**Progress:** `{percent}`\n"
                f"**Speed:** `{speed}`\n"
                f"**ETA:** `{eta}`\n\n"
                f"_To stop, use /cancel_",
                parse_mode='Markdown'
            )
            last_update_time = current_time
        except Exception:
            pass

    async def ytdl_progress_hook(d):
        if d['status'] == 'downloading':
            percent_str = d.get('_percent_str', '0.0%').strip()
            speed_str = d.get('_speed_str', 'N/A').strip()
            eta_str = d.get('_eta_str', 'N/A').strip()
            await progress_hook({'percent': percent_str, 'speed': speed_str, 'eta': eta_str}, "📥", "Downloading Video")

    async def pyrogram_progress_callback(current, total):
        elapsed = time.time() - upload_start_time
        speed = f"{current / elapsed / 1024 / 1024:.2f} MB/s" if elapsed > 0 else "N/A"
        percent = f"{current * 100 / total:.1f}%"
        await progress_hook({'percent': percent, 'speed': speed, 'eta': "N/A"}, "⬆️", "Uploading")

    try:
        await status_msg.edit_text("🖼️ Downloading thumbnail...")
        proxy_url = proxy_config['url'] if proxy_config.get('enabled') else None
        download_high_quality_thumbnail(video_url, proxy_url)

        ydl_opts = {
            'format': 'best[height<=480][ext=mp4]/best[ext=mp4]/best',
            'outtmpl': '%(title)s.%(ext)s',
            'merge_output_format': 'mp4',
            'quiet': True,
            'progress_hooks': [ytdl_progress_hook],
            'cookiefile': 'cookies.txt',
            'retries': 10
        }
        if proxy_url: ydl_opts['proxy'] = proxy_url
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        video_file = find_downloaded_video()
        if not video_file: raise FileNotFoundError("🚫 Downloaded video file not found.")

        await status_msg.edit_text("💧 Applying watermark...")
        prepare_thumbnail(source_thumb_jpg, settings['watermark_text'], settings['watermark_enabled'])
        
        await status_msg.edit_text("⏳ Extracting video metadata...")
        media_info = MediaInfo.parse(video_file)
        video_track = next((t for t in media_info.tracks if t.track_type == 'Video'), None)
        duration = int(video_track.duration / 1000) if video_track and video_track.duration else 0
        width = video_track.width if video_track and video_track.width else 0
        height = video_track.height if video_track and video_track.height else 0

        await status_msg.edit_text("📲 Connecting to Telegram for upload...")
        app = Client("my_account", api_id=API_ID, api_hash=API_HASH)
        upload_start_time = time.time()
        async with app:
            final_caption = settings['caption'] if settings['caption_enabled'] else None
            await app.send_video(
                chat_id=settings['target_chat_id'],
                video=video_file,
                caption=final_caption,
                thumb=final_thumb_jpg,
                duration=duration, width=width, height=height,
                supports_streaming=True,
                progress=pyrogram_progress_callback
            )
        await status_msg.edit_text("✅ Done! Video uploaded successfully.")

    except Exception as e:
        error_message = f"❌ An error occurred: {e}"
        print(error_message)
        await status_msg.edit_text(error_message)
    finally:
        download_process_active = False
        cleanup_files()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"An error occurred: {context.error}")


def main():
    print("🚀 Bot is starting...")
    application = Application.builder().token(BOT_TOKEN).build()

    # Register all command handlers
    handlers = [
        CommandHandler("start", start_command),
        CommandHandler("help", start_command),
        CommandHandler("status", status_command),
        CommandHandler("send_to", send_to_command),
        CommandHandler("set_proxy", set_proxy_command),
        CommandHandler("proxy", proxy_toggle_command),
        CommandHandler("caption", set_caption_command),
        CommandHandler("watermark", set_watermark_command),
        CommandHandler("dl", download_command),
        CommandHandler("cancel", cancel_command)
    ]
    for handler in handlers:
        application.add_handler(handler)

    application.add_error_handler(error_handler)
    application.run_polling()


if __name__ == '__main__':
    main()
