"""
Бот для обработки фотографий.
Функции: удаление фона, изменение размера, добавление водяного знака.
"""
import io
import logging
import os

from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID", "")

user_state: dict[int, dict] = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("🔲 Удалить фон", callback_data="remove_bg")],
        [InlineKeyboardButton("📐 Изменить размер", callback_data="resize")],
        [InlineKeyboardButton("💧 Водяной знак", callback_data="watermark")],
    ]
    await update.message.reply_text(
        "Привет! Я помогу обработать ваши фотографии.\n\n"
        "Выберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    action = query.data
    user_state[user_id] = {"action": action}

    messages = {
        "remove_bg": "Отправьте фото — я удалю фон и пришлю PNG с прозрачным фоном.",
        "resize": "Отправьте фото. Затем укажите размер: например, «800x600».",
        "watermark": "Отправьте фото — я добавлю водяной знак с вашим именем.",
    }
    await query.edit_message_text(messages[action])


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    state = user_state.get(user_id)

    if not state:
        keyboard = [[InlineKeyboardButton("📋 Выбрать действие", callback_data="menu")]]
        await update.message.reply_text(
            "Сначала выберите действие через /start",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    action = state.get("action")
    await update.message.reply_text("⏳ Обрабатываю фото...")

    tg_file = await update.message.photo[-1].get_file()
    file_bytes = await tg_file.download_as_bytearray()
    img = Image.open(io.BytesIO(bytes(file_bytes))).convert("RGBA")

    try:
        if action == "remove_bg":
            result_bytes = _remove_bg(img)
            await update.message.reply_document(
                document=io.BytesIO(result_bytes),
                filename="result_no_bg.png",
                caption="✅ Готово! Фон удалён.",
            )

        elif action == "resize":
            state["photo_bytes"] = bytes(file_bytes)
            user_state[user_id] = state
            await update.message.reply_text(
                "Укажите размер в формате «ширинаxвысота», например: «800x600»"
            )
            return

        elif action == "watermark":
            name = update.effective_user.first_name or "Клиент"
            result_bytes = _add_watermark(img, name)
            await update.message.reply_photo(
                photo=io.BytesIO(result_bytes),
                caption="✅ Готово! Водяной знак добавлен.",
            )

        user_state.pop(user_id, None)
        keyboard = [[InlineKeyboardButton("🔄 Обработать ещё", callback_data="menu")]]
        await update.message.reply_text(
            "Хотите обработать ещё одно фото?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.error(f"Processing error: {e}")
        await update.message.reply_text(f"❌ Ошибка обработки: {e}\nПопробуйте ещё раз.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    state = user_state.get(user_id, {})

    if state.get("action") == "resize" and state.get("photo_bytes"):
        size_text = update.message.text.strip().lower().replace(" ", "")
        if "x" not in size_text:
            await update.message.reply_text("Укажите размер в формате «800x600»")
            return
        try:
            w, h = map(int, size_text.split("x"))
        except ValueError:
            await update.message.reply_text("Неверный формат. Используйте: «800x600»")
            return

        img = Image.open(io.BytesIO(state["photo_bytes"])).convert("RGBA")
        img = img.resize((w, h), Image.LANCZOS)
        output = io.BytesIO()
        img.save(output, format="PNG")
        output.seek(0)

        await update.message.reply_document(
            document=output,
            filename=f"result_{w}x{h}.png",
            caption=f"✅ Готово! Размер изменён до {w}×{h} px.",
        )
        user_state.pop(user_id, None)
    else:
        await update.message.reply_text("Отправьте /start чтобы начать.")


async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🔲 Удалить фон", callback_data="remove_bg")],
        [InlineKeyboardButton("📐 Изменить размер", callback_data="resize")],
        [InlineKeyboardButton("💧 Водяной знак", callback_data="watermark")],
    ]
    await query.edit_message_text(
        "Выберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def _remove_bg(img: Image.Image) -> bytes:
    """Simple background removal by making white/light pixels transparent."""
    img = img.convert("RGBA")
    data = img.getdata()
    new_data = []
    for item in data:
        r, g, b, a = item
        # Consider pixel "background" if it's close to white
        if r > 200 and g > 200 and b > 200:
            new_data.append((r, g, b, 0))
        else:
            new_data.append(item)
    img.putdata(new_data)
    output = io.BytesIO()
    img.save(output, format="PNG")
    return output.getvalue()


def _add_watermark(img: Image.Image, text: str) -> bytes:
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(img)
    w, h = img.size
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=max(20, h // 20))
    except Exception:
        font = ImageFont.load_default()
    watermark = f"© {text}"
    bbox = draw.textbbox((0, 0), watermark, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = w - tw - 20, h - th - 20
    draw.text((x + 2, y + 2), watermark, fill=(0, 0, 0, 100), font=font)
    draw.text((x, y), watermark, fill=(255, 255, 255, 200), font=font)
    output = io.BytesIO()
    img.save(output, format="PNG")
    return output.getvalue()


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_menu, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(handle_action, pattern="^(remove_bg|resize|watermark)$"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()


if __name__ == "__main__":
    main()
