import asyncio
import sqlite3
import aiohttp
from datetime import datetime
from maxbot.bot import Bot
from maxbot.dispatcher import Dispatcher
from maxbot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    Callback
)

BOT_TOKEN = "f9LHodD0cOIdrNPjh3CWiZlW8bj-DhNpjF6VBTWDQP66-wijDIChpbtLyNZeZOtubmx3thZhMxQe7j8oXnCq"

# ⭐ Имя бота (ваш username в MAX)
BOT_USERNAME = "id250300578953_1_bot"

# ⭐ URL веб-приложения (пока заглушка, потом заменим)
WEB_APP_URL = "https://arturmikheev37-pixel-comment-app1-be1e.twc1.net"

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot)

# ========== БАЗА ДАННЫХ ==========
conn = sqlite3.connect("comments.db")
cursor = conn.cursor()

# Удаляем старую таблицу, если есть, и создаём заново с правильной структурой
cursor.execute("DROP TABLE IF EXISTS posts")
cursor.execute("DROP TABLE IF EXISTS channels")
cursor.execute("DROP TABLE IF EXISTS comments")

# Таблица для постов и их счётчиков
cursor.execute("""
    CREATE TABLE posts (
        post_id TEXT PRIMARY KEY,
        channel_id TEXT,
        author_id TEXT,
        author_name TEXT,
        text TEXT,
        created_at TIMESTAMP,
        comment_count INTEGER DEFAULT 0,
        last_update TIMESTAMP
    )
""")

# Таблица для каналов, где находится бот
cursor.execute("""
    CREATE TABLE channels (
        channel_id TEXT PRIMARY KEY,
        channel_name TEXT,
        added_at TIMESTAMP
    )
""")

# Таблица для комментариев (будет использоваться веб-приложением)
cursor.execute("""
    CREATE TABLE comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        username TEXT NOT NULL,
        comment TEXT NOT NULL,
        created_at TIMESTAMP
    )
""")

conn.commit()
print("✅ База данных создана с правильной структурой")


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

async def get_comment_count_from_api(post_id: str) -> int:
    """Получает количество комментариев из API веб-приложения"""
    try:
        url = f"{WEB_APP_URL}/api/comments/{post_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    return len(data.get("comments", []))
    except Exception as e:
        print(f"⚠️ Ошибка получения счётчика из API: {e}")
    return 0


async def update_post_counter(post_id: str, count: int):
    """Обновляет счётчик на кнопке поста"""
    try:
        # Формируем текст кнопки
        if count > 0:
            button_text = f"✏️ Написать комментарий ({count})"
        else:
            button_text = "✏️ Написать комментарий"

        # Ссылка на мини-приложение с данными поста
        miniapp_link = f"https://max.ru/{BOT_USERNAME}?startapp={post_id}"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button_text,
                    type="link",
                    url=miniapp_link
                )
            ]
        ])

        # Обновляем сообщение
        await bot.update_message(
            message_id=post_id,
            reply_markup=keyboard
        )
        print(f"✅ Обновлён счётчик для {post_id[:20]}... → {count} комм.")
        return True
    except Exception as e:
        print(f"❌ Ошибка обновления кнопки: {e}")
        return False


