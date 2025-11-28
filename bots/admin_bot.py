"""
Admin Bot v2.3

Telegram-бот для управления автоответчиком с AI.
Настройка промпта для каждого контакта.

Использование:
    python -m bots.admin_bot
"""
import asyncio
import logging
import os
import sys

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('ADMIN_BOT_TOKEN')
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID')
DATABASE_URL = os.getenv('DATABASE_URL')

ACCOUNT_ID = 1
PEERS_PER_PAGE = 20
DEFAULT_INTERVAL = 0

if not all([BOT_TOKEN, ADMIN_USER_ID, DATABASE_URL]):
    logger.error("Missing required environment variables.")
    sys.exit(1)

try:
    ADMIN_USER_ID = int(ADMIN_USER_ID)
except ValueError:
    logger.error("ADMIN_USER_ID must be a number")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
db_pool = None


class PromptState(StatesGroup):
    waiting_prompt = State()


async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5, command_timeout=60)
    logger.info("Database pool initialized")


async def close_db():
    global db_pool
    if db_pool:
        await db_pool.close()


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID


def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статус", callback_data="status"),
            InlineKeyboardButton(text="📈 Стат", callback_data="stats")
        ],
        [
            InlineKeyboardButton(text="🟢 Авто ON", callback_data="auto_on"),
            InlineKeyboardButton(text="🔴 Авто OFF", callback_data="auto_off")
        ],
        [
            InlineKeyboardButton(text="🤖 AI ON", callback_data="ai_on"),
            InlineKeyboardButton(text="🚫 AI OFF", callback_data="ai_off")
        ],
        [
            InlineKeyboardButton(text="📋 Правила", callback_data="rules"),
            InlineKeyboardButton(text="👥 Контакты", callback_data="peers:0")
        ],
        [
            InlineKeyboardButton(text="🔍 Поиск", callback_data="search_help")
        ]
    ])


def back_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="menu")]
    ])


def peer_settings_keyboard(peer_id: int, has_rule: bool):
    """Клавиатура настроек контакта"""
    keyboard = []
    
    if has_rule:
        keyboard.append([
            InlineKeyboardButton(text="🔴 Выключить", callback_data=f"rule_off:{peer_id}"),
            InlineKeyboardButton(text="✏️ Промпт", callback_data=f"prompt:{peer_id}")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(text="🟢 Включить", callback_data=f"rule_on:{peer_id}")
        ])
    
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="peers:0")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def peers_keyboard(peers: list, offset: int, total: int):
    """Клавиатура со списком контактов"""
    keyboard = []
    
    for i in range(0, len(peers), 2):
        row = []
        for j in range(2):
            if i + j < len(peers):
                p = peers[i + j]
                name = p['first_name'] or p['username'] or "—"
                username = p['username'] or ""
                has_rule = p['has_rule']
                
                status = "✅" if has_rule else "⚪"
                display = f"{name[:8]}"
                if username:
                    display += f"@{username[:6]}"
                btn_text = f"{status}{display}"[:18]
                
                row.append(InlineKeyboardButton(text=btn_text, callback_data=f"peer:{p['id']}"))
        keyboard.append(row)
    
    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"peers:{offset - PEERS_PER_PAGE}"))
    
    page = offset // PEERS_PER_PAGE + 1
    total_pages = (total + PEERS_PER_PAGE - 1) // PEERS_PER_PAGE
    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    
    if offset + PEERS_PER_PAGE < total:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"peers:{offset + PEERS_PER_PAGE}"))
    
    keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton(text="◀️ Меню", callback_data="menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ==================== HANDLERS ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await state.clear()
    await message.answer("🤖 Auto-Reply v2.3", reply_markup=main_menu_keyboard())


@dp.message(Command("help"))
async def cmd_help(message: Message):
    if not is_admin(message.from_user.id):
        return
    text = (
        "📖 Команды\n\n"
        "/find <имя|@user|tg_id> — поиск\n"
        "/add <id|@user|tg_id> — добавить\n"
        "/del <id|@user|tg_id> — удалить\n\n"
        "Нажми на контакт для настройки"
    )
    await message.answer(text, reply_markup=back_button())


async def show_status(target):
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'auto_reply_enabled'")
            auto_on = row and row['value'] == '1'
            
            row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'ai_enabled'")
            ai_on = row and row['value'] == '1'
            
            rules = await conn.fetchval("SELECT COUNT(*) FROM auto_reply_rules WHERE account_id = $1 AND enabled = true", ACCOUNT_ID)
            peers = await conn.fetchval("SELECT COUNT(*) FROM peers WHERE is_bot = false")
            msgs = await conn.fetchval("SELECT COUNT(*) FROM messages")
        
        text = (
            f"📊 Статус\n\n"
            f"{'🟢' if auto_on else '🔴'} Автоответ: {'Вкл' if auto_on else 'Выкл'}\n"
            f"{'🤖' if ai_on else '🚫'} AI: {'Вкл' if ai_on else 'Выкл'}\n\n"
            f"📋 Правил: {rules}\n"
            f"👥 Контактов: {peers}\n"
            f"💬 Сообщений: {msgs}"
        )
        
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=back_button())
        else:
            await target.answer(text, reply_markup=back_button())
    except Exception as e:
        logger.error(f"Error: {e}")


