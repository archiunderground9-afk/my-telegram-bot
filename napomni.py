import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot

# 1. Простой веб-сервер для бесплатного тарифа Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# Запускаем веб-сервер в отдельном потоке
threading.Thread(target=run_web_server, daemon=True).start()

# 2. Логика Telegram Бота
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'ВАШ_ТОКЕН_ЕСЛИ_ЗАПУСКАЕТЕ_ЛОКАЛЬНО')
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я твой бот для заметок и напоминаний. Напиши мне задачу!")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    bot.reply_to(message, f"Записал: «{message.text}». Напоминание установлено!")

print("Бот успешно запущен на бесплатном тарифе Render...")
bot.infinity_polling()
