import os
import re
import datetime
import telebot
from apscheduler.schedulers.background import BackgroundScheduler
import speech_recognition as sr
import pydub

# 1. Токен бота (получен у @BotFather)
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'ВАШ_ТОКЕН_ОТ_BOTFATHER')
bot = telebot.TeleBot(TOKEN)

# 2. Инициализация фонового планировщика (Календарь / Таймеры)
scheduler = BackgroundScheduler()
scheduler.start()

def send_reminder(chat_id, task_text):
    """Функция срабатывания напоминания в точное время"""
    try:
        bot.send_message(
            chat_id,
            f"⏰ **НАПОМИНАНИЕ!**\n\n📌 {task_text}\n\n✅ Время пришло!"
        )
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def parse_time_and_task(text):
    """Разбор даты, времени и текста задачи из текста или голосового сообщения"""
    now = datetime.datetime.now()
    
    # 1. Формат 'через N минут/часов/дней'
    rel_match = re.search(r'через\s+(\d+)\s+(минут|мин|часов|час|ч|дней|день|д)', text, re.IGNORECASE)
    if rel_match:
        num = int(rel_match.group(1))
        unit = rel_match.group(2).lower()
        if 'мин' in unit:
            rem_time = now + datetime.timedelta(minutes=num)
        elif 'час' in unit or unit == 'ч':
            rem_time = now + datetime.timedelta(hours=num)
        else:
            rem_time = now + datetime.timedelta(days=num)
        
        task_text = re.sub(r'напомни|через\s+\d+\s+(минут|мин|часов|час|ч|дней|день|д)', '', text, flags=re.IGNORECASE).strip()
        return rem_time, task_text or "Напоминание"

    # 2. Формат 'в HH:MM' (например 'в 18:30')
    time_match = re.search(r'в\s+(\d{1,2}):(\d{2})', text, re.IGNORECASE)
    if time_match:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        rem_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if rem_time <= now:
            rem_time += datetime.timedelta(days=1)  # Переносим на завтра, если время сегодня уже прошло
        
        task_text = re.sub(r'напомни|в\s+\d{1,2}:\d{2}', '', text, flags=re.IGNORECASE).strip()
        return rem_time, task_text or "Напоминание"

    return None, None

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message,
        "👋 Привет! Я твой умный бот-помощник с календарем и голосовым вводом.\n\n"
        "💡 **Как давать команды:**\n"
        "• Текстом: 'напомни через 5 минут позвонить Ивану'\n"
        "• Текстом: 'напомни в 18:30 сходить в магазин'\n"
        "• Голосом: просто нажми микрофон и скажи команду!\n\n"
        "Нажми кнопку **меню** снизу, чтобы открыть Веб-приложение!"
    )

# 3. Обработка голосовых сообщений
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
            
        # Конвертация OGG в WAV
        sound = pydub.AudioSegment.from_file(ogg_path)
        sound.export(wav_path, format="wav")
        
        # Распознавание речи через Google Speech API
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio = recognizer.record(source)
            text = recognizer.recognize_google(audio, language="ru-RU")
            
        # Удаляем временные файлы
        if os.path.exists(ogg_path): os.remove(ogg_path)
        if os.path.exists(wav_path): os.remove(wav_path)
        
        bot.send_message(chat_id, f"🗣️ Вы сказали: «{text}»")
        process_task_command(chat_id, text)

    except Exception as e:
        bot.send_message(
            chat_id,
            "⚠️ **Ошибка распознавания речи!**\n\n"
            f"Суть ошибки: {str(e) or 'Голос не распознан или записи нет.'}\n\n"
            "Пожалуйста, повторите голосовую команду чётче или отправьте текстом!"
        )

# 4. Обработка текстовых сообщений
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    process_task_command(message.chat.id, message.text)

def process_task_command(chat_id, text):
    rem_time, task_text = parse_time_and_task(text)
    
    if not rem_time:
        bot.send_message(
            chat_id,
            "⚠️ **Не удалось установить время напоминания.**\n\n"
            "**Суть ошибки:** В вашей команде не указано точное время (например: 'через 10 минут', 'в 19:00' или 'через 1 день').\n\n"
            "**Попробуйте повторить команду:**\n"
            "👉 *напомни через 15 минут купить хлеб*"
        )
        return
        
    # Добавляем задачу в календарь планировщика
    scheduler.add_job(
        send_reminder,
        'date',
        run_date=rem_time,
        args=[chat_id, task_text]
    )
    
    formatted_time = rem_time.strftime("%d.%m.%Y в %H:%M")
    bot.send_message(
        chat_id,
        f"✅ **Напоминание запланировано!**\n\n"
        f"📌 Задача: {task_text}\n"
        f"⏰ Время: {formatted_time}"
    )

print("🚀 Бот с планировщиком и голосовым вводом запущен...")
bot.infinity_polling()