def save_post_to_db(message: Message):
    """Сохраняет информацию о посте в базу данных"""
    try:
        post_id = message.id
        channel_id = str(message.chat.id) if message.chat else None
        author_id = str(message.sender.id) if message.sender else None
        author_name = message.sender.name if message.sender else "Неизвестно"
        text = message.text[:500] if message.text else ""

        cursor.execute("""
            INSERT OR REPLACE INTO posts (post_id, channel_id, author_id, author_name, text, created_at, comment_count, last_update)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (post_id, channel_id, author_id, author_name, text, datetime.now(), 0, datetime.now()))
        conn.commit()

        print(f"📝 Пост сохранён: {post_id[:20]}... от {author_name}")
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения поста: {e}")
        return False


# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========

@dp.message()
async def handle_post(message: Message):
    """Обрабатывает каждый пост в канале"""

    # Проверяем, что это текстовое сообщение
    if not message.text:
        print("⚠️ Сообщение без текста — пропускаем")
        return

    # Определяем тип чата
    chat_type = message.chat.type if message.chat else "unknown"

    # Сохраняем канал, если это канал
    if chat_type == "channel" and message.chat:
        channel_name = str(message.chat.id)
        cursor.execute("""
            INSERT OR IGNORE INTO channels (channel_id, channel_name, added_at)
            VALUES (?, ?, ?)
        """, (str(message.chat.id), channel_name, datetime.now()))
        conn.commit()
        print(f"📢 Канал: {channel_name}")

    # Сохраняем пост в базу
    save_post_to_db(message)

    # Получаем количество комментариев
    try:
        count = await get_comment_count_from_api(message.id)
    except:
        count = 0

    # Обновляем счётчик в базе
    cursor.execute("""
        UPDATE posts SET comment_count = ?, last_update = ? WHERE post_id = ?
    """, (count, datetime.now(), message.id))
    conn.commit()

    # Формируем текст кнопки
    button_text = f"✏️ Написать комментарий ({count})" if count > 0 else "✏️ Написать комментарий"

    # Формируем ссылку на мини-приложение
    user_id = str(message.sender.id) if message.sender else "unknown"
    user_name = message.sender.name if message.sender else "Гость"

    miniapp_link = f"https://max.ru/{BOT_USERNAME}?startapp={message.id}&user_id={user_id}&username={user_name}"

    # Создаём кнопку
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=button_text,
                type="link",
                url=miniapp_link
            )
        ]
    ])

    try:
        await bot.update_message(
            message_id=message.id,
            text=message.text,
            reply_markup=keyboard
        )
        print(f"✅ Кнопка добавлена к посту {message.id[:20]}...")
        print(f"   Канал: {message.chat.id if message.chat else 'неизвестен'}")
        print(f"   Автор: {user_name} ({user_id})")
        print(f"   Комментариев: {count}")
    except Exception as e:
        print(f"❌ Ошибка добавления кнопки: {e}")


@dp.callback()
async def handle_callback(callback: Callback):
    """Обрабатывает нажатия на кнопки (если будут)"""
    print(f"🔘 Получен callback: {callback.payload}")
    try:
        await callback.answer()
    except:
        pass


# ========== ФОНОВОЕ ОБНОВЛЕНИЕ СЧЁТЧИКОВ ==========

async def update_all_counters():
    """Фоновая задача: раз в минуту обновляет счётчики на всех постах"""
    await asyncio.sleep(10)  # Начальная задержка

    while True:
        await asyncio.sleep(60)  # Каждую минуту

        try:
            # Получаем все посты
            cursor.execute("SELECT post_id, comment_count FROM posts")
            posts = cursor.fetchall()

            if not posts:
                continue

            print(f"\n🔄 Проверка {len(posts)} постов...")
            updated = 0

            for post_id, old_count in posts:
                try:
                    new_count = await get_comment_count_from_api(post_id)

                    if new_count != old_count:
                        print(f"   {post_id[:20]}...: {old_count} → {new_count}")
                        await update_post_counter(post_id, new_count)

                        cursor.execute("""
                            UPDATE posts SET comment_count = ?, last_update = ? WHERE post_id = ?
                        """, (new_count, datetime.now(), post_id))
                        conn.commit()
                        updated += 1

                except Exception as e:
                    print(f"   ❌ Ошибка обновления {post_id[:20]}: {e}")

            if updated > 0:
                print(f"✅ Обновлено {updated} постов")
            else:
                print("📊 Изменений нет")

        except Exception as e:
            print(f"❌ Ошибка в фоновом обновлении: {e}")


# ========== КОМАНДЫ ==========

@dp.message()
async def handle_commands(message: Message):
    """Обрабатывает команды /start и /channels"""

    if not message.text:
        return

    if message.text == "/start":
        await bot.send_message(
            chat_id=message.sender.id,
            text="🤖 **Бот для комментариев MAX**\n\n"
                 "Я добавляю кнопки под постами в каналах.\n\n"
                 "📌 **Команды:**\n"
                 "/channels — список каналов, где я нахожусь\n"
                 "/stats — статистика постов\n\n"
                 "При нажатии на кнопку открывается мини-приложение для комментариев.",
            format="markdown"
        )
        print(f"👋 Приветствие отправлено {message.sender.name}")

    elif message.text == "/channels":
        cursor.execute("SELECT channel_id, channel_name, added_at FROM channels")
        channels = cursor.fetchall()

        if channels:
            text = "📢 **Каналы, где я нахожусь:**\n\n"
            for ch_id, ch_name, added in channels:
                text += f"• {ch_name}\n"
            await bot.send_message(
                chat_id=message.sender.id,
                text=text,
                format="markdown"
            )
        else:
            await bot.send_message(
                chat_id=message.sender.id,
                text="📢 Я пока не добавлен ни в один канал.\n\n"
                     "Добавьте меня в канал как администратора, и я начну работать!",
                format="markdown"
            )
        print(f"📋 Список каналов отправлен {message.sender.name}")

    elif message.text == "/stats":
        cursor.execute("SELECT COUNT(*) FROM posts")
        total_posts = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(comment_count) FROM posts")
        total_comments = cursor.fetchone()[0] or 0

        await bot.send_message(
            chat_id=message.sender.id,
            text=f"📊 **Статистика:**\n\n"
                 f"📝 Всего постов: {total_posts}\n"
                 f"💬 Всего комментариев: {total_comments}",
            format="markdown"
        )
        print(f"📊 Статистика отправлена {message.sender.name}")


# ========== ЗАПУСК ==========

async def main():
    print("=" * 70)
    print("🤖 БОТ ДЛЯ КОММЕНТАРИЕВ MAX")
    print("=" * 70)
    print()

    # Информация о боте
    bot_info = await bot.get_me()
    print(f"📱 Имя бота: {bot_info.get('name', 'Неизвестно')}")
    print(f"🆔 Username: {bot_info.get('username', 'Неизвестно')}")
    print(f"🌐 Веб-приложение: {WEB_APP_URL}")
    print()

    # Список каналов
    cursor.execute("SELECT channel_id, channel_name FROM channels")
    channels = cursor.fetchall()
    if channels:
        print("📢 Активные каналы:")
        for ch_id, ch_name in channels:
            print(f"   • {ch_name}")
    else:
        print("📢 Бот пока не добавлен ни в один канал")
    print()

    print("💡 КАК ЭТО РАБОТАЕТ:")
    print("1. Добавьте бота в канал как администратора")
    print("2. При публикации поста — бот добавляет кнопку со счётчиком")
    print("3. Счётчик обновляется каждую минуту")
    print("4. При нажатии на кнопку открывается мини-приложение")
    print("=" * 70)
    print()
    print("🚀 Бот запущен и готов к работе!")
    print()

    # Запускаем фоновое обновление
    asyncio.create_task(update_all_counters())

    try:
        await dp.run_polling()
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
