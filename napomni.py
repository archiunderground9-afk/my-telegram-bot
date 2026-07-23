import os
import re
import datetime
import threading
import time
from flask import Flask
import pytz
import requests
import telebot
import speech_recognition as sr
import pydub

# 1. Настройка часового пояса (Москва GMT+3)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

def get_moscow_now():
    return datetime.datetime.now(MOSCOW_TZ)

# 2. Токен бота
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8829968340:AAEL-zQ37tWtHYJdzxYE3bSqjGvLcVSJ9T0')
bot = telebot.TeleBot(TOKEN)

# 3. Веб-сервер Flask + Keep-Alive (чтобы Render не отключал и не "усыплял" бота)
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Telegram Bot с таймерами и планировщиком работает 24/7!"

def keep_alive():
    """Пингует сам себя каждые 10 минут, чтобы бесплатный Render не засыпал"""
    time.sleep(15)
    while True:
        try:
            render_url = os.getenv('RENDER_EXTERNAL_URL')
            if render_url:
                requests.get(render_url)
        except Exception as e:
            print(f"Keep-alive error: {e}")
        time.sleep(600)  # каждые 10 минут

# 4. Функция отправки напоминания
def send_reminder(chat_id, task_text):
    try:
        bot.send_message(
            chat_id,
            f"⏰ **НАПОМИНАНИЕ!**\n\n📌 {task_text}\n\n✅ Время пришло!",
            parse_mode='Markdown'
        )
        print(f"Успешно отправлено напоминание в чат {chat_id}: {task_text}")
    except Exception as e:
        print(f"Ошибка отправки сообщения: {e}")

# 5. Функция разбора времени и запуска таймера
def parse_and_schedule(chat_id, text):
    now = get_moscow_now()
    delay_seconds = 0
    
    # А. Поиск формата: 'через N секунд/минут/часов/дней'
    rel_match = re.search(r'через\s+(\d+)\s+(секунд|сек|с|минут|мин|часов|час|ч|дней|день|д)', text, re.IGNORECASE)
    if rel_match:
        num = int(rel_match.group(1))
        unit = rel_match.group(2).lower()
        if 'сек' in unit or unit == 'с':
            delay_seconds = num
        elif 'мин' in unit:
            delay_seconds = num * 60
        elif 'час' in unit or unit == 'ч':
            delay_seconds = num * 3600
        else:
            delay_seconds = num * 86400
        
        task_text = re.sub(r'напомни|через\s+\d+\s+(секунд|сек|с|минут|мин|часов|час|ч|дней|день|д)', '', text, flags=re.IGNORECASE).strip()

    # Б. Поиск формата: 'в HH:MM' (например 'в 18:30')
    else:
        time_match = re.search(r'в\s+(\d{1,2}):(\d{2})', text, re.IGNORECASE)
        if time_match:
            hour, minute = int(time_match.group(1)), int(time_match.group(2))
            target_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_dt <= now:
                target_dt += datetime.timedelta(days=1)  # Перенос на завтра
            
            delay_seconds = (target_dt - now).total_seconds()
            task_text = re.sub(r'напомни|в\s+\d{1,2}:\d{2}', '', text, flags=re.IGNORECASE).strip()
        else:
            delay_seconds = 0
            task_text = ""

    if delay_seconds <= 0:
        bot.send_message(
            chat_id,
            "⚠️ **Не удалось распознать время напоминания!**\n\n"
            "**Суть ошибки:** В команде нет времени.\n\n"
            "**Примеры:**\n"
            "• *напомни через 30 секунд позвонить Роману*\n"
            "• *напомни в 18:30 купить хлеб*",
            parse_mode='Markdown'
        )
        return

    if not task_text:
        task_text = "Напоминание"

    # Запускаем фоновый таймер
    timer = threading.Timer(delay_seconds, send_reminder, args=[chat_id, task_text])
    timer.daemon = True
    timer.start()

    rem_time = now + datetime.timedelta(seconds=delay_seconds)
    formatted_time = rem_time.strftime("%d.%m.%Y в %H:%M:%S")

    bot.send_message(
        chat_id,
        f"✅ **Напоминание установлено!**\n\n"
        f"📌 Задача: {task_text}\n"
        f"⏰ Время (МСК): {formatted_time}",
        parse_mode='Markdown'
    )

# 6. Команда /start
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message,
        "👋 Привет! Я твой бот-напоминалка с таймером и голосовым вводом.\n\n"
        "💡 **Примеры:**\n"
        "• *напомни через 30 секунд позвонить Роману*\n"
        "• *напомни в 18:30 сходить в магазин*\n"
        "• Голосовое сообщение: нажми микрофон и скажи команду!\n\n"
        "Нажми кнопку **меню**, чтобы открыть веб-приложение!",
        parse_mode='Markdown'
    )

# 7. Голосовые сообщения
@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🎙️ Обрабатываю голос...")
    
    ogg_path = f"voice_{message.message_id}.ogg"
    wav_path = f"voice_{message.message_id}.wav"

    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        with open(ogg_path, 'wb') as f:
            f.write(downloaded_file)

        sound = pydub.AudioSegment.from_file(ogg_path)
        sound.export(wav_path, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio = recognizer.record(source)
            text = recognizer.recognize_google(audio, language="ru-RU")

        bot.send_message(chat_id, f"🗣️ Распознано: «{text}»")
        parse_and_schedule(chat_id, text)

    except Exception as e:
        bot.send_message(
            chat_id,
            f"⚠️ **Ошибка распознавания речи!**\n\nСуть: {e}\n\nПовторите чётче или отправьте текстом.",
            parse_mode='Markdown'
        )
    finally:
        if os.path.exists(ogg_path): os.remove(ogg_path)
        if os.path.exists(wav_path): os.remove(wav_path)

# 8. Текстовые сообщения
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    parse_and_schedule(message.chat.id, message.text)

if __name__ == "__main__":
    port = int(os.getenv('PORT', 10000))
    # Запуск Flask сервера в отдельном потоке
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()

    print("🚀 Бот 24/7 с таймерами запущен...")
    bot.infinity_polling()