@dp.message(Command("status"))
async def cmd_status(message: Message):
    if is_admin(message.from_user.id):
        await show_status(message)


async def toggle_setting(target, key: str, value: str, text: str):
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES ($1, $2, now())
                ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now()
            """, key, value)
        
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=back_button())
        else:
            await target.answer(text, reply_markup=back_button())
    except Exception as e:
        logger.error(f"Error: {e}")


@dp.message(Command("auto_on"))
async def cmd_auto_on(message: Message):
    if is_admin(message.from_user.id):
        await toggle_setting(message, 'auto_reply_enabled', '1', "🟢 Автоответы включены")


@dp.message(Command("auto_off"))
async def cmd_auto_off(message: Message):
    if is_admin(message.from_user.id):
        await toggle_setting(message, 'auto_reply_enabled', '0', "🔴 Автоответы выключены")


@dp.message(Command("ai_on"))
async def cmd_ai_on(message: Message):
    if is_admin(message.from_user.id):
        await toggle_setting(message, 'ai_enabled', '1', "🤖 AI включен")


@dp.message(Command("ai_off"))
async def cmd_ai_off(message: Message):
    if is_admin(message.from_user.id):
        await toggle_setting(message, 'ai_enabled', '0', "🚫 AI выключен")


async def show_rules(target):
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT p.first_name, p.username, r.template
                FROM auto_reply_rules r
                JOIN peers p ON p.id = r.peer_id
                WHERE r.account_id = $1 AND r.enabled = true
                ORDER BY r.updated_at DESC LIMIT 30
            """, ACCOUNT_ID)
        
        if not rows:
            text = "📋 Нет активных правил"
        else:
            text = f"📋 Активные правила ({len(rows)}):\n\n"
            for r in rows:
                name = r['first_name'] or "—"
                user = f"@{r['username']}" if r['username'] else ""
                prompt = (r['template'] or "—")[:20]
                text += f"✅ {name} {user}\n   📝 {prompt}\n\n"
        
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=back_button())
        else:
            await target.answer(text, reply_markup=back_button())
    except Exception as e:
        logger.error(f"Error: {e}")


@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    if is_admin(message.from_user.id):
        await show_rules(message)


async def show_peers(target, offset: int = 0):
    try:
        async with db_pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM peers WHERE is_bot = false")
            
            rows = await conn.fetch("""
                SELECT 
                    p.id, p.tg_peer_id, p.username, p.first_name,
                    EXISTS(SELECT 1 FROM auto_reply_rules WHERE peer_id = p.id AND account_id = $1 AND enabled = true) as has_rule
                FROM peers p
                WHERE p.is_bot = false
                ORDER BY p.updated_at DESC
                LIMIT $2 OFFSET $3
            """, ACCOUNT_ID, PEERS_PER_PAGE, offset)
        
        peers = [dict(r) for r in rows]
        text = f"👥 Контакты\n\n✅ = автоответ вкл\nНажми для настройки"
        
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=peers_keyboard(peers, offset, total))
        else:
            await target.answer(text, reply_markup=peers_keyboard(peers, offset, total))
    except Exception as e:
        logger.error(f"Error: {e}")


@dp.message(Command("peers"))
async def cmd_peers(message: Message):
    if is_admin(message.from_user.id):
        await show_peers(message, 0)


