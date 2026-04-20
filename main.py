import asyncio
import logging
import sqlite3
from datetime import datetime
from os import getenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

load_dotenv()

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = getenv("BOT_TOKEN")
ADMIN_ID = int(getenv("ADMIN_ID") if getenv("ADMIN_ID") else 0)
CH_ID = getenv("CHANNEL_ID")
CH_URL = getenv("CHANNEL_URL")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
db = sqlite3.connect("bot.db", check_same_thread=False)
cur = db.cursor()
cur.execute('''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, 
    tg_id BIGINT UNIQUE, 
    alias TEXT UNIQUE,
    lang TEXT DEFAULT 'ru', 
    sent INTEGER DEFAULT 0, 
    rec INTEGER DEFAULT 0,
    rec_today INTEGER DEFAULT 0,
    last_date TEXT)''')
cur.execute("CREATE TABLE IF NOT EXISTS msgs (id INTEGER PRIMARY KEY AUTOINCREMENT, s_id BIGINT, r_id BIGINT, m_id INTEGER)")
db.commit()

class MyStates(StatesGroup):
    txt = State()
    mail = State()
    set_alias = State()

# --- ТЕКСТЫ ---
T = {
    'ru': {
        'hi': "🌟 <b>Привет! Добро пожаловать!</b>\n\nТут ты можешь получать анонимные сообщения, видео и аудио. Твоя личная ссылка ниже — поделись ей!\n\n🔗 <code>{link}</code>",
        'prof': "👤 <b>Твой профиль</b>\n\n📊 <b>Статистика:</b>\n├ Получено: <code>{r}</code> <i>(за сегодня: {rt})</i>\n└ Отправлено: <code>{s}</code>\n\n🔗 <b>Ссылка:</b>\n<code>{link}</code>",
        'go': "🚀 <b>Пиши сообщение!</b>\nМожно отправить текст, фото, видео, кружочки или голосовое. Я всё передам анонимно.",
        'ok': "✅ <b>Отправлено!</b>\nТеперь ты можешь удалить его у получателя, если передумаешь.",
        'del': "🗑 Удалить у него",
        'rep': "💬 Ответить",
        'set_lang': "🌍 Выбрать язык",
        'set_alias': "✏️ Сделать ник",
        'sub': "⚠️ <b>Внимание!</b>\nДля использования бота нужно подписаться на наш канал.",
        'sub_btn': "Подписаться",
        'err_alias': "❌ Ник может содержать только буквы и цифры!",
        'alias_ok': "✅ Ник установлен!"
    },
    'en': {
        'hi': "🌟 <b>Welcome!</b>\n\nHere you can receive anonymous messages, videos, and audio. Your personal link is below — share it!\n\n🔗 <code>{link}</code>",
        'prof': "👤 <b>Your Profile</b>\n\n📊 <b>Stats:</b>\n├ Received: <code>{r}</code> <i>(today: {rt})</i>\n└ Sent: <code>{s}</code>\n\n🔗 <b>Link:</b>\n<code>{link}</code>",
        'go': "🚀 <b>Send your message!</b>\nText, photos, videos, or voices are all allowed. I'll deliver it anonymously.",
        'ok': "✅ <b>Sent!</b>\nNow you can delete it for the recipient if you change your mind.",
        'del': "🗑 Delete for him",
        'rep': "💬 Reply",
        'set_lang': "🌍 Language",
        'set_alias': "✏️ Set Alias",
        'sub': "⚠️ <b>Attention!</b>\nYou must subscribe to our channel to use this bot.",
        'sub_btn': "Subscribe",
        'err_alias': "❌ Alias must contain only letters and numbers!",
        'alias_ok': "✅ Alias updated!"
    }
}

# --- ФУНКЦИИ ---
async def is_sub(uid):
    if not CH_ID: return True
    try:
        m = await bot.get_chat_member(CH_ID, uid)
        return m.status != 'left'
    except: return True

def get_u(uid):
    u = cur.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()
    if not u:
        cur.execute("INSERT INTO users (tg_id, last_date) VALUES (?, ?)", (uid, str(datetime.now().date())))
        db.commit()
        return cur.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()
    
    # Сброс ежедневной статистики
    today = str(datetime.now().date())
    if u[7] != today:
        cur.execute("UPDATE users SET rec_today = 0, last_date = ? WHERE tg_id = ?", (today, uid))
        db.commit()
        return cur.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()
    return u

def get_kb(lang):
    kb = ReplyKeyboardBuilder()
    kb.button(text="👤 Профиль" if lang == 'ru' else "👤 Profile")
    kb.button(text="⚙️ Настройки" if lang == 'ru' else "⚙️ Settings")
    kb.adjust(1, 1)
    return kb.as_markup(resize_keyboard=True)

