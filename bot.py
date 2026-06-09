import os
import tempfile
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import imageio_ffmpeg
ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

user_states = {}
STATE_IDLE = "idle"
STATE_WAITING_PACK_NAME = "waiting_pack_name"
STATE_WAITING_PACK_TITLE = "waiting_pack_title"
STATE_WAITING_EXISTING_PACK = "waiting_existing_pack"
STATE_READY = "ready"
STATE_WAITING_TRIM_START = "waiting_trim_start"
STATE_WAITING_TRIM_END = "waiting_trim_end"


def get_user_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = {
            "state": STATE_IDLE,
            "pack_name": None,
            "pack_title": None,
            "pending_video_path": None,
            "pending_video_duration": None,
            "pending_tmpdir": None,
            "trim_start": None,
            "trim_end": None,
        }
    return user_states[user_id]


def run_health_server():
    port = int(os.environ.get("PORT", 8080))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    state = get_user_state(user.id)
    state["state"] = STATE_IDLE
    keyboard = [
        [InlineKeyboardButton("Создать новый стикерпак", callback_data="new_pack")],
        [InlineKeyboardButton("Добавить в существующий пак", callback_data="existing_pack")],
    ]
    await update.message.reply_text(
        "Привет, " + user.first_name + "! Я конвертирую видео-кружки в видео стикеры. Что хочешь сделать?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n/start - главное меню\n/mypack - твой стикерпак\n/reset - сбросить настройки"
    )


async def my_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = get_user_state(update.effective_user.id)
    if state["pack_name"]:
        await update.message.reply_text(
            "Твой стикерпак: "
            + state["pack_title"]
            + "\nhttps://t.me/addstickers/"
            + state["pack_name"]
        )
    else:
        await update.message.reply_text("Стикерпак не выбран. Нажми /start")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_states[update.effective_user.id] = {
        "state": STATE_IDLE,
        "pack_name": None,
        "pack_title": None,
        "pending_video_path": None,
        "pending_video_duration": None,
        "pending_tmpdir": None,
        "trim_start": None,
        "trim_end": None,
    }
    await update.message.reply_text("Сброшено. Нажми /start")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    state = get_user_state(query.from_user.id)
    if query.data == "new_pack":
        state["state"] = STATE_WAITING_PACK_NAME
        await query.edit_message_text(
            "Введи короткое имя для стикерпака (только латинские буквы, цифры и _).\nПример: my_stickers"
        )
    elif query.data == "existing_pack":
        state["state"] = STATE_WAITING_EXISTING_PACK
        await query.edit_message_text(
            "Отправь ссылку на стикерпак или его имя.\nПример: https://t.me/addstickers/my_stickers"
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    text = update.message.text.strip()

    if state["state"] == STATE_WAITING_PACK_NAME:
        import re
        clean = re.sub(r"[^a-zA-Z0-9_]", "", text)
        if len(clean) < 2:
            await update.message.reply_text("Слишком короткое. Только латиница, цифры, _")
            return
        state["pack_name_short"] = clean
        state["state"] = STATE_WAITING_PACK_TITLE
        await update.message.reply_text(
            "Имя: " + clean + "\n\nТеперь введи название стикерпака.\nПример: Мои стикеры"
        )

    elif state["state"] == STATE_WAITING_PACK_TITLE:
        if len(text) < 2 or len(text) > 64:
            await update.message.reply_text("Название от 2 до 64 символов.")
            return
        state["pack_title"] = text
        await create_new_pack(update, context, state)

    elif state["state"] == STATE_WAITING_EXISTING_PACK:
        pack_name = text
        if "t.me/addstickers/" in text:
            pack_name = text.split("t.me/addstickers/")[-1].strip("/")
        await try_connect_pack(update, context, state, pack_name)

    elif state["state"] == STATE_WAITING_TRIM_START:
        try:
            val = float(text.replace(",", "."))
            dur = state["pending_video_duration"]
            if val < 0 or val >= dur:
                await update.message.reply_text("Введи число от 0 до " + str(round(dur, 1)))
                return
            state["trim_start"] = val
            state["state"] = STATE_WAITING_TRIM_END
            await update.message.reply_text(
                "Начало: " + str(val) + " сек.\n\nТеперь введи конечную секунду (макс 3 сек от начала).\nДлина видео: " + str(round(dur, 1)) + " сек."
            )
        except ValueError:
            await update.message.reply_text("Введи число, например: 0 или 1.5")

    elif state["state"] == STATE_WAITING_TRIM_END:
        try:
            val = float(text.replace(",", "."))
            start = state["trim_start"]
            dur = state["pending_video_duration"]
            if val <= start:
                await update.message.reply_text("Конец должен быть больше начала (" + str(start) + ")")
                return
            if val - start > 3:
                await update.message.reply_text("Максимум 3 секунды. Введи не больше " + str(round(start + 3, 1)))
                return
            if val > dur:
                await update.message.reply_text("Видео заканчивается на " + str(round(dur, 1)) + " сек.")
                return
            state["trim_end"] = val
            state["state"] = STATE_READY
            await process_trimmed_video(update, context, state)
        except ValueError:
            await update.message.reply_text("Введи число, например: 3 или 2.5")

    else:
        if state["state"] == STATE_IDLE:
            await update.message.reply_text("Нажми /start")
        else:
            await update.message.reply_text("Отправь видео-кружок!")


async def create_new_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict):
    user_id = update.effective_user.id
    bot_user = await context.bot.get_me()
    pack_name = state["pack_name_short"] + "_by_" + bot_user.username
    pack_title = state["pack_title"]
    msg = await update.message.reply_text("Создаю стикерпак...")
    try:
        placeholder = await make_placeholder()
        with open(placeholder, "rb") as f:
            await context.bot.create_new_sticker_set(
                user_id=user_id,
                name=pack_name,
                title=pack_title,
                stickers=[{"sticker": f, "emoji_list": ["\U0001f3ac"], "format": "video"}],
                sticker_format="video",
            )
        os.unlink(placeholder)
        state["pack_name"] = pack_name
        state["pack_title"] = pack_title
        state["state"] = STATE_READY
        await msg.edit_text(
            "Стикерпак создан!\n"
            + pack_title
            + "\nhttps://t.me/addstickers/"
            + pack_name
            + "\n\nТеперь пересылай мне кружки!"
        )
    except Exception as e:
        await msg.edit_text("Ошибка: " + str(e) + "\n\nПопробуй другое имя или /start заново.")


