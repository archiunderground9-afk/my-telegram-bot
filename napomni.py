import os
import re
import json
import datetime
import threading
import time
from flask import Flask
import pytz
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import speech_recognition as sr
import pydub

# 1. Настройка часового пояса (Москва GMT+3)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

def get_moscow_now():
    return datetime.datetime.now(MOSCOW_TZ)

# 2. Токен бота и ключ Gemini API
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8829968340:AAEL-zQ37tWtHYJdzxYE3bSqjGvLcVSJ9T0')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '') # Можно указать ключ Gemini в Render Environment

bot = telebot.TeleBot(TOKEN)

# 3. Веб-сервер Flask + Keep-Alive (чтобы Render не отключал бота)
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 ИИ-Секретарь Telegram запущен и работает 24/7!"

def keep_alive():
    time.sleep(15)
    while True:
        try:
            render_url = os.getenv('RENDER_EXTERNAL_URL')
            if render_url:
                requests.get(render_url)
        except Exception as e:
            print(f"Keep-alive error: {e}")
        time.sleep(600)

# 4. Базы данных Памяти и Повторяющихся задач (в памяти сервера)
USER_MEMORY = {}       # { chat_id: [ "Ксюша любит розы", "Паспорт 4510 123456" ] }
RECURRING_TASKS = {}   # { task_id: { "chat_id": 123, "interval": 1800, "text": "Зарядка", "active": True } }

# 5. Функция отправки напоминания с интерактивными кнопками (+5мин, +30мин, Ок)
def send_reminder(chat_id, task_text):
    try:
        markup = InlineKeyboardMarkup(row_width=3)
        btn_ok = InlineKeyboardButton("✅ Ок", callback_data="rem_ok")
        btn_5m = InlineKeyboardButton("⏳ +5 минут", callback_data=f"rem_snooze_300_{task_text[:20]}")
        btn_30m = InlineKeyboardButton("⏱️ +30 минут", callback_data=f"rem_snooze_1800_{task_text[:20]}")
        markup.add(btn_ok, btn_5m, btn_30m)

        bot.send_message(
            chat_id,
            f"⏰ **ИИ-СЕКРЕТАРЬ НАПОМИНАЕТ:**\n\n📌 {task_text}\n\n✅ Время пришло!",
            parse_mode='Markdown',
            reply_markup=markup
        )
    except Exception as e:
        print(f"Ошибка отправки уведомления: {e}")

# Обработка нажатий на интерактивные кнопки в уведомлениях
@bot.callback_query_handler(func=lambda call: call.data.startswith('rem_'))
def handle_reminder_buttons(call):
    chat_id = call.message.chat.id
    data = call.data
    
    if data == 'rem_ok':
        bot.answer_callback_query(call.id, "Отлично! Зафиксировано.")
        bot.edit_message_text(
            f"{call.message.text}\n\n✅ **Выполнено!**",
            chat_id=chat_id,
            message_id=call.message.message_id,
            parse_mode='Markdown'
        )
    elif data.startswith('rem_snooze_'):
        parts = data.split('_', 3)
        delay_sec = int(parts[2])
        task_text = parts[3] if len(parts) > 3 else "Напоминание"
        
        # Переставляем таймер
        timer = threading.Timer(delay_sec, send_reminder, args=[chat_id, task_text])
        timer.daemon = True
        timer.start()
        
        mins = delay_sec // 60
        bot.answer_callback_query(call.id, f"Отложено на {mins} минут!")
        bot.edit_message_text(
            f"{call.message.text}\n\n⏳ **Отложено на +{mins} минут!**",
            chat_id=chat_id,
            message_id=call.message.message_id,
            parse_mode='Markdown'
        )

def run_recurring_loop(task_id, chat_id, interval_seconds, task_text):
    """Фоновый цикл регулярных задач (каждые N минут)"""
    while task_id in RECURRING_TASKS and RECURRING_TASKS[task_id].get("active"):
        time.sleep(interval_seconds)
        if task_id in RECURRING_TASKS and RECURRING_TASKS[task_id].get("active"):
            send_reminder(chat_id, f"🔄 Повторяющаяся задача: {task_text}")

