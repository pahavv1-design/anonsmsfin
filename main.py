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
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
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
# Новая таблица для каналов
cur.execute("CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id BIGINT, link TEXT)")
db.commit()

class MyStates(StatesGroup):
    txt = State()
    mail = State()
    set_alias = State()
    # Состояния админки
    admin_broadcast = State()
    admin_add_channel = State()

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
        'new_msg': "📬 <b>Вам новое анонимное сообщение!</b>",
        'sub_req': "⚠️ <b>Для использования бота, подпишитесь на наши каналы:</b>"
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
        'new_msg': "📬 <b>You have a new anonymous message!</b>",
        'sub_req': "⚠️ <b>To use the bot, subscribe to our channels:</b>"
    }
}

# --- ФУНКЦИИ ---
def get_u(uid):
    u = cur.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()
    if not u:
        cur.execute("INSERT INTO users (tg_id) VALUES (?)", (uid,))
        db.commit()
        u = cur.execute("SELECT * FROM users WHERE tg_id = ?", (uid,)).fetchone()
    return u

async def check_sub(user_id):
    """Проверка подписки на все обязательные каналы"""
    channels = cur.execute("SELECT chat_id FROM channels").fetchall()
    for (chat_id,) in channels:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception:
            # Если бот не админ в канале или канал не существует
            continue
    return True

# --- КЛАВИАТУРЫ ---
def main_kb(lang):
    kb = ReplyKeyboardBuilder()
    if lang == 'ru':
        kb.button(text="👤 Профиль"), kb.button(text="⚙️ Настройки")
    else:
        kb.button(text="👤 Profile"), kb.button(text="⚙️ Settings")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

def sub_kb(lang):
    """Клавиатура со списком каналов и кнопкой проверки"""
    kb = InlineKeyboardBuilder()
    channels = cur.execute("SELECT chat_id, link FROM channels").fetchall()
    for idx, (chat_id, link) in enumerate(channels, 1):
        kb.button(text=f"Канал {idx}" if lang == 'ru' else f"Channel {idx}", url=link)
    kb.button(text="✅ Проверить" if lang == 'ru' else "✅ Check", callback_data="check_sub")
    kb.adjust(1)
    return kb.as_markup()

def profile_inline(lang, username, uid_or_alias):
    kb = InlineKeyboardBuilder()
    link = f"https://t.me/{username}?start={uid_or_alias}"
    kb.button(text=STR[lang]['share'], switch_inline_query=f"\nНапиши мне анонимно! 👇\n{link}")
    return kb.as_markup()

# --- АДМИН ПАНЕЛЬ ---

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_main(msg: types.Message):
    count = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Рассылка", callback_data="adm_broadcast")
    kb.button(text="🔗 Упр. каналами", callback_data="adm_channels")
    kb.adjust(1)
    await msg.answer(f"👑 <b>Админ-панель</b>\n\nВсего юзеров: <code>{count}</code>", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "adm_broadcast", F.from_user.id == ADMIN_ID)
async def adm_broadcast_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Перешлите сообщение для рассылки (текст, фото, видео и т.д.) или напишите текст.")
    await state.set_state(MyStates.admin_broadcast)
    await call.answer()

@dp.message(MyStates.admin_broadcast, F.from_user.id == ADMIN_ID)
async def adm_broadcast_run(msg: types.Message, state: FSMContext):
    users = cur.execute("SELECT tg_id FROM users").fetchall()
    count = 0
    await msg.answer("🚀 Рассылка запущена...")
    for (uid,) in users:
        try:
            await msg.copy_to(uid)
            count += 1
            await asyncio.sleep(0.05) # Защита от спам-фильтра
        except (TelegramForbiddenError, TelegramBadRequest):
            continue
    await msg.answer(f"✅ Рассылка завершена. Получили: {count} человек.")
    await state.clear()