async def show_peer_settings(target, peer_id: int):
    """Показать настройки конкретного контакта"""
    try:
        async with db_pool.acquire() as conn:
            peer = await conn.fetchrow("""
                SELECT p.id, p.first_name, p.username, p.tg_peer_id,
                       r.enabled, r.template
                FROM peers p
                LEFT JOIN auto_reply_rules r ON r.peer_id = p.id AND r.account_id = $1
                WHERE p.id = $2
            """, ACCOUNT_ID, peer_id)
        
        if not peer:
            if isinstance(target, CallbackQuery):
                await target.answer("❌ Не найден", show_alert=True)
            return
        
        name = peer['first_name'] or "—"
        username = f"@{peer['username']}" if peer['username'] else ""
        tg_id = peer['tg_peer_id']
        has_rule = peer['enabled'] or False
        prompt = peer['template'] or "Не задан"
        
        status = "🟢 Включен" if has_rule else "⚪ Выключен"
        
        text = (
            f"👤 {name} {username}\n"
            f"🆔 TG: {tg_id}\n\n"
            f"Автоответ: {status}\n"
            f"📝 Промпт: {prompt}"
        )
        
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=peer_settings_keyboard(peer_id, has_rule))
        else:
            await target.answer(text, reply_markup=peer_settings_keyboard(peer_id, has_rule))
    except Exception as e:
        logger.error(f"Error: {e}")


@dp.message(Command("find"))
async def cmd_find(message: Message):
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ /find <имя|@user|tg_id>")
        return
    
    query = parts[1].strip().lstrip('@')
    
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    p.id, p.tg_peer_id, p.username, p.first_name,
                    EXISTS(SELECT 1 FROM auto_reply_rules WHERE peer_id = p.id AND account_id = $1 AND enabled = true) as has_rule
                FROM peers p
                WHERE p.is_bot = false AND (
                    p.username ILIKE $2 OR
                    p.first_name ILIKE $2 OR
                    CAST(p.tg_peer_id AS TEXT) = $3
                )
                LIMIT 10
            """, ACCOUNT_ID, f"%{query}%", query)
        
        if not rows:
            await message.answer(f"❌ '{query}' не найден")
            return
        
        keyboard = []
        text = f"🔍 Найдено: {len(rows)}\n\n"
        
        for r in rows:
            name = r['first_name'] or "—"
            user = f"@{r['username']}" if r['username'] else ""
            status = "✅" if r['has_rule'] else "⚪"
            text += f"{status} {name} {user}\n"
            
            btn = f"⚙️ {name} {user}"[:25]
            keyboard.append([InlineKeyboardButton(text=btn, callback_data=f"peer:{r['id']}")])
        
        keyboard.append([InlineKeyboardButton(text="◀️ Меню", callback_data="menu")])
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        
    except Exception as e:
        logger.error(f"Error: {e}")


async def show_stats(target):
    try:
        async with db_pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM messages")
            today = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE date >= CURRENT_DATE")
            auto = await conn.fetchval("SELECT COUNT(*) FROM auto_reply_state WHERE last_reply_time >= CURRENT_DATE")
        
        text = f"📈 Статистика\n\n💬 Сообщений: {total}\n📅 Сегодня: {today}\n🤖 Автоответов: {auto or 0}"
        
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=back_button())
        else:
            await target.answer(text, reply_markup=back_button())
    except Exception as e:
        logger.error(f"Error: {e}")


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if is_admin(message.from_user.id):
        await show_stats(message)


# ==================== FSM: Ввод промпта ====================

@dp.message(PromptState.waiting_prompt)
async def process_prompt(message: Message, state: FSMContext):
    """Обработка введённого промпта"""
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    peer_id = data.get('peer_id')
    
    if not peer_id:
        await state.clear()
        await message.answer("❌ Ошибка, попробуйте снова")
        return
    
    prompt = message.text.strip()
    
    try:
        async with db_pool.acquire() as conn:
            # Обновляем или создаём правило
            await conn.execute("""
                INSERT INTO auto_reply_rules (account_id, peer_id, enabled, template, min_interval_sec)
                VALUES ($1, $2, true, $3, $4)
                ON CONFLICT (account_id, peer_id) DO UPDATE SET 
                    template = $3, updated_at = now()
            """, ACCOUNT_ID, peer_id, prompt, DEFAULT_INTERVAL)
            
            peer = await conn.fetchrow("SELECT first_name, username FROM peers WHERE id = $1", peer_id)
        
        name = peer['first_name'] if peer else str(peer_id)
        await state.clear()
        await message.answer(f"✅ Промпт для {name} сохранён:\n\n📝 {prompt}", reply_markup=back_button())
        logger.info(f"Prompt set for peer {peer_id}: {prompt[:30]}")
        
    except Exception as e:
        logger.error(f"Error saving prompt: {e}")
        await state.clear()
        await message.answer(f"❌ Ошибка: {e}")


# ==================== CALLBACKS ====================

@dp.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text("🤖 Auto-Reply v2.3", reply_markup=main_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data == "status")
async def cb_status(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        await show_status(callback)
        await callback.answer()


@dp.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        await show_stats(callback)
        await callback.answer()


@dp.callback_query(F.data == "auto_on")
async def cb_auto_on(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        await toggle_setting(callback, 'auto_reply_enabled', '1', "🟢 Автоответы включены")
        await callback.answer("✅")


@dp.callback_query(F.data == "auto_off")
async def cb_auto_off(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        await toggle_setting(callback, 'auto_reply_enabled', '0', "🔴 Автоответы выключены")
        await callback.answer("✅")


@dp.callback_query(F.data == "ai_on")
async def cb_ai_on(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        await toggle_setting(callback, 'ai_enabled', '1', "🤖 AI включен")
        await callback.answer("✅")


@dp.callback_query(F.data == "ai_off")
async def cb_ai_off(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        await toggle_setting(callback, 'ai_enabled', '0', "🚫 AI выключен")
        await callback.answer("✅")


@dp.callback_query(F.data == "rules")
async def cb_rules(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        await show_rules(callback)
        await callback.answer()


@dp.callback_query(F.data.startswith("peers:"))
async def cb_peers(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        offset = int(callback.data.split(":")[1])
        await show_peers(callback, offset)
        await callback.answer()


@dp.callback_query(F.data.startswith("peer:"))
async def cb_peer(callback: CallbackQuery):
    """Открыть настройки контакта"""
    if is_admin(callback.from_user.id):
        peer_id = int(callback.data.split(":")[1])
        await show_peer_settings(callback, peer_id)
        await callback.answer()


@dp.callback_query(F.data.startswith("rule_on:"))
async def cb_rule_on(callback: CallbackQuery):
    """Включить автоответ для контакта"""
    if not is_admin(callback.from_user.id):
        return
    
    peer_id = int(callback.data.split(":")[1])
    
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO auto_reply_rules (account_id, peer_id, enabled, template, min_interval_sec)
                VALUES ($1, $2, true, 'Сейчас занят', $3)
                ON CONFLICT (account_id, peer_id) DO UPDATE SET enabled = true, updated_at = now()
            """, ACCOUNT_ID, peer_id, DEFAULT_INTERVAL)
        
        await callback.answer("✅ Включено", show_alert=True)
        await show_peer_settings(callback, peer_id)
    except Exception as e:
        logger.error(f"Error: {e}")


