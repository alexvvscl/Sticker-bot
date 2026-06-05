import os
import asyncio
import tempfile
import subprocess
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

user_states = {}

STATE_IDLE = "idle"
STATE_WAITING_PACK_NAME = "waiting_pack_name"
STATE_WAITING_PACK_TITLE = "waiting_pack_title"
STATE_WAITING_EXISTING_PACK = "waiting_existing_pack"
STATE_READY = "ready"


def get_user_state(user_id: int) -> dict:
    if user_id not in user_states:
        user_states[user_id] = {
            "state": STATE_IDLE,
            "pack_name": None,
            "pack_title": None,
            "is_new_pack": False,
        }
    return user_states[user_id]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    state = get_user_state(user.id)
    state["state"] = STATE_IDLE

    keyboard = [
        [InlineKeyboardButton("🆕 Создать новый стикерпак", callback_data="new_pack")],
        [InlineKeyboardButton("➕ Добавить в существующий пак", callback_data="existing_pack")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\nЯ конвертирую *видео-кружки* в *видео стикеры* для Telegram.\n\nЧто хочешь сделать?",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Как пользоваться ботом:*\n\n1. Нажми /start\n2. Выбери — создать новый стикерпак или добавить в существующий\n3. После настройки — просто пересылай кружки боту\n\n*Команды:*\n/start — главное меню\n/mypack — показать текущий стикерпак\n/reset — сбросить настройки\n/help — эта справка",
        parse_mode=ParseMode.MARKDOWN,
    )


async def my_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)

    if state["pack_name"]:
        pack_link = f"https://t.me/addstickers/{state['pack_name']}"
        await update.message.reply_text(
            f"📦 Твой текущий стикерпак:\n*{state['pack_title']}​​​​​​​​​​​​​​​​