# 6. Основная система ИИ-Секретаря (Gemini API + Мощный автономный парсер)
def process_ai_secretary_command(chat_id, text):
    now = get_moscow_now()
    if chat_id not in USER_MEMORY: USER_MEMORY[chat_id] = []
    
    # А. Попытка использования Gemini AI
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
            prompt = f"""
Ты — персональный онлайн ИИ-Секретарь. Время сейчас (МСК): {now.strftime('%Y-%m-%d %H:%M:%S')}.
Память фактов пользователя: {json.dumps(USER_MEMORY[chat_id], ensure_ascii=False)}

Проанализируй запрос: "{text}"

Верни СТРОГО JSON без markdown символов:
{{
  "action": "REMINDER" | "SAVE_MEMORY" | "SHOW_MEMORY" | "CLEAR_MEMORY" | "RECURRING" | "CANCEL_RECURRING" | "CHAT",
  "task_text": "текст задачи/памяти",
  "delay_seconds": число_секунд_до_одноразового_напоминания,
  "interval_seconds": интервал_в_секундах_для_повторов,
  "reply": "краткий вежливый ответ секретаря"
}}
"""
            res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=10)
            if res.status_code == 200:
                json_text = res.json()['candidates'][0]['content']['parts'][0]['text']
                json_text = json_text.replace('```json', '').replace('```', '').strip()
                data = json.loads(json_text)
                
                action = data.get('action')
                reply = data.get('reply', 'Принято!')
                
                if action == 'SAVE_MEMORY':
                    fact = data.get('task_text', text)
                    USER_MEMORY[chat_id].append(fact)
                    bot.send_message(chat_id, f"📝 **Сохранил в вашу память:**\n• {fact}\n\n{reply}", parse_mode='Markdown')
                    return
                elif action == 'SHOW_MEMORY':
                    facts = USER_MEMORY[chat_id]
                    if not facts:
                        bot.send_message(chat_id, "🧠 Ваша память пока пуста. Скажите: *'запомни ксюша любит розы'*", parse_mode='Markdown')
                    else:
                        formatted = "\n".join([f"• {f}" for f in facts])
                        bot.send_message(chat_id, f"🧠 **Вот что я помню:**\n\n{formatted}", parse_mode='Markdown')
                    return
                elif action == 'CLEAR_MEMORY':
                    USER_MEMORY[chat_id] = []
                    bot.send_message(chat_id, "🧹 Ваша память полностью очищена!", parse_mode='Markdown')
                    return
                elif action == 'RECURRING':
                    interval = data.get('interval_seconds', 1800)
                    task_text = data.get('task_text', text)
                    task_id = f"{chat_id}_{len(RECURRING_TASKS) + 1}"
                    RECURRING_TASKS[task_id] = {"chat_id": chat_id, "interval": interval, "text": task_text, "active": True}
                    
                    t = threading.Thread(target=run_recurring_loop, args=[task_id, chat_id, interval, task_text], daemon=True)
                    t.start()
                    bot.send_message(chat_id, f"🔄 **Установлена регулярная задача!**\n📌 Задача: {task_text}\n⏱️ Интервал: каждые {interval // 60} мин.\n(Чтобы отменить: *'отмени повторы'*)", parse_mode='Markdown')
                    return
                elif action == 'CANCEL_RECURRING':
                    for tid, tinfo in RECURRING_TASKS.items():
                        if tinfo['chat_id'] == chat_id: tinfo['active'] = False
                    bot.send_message(chat_id, "🛑 Все ваши повторяющиеся задачи остановлены!", parse_mode='Markdown')
                    return
                elif action == 'REMINDER':
                    delay = data.get('delay_seconds', 0)
                    task_text = data.get('task_text', text)
                    if delay > 0:
                        timer = threading.Timer(delay, send_reminder, args=[chat_id, task_text])
                        timer.daemon = True
                        timer.start()
                        rem_dt = now + datetime.timedelta(seconds=delay)
                        bot.send_message(chat_id, f"⏰ **Напоминание установлено!**\n📌 Задача: {task_text}\n📅 Точное время (МСК): {rem_dt.strftime('%d.%m.%Y в %H:%M:%S')}", parse_mode='Markdown')
                        return
                elif action == 'CHAT':
                    bot.send_message(chat_id, f"🤖 {reply}", parse_mode='Markdown')
                    return
        except Exception as e:
            print(f"Gemini API fallback error: {e}")

    # Б. Мощный автономный обработчик (если нет ключа Gemini)
    text_lower = text.lower()

    # 1. Запоминание фактов: "запомни ксюша любит розы" или "сохрани номер паспорта 4510"
    if re.search(r'^(запомни|запиши|сохрани)', text_lower):
        fact = re.sub(r'^(запомни|запиши|сохрани)s*', '', text, flags=re.IGNORECASE).strip()
        if fact:
            USER_MEMORY[chat_id].append(fact)
            bot.send_message(chat_id, f"📝 **Запомнил!**\n• {fact}", parse_mode='Markdown')
            return

    # 2. Показать память: "что ты помнишь?", "моя память", "заметки", "вспомни"
    if re.search(r'^(что ты помнишь|моя память|вспомни|покажи память|заметки|список заметок)', text_lower):
        facts = USER_MEMORY[chat_id]
        if not facts:
            bot.send_message(chat_id, "🧠 **Память пуста.** Напишите: *запомни ксюша любит розы*", parse_mode='Markdown')
        else:
            formatted = "\n".join([f"• {f}" for f in facts])
            bot.send_message(chat_id, f"🧠 **Сохраненные факты:**\n\n{formatted}", parse_mode='Markdown')
        return

    # 3. Очистка памяти: "очисти память", "стереть память"
    if re.search(r'^(очисти память|стереть память|забудь всё)', text_lower):
        USER_MEMORY[chat_id] = []
        bot.send_message(chat_id, "🧹 Память полностью очищена!", parse_mode='Markdown')
        return

    # 4. Просмотр и отмена повторяющихся задач: "мои повторы", "отмени повтор", "стоп повторы"
    if "мои повторы" in text_lower or "активные повторы" in text_lower:
        user_tasks = [f"#{tid.split('_')[-1]}: {t['text']} (каждые {t['interval']//60} мин)" for tid, t in RECURRING_TASKS.items() if t['chat_id'] == chat_id and t['active']]
        if not user_tasks:
            bot.send_message(chat_id, "🔄 У вас нет активных повторяющихся задач.", parse_mode='Markdown')
        else:
            bot.send_message(chat_id, "🔄 **Ваши регулярные задачи:**\n\n" + "\n".join(user_tasks) + "\n\n Чтобы отменить, напишите: *отмени повторы*", parse_mode='Markdown')
        return

    if "отмени повтор" in text_lower or "стоп повтор" in text_lower or "останови повтор" in text_lower or "отменить повторы" in text_lower:
        for tid, t in RECURRING_TASKS.items():
            if t['chat_id'] == chat_id: t['active'] = False
        bot.send_message(chat_id, "🛑 Все повторяющиеся задачи успешно остановлены!", parse_mode='Markdown')
        return

    # 5. Повторы: "напоминай каждые 30 минут делать зарядку"
    rec_match = re.search(r'каждыеs+(d+)s+(минут|мин|часов|час|ч)', text_lower)
    if rec_match:
        num = int(rec_match.group(1))
        unit = rec_match.group(2)
        interval = num * 60 if 'мин' in unit else num * 3600
        task_text = re.sub(r'напоминай|напомни|каждыеs+d+s+(минут|мин|часов|час|ч)', '', text, flags=re.IGNORECASE).strip() or "Зарядка"
        
        task_id = f"{chat_id}_{len(RECURRING_TASKS) + 1}"
        RECURRING_TASKS[task_id] = {"chat_id": chat_id, "interval": interval, "text": task_text, "active": True}
        
        t = threading.Thread(target=run_recurring_loop, args=[task_id, chat_id, interval, task_text], daemon=True)
        t.start()
        bot.send_message(chat_id, f"🔄 **Регулярное напоминание запущено!**\n📌 Задача: {task_text}\n⏱️ Повтор каждые {num} мин.\n\nЧтобы отменить, напишите: *отмени повторы*", parse_mode='Markdown')
        return

    # 6. Обычные одноразовые напоминания: "через N секунд/минут/часов/дней"
    rel_match = re.search(r'черезs+(d+)s+(секунд|сек|с|минут|мин|часов|час|ч|дней|день|д)', text_lower)
    if rel_match:
        num = int(rel_match.group(1))
        unit = rel_match.group(2)
        delay = num if ('сек' in unit or unit == 'с') else (num * 60 if 'мин' in unit else (num * 3600 if 'час' in unit else num * 86400))
        task_text = re.sub(r'напомни|черезs+d+s+(секунд|сек|с|минут|мин|часов|час|ч|дней|день|д)', '', text, flags=re.IGNORECASE).strip() or "Напоминание"
        
        timer = threading.Timer(delay, send_reminder, args=[chat_id, task_text])
        timer.daemon = True
        timer.start()
        rem_dt = now + datetime.timedelta(seconds=delay)
        bot.send_message(chat_id, f"⏰ **Напоминание установлено!**\n📌 Задача: {task_text}\n📅 Точное время (МСК): {rem_dt.strftime('%d.%m.%Y в %H:%M:%S')}", parse_mode='Markdown')
        return

    # 7. Фиксированное время: "в HH:MM"
    time_match = re.search(r'вs+(d{1,2}):(d{2})', text_lower)
    if time_match:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        target_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target_dt <= now: target_dt += datetime.timedelta(days=1)
        delay = (target_dt - now).total_seconds()
        task_text = re.sub(r'напомни|вs+d{1,2}:d{2}', '', text, flags=re.IGNORECASE).strip() or "Напоминание"
        
        timer = threading.Timer(delay, send_reminder, args=[chat_id, task_text])
        timer.daemon = True
        timer.start()
        bot.send_message(chat_id, f"⏰ **Напоминание установлено!**\n📌 Задача: {task_text}\n📅 Точное время (МСК): {target_dt.strftime('%d.%m.%Y в %H:%M:%S')}", parse_mode='Markdown')
        return

    bot.send_message(
        chat_id,
        "🤖 **Я ваш ИИ-Секретарь! Вот что я умею:**\n\n"
        "1️⃣ **Память:** *'запомни ксюша любит розы'* или *'что ты помнишь?'*\n"
        "2️⃣ **Повторы:** *'напоминай каждые 30 минут делать зарядку'*\n"
        "3️⃣ **Отмена повторов:** *'мои повторы'* или *'отмени повторы'*\n"
        "4️⃣ **Таймеры:** *'напомни через 15 минут позвонить'*",
        parse_mode='Markdown'
    )

