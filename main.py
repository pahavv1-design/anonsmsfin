import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties # Для исправления предупреждения
from os import getenv
from dotenv import load_dotenv

load_dotenv()

# Настройки (убедись, что на Bothost эти переменные заполнены!)
BOT_TOKEN = getenv("BOT_TOKEN")
ADMIN_ID = int(getenv("ADMIN_ID") if getenv("ADMIN_ID") else 0)
CHANNEL_ID = getenv("CHANNEL_ID") # Для обязательной подписки (если нужно)

# Исправляем ту самую ошибку из логов:
bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users 
               (id INTEGER PRIMARY KEY, tg_id BIGINT UNIQUE, username TEXT, 
               alias TEXT UNIQUE, lang TEXT DEFAULT 'ru', 
               sent_count INTEGER DEFAULT 0, rec_count INTEGER DEFAULT 0)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS messages 
               (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id BIGINT, 
               receiver_id BIGINT, msg_id_in_receiver INTEGER)''')
conn.commit()

class Form(StatesGroup):
    waiting_for_anon_msg = State()
    waiting_for_broadcast = State()

# --- ТЕКСТЫ ---
TEXTS = {
    'ru': {
        'start': "<b>👋 Привет!</b>\n\nВ этом боте тебе могут писать <b>анонимно</b>. Отправь свою ссылку друзьям, чтобы получить первое сообщение!\n\nТвоя ссылка:\n🔗 <code>t.me/{bot_user}?start={uid}</code>",
        'profile': "👤 <b>Профиль</b>\n\n📊 Статистика:\n📤 Отправлено: {sent}\n📥 Получено: {rec}\n\nТвоя ссылка:\n<code>{link}</code>",
        'anon_ready': "🚀 Напиши сообщение для этого пользователя.\n<i>Можно отправить текст, фото, видео или голосовое:</i>",
        'msg_sent': "✅ Сообщение отправлено!",
        'msg_del': "🗑 Удалить",
        'reply': "💬 Ответить",
        'lang_btn': "🌍 Сменить язык",
        'lang_changed': "✅ Язык изменен на Русский"
    },
    'en': {
        'start': "<b>👋 Hi!</b>\n\nIn this bot, people can write to you <b>anonymously</b>. Send your link to friends to get your first message!\n\nYour link:\n🔗 <code>t.me/{bot_user}?start={uid}</code>",
        'profile': "👤 <b>Profile</b>\n\n📊 Stats:\n📤 Sent: {sent}\n📥 Received: {rec}\n\nYour link:\n<code>{link}</code>",
        'anon_ready': "🚀 Write a message for this user.\n<i>You can send text, photos, videos, or voice:</i>",
        'msg_sent': "✅ Message sent!",
        'msg_del': "🗑 Delete",
        'reply': "💬 Reply",
        'lang_btn': "🌍 Change Language",
        'lang_changed': "✅ Language changed to English"
    }
}

# --- КНОПКИ ---
def main_kb(lang):
    kb = ReplyKeyboardBuilder()
    if lang == 'ru':
        kb.button(text="👤 Профиль"), kb.button(text="🌍 Сменить язык")
    else:
        kb.button(text="👤 Profile"), kb.button(text="🌍 Change Language")
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)

def lang_inline():
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 Русский", callback_data="setlang_ru")
    kb.button(text="🇬🇧 English", callback_data="setlang_en")
    return kb.as_markup()

# --- ЛОГИКА ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    args = message.text.split()
    user_id = message.from_user.id
    
    # Регистрация
    user = cursor.execute("SELECT * FROM users WHERE tg_id = ?", (user_id,)).fetchone()
    if not user:
        cursor.execute("INSERT INTO users (tg_id, username) VALUES (?, ?)", (user_id, message.from_user.username))
        conn.commit()
        user = cursor.execute("SELECT * FROM users WHERE tg_id = ?", (user_id,)).fetchone()

    # Если перешли по ссылке
    if len(args) > 1:
        target_id = int(args[1])
        if target_id == user_id:
            await message.answer("❌ Нельзя писать самому себе!")
            return
        await state.update_data(target_id=target_id)
        await message.answer(TEXTS[user[4]]['anon_ready'])
        await state.set_state(Form.waiting_for_anon_msg)
        return

    bot_info = await bot.get_me()
    await message.answer(
        TEXTS[user[4]]['start'].format(bot_user=bot_info.username, uid=user[1]),
        reply_markup=main_kb(user[4])
    )

@dp.message(Form.waiting_for_anon_msg)
async def anon_delivery(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data['target_id']
    user = cursor.execute("SELECT * FROM users WHERE tg_id = ?", (message.from_user.id,)).fetchone()
    
    try:
        # Пересылаем контент (текст, фото, видео и т.д.)
        sent = await message.copy_to(chat_id=target_id)
        
        # Сохраняем в БД для удаления
        cursor.execute("INSERT INTO messages (sender_id, receiver_id, msg_id_in_receiver) VALUES (?, ?, ?)",
                       (message.from_user.id, target_id, sent.message_id))
        conn.commit()
        msg_db_id = cursor.lastrowid

        # Кнопка удаления для отправителя
        del_kb = InlineKeyboardBuilder()
        del_kb.button(text=TEXTS[user[4]]['msg_del'], callback_data=f"del_{msg_db_id}")
        
        await message.answer(TEXTS[user[4]]['msg_sent'], reply_markup=del_kb.as_markup())
        
        # Уведомление получателю
        reply_kb = InlineKeyboardBuilder()
        reply_kb.button(text=TEXTS[user[4]]['reply'], callback_data=f"reply_{message.from_user.id}")
        await bot.send_message(target_id, "📩 <b>Новое анонимное сообщение!</b>", reply_markup=reply_kb.as_markup())
        
        cursor.execute("UPDATE users SET sent_count = sent_count + 1 WHERE tg_id = ?", (message.from_user.id,))
        cursor.execute("UPDATE users SET rec_count = rec_count + 1 WHERE tg_id = ?", (target_id,))
        conn.commit()
    except:
        await message.answer("❌ Ошибка: пользователь заблокировал бота.")
    
    await state.clear()

@dp.message(F.text.in_(["👤 Профиль", "👤 Profile"]))
async def profile(message: types.Message):
    user = cursor.execute("SELECT * FROM users WHERE tg_id = ?", (message.from_user.id,)).fetchone()
    bot_info = await bot.get_me()
    link = f"t.me/{bot_info.username}?start={user[1]}"
    await message.answer(
        TEXTS[user[4]]['profile'].format(sent=user[5], rec=user[6], link=link),
        reply_markup=main_kb(user[4])
    )

@dp.message(F.text.in_(["🌍 Сменить язык", "🌍 Change Language"]))
async def change_lang(message: types.Message):
    await message.answer("Выберите язык / Choose language:", reply_markup=lang_inline())

@dp.callback_query(F.data.startswith("setlang_"))
async def set_lang(call: types.CallbackQuery):
    new_lang = call.data.split("_")[1]
    cursor.execute("UPDATE users SET lang = ? WHERE tg_id = ?", (new_lang, call.from_user.id))
    conn.commit()
    await call.message.delete()
    await call.message.answer(TEXTS[new_lang]['lang_changed'], reply_markup=main_kb(new_lang))

@dp.callback_query(F.data.startswith("del_"))
async def delete_anon(call: types.CallbackQuery):
    msg_id = int(call.data.split("_")[1])
    msg = cursor.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
    if msg:
        try:
            await bot.delete_message(chat_id=msg[2], message_id=msg[3])
            await call.answer("Удалено!")
            await call.message.edit_text("🗑 Сообщение удалено.")
        except:
            await call.answer("Ошибка или прошло более 48 часов", show_alert=True)

# Запуск
async def main():
    print("--- БОТ ЗАПУЩЕН ---") # Появится в логах Bothost
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
