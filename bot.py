import os
import tempfile
import subprocess 
import imageio_ffmpeg
os.environ["PATH"] += os.pathsep + os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())


from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode

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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    state = get_user_state(user.id)
    state["state"] = STATE_IDLE
    keyboard = [
        [InlineKeyboardButton("Создать новый стикерпак", callback_data="new_pack")],
        [InlineKeyboardButton("Добавить в существующий пак", callback_data="existing_pack")],
    ]
    await update.message.reply_text(
        "Привет, " + user.first_name + "!\n\nЯ конвертирую видео-кружки в видео стикеры для Telegram.\n\nЧто хочешь сделать?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Как пользоваться:\n\n1. Нажми /start\n2. Выбери — создать новый стикерпак или добавить в существующий\n3. После настройки — пересылай кружки боту\n\nКоманды:\n/start — главное меню\n/mypack — показать текущий стикерпак\n/reset — сбросить настройки"
    )


async def my_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    if state["pack_name"]:
        pack_link = "https://t.me/addstickers/" + state["pack_name"]
        await update.message.reply_text("Твой стикерпак: " + state["pack_title"] + "\n\n" + pack_link)
    else:
        await update.message.reply_text("У тебя пока не выбран стикерпак. Нажми /start чтобы настроить.")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = {"state": STATE_IDLE, "pack_name": None, "pack_title": None}
    await update.message.reply_text("Настройки сброшены. Нажми /start чтобы начать заново.")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = get_user_state(user_id)

    if query.data == "new_pack":
        state["state"] = STATE_WAITING_PACK_NAME
        await query.edit_message_text(
            "Создание нового стикерпака\n\nВведи короткое имя для стикерпака (только латинские буквы, цифры и _).\n\nПример: my_cool_stickers"
        )
    elif query.data == "existing_pack":
        state["state"] = STATE_WAITING_EXISTING_PACK
        await query.edit_message_text(
            "Добавление в существующий стикерпак\n\nОтправь ссылку на стикерпак или его короткое имя.\n\nПример: https://t.me/addstickers/my_stickers"
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    text = update.message.text.strip()

    if state["state"] == STATE_WAITING_PACK_NAME:
        import re
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "", text)
        if len(clean_name) < 2:
            await update.message.reply_text("Имя слишком короткое. Используй только латинские буквы, цифры и _")
            return
        state["pack_name_short"] = clean_name
        state["state"] = STATE_WAITING_PACK_TITLE
        await update.message.reply_text("Имя принято: " + clean_name + "\n\nТеперь введи название стикерпака.\n\nПример: Мои крутые стикеры")

    elif state["state"] == STATE_WAITING_PACK_TITLE:
        if len(text) < 2 or len(text) > 64:
            await update.message.reply_text("Название должно быть от 2 до 64 символов.")
            return
        state["pack_title"] = text
        await create_new_pack(update, context, state)

    elif state["state"] == STATE_WAITING_EXISTING_PACK:
        pack_name = text
        if "t.me/addstickers/" in text:
            pack_name = text.split("t.me/addstickers/")[-1].strip("/")
        await try_connect_existing_pack(update, context, state, pack_name)

    else:
        if state["state"] == STATE_READY:
            await update.message.reply_text("Отправь мне видео-кружок для конвертации!")
        else:
            await update.message.reply_text("Нажми /start чтобы настроить стикерпак.")


async def create_new_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict):
    user_id = update.effective_user.id
    bot_user = await context.bot.get_me()
    pack_name = state["pack_name_short"] + "_by_" + bot_user.username
    pack_title = state["pack_title"]
    msg = await update.message.reply_text("Создаю стикерпак...")
    try:
        placeholder_path = await generate_placeholder_sticker()
        with open(placeholder_path, "rb") as f:
            await context.bot.create_new_sticker_set(
                user_id=user_id,
                name=pack_name,
                title=pack_title,
                stickers=[{"sticker": f, "emoji_list": ["🎬"], "format": "video"}],
                sticker_format="video",
            )
        os.unlink(placeholder_path)
        state["pack_name"] = pack_name
        state["pack_title"] = pack_title
        state["state"] = STATE_READY
        pack_link = "https://t.me/addstickers/" + pack_name
        await msg.edit_text("Стикерпак создан!\n\nНазвание: " + pack_title + "\n\n" + pack_link + "\n\nТеперь просто пересылай мне видео-кружки!")
    except Exception as e:
        await msg.edit_text("Ошибка при создании стикерпака:\n" + str(e) + "\n\nПопробуй другое имя или нажми /start заново.")


