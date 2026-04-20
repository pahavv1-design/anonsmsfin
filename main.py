import asyncio, logging, sqlite3, random
from datetime import datetime, timedelta
from os import getenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = getenv("BOT_TOKEN")
ADMIN_ID = int(getenv("ADMIN_ID") or 0)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# БАЗА ДАННЫХ
db = sqlite3.connect("bot.db", check_same_thread=False)
cur = db.cursor()
cur.execute('''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, tg_id BIGINT UNIQUE, alias TEXT UNIQUE,
    lang TEXT DEFAULT 'ru', sent INTEGER DEFAULT 0, rec INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1, exp INTEGER DEFAULT 0, clicks INTEGER DEFAULT 0)''')
cur.execute("CREATE TABLE IF NOT EXISTS msgs (id INTEGER PRIMARY KEY AUTOINCREMENT, s_id BIGINT, r_id BIGINT, m_id INTEGER)")
cur.execute("CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id BIGINT, link TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS blacklist (user_id BIGINT PRIMARY KEY, until TIMESTAMP)")
db.commit()

class State(StatesGroup):
    txt = State()
    alias = State()
    broadcast = State()
    add_channel = State()

# ТЕКСТЫ (КРАСИВЫЕ)
T = {
    'ru': {
        'start': "🤫 <b>Анонимные сообщения</b>\n\n"
                 "<b>Что умеет этот бот?</b>\n\n"
                 "• 📩 Получать анонимные вопросы\n"
                 "• 💬 Отвечать не раскрывая себя\n"
                 "• 🔗 Красивая ссылка для соцсетей\n"
                 "• 🎁 Повышай уровень за активность\n\n"
                 "👇 <i>Нажми «Начать», чтобы отправлять анонимные сообщения</i> 🚫\n\n"
                 "──────────────\n"
                 "<b>📎 Ваша ссылка:</b>\n"
                 "<code>{link}</code>\n\n"
                 "✨ <i>Разместите эту ссылку в описании профиля Telegram, TikTok или Instagram, чтобы вам могли написать</i> 😉",
        'profile': "👤 <b>ТВОЙ ПРОФИЛЬ</b>\n\n"
                   "📊 <b>Статистика:</b>\n"
                   "├ ✉️ Получено: <code>{r}</code>\n"
                   "├ 📤 Отправлено: <code>{s}</code>\n"
                   "├ 🏆 Уровень: <code>{lvl}</code>\n"
                   "└ ⭐ Опыт: <code>{exp}</code>/<code>{next_exp}</code>\n\n"
                   "🔗 <b>Твоя ссылка:</b>\n"
                   "<code>{link}</code>\n\n"
                   "💡 <i>Чем больше сообщений — тем выше уровень!</i>",
        'go': "✍️ <b>Напиши анонимное сообщение...</b>\n\n"
              "💬 <i>Твой собеседник не узнает, кто ты 🔥</i>",
        'ok': "✅ <b>Сообщение доставлено!</b>\n\n✨ +5 опыта",
        'new': "📬 <b>НОВОЕ АНОНИМНОЕ СООБЩЕНИЕ!</b>\n\n👇 Нажми «Ответить»",
        'del': "🗑 Удалить",
        'rep': "💬 Ответить",
        'link': "🔗 <b>УПРАВЛЕНИЕ ССЫЛКОЙ</b>\n\n"
                "📎 <b>Твоя ссылка:</b>\n<code>{link}</code>\n\n"
                "📊 <b>Статистика:</b>\n├ 👆 Переходов: <code>{clicks}</code>\n└ ✉️ Сообщений: <code>{msgs}</code>",
        'alias_ask': "✏️ <b>Введи новый alias:</b>\n\n📌 Только буквы/цифры, 3-20 символов",
        'alias_ok': "✅ <b>ALIAS ИЗМЕНЁН!</b>\n\n🔗 <code>{link}</code>",
        'alias_bad': "❌ Занят или неверный формат!",
        'sub_required': "⚠️ <b>ПОДПИШИСЬ НА КАНАЛЫ</b>",
        'check_sub': "✅ Проверить",
        'sub_ok': "✅ Спасибо! Теперь можно пользоваться ботом.",
        'settings': "⚙️ <b>НАСТРОЙКИ</b>",
        'help': "📚 <b>ПОМОЩЬ</b>\n\n/start - Главное меню\n/profile - Профиль\n/link - Ссылка",
    },
    'en': {
        'start': "🤫 <b>Anonymous Messages</b>\n\n📎 <code>{link}</code>",
        'profile': "👤 <b>Profile</b>\n\n📤 Sent: {s}\n📥 Received: {r}\n🏆 Level: {lvl}",
        'go': "✍️ Send anonymous message:",
        'ok': "✅ Delivered! +5 XP",
        'new': "📬 New message!",
        'del': "🗑 Delete",
        'rep': "💬 Reply",
        'link': "🔗 <b>Link</b>\n<code>{link}</code>\n👆 Clicks: {clicks}\n✉️ Messages: {msgs}",
        'alias_ask': "✏️ Enter new alias:",
        'alias_ok': "✅ Alias changed!\n<code>{link}</code>",
        'alias_bad': "❌ Invalid or taken!",
        'sub_required': "⚠️ Subscribe to channels",
        'check_sub': "✅ Check",
        'sub_ok': "✅ Thanks!",
        'settings': "⚙️ Settings",
        'help': "📚 Help",
    }
}

