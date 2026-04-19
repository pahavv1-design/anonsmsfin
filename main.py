import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from os import getenv
from dotenv import load_dotenv

load_dotenv()

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = getenv("BOT_TOKEN")
ADMIN_ID = int(getenv("ADMIN_ID") if getenv("ADMIN_ID") else 0)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users 
               (id INTEGER PRIMARY KEY, tg_id BIGINT UNIQUE, username TEXT, 
               lang TEXT DEFAULT 'ru', sent_count INTEGER DEFAULT 0, 
               rec_count INTEGER DEFAULT 0)''')
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
        'start': "<b>👋 Привет!</b>\n\nТут тебе могут писать анонимно. Отправь ссылку друзьям!\n\n🔗 <code>t.me/{bot_user}?start={uid}</code>",
        'profile': "👤 <b>Профиль</b>\n\n📤 Отправлено: {sent}\n📥 Получено: {rec}\n\nТвоя ссылка:\n<code>{link}</code>",
        'anon_ready': "🚀 Напиши сообщение (текст, фото, видео или голос):",
        'msg_sent': "✅ Отправлено!",
        'msg_del': "🗑 Удалить у него",
        'reply': "💬 Ответить",
        'lang_btn': "🌍 Язык / Language",
        'stats_btn': "📊 Статистика",
        'deleted': "🗑 Сообщение удалено отправителем."
    },
    'en': {
        'start': "<b>👋 Hi!</b>\n\nHere you can receive anonymous messages. Share your link!\n\n🔗 <code>t.me/{bot_user}?start={uid}</code>",
        'profile': "👤 <b>Profile</b>\n\n📤 Sent: {sent}\n📥 Received: {rec}\n\nYour link:\n<code>{link}</code>",
        'anon_ready': "🚀 Write your message (text, photo, video or voice):",
        'msg_sent': "✅ Sent!",
        'msg_del': "🗑 Delete for him",
        'reply': "💬 Reply",
        'lang_btn': "🌍 Language / Язык",
        'stats_btn': "📊 Stats",
        'deleted': "🗑 Message was deleted by the sender."
    }
}

# --- КНОПКИ ---
def main_kb(lang):
    kb = ReplyKeyboardBuilder()
    t = TEXTS[lang]
    kb.button(text="👤 Профиль" if lang == 'ru' else "👤 Profile")
    kb.button(text=t['lang_btn'])
    kb.button(text=t['stats_btn'])
    kb.adjust(1, 2)
    return kb.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    args = message.text.split()
    uid = message.from_user.id
    
    # Регистрация
    user = cursor.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()
    if not user:
        cursor.execute("INSERT INTO users (tg_id, username) VALUES (?, ?)", (uid, message.from_user.username))
        conn.commit()
        user = cursor.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()

    # Анонимка
    if len(args) > 1:
        target_id = int(args[1])
        if target_id == uid:
            return await message.answer("❌ Нельзя писать самому себе.")
        await state.update_data(target_id=target_id)
        await message.answer(TEXTS[user[3]]['anon_ready'])
        await state.set_state(Form.waiting_for_anon_msg)
        return

    bot_info = await bot.get_me()
    await message.answer(TEXTS[user[3]]['start'].format(bot_user=bot_info.username, uid=uid), reply_markup=main_kb(user[3]))

@dp.message(Form.waiting_for_anon_msg)
async def anon_delivery(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data['target_id']
    user = cursor.execute("SELECT * FROM users WHERE tg_id = ?", (message.from_user.id,)).fetchone()
    
    try:
        sent = await message.copy_to(chat_id=target_id)
        cursor.execute("INSERT INTO messages (sender_id, receiver_id, msg_id_in_receiver) VALUES (?, ?, ?)",
                       (message.from_user.id, target_id, sent.message_id))
        conn.commit()
        
        # Кнопка удаления для отправителя
        del_kb = InlineKeyboardBuilder()
        del_kb.button(text=TEXTS[user[3]]['msg_del'], callback_data=f"del_{cursor.lastrowid}")
        await message.answer(TEXTS[user[3]]['msg_sent'], reply_markup=del_kb.as_markup())
        
        # Кнопка ответа для получателя
        rep_kb = InlineKeyboardBuilder()
        rep_kb.button(text=TEXTS[user[3]]['reply'], callback_data=f"reply_{message.from_user.id}")
        await bot.send_message(target_id, "📩 <b>Новое анонимное сообщение!</b>", reply_markup=rep_kb.as_markup())
        
        cursor.execute("UPDATE users SET sent_count = sent_count + 1 WHERE tg_id = ?", (message.from_user.id,))
        cursor.execute("UPDATE users SET rec_count = rec_count + 1 WHERE tg_id = ?", (target_id,))
        conn.commit()
    except:
        await message.answer("❌ Ошибка отправки.")
    await state.clear()

@dp.callback_query(F.data.startswith("del_"))
async def delete_msg(call: types.CallbackQuery):
    db_id = call.data.split("_")[1]
    msg = cursor.execute("SELECT * FROM messages WHERE id = ?", (db_id,)).fetchone()
    if msg:
        try:
            await bot.delete_message(chat_id=msg[2], message_id=msg[3])
            await bot.send_message(msg[2], TEXTS['ru']['deleted'])
            await call.message.edit_text("🗑 Удалено.")
        except:
            await call.answer("Не удалось удалить (прошло >48ч)")

@dp.message(F.text.contains("Профиль") | F.text.contains("Profile"))
async def profile_cmd(message: types.Message):
    user = cursor.execute("SELECT * FROM users WHERE tg_id = ?", (message.from_user.id,)).fetchone()
    bot_info = await bot.get_me()
    link = f"t.me/{bot_info.username}?start={user[1]}"
    await message.answer(TEXTS[user[3]]['profile'].format(sent=user[4], rec=user[5], link=link))

@dp.message(F.text.contains("Язык") | F.text.contains("Language"))
async def lang_cmd(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 Русский", callback_data="set_ru")
    kb.button(text="🇬🇧 English", callback_data="set_en")
    await message.answer("Выберите язык:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("set_"))
async def set_lang(call: types.CallbackQuery):
    l = call.data.split("_")[1]
    cursor.execute("UPDATE users SET lang = ? WHERE tg_id = ?", (l, call.from_user.id))
    conn.commit()
    await call.message.delete()
    await call.message.answer("✅ Done!", reply_markup=main_kb(l))

# --- АДМИНКА ---
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_cmd(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Рассылка", callback_data="admin_mail")
    await message.answer("Админка:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "admin_mail", F.from_user.id == ADMIN_ID)
async def admin_mail(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Отправь сообщение для рассылки:")
    await state.set_state(Form.waiting_for_broadcast)

@dp.message(Form.waiting_for_broadcast)
async def do_broadcast(message: types.Message, state: FSMContext):
    ids = cursor.execute("SELECT tg_id FROM users").fetchall()
    for i in ids:
        try:
            await message.copy_to(i[0])
            await asyncio.sleep(0.05)
        except: pass
    await message.answer("✅ Рассылка завершена.")
    await state.clear()

# --- ЗАПУСК ---
async def start_bot():
    try:
        print("--- БОТ ЗАПУСКАЕТСЯ ---")
        await dp.start_polling(bot)
    except Exception as e:
        print(f"ОШИБКА: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_bot())
