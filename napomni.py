import telebot
import os

# Получите токен у @BotFather
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8829968340:AAEL-zQ37tWtHYJdzxYE3bSqjGvLcVSJ9T0')
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я твой бот для списков покупок и напоминаний.")

@bot.message_handler(func=lambda message: True)
def handle_task(message):
    text = message.text
    bot.reply_to(message, f"Записал задачу: '{text}'. Уведомление создано!")

print("Бот запущен...")
bot.infinity_polling()