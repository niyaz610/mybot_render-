import asyncio
from datetime import datetime, time as dtime
import pytz
from flask import Flask
import threading
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# --- Конфигурация ---
BOT_TOKEN = "8368039960:AAHAzUhtYMd0nLLVx4Fk23dh5oLcazySWKU"
TZ = pytz.timezone("Asia/Yekaterinburg")
ADMINS = [1293474567]
OWNER_ID = 1188715935

# --- Данные пользователей ---
user_message_count = {}
processed_albums = set()


# --- Вспомогательные функции ---
def is_working_day():
    return datetime.now(TZ).weekday() < 5  # пн-пт


def is_privileged_user(user_id):
    return user_id == OWNER_ID or user_id in ADMINS


def get_user_count(chat_id, user_id):
    return user_message_count.get(chat_id, {}).get(user_id, 0)


def increment_user_count(chat_id, user_id):
    if chat_id not in user_message_count:
        user_message_count[chat_id] = {}
    user_message_count[chat_id][user_id] = user_message_count[chat_id].get(
        user_id, 0) + 1
    return user_message_count[chat_id][user_id]


async def delete_message_after_delay(context, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id,
                                         message_id=message_id)
    except:
        pass


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    now = datetime.now(TZ).time()
    weekday = datetime.now(TZ).weekday()  # 0 = понедельник, 6 = воскресенье

    # --- Платные сообщения ---
    if getattr(update.message, "paid_media", None):
        return

    # --- Альбомы ---
    media_group_id = update.message.media_group_id
    if media_group_id:
        if (chat_id, media_group_id) in processed_albums:
            return
        processed_albums.add((chat_id, media_group_id))

    # --- Привилегированные пользователи ---
    if is_privileged_user(user_id):
        return

    # --- Проверка времени и дня ---
    # Если сейчас Пт после 22:00, Сб, Вс, Пн до 10:00 — не удаляем
    if (weekday == 4 and now >= dtime(22, 0)) or \
       (weekday in (5, 6)) or \
       (weekday == 0 and now < dtime(10, 0)):
        return

    # --- Лимит сообщений в рабочие часы ---
    messages_today = get_user_count(chat_id, user_id)
    if messages_today >= 4:
        try:
            await update.message.delete()
        except:
            pass
        return

    current_count = increment_user_count(chat_id, user_id)

    # --- Уведомления пользователю ---
    try:
        if current_count == 1:
            text, delay = "📝 У вас осталось ещё 3 сообщения сегодня", 10
        elif current_count == 2:
            text, delay = "📝 У вас осталось ещё 2 сообщения сегодня", 10
        elif current_count == 3:
            text, delay = "⚠️ Ваше следующее сообщение будет последним за сегодняшний день", 20
        elif current_count == 4:
            text, delay = "✅ Спасибо за ваши сообщения! Ваш дневной лимит к сожалению уже исчерпан.", 30
        else:
            return

        bot_message = await context.bot.send_message(chat_id=chat_id,
                                                     text=text)
        asyncio.create_task(
            delete_message_after_delay(context, chat_id,
                                       bot_message.message_id, delay))
    except:
        pass


# --- Сброс счетчиков ---
async def reset_users(context: ContextTypes.DEFAULT_TYPE):
    global user_message_count, processed_albums
    user_message_count = {}
    processed_albums = set()


# --- Утреннее и вечернее сообщение ---
async def morning_msg(context: ContextTypes.DEFAULT_TYPE):
    text = "🌅 Доброе утро! Предупреждаем! Действует лимит сообщений. Удачного Вам дня!"
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


async def night_msg(context: ContextTypes.DEFAULT_TYPE):
    text = "🌙 Доброй ночи! Ночью сообщения только за звездочки."
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


# --- Flask для мониторинга ---
web_app = Flask('')


@web_app.route('/')
def home():
    return f"Бот работает! Время: {datetime.now(TZ).strftime('%H:%M:%S')}"


@web_app.route('/health')
def health():
    working = is_working_day() and dtime(
        5, 0) <= datetime.now(TZ).time() <= dtime(21, 0)
    return {
        "status": "ok",
        "users_today": sum(len(u) for u in user_message_count.values()),
        "working_now": working,
        "is_working_day": is_working_day()
    }


def run_web():
    web_app.run(host='0.0.0.0', port=8080, debug=False)


threading.Thread(target=run_web, daemon=True).start()

# --- Запуск бота ---
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

# Сброс счетчиков утром
app.job_queue.run_daily(reset_users, dtime(hour=9, minute=59, tzinfo=TZ))
# Утреннее сообщение
app.job_queue.run_daily(morning_msg, dtime(hour=10, minute=0, tzinfo=TZ))
# Вечернее сообщение
app.job_queue.run_daily(night_msg, dtime(hour=22, minute=0, tzinfo=TZ))

app.run_polling()
