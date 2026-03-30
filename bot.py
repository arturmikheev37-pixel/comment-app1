import asyncio
import sqlite3
import aiohttp
from datetime import datetime
from maxbot.bot import Bot
from maxbot.dispatcher import Dispatcher
from maxbot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message
)

BOT_TOKEN = "f9LHodD0cOIdrNPjh3CWiZlW8bj-DhNpjF6VBTWDQP66-wijDIChpbtLyNZeZOtubmx3thZhMxQe7j8oXnCq"

# ⭐ Имя бота (ваш username в MAX)
BOT_USERNAME = "id250300578953_1_bot"

# ⭐ URL веб-приложения (пока заглушка, потом заменим)
WEB_APP_URL = "https://arturmikheev37-pixel-comment-app1-be1e.twc1.net"

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot)

# ========== БАЗА ДАННЫХ (общая с веб-апп) ==========
conn = sqlite3.connect("comments.db")
cursor = conn.cursor()

# Таблица для счётчиков постов (общая с веб-апп)
cursor.execute("""
    CREATE TABLE IF NOT EXISTS post_counts (
        post_id TEXT PRIMARY KEY,
        count INTEGER DEFAULT 0,
        updated_at TEXT
    )
""")
conn.commit()


async def get_comment_count(post_id: str) -> int:
    """Получает количество комментариев из общей БД"""
    cursor.execute("SELECT count FROM post_counts WHERE post_id = ?", (post_id,))
    row = cursor.fetchone()
    return row[0] if row else 0


async def update_post_counter(post_id: str, count: int):
    """Обновляет кнопку с новым счётчиком"""
    try:
        button_text = f"✏️ Написать комментарий ({count})" if count > 0 else "✏️ Написать комментарий"
        miniapp_link = f"https://max.ru/{BOT_USERNAME}?startapp={post_id}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=button_text, type="link", url=miniapp_link)]
        ])
        
        await bot.update_message(message_id=post_id, reply_markup=keyboard)
        print(f"✅ Обновлена кнопка {post_id[:20]}... → {count} комм.")
    except Exception as e:
        print(f"❌ Ошибка обновления: {e}")


@dp.message()
async def handle_post(message: Message):
    if not message.text:
        return
    
    print(f"📨 Получен пост: {message.id[:20]}...")
    
    # Получаем количество комментариев из общей БД
    count = await get_comment_count(message.id)
    
    # Формируем кнопку
    button_text = f"✏️ Написать комментарий ({count})" if count > 0 else "✏️ Написать комментарий"
    user_id = message.sender.id if message.sender else "unknown"
    user_name = message.sender.name if message.sender else "Гость"
    
    miniapp_link = f"https://max.ru/{BOT_USERNAME}?startapp={message.id}&user_id={user_id}&username={user_name}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=button_text, type="link", url=miniapp_link)]
    ])
    
    try:
        await bot.update_message(
            message_id=message.id,
            text=message.text,
            reply_markup=keyboard
        )
        print(f"✅ Кнопка добавлена (комм: {count})")
    except Exception as e:
        print(f"❌ Ошибка: {e}")


async def periodic_update():
    """Раз в минуту обновляет счётчики из общей БД"""
    await asyncio.sleep(10)
    while True:
        await asyncio.sleep(60)
        try:
            cursor.execute("SELECT post_id, count FROM post_counts")
            posts = cursor.fetchall()
            
            for post_id, count in posts:
                await update_post_counter(post_id, count)
                
        except Exception as e:
            print(f"❌ Ошибка обновления: {e}")


async def main():
    print("=" * 60)
    print("🤖 БОТ ДЛЯ КОММЕНТАРИЕВ MAX")
    print("=" * 60)
    print(f"🌐 Веб-приложение: {WEB_APP_URL}")
    print()
    print("💡 КАК ЭТО РАБОТАЕТ:")
    print("1. При публикации поста — бот добавляет кнопку со счётчиком")
    print("2. Счётчик обновляется из общей БД с веб-апп")
    print("3. При нажатии открывается Web App с WebSocket")
    print("4. Комментарии появляются мгновенно у всех")
    print("=" * 60)
    
    asyncio.create_task(periodic_update())
    
    try:
        await dp.run_polling()
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