@dp.callback_query(F.data == "adm_channels", F.from_user.id == ADMIN_ID)
async def adm_channels_list(call: types.CallbackQuery):
    channels = cur.execute("SELECT id, chat_id FROM channels").fetchall()
    text = "🔗 <b>Список каналов для ОП:</b>\n\n"
    kb = InlineKeyboardBuilder()
    for cid, chat_id in channels:
        text += f"ID: <code>{chat_id}</code>\n"
        kb.button(text=f"❌ {chat_id}", callback_data=f"adm_delchan_{cid}")
    
    kb.button(text="➕ Добавить канал", callback_data="adm_addchan")
    kb.button(text="⬅️ Назад", callback_data="adm_back")
    kb.adjust(1)
    await call.message.edit_text(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data == "adm_addchan", F.from_user.id == ADMIN_ID)
async def adm_addchan_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Отправьте ChatID и Ссылку через пробел.\nПример:\n-10012345678 https://t.me/mychannel\n\n<i>Важно: Бот должен быть админом в этом канале!</i>")
    await state.set_state(MyStates.admin_add_channel)
    await call.answer()

@dp.message(MyStates.admin_add_channel, F.from_user.id == ADMIN_ID)
async def adm_addchan_save(msg: types.Message, state: FSMContext):
    try:
        chat_id, link = msg.text.split()
        cur.execute("INSERT INTO channels (chat_id, link) VALUES (?, ?)", (int(chat_id), link))
        db.commit()
        await msg.answer("✅ Канал добавлен!")
        await state.clear()
    except:
        await msg.answer("❌ Ошибка. Введите данные корректно (ID и ссылку).")

@dp.callback_query(F.data.startswith("adm_delchan_"), F.from_user.id == ADMIN_ID)
async def adm_delchan(call: types.CallbackQuery):
    cid = call.data.split("_")[2]
    cur.execute("DELETE FROM channels WHERE id = ?", (cid,))
    db.commit()
    await call.answer("Удалено")
    await adm_channels_list(call)

# --- ОБРАБОТЧИКИ ---

@dp.message(CommandStart())
async def cmd_start(msg: types.Message, state: FSMContext):
    await state.clear()
    u = get_u(msg.from_user.id)
    
    # ПРОВЕРКА ПОДПИСКИ
    if not await check_sub(msg.from_user.id):
        return await msg.answer(STR[u[3]]['sub_req'], reply_markup=sub_kb(u[3]))

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

@dp.callback_query(F.data == "check_sub")
async def callback_check_sub(call: types.CallbackQuery, state: FSMContext):
    u = get_u(call.from_user.id)
    if await check_sub(call.from_user.id):
        await call.message.delete()
        await cmd_start(call.message, state)
    else:
        await call.answer("❌ Вы не подписались на все каналы!", show_alert=True)

@dp.message(MyStates.txt, ~F.text.startswith("/"))
async def handle_anon(msg: types.Message, state: FSMContext):
    # Добавляем проверку подписки даже при отправке сообщения
    if not await check_sub(msg.from_user.id):
        return await msg.answer("⚠️ Сначала подпишитесь на каналы!", reply_markup=sub_kb('ru'))
    
    data = await state.get_data()
    u = get_u(msg.from_user.id)
    try:
        res = await msg.copy_to(data['t_id'])
        cur.execute("INSERT INTO msgs (s_id, r_id, m_id) VALUES (?, ?, ?)", (msg.from_user.id, data['t_id'], res.message_id))
        cur.execute("UPDATE users SET sent = sent + 1 WHERE tg_id = ?", (msg.from_user.id,))
        cur.execute("UPDATE users SET rec = rec + 1 WHERE tg_id = ?", (data['t_id'],))
        db.commit()
        
        kb = InlineKeyboardBuilder()
        kb.button(text=STR[u[3]]['del'], callback_data=f"del_{cur.lastrowid}")
        await msg.answer(STR[u[3]]['ok'], reply_markup=kb.as_markup())
        
        rk = InlineKeyboardBuilder()
        rk.button(text=STR[u[3]]['rep'], callback_data=f"rep_{msg.from_user.id}")
        await bot.send_message(data['t_id'], STR[u[3]]['new_msg'], reply_markup=rk.as_markup())
    except:
        await msg.answer("❌ Ошибка: не удалось отправить.")
    await state.clear()

# --- Остальные обработчики (Profile, Settings и т.д. остаются как были) ---

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
