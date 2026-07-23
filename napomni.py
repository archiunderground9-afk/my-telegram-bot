import os
import re
import datetime
import threading
from flask import Flask
import pytz
import telebot
from apscheduler.schedulers.background import BackgroundScheduler
import speech_recognition as sr
import pydub

# 1. Настройка часового пояса (Москва GMT+3)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

def get_now():
    return datetime.datetime.now(MOSCOW_TZ)

# 2. Токен бота
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8829968340:AAEL-zQ37tWtHYJdzxYE3bSqjGvLcVSJ9T0')
bot = telebot.TeleBot(TOKEN)

# 3. Микро-сервер Flask для Render (чтобы Render не отключал бота)
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Telegram Bot is running 24/7!"

def run_flask():
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# 4. Инициализация фонового планировщика
scheduler = BackgroundScheduler(timezone=MOSCOW_TZ)
scheduler.start()

def send_reminder(chat_id, task_text):
    """Функция отправки напоминания пользователю"""
    try:
        bot.send_message(
            chat_id,
            f"⏰ **НАПОМИНАНИЕ!**

📌 {task_text}

✅ Время пришло!"
        )
    except Exception as e:
        print(f"Ошибка отправки уведомления: {e}")

def parse_time_and_task(text):
    """Разбор даты/времени с учетом часового пояса МСК"""
    now = get_now()
    
    # 1. Формат: 'через N секунд/минут/часов/дней'
    rel_match = re.search(r'черезs+(d+)s+(секунд|сек|с|минут|мин|часов|час|ч|дней|день|д)', text, re.IGNORECASE)
    if rel_match:
        num = int(rel_match.group(1))
        unit = rel_match.group(2).lower()
        if 'сек' in unit or unit == 'с':
            rem_time = now + datetime.timedelta(seconds=num)
        elif 'мин' in unit:
            rem_time = now + datetime.timedelta(minutes=num)
        elif 'час' in unit or unit == 'ч':
            rem_time = now + datetime.timedelta(hours=num)
        else:
            rem_time = now + datetime.timedelta(days=num)
        
        task_text = re.sub(r'напомни|черезs+d+s+(секунд|сек|с|минут|мин|часов|час|ч|дней|день|д)', '', text, flags=re.IGNORECASE).strip()
        return rem_time, task_text or "Напоминание"

    # 2. Формат: 'в HH:MM' (например 'в 18:01')
    time_match = re.search(r'вs+(d{1,2}):(d{2})', text, re.IGNORECASE)
    if time_match:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        rem_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if rem_time <= now:
            rem_time += datetime.timedelta(days=1)  # Перенос на завтра, если время прошло
        
        task_text = re.sub(r'напомни|вs+d{1,2}:d{2}', '', text, flags=re.IGNORECASE).strip()
        return rem_time, task_text or "Напоминание"

    return None, None

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message,
        "👋 Привет! Я твой умный бот-помощник с планировщиком и голосовым вводом.

"
        "💡 **Примеры команд:**
"
        "• 'напомни через 30 секунд позвонить Роману'
"
        "• 'напомни в 18:30 купить хлеб'
"
        "• Голосовое сообщение: нажми микрофон и скажи команду!

"
        "Нажми кнопку **меню**, чтобы открыть веб-приложение!"
    )

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🎙️ Обрабатываю голосовое сообщение...")
    
    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        ogg_path = f"voice_{message.message_id}.ogg"
        wav_path = f"voice_{message.message_id}.wav"
        
        with open(ogg_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        sound = pydub.AudioSegment.from_file(ogg_path)
        sound.export(wav_path, format="wav")
        
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio = recognizer.record(source)
            text = recognizer.recognize_google(audio, language="ru-RU")
            
        if os.path.exists(ogg_path): os.remove(ogg_path)
        if os.path.exists(wav_path): os.remove(wav_path)
        
        bot.send_message(chat_id, f"🗣️ Распознано: «{text}»")
        process_task_command(chat_id, text)

    except Exception as e:
        bot.send_message(
            chat_id,
            "⚠️ **Ошибка распознавания речи!**

"
            f"Суть ошибки: {str(e) or 'Речь не распознана.'}

"
            "Пожалуйста, повторите чётче или отправьте текстом!"
        )

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    process_task_command(message.chat.id, message.text)

def process_task_command(chat_id, text):
    rem_time, task_text = parse_time_and_task(text)
    
    if not rem_time:
        bot.send_message(
            chat_id,
            "⚠️ **Не удалось разобрать время.**

"
            "**Суть ошибки:** В команде не найдено время ('через 30 секунд', 'в 18:30').

"
            "**Пример:** *напомни через 1 минуту позвонить Роману*"
        )
        return
        
    scheduler.add_job(
        send_reminder,
        'date',
        run_date=rem_time,
        args=[chat_id, task_text]
    )
    
    formatted_time = rem_time.strftime("%d.%m.%Y в %H:%M:%S")
    bot.send_message(
        chat_id,
        f"✅ **Напоминание запланировано!**

"
        f"📌 Задача: {task_text}
"
        f"⏰ Точное время (МСК): {formatted_time}"
    )

if __name__ == "__main__":
    # Запускаем Flask в отдельном потоке для Render Keep-Alive
    threading.Thread(target=run_flask, daemon=True).start()
    print("🚀 Бот и HTTP-сервер 24/7 запущены...")
    bot.infinity_polling()