def get_user(uid):
    u = cur.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()
    if not u:
        cur.execute("INSERT INTO users (tg_id) VALUES (?)", (uid,))
        db.commit()
        u = cur.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()
    banned = cur.execute("SELECT until FROM blacklist WHERE user_id = ? AND until > datetime('now')", (uid,)).fetchone()
    return None if banned else u

def add_exp(uid):
    cur.execute("UPDATE users SET exp = exp + 5, level = 1 + (exp/100) WHERE tg_id = ?", (uid,))
    db.commit()

async def check_sub(user_id):
    channels = cur.execute("SELECT chat_id FROM channels").fetchall()
    if not channels:
        return True
    for (chat_id,) in channels:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except:
            continue
    return True

def sub_kb(lang):
    ikb = InlineKeyboardBuilder()
    channels = cur.execute("SELECT link FROM channels").fetchall()
    for i, (link,) in enumerate(channels, 1):
        ikb.button(text=f"📢 Канал {i}" if lang=='ru' else f"📢 Channel {i}", url=link)
    ikb.button(text=T[lang]['check_sub'], callback_data="check_sub")
    ikb.adjust(1)
    return ikb.as_markup()

def kb(lang):
    rkb = ReplyKeyboardBuilder()
    for btn in ["👤 Profile", "🔗 Link", "⚙️ Settings"] if lang == 'en' else ["👤 Профиль", "🔗 Ссылка", "⚙️ Настройки"]:
        rkb.button(text=btn)
    rkb.adjust(2)
    return rkb.as_markup(resize_keyboard=True)

# ============= КОМАНДЫ =============

@dp.message(CommandStart())
async def start(m: types.Message, state: State):
    await state.clear()
    args = m.text.split()
    me = await bot.get_me()
    
    if len(args) > 1:
        target = args[1]
        tu = cur.execute("SELECT tg_id FROM users WHERE tg_id = ? OR alias = ?", (target, target)).fetchone()
        if tu and tu[0] != m.from_user.id:
            if not await check_sub(m.from_user.id):
                u = get_user(m.from_user.id)
                if u:
                    return await m.answer(T[u[3]]['sub_required'], reply_markup=sub_kb(u[3]))
                return
            cur.execute("UPDATE users SET clicks = clicks + 1 WHERE tg_id = ?", (tu[0],))
            db.commit()
            await state.update_data(t_id=tu[0])
            u = get_user(m.from_user.id)
            if u: await m.answer(T[u[3]]['go'], reply_markup=kb(u[3]))
            await state.set_state(State.txt)
            return
    
    u = get_user(m.from_user.id)
    if not u: return await m.answer("🚫 Бан")
    
    if not await check_sub(m.from_user.id):
        return await m.answer(T[u[3]]['sub_required'], reply_markup=sub_kb(u[3]))
    
    alias = u[2] or str(u[1])
    link = f"t.me/{me.username}?start={alias}"
    await m.answer(T[u[3]]['start'].format(link=link), reply_markup=kb(u[3]))

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(call: types.CallbackQuery):
    if await check_sub(call.from_user.id):
        u = get_user(call.from_user.id)
        await call.message.delete()
        me = await bot.get_me()
        alias = u[2] or str(u[1])
        link = f"t.me/{me.username}?start={alias}"
        await call.message.answer(T[u[3]]['start'].format(link=link), reply_markup=kb(u[3]))
    else:
        u = get_user(call.from_user.id)
        await call.answer("❌ Подпишись на все каналы!" if u[3]=='ru' else "❌ Subscribe!", show_alert=True)

@dp.message(F.text.in_(["👤 Profile", "👤 Профиль"]))
async def profile(m: types.Message):
    u = get_user(m.from_user.id)
    if not u: return
    if not await check_sub(m.from_user.id):
        return await m.answer(T[u[3]]['sub_required'], reply_markup=sub_kb(u[3]))
    me = await bot.get_me()
    alias = u[2] or str(u[1])
    link = f"t.me/{me.username}?start={alias}"
    next_exp = ((u[6] * 100) + 100) - u[7]
    await m.answer(T[u[3]]['profile'].format(s=u[4], r=u[5], lvl=u[6], exp=u[7], next_exp=next_exp, link=link), reply_markup=kb(u[3]))

