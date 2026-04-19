import asyncio
import logging
import sqlite3
from os import getenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

load_dotenv()

# --- ПЕРЕМЕННЫЕ ---
BOT_TOKEN = getenv("BOT_TOKEN")
ADMIN_ID = int(getenv("ADMIN_ID") if getenv("ADMIN_ID") else 0)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
db = sqlite3.connect("bot.db", check_same_thread=False)
cur = db.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, tg_id BIGINT UNIQUE, lang TEXT DEFAULT 'ru', sent INTEGER DEFAULT 0, rec INTEGER DEFAULT 0)")
cur.execute("CREATE TABLE IF NOT EXISTS msgs (id INTEGER PRIMARY KEY AUTOINCREMENT, s_id BIGINT, r_id BIGINT, m_id INTEGER)")
db.commit()

class MyStates(StatesGroup):
    txt = State()
    mail = State()

# --- ТЕКСТЫ ---
T = {
    'ru': {
        'hi': "👋 <b>Привет!</b>\n\nТут пишут анонимно. Твоя ссылка:\n🔗 <code>t.me/{u}?start={i}</code>",
        'prof': "👤 <b>Профиль</b>\n\nОтправлено: {s}\nПолучено: {r}\n\nСсылка:\n<code>t.me/{u}?start={i}</code>",
        'go': "🚀 Пиши сообщение (текст, фото или видео):",
        'ok': "✅ Отправлено!",
        'del': "🗑 Удалить",
        'rep': "💬 Ответить",
        'lang': "🌍 Язык / Language"
    },
    'en': {
        'hi': "👋 <b>Hi!</b>\n\nReceive anon messages here. Your link:\n🔗 <code>t.me/{u}?start={i}</code>",
        'prof': "👤 <b>Profile</b>\n\nSent: {s}\nReceived: {r}\n\nLink:\n<code>t.me/{u}?start={i}</code>",
        'go': "🚀 Send your message (text, photo or video):",
        'ok': "✅ Sent!",
        'del': "🗑 Delete",
        'rep': "💬 Reply",
        'lang': "🌍 Language / Язык"
    }
}

# --- КНОПКИ ---
def get_kb(lang):
    kb = ReplyKeyboardBuilder()
    kb.button(text="👤 Профиль" if lang == 'ru' else "👤 Profile")
    kb.button(text=T[lang]['lang'])
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)

# --- ЛОГИКА ---
@dp.message(CommandStart())
async def start(msg: types.Message, state: FSMContext):
    uid = msg.from_user.id
    arg = msg.text.split()
    
    user = cur.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()
    if not user:
        cur.execute("INSERT INTO users (tg_id) VALUES (?)", (uid,))
        db.commit()
        user = (0, uid, 'ru', 0, 0)

    if len(arg) > 1:
        target = int(arg[1])
        if target == uid: return await msg.answer("❌ Нельзя писать себе.")
        await state.update_data(t_id=target)
        await msg.answer(T[user[2]]['go'])
        await state.set_state(MyStates.txt)
        return

    me = await bot.get_me()
    await msg.answer(T[user[2]]['hi'].format(u=me.username, i=uid), reply_markup=get_kb(user[2]))

@dp.message(MyStates.txt)
async def send_anon(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    tid = data['t_id']
    u = cur.execute("SELECT * FROM users WHERE tg_id = ?", (msg.from_user.id,)).fetchone()
    
    try:
        res = await msg.copy_to(tid)
        cur.execute("INSERT INTO msgs (s_id, r_id, m_id) VALUES (?, ?, ?)", (msg.from_user.id, tid, res.message_id))
        cur.execute("UPDATE users SET sent = sent + 1 WHERE tg_id = ?", (msg.from_user.id,))
        cur.execute("UPDATE users SET rec = rec + 1 WHERE tg_id = ?", (tid,))
        db.commit()
        
        kb = InlineKeyboardBuilder()
        kb.button(text=T[u[2]]['del'], callback_data=f"d_{cur.lastrowid}")
        await msg.answer(T[u[2]]['ok'], reply_markup=kb.as_markup())
        
        rk = InlineKeyboardBuilder()
        rk.button(text=T[u[2]]['rep'], callback_data=f"r_{msg.from_user.id}")
        await bot.send_message(tid, "📩 <b>Новое анонимное сообщение!</b>", reply_markup=rk.as_markup())
    except:
        await msg.answer("❌ Ошибка.")
    await state.clear()

@dp.callback_query(F.data.startswith("d_"))
async def del_anon(call: types.CallbackQuery):
    mid = call.data.split("_")[1]
    m = cur.execute("SELECT * FROM msgs WHERE id = ?", (mid,)).fetchone()
    if m:
        try:
            await bot.delete_message(m[2], m[3])
            await call.message.edit_text("🗑 Удалено.")
        except:
            await call.answer("Ошибка удаления.")

@dp.callback_query(F.data.startswith("r_"))
async def rep_anon(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(t_id=call.data.split("_")[1])
    await call.message.answer("🚀 Напиши ответ:")
    await state.set_state(MyStates.txt)
    await call.answer()

@dp.message(F.text.in_(["👤 Профиль", "👤 Profile"]))
async def profile(msg: types.Message):
    u = cur.execute("SELECT * FROM users WHERE tg_id = ?", (msg.from_user.id,)).fetchone()
    me = await bot.get_me()
    await msg.answer(T[u[2]]['prof'].format(s=u[3], r=u[4], u=me.username, i=u[1]))

@dp.message(F.text == "🌍 Язык / Language")
async def lang(msg: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 RU", callback_data="l_ru")
    kb.button(text="🇬🇧 EN", callback_data="l_en")
    await msg.answer("Choice:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("l_"))
async def set_l(call: types.CallbackQuery):
    l = call.data.split("_")[1]
    cur.execute("UPDATE users SET lang = ? WHERE tg_id = ?", (l, call.from_user.id))
    db.commit()
    await call.message.delete()
    await call.message.answer("✅ Done!", reply_markup=get_kb(l))

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def adm(msg: types.Message):
    await msg.answer("📢 Отправь текст рассылки:")
    await state.set_state(MyStates.mail)

async def run():
    print("--- BOT STARTED ---")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