# --- ЛОГИКА ---
@dp.message(CommandStart())
async def start(msg: types.Message, state: FSMContext):
    u = get_u(msg.from_user.id)
    arg = msg.text.split()
    
    if not await is_sub(msg.from_user.id):
        kb = InlineKeyboardBuilder()
        kb.button(text=T[u[3]]['sub_btn'], url=CH_URL)
        return await msg.answer(T[u[3]]['sub'], reply_markup=kb.as_markup())

    if len(arg) > 1:
        target_val = arg[1]
        t_user = cur.execute("SELECT tg_id FROM users WHERE tg_id = ? OR alias = ?", (target_val, target_val)).fetchone()
        if t_user:
            if t_user[0] == msg.from_user.id: return await msg.answer("❌ Писать себе нельзя.")
            await state.update_data(t_id=t_user[0])
            await msg.answer(T[u[3]]['go'])
            await state.set_state(MyStates.txt)
            return

    me = await bot.get_me()
    link = f"t.me/{me.username}?start={u[2] if u[2] else u[1]}"
    await msg.answer(T[u[3]]['hi'].format(link=link), reply_markup=get_kb(u[3]))

@dp.message(MyStates.txt)
async def send_anon(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    u = get_u(msg.from_user.id)
    try:
        res = await msg.copy_to(data['t_id'])
        cur.execute("INSERT INTO msgs (s_id, r_id, m_id) VALUES (?, ?, ?)", (msg.from_user.id, data['t_id'], res.message_id))
        cur.execute("UPDATE users SET sent = sent + 1 WHERE tg_id = ?", (msg.from_user.id,))
        cur.execute("UPDATE users SET rec = rec + 1, rec_today = rec_today + 1 WHERE tg_id = ?", (data['t_id'],))
        db.commit()
        
        kb = InlineKeyboardBuilder().button(text=T[u[3]]['del'], callback_data=f"d_{cur.lastrowid}")
        await msg.answer(T[u[3]]['ok'], reply_markup=kb.as_markup())
        
        rk = InlineKeyboardBuilder().button(text=T[u[3]]['rep'], callback_data=f"r_{msg.from_user.id}")
        await bot.send_message(data['t_id'], "📩 <b>Новое сообщение!</b>", reply_markup=rk.as_markup())
    except: await msg.answer("❌ Ошибка доставки.")
    await state.clear()

@dp.message(F.text.in_(["👤 Профиль", "👤 Profile"]))
async def profile(msg: types.Message):
    u = get_u(msg.from_user.id)
    me = await bot.get_me()
    link = f"t.me/{me.username}?start={u[2] if u[2] else u[1]}"
    await msg.answer(T[u[3]]['prof'].format(s=u[4], r=u[5], rt=u[6], link=link))

@dp.message(F.text.in_(["⚙️ Настройки", "⚙️ Settings"]))
async def settings(msg: types.Message):
    u = get_u(msg.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=T[u[3]]['set_lang'], callback_data="lang")
    kb.button(text=T[u[3]]['set_alias'], callback_data="alias")
    await msg.answer("⚙️ <b>Меню настроек:</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "lang")
async def lang_call(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 RU", callback_data="l_ru")
    kb.button(text="🇬🇧 EN", callback_data="l_en")
    await call.message.edit_text("Выбери язык / Choose lang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("l_"))
async def set_l(call: types.CallbackQuery):
    l = call.data.split("_")[1]
    cur.execute("UPDATE users SET lang = ? WHERE tg_id = ?", (l, call.from_user.id))
    db.commit()
    await call.message.delete()
    await call.message.answer("✅", reply_markup=get_kb(l))

@dp.callback_query(F.data == "alias")
async def alias_call(call: types.CallbackQuery, state: FSMContext):
    u = get_u(call.from_user.id)
    await call.message.answer("✏️ <b>Введи свой ник для ссылки</b> (только буквы и цифры):")
    await state.set_state(MyStates.set_alias)
    await call.answer()

@dp.message(MyStates.set_alias)
async def set_alias_text(msg: types.Message, state: FSMContext):
    u = get_u(msg.from_user.id)
    new_alias = msg.text.strip()
    if not new_alias.isalnum():
        return await msg.answer(T[u[3]]['err_alias'])
    
    try:
        cur.execute("UPDATE users SET alias = ? WHERE tg_id = ?", (new_alias, msg.from_user.id))
        db.commit()
        await msg.answer(T[u[3]]['alias_ok'], reply_markup=get_kb(u[3]))
        await state.clear()
    except:
        await msg.answer("❌ Этот ник уже занят!")

@dp.callback_query(F.data.startswith("d_"))
async def del_msg(call: types.CallbackQuery):
    m = cur.execute("SELECT * FROM msgs WHERE id = ?", (call.data.split("_")[1],)).fetchone()
    if m:
        try:
            await bot.delete_message(m[2], m[3])
            await call.message.edit_text("🗑 Удалено.")
        except: await call.answer("Невозможно удалить.")

@dp.callback_query(F.data.startswith("r_"))
async def reply_call(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(t_id=call.data.split("_")[1])
    await call.message.answer("🚀 <b>Пиши ответ:</b>")
    await state.set_state(MyStates.txt)
    await call.answer()

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin(msg: types.Message, state: FSMContext):
    await msg.answer("📢 <b>Режим рассылки.</b>\nПришли сообщение (можно с фото):")
    await state.set_state(MyStates.mail)

@dp.message(MyStates.mail, F.from_user.id == ADMIN_ID)
async def mail_send(msg: types.Message, state: FSMContext):
    ids = cur.execute("SELECT tg_id FROM users").fetchall()
    count = 0
    for i in ids:
        try:
            await msg.copy_to(i[0])
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await msg.answer(f"✅ Рассылка завершена! Получили {count} чел.")
    await state.clear()

async def run():
    print("--- BOT STARTED ---")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