@dp.message(F.text.in_(["🔗 Link", "🔗 Ссылка"]))
async def link_menu(m: types.Message):
    u = get_user(m.from_user.id)
    if not u: return
    if not await check_sub(m.from_user.id):
        return await m.answer(T[u[3]]['sub_required'], reply_markup=sub_kb(u[3]))
    me = await bot.get_me()
    alias = u[2] or str(u[1])
    link = f"t.me/{me.username}?start={alias}"
    ikb = InlineKeyboardBuilder()
    ikb.button(text="✏️ Изменить" if u[3]=='ru' else "✏️ Change", callback_data="ch_alias")
    ikb.button(text="🎲 Случайный" if u[3]=='ru' else "🎲 Random", callback_data="rand_alias")
    await m.answer(T[u[3]]['link'].format(link=link, clicks=u[8] if len(u)>8 else 0, msgs=u[5]), reply_markup=ikb.as_markup())

@dp.message(F.text.in_(["⚙️ Settings", "⚙️ Настройки"]))
async def settings(m: types.Message):
    u = get_user(m.from_user.id)
    if not u: return
    ikb = InlineKeyboardBuilder()
    ikb.button(text="🇷🇺 Русский", callback_data="lang_ru")
    ikb.button(text="🇬🇧 English", callback_data="lang_en")
    await m.answer("🌍 Язык / Language:", reply_markup=ikb.as_markup())

@dp.callback_query(F.data.startswith("lang_"))
async def set_lang(call: types.CallbackQuery):
    l = call.data.split("_")[1]
    cur.execute("UPDATE users SET lang = ? WHERE tg_id = ?", (l, call.from_user.id))
    db.commit()
    await call.message.delete()
    await call.message.answer("✅ Language changed!" if l=='en' else "✅ Язык изменен!", reply_markup=kb(l))

@dp.callback_query(F.data == "ch_alias")
async def ch_alias(call: types.CallbackQuery, state: State):
    u = get_user(call.from_user.id)
    await call.message.answer(T[u[3]]['alias_ask'])
    await state.set_state(State.alias)
    await call.answer()

@dp.callback_query(F.data == "rand_alias")
async def rand_alias(call: types.CallbackQuery):
    u = get_user(call.from_user.id)
    prefixes = ['cool', 'anon', 'shadow', 'mystic', 'star', 'wild']
    for _ in range(5):
        alias = f"{random.choice(prefixes)}_{random.randint(10,999)}"
        if not cur.execute("SELECT id FROM users WHERE alias = ?", (alias,)).fetchone():
            cur.execute("UPDATE users SET alias = ? WHERE tg_id = ?", (alias, call.from_user.id))
            db.commit()
            me = await bot.get_me()
            await call.message.edit_text(T[u[3]]['alias_ok'].format(link=f"t.me/{me.username}?start={alias}"))
            return
    await call.answer("❌ Ошибка", show_alert=True)

@dp.message(State.alias)
async def save_alias(m: types.Message, state: State):
    u = get_user(m.from_user.id)
    alias = m.text.strip().lower()
    if not alias.replace('_', '').isalnum() or len(alias) < 3 or len(alias) > 20:
        return await m.answer(T[u[3]]['alias_bad'])
    if cur.execute("SELECT id FROM users WHERE alias = ? AND tg_id != ?", (alias, m.from_user.id)).fetchone():
        return await m.answer(T[u[3]]['alias_bad'])
    cur.execute("UPDATE users SET alias = ? WHERE tg_id = ?", (alias, m.from_user.id))
    db.commit()
    me = await bot.get_me()
    await m.answer(T[u[3]]['alias_ok'].format(link=f"t.me/{me.username}?start={alias}"))
    await state.clear()

@dp.message(State.txt)
async def send_anon(m: types.Message, state: State):
    u = get_user(m.from_user.id)
    if not u: return await m.answer("🚫 Забанен")
    if not await check_sub(m.from_user.id):
        return await m.answer(T[u[3]]['sub_required'], reply_markup=sub_kb(u[3]))
    data = await state.get_data()
    try:
        res = await m.copy_to(data['t_id'])
        cur.execute("INSERT INTO msgs (s_id, r_id, m_id) VALUES (?, ?, ?)", (m.from_user.id, data['t_id'], res.message_id))
        cur.execute("UPDATE users SET sent = sent + 1 WHERE tg_id = ?", (m.from_user.id,))
        cur.execute("UPDATE users SET rec = rec + 1 WHERE tg_id = ?", (data['t_id'],))
        db.commit()
        add_exp(m.from_user.id)
        ikb = InlineKeyboardBuilder()
        ikb.button(text=T[u[3]]['del'], callback_data=f"del_{cur.lastrowid}")
        await m.answer(T[u[3]]['ok'], reply_markup=ikb.as_markup())
        rkb = InlineKeyboardBuilder()
        rkb.button(text=T[u[3]]['rep'], callback_data=f"rep_{m.from_user.id}")
        await bot.send_message(data['t_id'], T[u[3]]['new'], reply_markup=rkb.as_markup())
    except: await m.answer("❌ Ошибка")
    await state.clear()

