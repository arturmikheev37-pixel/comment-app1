import asyncio
import sqlite3
from datetime import datetime
from maxbot.bot import Bot
from maxbot.dispatcher import Dispatcher
from maxbot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

BOT_TOKEN = "f9LHodD0cOIdrNPjh3CWiZlW8bj-DhNpjF6VBTWDQP66-wijDIChpbtLyNZeZOtubmx3thZhMxQe7j8oXnCq"
BOT_USERNAME = "id250300578953_1_bot"
MINI_APP_URL = "https://arturmikheev37-pixel-comment-app1-be1e.twc1.net/"  # адрес вашего веб-приложения

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot)

# ---------------- База данных ----------------
conn = sqlite3.connect("comments.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS posts (
    post_id TEXT PRIMARY KEY,
    created_at TIMESTAMP
)
""")
conn.commit()

# ---------------- Обработка постов ----------------
@dp.message()
async def handle_post(message: Message):
    if not message.text:
        return

    print(f"📨 Новый пост: ID {message.id}")

    # Сохраняем пост
    cursor.execute(
        "INSERT OR IGNORE INTO posts (post_id, created_at) VALUES (?, ?)",
        (message.id, datetime.now())
    )
    conn.commit()

    # Ссылка на мини-приложение с параметром post_id
    miniapp_link = f"{MINI_APP_URL}?post={message.id}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Написать комментарий", type="link", url=miniapp_link)]
    ])

    try:
        await bot.update_message(
            message_id=message.id,
            text=message.text,
            reply_markup=keyboard
        )
        print(f"✅ Кнопка добавлена к посту {message.id}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

# ---------------- Запуск бота ----------------
async def main():
    print("🤖 Бот для комментариев MAX запущен!")
    try:
        await dp.run_polling()
    finally:
        conn.close()

if __name__ == "__main__":
    asyncio.run(main())
