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

def get_user_state(user_id):
if user_id not in user_states:
user_states[user_id] = {
"state": STATE_IDLE,
"pack_name": None,
"pack_title": None,
}
return user_states[user_id]

def run_health_server():
port = int(os.environ.get("PORT", 8080))

```
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass

server = HTTPServer(("0.0.0.0", port), Handler)
server.serve_forever()
```

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
user = update.effective_user
state = get_user_state(user.id)
state["state"] = STATE_IDLE
keyboard = [
[InlineKeyboardButton("Создать новый стикерпак", callback_data="new_pack")],
[InlineKeyboardButton("Добавить в существующий пак", callback_data="existing_pack")],
]
await update.message.reply_text(
"Привет, " + user.first_name + "! Отправь мне видео-кружок после настройки пака.",
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
"Твой стикерпак: " + state["pack_title"] + "\nhttps://t.me/addstickers/" + state["pack_name"]
)
else:
await update.message.reply_text("Стикерпак не выбран. Нажми /start")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_states[update.effective_user.id] = {
"state": STATE_IDLE,
"pack_name": None,
"pack_title": None,
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
else:
if state["state"] == STATE_IDLE:
await update.message.reply_text("Нажми /start")
else:
await update.message.reply_text("Отправь видео-кружок!")

async def create_new_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict):
user_id = update.effective_user.id
bot_user = await context.bot.get_me()
pack_name = state["pack_name_short"] + "*by*" + bot_user.username
pack_title = state["pack_title"]
msg = await update.message.reply_text("Создаю стикерпак…")
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
"Стикерпак создан!\n" + pack_title + "\nhttps://t.me/addstickers/" + pack_name + "\n\nТеперь пересылай мне кружки!"
)
except Exception as e:
await msg.edit_text("Ошибка: " + str(e) + "\n\nПопробуй другое имя или /start заново.")

async def try_connect_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict, pack_name: str):
msg = await update.message.reply_text("Проверяю…")
try:
s = await context.bot.get_sticker_set(pack_name)
state["pack_name"] = pack_name
state["pack_title"] = s.title
state["state"] = STATE_READY
await msg.edit_text(
"Подключено!\n" + s.title + "\nhttps://t.me/addstickers/" + pack_name + "\n\nПересылай кружки!"
)
except Exception as e:
await msg.edit_text("Не найден: " + pack_name + "\nОшибка: " + str(e))

async def video_note_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = update.effective_user.id
state = get_user_state(user_id)
if state["state"] != STATE_READY or not state["pack_name"]:
keyboard = [
[InlineKeyboardButton("Создать новый стикерпак", callback_data="new_pack")],
[InlineKeyboardButton("Добавить в существующий", callback_data="existing_pack")],
]
await update.message.reply_text(
"Сначала настрой стикерпак!", reply_markup=InlineKeyboardMarkup(keyboard)
)
return
msg = await update.message.reply_text("Конвертирую…")
try:
file = await context.bot.get_file(update.message.video_note.file_id)
with tempfile.TemporaryDirectory() as d:
inp = os.path.join(d, "in.mp4")
out = os.path.join(d, "out.webm")
await file.download_to_drive(inp)
ok = convert(inp, out)
if not ok:
await msg.edit_text("Ошибка конвертации. Кружок не длиннее 3 секунд.")
return
if os.path.getsize(out) > 256 * 1024:
await msg.edit_text("Файл слишком большой. Попробуй короткий кружок.")
return
with open(out, "rb") as f:
await context.bot.add_sticker_to_set(
user_id=user_id,
name=state["pack_name"],
sticker={"sticker": f, "emoji_list": ["\U0001f3ac"], "format": "video"},
)
await msg.edit_text("Стикер добавлен!\nhttps://t.me/addstickers/" + state["pack_name"])
except Exception as e:
if "STICKERSET_INVALID" in str(e):
state["state"] = STATE_IDLE
await msg.edit_text("Стикерпак не найден. Нажми /start заново.")
else:
await msg.edit_text("Ошибка: " + str(e))

def convert(inp, out):
try:
r = subprocess.run(
[
"ffmpeg", "-y", "-i", inp, "-t", "3",
"-vf", "crop=min(iw\,ih):min(iw\,ih),scale=512:512:flags=lanczos",
"-c:v", "libvpx-vp9", "-b:v", "400k", "-crf", "30",
"-an", "-pix_fmt", "yuva420p", "-deadline", "realtime", "-cpu-used", "8",
out,
],
capture_output=True,
timeout=60,
)
return r.returncode == 0 and os.path.exists(out)
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

if **name** == "**main**":
main()