@dp.callback_query(F.data.startswith("rep_"))
async def reply_msg(call: types.CallbackQuery, state: State):
    await state.update_data(t_id=int(call.data.split("_")[1]))
    u = get_user(call.from_user.id)
    await call.message.answer(T[u[3]]['go'])
    await state.set_state(State.txt)
    await call.answer()

@dp.callback_query(F.data.startswith("del_"))
async def del_msg(call: types.CallbackQuery):
    mid = call.data.split("_")[1]
    m = cur.execute("SELECT * FROM msgs WHERE id = ?", (mid,)).fetchone()
    if m:
        try: await bot.delete_message(m[2], m[3])
        except: pass
        await call.message.edit_text("🗑 Удалено")

# ============= АДМИНКА =============

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    cnt = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    channels_cnt = cur.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
    ikb = InlineKeyboardBuilder()
    ikb.button(text="📢 Рассылка", callback_data="admin_broadcast")
    ikb.button(text="🔗 Каналы", callback_data="admin_channels")
    ikb.adjust(1)
    await m.answer(f"👑 Админ-панель\n\n👥 Юзеров: {cnt}\n📢 Каналов: {channels_cnt}", reply_markup=ikb.as_markup())

@dp.callback_query(F.data == "admin_channels", F.from_user.id == ADMIN_ID)
async def admin_channels(call: types.CallbackQuery):
    channels = cur.execute("SELECT id, chat_id, link FROM channels").fetchall()
    text = "📢 Обязательные каналы:\n\n" if channels else "📢 Нет каналов\n\n"
    for cid, chat_id, link in channels:
        text += f"• {link}\n"
    ikb = InlineKeyboardBuilder()
    ikb.button(text="➕ Добавить", callback_data="admin_add_channel")
    ikb.button(text="🗑 Удалить все", callback_data="admin_del_channels")
    ikb.button(text="⬅️ Назад", callback_data="admin_back")
    ikb.adjust(1)
    await call.message.edit_text(text, reply_markup=ikb.as_markup())
    await call.answer()

@dp.callback_query(F.data == "admin_add_channel", F.from_user.id == ADMIN_ID)
async def admin_add_channel(call: types.CallbackQuery, state: State):
    await call.message.answer("📢 Отправь ссылку на канал:\nПример: https://t.me/channel")
    await state.set_state(State.add_channel)
    await call.answer()

@dp.message(State.add_channel, F.from_user.id == ADMIN_ID)
async def save_channel(m: types.Message, state: State):
    link = m.text.strip()
    try:
        username = link.split("t.me/")[1].split("?")[0]
        chat = await bot.get_chat(f"@{username}")
        chat_id = chat.id
        cur.execute("INSERT INTO channels (chat_id, link) VALUES (?, ?)", (chat_id, link))
        db.commit()
        await m.answer(f"✅ Канал {link} добавлен!")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")
    await state.clear()

@dp.callback_query(F.data == "admin_del_channels", F.from_user.id == ADMIN_ID)
async def del_channels(call: types.CallbackQuery):
    cur.execute("DELETE FROM channels")
    db.commit()
    await call.message.edit_text("✅ Все каналы удалены")
    await call.answer()

@dp.callback_query(F.data == "admin_broadcast", F.from_user.id == ADMIN_ID)
async def admin_broadcast(call: types.CallbackQuery, state: State):
    await call.message.answer("📢 Перешли сообщение для рассылки:\n/exit - отмена")
    await state.set_state(State.broadcast)
    await call.answer()

@dp.message(State.broadcast, F.from_user.id == ADMIN_ID)
async def do_broadcast(m: types.Message, state: State):
    if m.text == "/exit":
        await state.clear()
        return await m.answer("❌ Отменено")
    users = cur.execute("SELECT tg_id FROM users").fetchall()
    ok = 0
    await m.answer(f"🚀 Рассылка для {len(users)} пользователей...")
    for (uid,) in users:
        try:
            await m.copy_to(uid)
            ok += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await m.answer(f"✅ Готово! Доставлено: {ok}/{len(users)}")
    await state.clear()

@dp.callback_query(F.data == "admin_back", F.from_user.id == ADMIN_ID)
async def admin_back(call: types.CallbackQuery):
    await admin(call.message)

# ============= ЗАПУСК =============
async def main():
    print("🤫 Бот Анонимных Сообщений запущен!")
    print(f"👑 Админ: {ADMIN_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
