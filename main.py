import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from os import getenv
from dotenv import load_dotenv

load_dotenv()

# Настройки
BOT_TOKEN = getenv("BOT_TOKEN")
ADMIN_ID = int(getenv("ADMIN_ID"))
CHANNEL_ID = getenv("CHANNEL_ID")
CHANNEL_URL = getenv("CHANNEL_URL")

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users 
               (id INTEGER PRIMARY KEY, tg_id BIGINT UNIQUE, username TEXT, 
               alias TEXT UNIQUE, lang TEXT DEFAULT 'ru', 
               sent_count INTEGER DEFAULT 0, rec_count INTEGER DEFAULT 0, 
               join_date TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS messages 
               (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id BIGINT, 
               receiver_id BIGINT, msg_id_in_receiver INTEGER)''')
conn.commit()

# --- СОСТОЯНИЯ ---
class Form(StatesGroup):
    waiting_for_alias = State()
    waiting_for_anon_msg = State()
    waiting_for_broadcast = State()

# --- ЛОКАЛИЗАЦИЯ ---
TEXTS = {
    'ru': {
        'start': "<b>👋 Привет!</b>\n\nЗдесь тебе могут писать <b>анонимно</b>. Твоя ссылка ниже. Ты можешь отправлять текст, фото, видео и даже голосовые!\n\n🔗 <code>t.me/{bot_user}?start={uid}</code>",
        'profile': "👤 <b>Профиль</b>\n\nСтатистика:\n📤 Отправлено: {sent}\n📥 Получено: {rec}\n\nТвоя ссылка:\n<code>{link}</code>",
        'set_lang': "Выберите язык / Choose language:",
        'sub_req': "❌ Для работы с ботом подпишитесь на канал!",
        'anon_ready': "🚀 Отправь сообщение (текст, фото или видео) для этого пользователя:",
        'msg_sent': "✅ Сообщение отправлено! Вы можете удалить его кнопкой ниже.",
        'msg_del': "🗑 Удалить сообщение",
        'deleted': "💥 Сообщение было удалено отправителем.",
        'reply': "💬 Ответить"
    },
    'en': {
        'start': "<b>👋 Hi!</b>\n\nHere people can write to you <b>anonymously</b>. Your link is below. You can send text, photos, videos, and even voice messages!\n\n🔗 <code>t.me/{bot_user}?start={uid}</code>",
        'profile': "👤 <b>Profile</b>\n\nStats:\n📤 Sent: {sent}\n📥 Received: {rec}\n\nYour link:\n<code>{link}</code>",
        'set_lang': "Choose language:",
        'sub_req': "❌ Please subscribe to our channel to use the bot!",
        'anon_ready': "🚀 Send your message (text, photo, or video) to this user:",
        'msg_sent': "✅ Message sent! You can delete it using the button below.",
        'msg_del': "🗑 Delete message",
        'deleted': "💥 Message was deleted by the sender.",
        'reply': "💬 Reply"
    }
}

# --- ФУНКЦИИ ХЕЛПЕРЫ ---
def get_user(tg_id):
    return cursor.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()

async def check_sub(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status != 'left'
    except: return True

# --- КЛАВИАТУРЫ ---
def main_kb(lang):
    kb = ReplyKeyboardBuilder()
    if lang == 'ru':
        kb.button(text="👤 Профиль"), kb.button(text="⚙️ Настройки"), kb.button(text="📊 Статистика")
    else:
        kb.button(text="👤 Profile"), kb.button(text="⚙️ Settings"), kb.button(text="📊 Stats")
    kb.adjust(1, 2)
    return kb.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    args = message.text.split()
    user = get_user(message.from_user.id)
    
    if not user:
        cursor.execute("INSERT INTO users (tg_id, username, join_date) VALUES (?, ?, ?)", 
                       (message.from_user.id, message.from_user.username, datetime.now().date()))
        conn.commit()
        user = get_user(message.from_user.id)

    # Проверка на анонимное сообщение (через start)
    if len(args) > 1:
        target_id = args[1]
        # Проверяем кастомную ссылку
        target = cursor.execute("SELECT tg_id FROM users WHERE alias = ? OR tg_id = ?", (target_id, target_id)).fetchone()
        if target:
            await state.update_data(target_id=target[0])
            await message.answer(TEXTS[user[4]]['anon_ready'])
            await state.set_state(Form.waiting_for_anon_msg)
            return

    bot_info = await bot.get_me()
    link = f"t.me/{bot_info.username}?start={user[1]}"
    await message.answer(TEXTS[user[4]]['start'].format(bot_user=bot_info.username, uid=user[3] or user[1]), 
                         reply_markup=main_kb(user[4]))

@dp.message(Form.waiting_for_anon_msg)
async def handle_anon_delivery(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data['target_id']
    user = get_user(message.from_user.id)
    
    # Кнопка удаления для отправителя
    del_kb = InlineKeyboardBuilder()
    
    # Пересылаем сообщение
    try:
        sent = await message.copy_to(chat_id=target_id)
        
        # Сохраняем связь в БД для удаления
        cursor.execute("INSERT INTO messages (sender_id, receiver_id, msg_id_in_receiver) VALUES (?, ?, ?)",
                       (message.from_user.id, target_id, sent.message_id))
        msg_db_id = cursor.lastrowid
        conn.commit()
        
        del_kb.button(text=TEXTS[user[4]]['msg_del'], callback_data=f"del_{msg_db_id}")
        await message.answer(TEXTS[user[4]]['msg_sent'], reply_markup=del_kb.as_markup())
        
        # Кнопка ответа для получателя
        reply_kb = InlineKeyboardBuilder()
        reply_kb.button(text=TEXTS['ru' if user[4]=='ru' else 'en']['reply'], callback_data=f"reply_{message.from_user.id}")
        await bot.send_message(target_id, "✉️ <b>Новое анонимное сообщение!</b>", reply_markup=reply_kb.as_markup())
        
        # Обновляем статистику
        cursor.execute("UPDATE users SET sent_count = sent_count + 1 WHERE tg_id = ?", (message.from_user.id,))
        cursor.execute("UPDATE users SET rec_count = rec_count + 1 WHERE tg_id = ?", (target_id,))
        conn.commit()
        
    except Exception as e:
        await message.answer("❌ Ошибка при отправке. Возможно, пользователь заблокировал бота.")
    
    await state.clear()

@dp.callback_query(F.data.startswith("del_"))
async def delete_msg(call: types.CallbackQuery):
    msg_db_id = call.data.split("_")[1]
    msg_data = cursor.execute("SELECT * FROM messages WHERE id = ?", (msg_db_id,)).fetchone()
    
    if msg_data:
        try:
            await bot.delete_message(chat_id=msg_data[2], message_id=msg_data[3])
            await bot.send_message(msg_data[2], TEXTS['ru']['deleted']) # Упрощенно ru
            await call.answer("Удалено!")
            await call.message.delete()
        except:
            await call.answer("Ошибка или сообщение слишком старое", show_alert=True)

@dp.message(F.text.in_(["👤 Профиль", "👤 Profile"]))
async def profile(message: types.Message):
    user = get_user(message.from_user.id)
    bot_info = await bot.get_me()
    link = f"t.me/{bot_info.username}?start={user[3] or user[1]}"
    await message.answer(TEXTS[user[4]]['profile'].format(sent=user[5], rec=user[6], link=link))

# --- АДМИН ПАНЕЛЬ (Рассылка) ---
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_panel(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Рассылка", callback_data="broadcast")
    await message.answer("🛠 Админ-панель", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "broadcast", F.from_user.id == ADMIN_ID)
async def broadcast_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите текст рассылки:")
    await state.set_state(Form.waiting_for_broadcast)

@dp.message(Form.waiting_for_broadcast)
async def do_broadcast(message: types.Message, state: FSMContext):
    users = cursor.execute("SELECT tg_id FROM users").fetchall()
    count = 0
    for u in users:
        try:
            await message.copy_to(u[0])
            count += 1
            await asyncio.sleep(0.05) # Защита от спам-фильтра
        except: pass
    await message.answer(f"✅ Рассылка завершена. Получили {count} чел.")
    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
