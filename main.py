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
    rec INTEGER DEFAULT 0)''')
cur.execute("CREATE TABLE IF NOT EXISTS msgs (id INTEGER PRIMARY KEY AUTOINCREMENT, s_id BIGINT, r_id BIGINT, m_id INTEGER)")
db.commit()

class MyStates(StatesGroup):
    txt = State()
    mail = State()
    set_alias = State()

# --- ДИЗАЙН ТЕКСТА ---
STR = {
    'ru': {
        'hi': "<b>Начните получать анонимные сообщения прямо сейчас!</b>\n\n"
              "Ваша ссылка:\n"
              "🟢 <code>{link}</code>\n\n"
              "Разместите эту ссылку ☝️ в описании своего профиля Telegram, TikTok или Instagram, чтобы вам могли написать 💬",
        'prof': "👤 <b>Ваш профиль</b>\n\n"
                "📊 <b>Статистика:</b>\n"
                "├ Получено: <code>{r}</code>\n"
                "└ Отправлено: <code>{s}</code>\n\n"
                "🔗 <b>Ваша ссылка для Stories:</b>\n"
                "<code>{link}</code>",
        'go': "🚀 <b>Отправьте анонимное сообщение...</b>\n\n"
              "Вы можете отправить текст, фото, видео или голосовое сообщение. "
              "Получатель не узнает, кто вы!",
        'ok': "✅ <b>Сообщение доставлено!</b>",
        'del': "🗑 Удалить",
        'rep': "💬 Ответить",
        'share': "🔗 Поделиться ссылкой",
        'settings': "⚙️ Настройки",
        'alias': "✏️ Изменить ник ссылки",
        'lang': "🌍 Сменить язык",
        'back': "⬅️ Назад",
        'new_msg': "📬 <b>Вам новое анонимное сообщение!</b>"
    },
    'en': {
        'hi': "<b>Start receiving anonymous messages right now!</b>\n\n"
              "Your link:\n"
              "🟢 <code>{link}</code>\n\n"
              "Place this link ☝️ in your Telegram, TikTok, or Instagram bio to get messages 💬",
        'prof': "👤 <b>Your Profile</b>\n\n"
                "📊 <b>Statistics:</b>\n"
                "├ Received: <code>{r}</code>\n"
                "└ Sent: <code>{s}</code>\n\n"
                "🔗 <b>Your link for Stories:</b>\n"
                "<code>{link}</code>",
        'go': "🚀 <b>Send an anonymous message...</b>\n\n"
              "You can send text, photos, video, or voice. The recipient won't know who you are!",
        'ok': "✅ <b>Message delivered!</b>",
        'del': "🗑 Delete",
        'rep': "💬 Reply",
        'share': "🔗 Share link",
        'settings': "⚙️ Settings",
        'alias': "✏️ Change Alias",
        'lang': "🌍 Change Language",
        'back': "⬅️ Back",
        'new_msg': "📬 <b>You have a new anonymous message!</b>"
    }
}

# --- КЛАВИАТУРЫ ---
def main_kb(lang):
    kb = ReplyKeyboardBuilder()
    if lang == 'ru':
        kb.button(text="👤 Профиль"), kb.button(text="⚙️ Настройки")
    else:
        kb.button(text="👤 Profile"), kb.button(text="⚙️ Settings")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

def profile_inline(lang, username, uid_or_alias):
    kb = InlineKeyboardBuilder()
    link = f"https://t.me/{username}?start={uid_or_alias}"
    kb.button(text=STR[lang]['share'], switch_inline_query=f"\nНапиши мне анонимно! 👇\n{link}")
    return kb.as_markup()

# --- ФУНКЦИИ ---
def get_u(uid):
    u = cur.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()
    if not u:
        cur.execute("INSERT INTO users (tg_id) VALUES (?)", (uid,))
        db.commit()
        u = cur.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()
    return u

# --- ОБРАБОТЧИКИ ---

@dp.message(CommandStart())
async def cmd_start(msg: types.Message, state: FSMContext):
    await state.clear() # Сбрасываем любые состояния при команде старт
    u = get_u(msg.from_user.id)
    args = msg.text.split()
    me = await bot.get_me()

    if len(args) > 1:
        target_val = args[1]
        t_user = cur.execute("SELECT tg_id FROM users WHERE tg_id = ? OR alias = ?", (target_val, target_val)).fetchone()
        if t_user and t_user[0] != msg.from_user.id:
            await state.update_data(t_id=t_user[0])
            await msg.answer(STR[u[3]]['go'])
            await state.set_state(MyStates.txt)
            return

    link = f"t.me/{me.username}?start={u[2] if u[2] else u[1]}"
    await msg.answer(STR[u[3]]['hi'].format(link=link), 
                     reply_markup=main_kb(u[3]))
    await msg.answer("📸 <i>Вы также можете опубликовать ссылку в Stories прямо сейчас!</i>", 
                     reply_markup=profile_inline(u[3], me.username, u[2] if u[2] else u[1]))

@dp.message(MyStates.txt, ~F.text.startswith("/")) # Игнорируем команды внутри анонимки
async def handle_anon(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    u = get_u(msg.from_user.id)
    try:
        # Пересылка
        res = await msg.copy_to(data['t_id'])
        cur.execute("INSERT INTO msgs (s_id, r_id, m_id) VALUES (?, ?, ?)", (msg.from_user.id, data['t_id'], res.message_id))
        cur.execute("UPDATE users SET sent = sent + 1 WHERE tg_id = ?", (msg.from_user.id,))
        cur.execute("UPDATE users SET rec = rec + 1 WHERE tg_id = ?", (data['t_id'],))
        db.commit()
        
        # Инлайн для управления
        kb = InlineKeyboardBuilder()
        kb.button(text=STR[u[3]]['del'], callback_data=f"del_{cur.lastrowid}")
        await msg.answer(STR[u[3]]['ok'], reply_markup=kb.as_markup())
        
        # Получателю
        rk = InlineKeyboardBuilder()
        rk.button(text=STR[u[3]]['rep'], callback_data=f"rep_{msg.from_user.id}")
        await bot.send_message(data['t_id'], STR[u[3]]['new_msg'], reply_markup=rk.as_markup())
    except:
        await msg.answer("❌ Ошибка: не удалось отправить.")
    await state.clear()

@dp.message(F.text.in_(["👤 Профиль", "👤 Profile"]))
async def profile(msg: types.Message):
    u = get_u(msg.from_user.id)
    me = await bot.get_me()
    link = f"t.me/{me.username}?start={u[2] if u[2] else u[1]}"
    await msg.answer(STR[u[3]]['prof'].format(s=u[4], r=u[5], link=link), 
                     reply_markup=profile_inline(u[3], me.username, u[2] if u[2] else u[1]))

@dp.message(F.text.in_(["⚙️ Настройки", "⚙️ Settings"]))
async def settings(msg: types.Message):
    u = get_u(msg.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=STR[u[3]]['alias'], callback_data="set_alias")
    kb.button(text=STR[u[3]]['lang'], callback_data="set_lang")
    kb.adjust(1)
    await msg.answer(f"<b>{STR[u[3]]['settings']}</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "set_lang")
async def lang_call(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 Русский", callback_data="l_ru")
    kb.button(text="🇬🇧 English", callback_data="l_en")
    await call.message.edit_text("Выберите язык / Choose language:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("l_"))
async def set_l(call: types.CallbackQuery):
    l = call.data.split("_")[1]
    cur.execute("UPDATE users SET lang = ? WHERE tg_id = ?", (l, call.from_user.id))
    db.commit()
    await call.message.delete()
    await call.message.answer("✅ Success!", reply_markup=main_kb(l))

@dp.callback_query(F.data == "set_alias")
async def alias_call(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("<b>Введите новый ник для вашей ссылки:</b>\n<i>Например: pavel_2024</i>")
    await state.set_state(MyStates.set_alias)
    await call.answer()

@dp.message(MyStates.set_alias)
async def process_alias(msg: types.Message, state: FSMContext):
    u = get_u(msg.from_user.id)
    new_alias = msg.text.strip()
    if not new_alias.isalnum():
        return await msg.answer("❌ Ник должен состоять только из букв и цифр.")
    
    try:
        cur.execute("UPDATE users SET alias = ? WHERE tg_id = ?", (new_alias, msg.from_user.id))
        db.commit()
        await msg.answer(f"✅ Готово! Ваша новая ссылка:\n<code>t.me/{(await bot.get_me()).username}?start={new_alias}</code>")
        await state.clear()
    except:
        await msg.answer("❌ Этот ник уже занят другим пользователем.")

@dp.callback_query(F.data.startswith("rep_"))
async def reply_call(call: types.CallbackQuery, state: FSMContext):
    target = call.data.split("_")[1]
    await state.update_data(t_id=target)
    await call.message.answer("🚀 <b>Введите ваш ответ:</b>")
    await state.set_state(MyStates.txt)
    await call.answer()

@dp.callback_query(F.data.startswith("del_"))
async def delete_call(call: types.CallbackQuery):
    mid = call.data.split("_")[1]
    m = cur.execute("SELECT * FROM msgs WHERE id = ?", (mid,)).fetchone()
    if m:
        try:
            await bot.delete_message(m[2], m[3])
            await call.message.edit_text("🗑 <b>Вы удалили это сообщение.</b>")
        except:
            await call.answer("Не удалось удалить.")

async def run():
    print("--- BOT STARTED ---")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
    # --- АДМИН ПАНЕЛЬ ---

@dp.message(Command("admin"))
async def admin_panel(msg: types.Message):
    # Проверка на админа
    if msg.from_user.id != ADMIN_ID:
        return

    # Считаем количество пользователей в базе
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]

    # Считаем сколько сообщений было отправлено всего через бота
    cur.execute("SELECT SUM(sent) FROM users")
    total_messages = cur.fetchone()[0] or 0

    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Начать рассылку", callback_data="admin_broadcast")
    kb.button(text="🔄 Обновить", callback_data="admin_stats_update")
    kb.adjust(1)

    await msg.answer(
        f"🛠 <b>Панель администратора</b>\n\n"
        f"👥 <b>Всего пользователей:</b> <code>{total_users}</code>\n"
        f"✉️ <b>Всего анонимок:</b> <code>{total_messages}</code>\n\n"
        f"<i>Статистика обновляется в реальном времени.</i>", 
        reply_markup=kb.as_markup()
    )

# Обработка обновления статистики
@dp.callback_query(F.data == "admin_stats_update")
async def update_stats_call(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    cur.execute("SELECT SUM(sent) FROM users")
    total_messages = cur.fetchone()[0] or 0

    try:
        await call.message.edit_text(
            f"🛠 <b>Панель администратора</b>\n\n"
            f"👥 <b>Всего пользователей:</b> <code>{total_users}</code>\n"
            f"✉️ <b>Всего анонимок:</b> <code>{total_messages}</code>\n\n"
            f"<i>Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>",
            reply_markup=call.message.reply_markup
        )
    except:
        await call.answer("Данные актуальны!")
    await call.answer()

# Рассылка (как в прошлом сообщении)
@dp.callback_query(F.data == "admin_broadcast")
async def broadcast_step1(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.answer("📢 <b>Введите сообщение для рассылки:</b>")
    await state.set_state(MyStates.mail)
    await call.answer()

@dp.message(MyStates.mail)
async def broadcast_step2(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    
    users = cur.execute("SELECT tg_id FROM users").fetchall()
    count, blocked = 0, 0
    
    status_msg = await msg.answer("⏳ <i>Рассылка...</i>")

    for user in users:
        try:
            await msg.copy_to(chat_id=user[0])
            count += 1
            await asyncio.sleep(0.05)
        except:
            blocked += 1
    
    await status_msg.edit_text(f"✅ <b>Готово!</b>\n\nПолучили: {count}\nВ бане: {blocked}")
    await state.clear()
