import os
import tempfile
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import imageio_ffmpeg
os.environ["PATH"] += os.pathsep + os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

user_states = {}
STATE_IDLE = "idle"
STATE_WAITING_PACK_NAME = "waiting_pack_name"
STATE_WAITING_PACK_TITLE = "waiting_pack_title"
STATE_WAITING_EXISTING_PACK = "waiting_existing_pack"
STATE_READY = "ready"


def get_user_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = {"state": STATE_IDLE, "pack_name": None, "pack_title": None}
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
        "Команды:\n/start - главное меню\n/mypack - твой стикерпак\n/reset - сбросить настройки\n\nПросто пересылай кружки после настройки пака."
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
    user_states[update.effective_user.id] = {"state": STATE_IDLE, "pack_name": None, "pack_title": None}
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
        await update.message.reply_text("Имя: " + clean + "\n\nТеперь введи название стикерпака.\nПример: Мои стикеры")

    elif state["state"] == STATE_WAITING_PACK_TITLE:
        if len​​​​​​​​​​​​​​​​