async def try_connect_existing_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict, pack_name: str):
    msg = await update.message.reply_text("Проверяю стикерпак...")
    try:
        sticker_set = await context.bot.get_sticker_set(pack_name)
        state["pack_name"] = pack_name
        state["pack_title"] = sticker_set.title
        state["state"] = STATE_READY
        pack_link = "https://t.me/addstickers/" + pack_name
        await msg.edit_text("Стикерпак подключён!\n\nНазвание: " + sticker_set.title + "\nСтикеров: " + str(len(sticker_set.stickers)) + "\n\n" + pack_link + "\n\nТеперь просто пересылай мне видео-кружки!")
    except Exception as e:
        await msg.edit_text("Не удалось найти стикерпак " + pack_name + "\n\nОшибка: " + str(e))


async def video_note_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)

    if state["state"] != STATE_READY or not state["pack_name"]:
        keyboard = [
            [InlineKeyboardButton("Создать новый стикерпак", callback_data="new_pack")],
            [InlineKeyboardButton("Добавить в существующий", callback_data="existing_pack")],
        ]
        await update.message.reply_text("Сначала настрой стикерпак!", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    msg = await update.message.reply_text("Конвертирую кружок в стикер...")
    video_note = update.message.video_note

    try:
        file = await context.bot.get_file(video_note.file_id)
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp4")
            output_path = os.path.join(tmpdir, "sticker.webm")
            await file.download_to_drive(input_path)
            success = await convert_to_sticker_webm(input_path, output_path)
            if not success:
                await msg.edit_text("Ошибка конвертации. Убедись, что кружок не длиннее 3 секунд.")
                return
            file_size = os.path.getsize(output_path)
            if file_size > 256 * 1024:
                await msg.edit_text("Файл слишком большой (" + str(file_size // 1024) + "KB, максимум 256KB).")
                return
            with open(output_path, "rb") as f:
                await context.bot.add_sticker_to_set(
                    user_id=user_id,
                    name=state["pack_name"],
                    sticker={"sticker": f, "emoji_list": ["🎬"], "format": "video"},
                )
            pack_link = "https://t.me/addstickers/" + state["pack_name"]
            await msg.edit_text("Стикер добавлен!\n\n" + pack_link)
    except Exception as e:
        error_text = str(e)
        if "STICKERSET_INVALID" in error_text:
            state["state"] = STATE_IDLE
            await msg.edit_text("Стикерпак не найден. Нажми /start чтобы настроить заново.")
        else:
            await msg.edit_text("Ошибка: " + error_text)


async def convert_to_sticker_webm(input_path, output_path):
    try:
        cmd = [
            "ffmpeg", "-y", "-i", input_path, "-t", "3",
            "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=512:512:flags=lanczos",
            "-c:v", "libvpx-vp9", "-b:v", "400k", "-crf", "30",
            "-an", "-pix_fmt", "yuva420p", "-deadline", "realtime", "-cpu-used", "8",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result.returncode == 0 and os.path.exists(output_path)
    except Exception:
        return False


async def generate_placeholder_sticker():
    tmpfile = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
    tmpfile.close()
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=512x512:d=1",
        "-c:v", "libvpx-vp9", "-b:v", "50k", "-an", "-pix_fmt", "yuva420p", "-t", "1",
        tmpfile.name
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        raise Exception("ffmpeg не найден")
    return tmpfile.name


def main():
    if not BOT_TOKEN:
        print("Установи переменную окружения BOT_TOKEN")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mypack", my_pack))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, video_note_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