@dp.callback_query(F.data.startswith("rule_off:"))
async def cb_rule_off(callback: CallbackQuery):
    """Выключить автоответ для контакта"""
    if not is_admin(callback.from_user.id):
        return
    
    peer_id = int(callback.data.split(":")[1])
    
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE auto_reply_rules SET enabled = false, updated_at = now()
                WHERE account_id = $1 AND peer_id = $2
            """, ACCOUNT_ID, peer_id)
        
        await callback.answer("🔴 Выключено", show_alert=True)
        await show_peer_settings(callback, peer_id)
    except Exception as e:
        logger.error(f"Error: {e}")


@dp.callback_query(F.data.startswith("prompt:"))
async def cb_prompt(callback: CallbackQuery, state: FSMContext):
    """Начать ввод промпта"""
    if not is_admin(callback.from_user.id):
        return
    
    peer_id = int(callback.data.split(":")[1])
    
    await state.set_state(PromptState.waiting_prompt)
    await state.update_data(peer_id=peer_id)
    
    await callback.message.edit_text(
        "✏️ Введите промпт для этого контакта:\n\n"
        "Примеры:\n"
        "• Отвечай коротко и дерзко\n"
        "• Будь вежлив и формален\n"
        "• Отвечай с юмором\n\n"
        "Или /start для отмены"
    )
    await callback.answer()


@dp.callback_query(F.data == "search_help")
async def cb_search_help(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        text = "🔍 Поиск\n\n/find <имя|@user|tg_id>"
        await callback.message.edit_text(text, reply_markup=back_button())
        await callback.answer()


@dp.message()
async def unknown(message: Message, state: FSMContext):
    if is_admin(message.from_user.id):
        current_state = await state.get_state()
        if current_state is None:
            await message.answer("❓ /start", reply_markup=back_button())


async def main():
    logger.info("Admin Bot v2.3")
    await init_db()
    try:
        await dp.start_polling(bot)
    finally:
        await close_db()
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