async def try_connect_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict, pack_name: str):
    msg = await update.message.reply_text("Проверяю...")
    try:
        s = await context.bot.get_sticker_set(pack_name)
        state["pack_name"] = pack_name
        state["pack_title"] = s.title
        state["state"] = STATE_READY
        await msg.edit_text(
            "Подключено!\n"
            + s.title
            + "\nhttps://t.me/addstickers/"
            + pack_name
            + "\n\nПересылай кружки!"
        )
    except Exception as e:
        await msg.edit_text("Не найден: " + pack_name + "\nОшибка: " + str(e))


def get_duration(path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10
        )
        return float(r.stdout.strip())
    except Exception:
        return None


async def video_note_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)

    if state["state"] not in (STATE_READY,):
        if state["state"] == STATE_IDLE:
            keyboard = [
                [InlineKeyboardButton("Создать новый стикерпак", callback_data="new_pack")],
                [InlineKeyboardButton("Добавить в существующий", callback_data="existing_pack")],
            ]
            await update.message.reply_text(
                "Сначала настрой стикерпак!", reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return

    msg = await update.message.reply_text("Скачиваю...")
    try:
        file = await context.bot.get_file(update.message.video_note.file_id)
        tmpdir = tempfile.mkdtemp()
        inp = os.path.join(tmpdir, "in.mp4")
        await file.download_to_drive(inp)

        duration = get_duration(inp)
        if duration is None:
            await msg.edit_text("Не удалось определить длину видео.")
            return

        dur_str = str(round(duration, 1))

        if duration <= 3:
            await msg.edit_text("Конвертирую...")
            out = os.path.join(tmpdir, "out.webm")
            ok = convert(inp, out, 0, duration)
            if ok:
                await add_sticker(update, context, state, msg, out)
            else:
                state["pending_video_path"] = inp
                state["pending_video_duration"] = duration
                state["pending_tmpdir"] = tmpdir
                state["state"] = STATE_WAITING_TRIM_START
                await msg.edit_text(
                    "Длина: " + dur_str + " сек.\n\n"
                    "Не удалось сжать автоматически.\n"
                    "Введи начальную секунду для обрезки (например: 0):"
                )
        else:
            state["pending_video_path"] = inp
            state["pending_video_duration"] = duration
            state["pending_tmpdir"] = tmpdir
            state["state"] = STATE_WAITING_TRIM_START
            await msg.edit_text(
                "Длина видео: " + dur_str + " сек. (больше 3 сек.)\n\n"
                "Введи начальную секунду для обрезки (например: 0 или 1.5):"
            )
    except Exception as e:
        await msg.edit_text("Ошибка: " + str(e))


async def process_trimmed_video(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict):
    msg = await update.message.reply_text("Конвертирую...")
    try:
        inp = state["pending_video_path"]
        tmpdir = state["pending_tmpdir"]
        start = state["trim_start"]
        end = state["trim_end"]
        out = os.path.join(tmpdir, "out.webm")

        ok = convert(inp, out, start, end - start)
        if ok:
            await add_sticker(update, context, state, msg, out)
        else:
            await msg.edit_text(
                "Не удалось сжать до 256KB.\n"
                "Попробуй более короткий отрезок.\n\n"
                "Введи начальную секунду снова:"
            )
            state["state"] = STATE_WAITING_TRIM_START
    except Exception as e:
        await msg.edit_text("Ошибка: " + str(e))
        state["state"] = STATE_READY


async def add_sticker(update, context, state, msg, out):
    user_id = update.effective_user.id
    try:
        with open(out, "rb") as f:
            await context.bot.add_sticker_to_set(
                user_id=user_id,
                name=state["pack_name"],
                sticker={"sticker": f, "emoji_list": ["\U0001f3ac"], "format": "video"},
            )
        state["state"] = STATE_READY
        await msg.edit_text(
            "Стикер добавлен!\nhttps://t.me/addstickers/" + state["pack_name"]
        )
    except Exception as e:
        if "STICKERSET_INVALID" in str(e):
            state["state"] = STATE_IDLE
            await msg.edit_text("Стикерпак не найден. Нажми /start заново.")
        else:
            await msg.edit_text("Ошибка при добавлении: " + str(e))


def convert(inp, out, start, duration):
    try:
        for crf in [33, 40, 48, 55]:
            r = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(start),
                    "-i", inp,
                    "-t", str(min(duration, 3)),
                    "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=512:512:flags=lanczos",
                    "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf),
                    "-an", "-pix_fmt", "yuva420p", "-deadline", "realtime", "-cpu-used", "8",
                    out,
                ],
                capture_output=True,
                timeout=60,
            )
            if r.returncode == 0 and os.path.exists(out):
                if os.path.getsize(out) <= 256 * 1024:
                    return True
        return False
    except Exception:
        return False


async def make_placeholder():
    f = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
    f.close()
    r = subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=512x512:d=1",
            "-c:v", "libvpx-vp9", "-b:v", "50k", "-an", "-pix_fmt", "yuva420p", "-t", "1",
            f.name,
        ],
        capture_output=True,
        timeout=30,
    )
    if r.returncode != 0:
        raise Exception("ffmpeg error: " + r.stderr.decode())
    return f.name


def main():
    if not BOT_TOKEN:
        print("No BOT_TOKEN!")
        return
    t = threading.Thread(target=run_health_server, daemon=True)
    t.start()
    print("Bot started!")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mypack", my_pack))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, video_note_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