# 7. Обработчики команд Telegram
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message,
        "👋 **Привет! Я твой ИИ-Секретарь.**\n\n"
        "💡 **Примеры команд:**\n"
        "• *запомни серии и номер паспорта 4510 123456*\n"
        "• *что ты помнишь?*\n"
        "• *напоминай каждые 30 минут делать зарядку*\n"
        "• *отмени повторы*\n"
        "• *напомни через 20 секунд проверять духовку*",
        parse_mode='Markdown'
    )

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🎙️ Обрабатываю голосовое сообщение...")
    ogg_path, wav_path = f"voice_{message.message_id}.ogg", f"voice_{message.message_id}.wav"
    try:
        file_info = bot.get_file(message.voice.file_id)
        with open(ogg_path, 'wb') as f: f.write(bot.download_file(file_info.file_path))
        pydub.AudioSegment.from_file(ogg_path).export(wav_path, format="wav")
        
        r = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            text = r.recognize_google(r.record(source), language="ru-RU")
            
        bot.send_message(chat_id, f"🗣️ Распознано: «{text}»")
        process_ai_secretary_command(chat_id, text)
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Ошибка распознавания речи: {e}")
    finally:
        if os.path.exists(ogg_path): os.remove(ogg_path)
        if os.path.exists(wav_path): os.remove(wav_path)

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    process_ai_secretary_command(message.chat.id, message.text)

if __name__ == "__main__":
    port = int(os.getenv('PORT', 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    print("🚀 ИИ-Секретарь запущен 24/7...")
    while True:
        try:
            bot.remove_webhook()
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except Exception as e:
            print(f"Ошибка связи или 409 Conflict: {e}. Автоматический повтор через 5 секунд...")
            time.sleep(5)
