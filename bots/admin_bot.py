"""
Admin Bot v3.3

Telegram-бот для управления автоответчиком с AI.
Настройка промпта и режима (AI/Template/Off) для каждого контакта.
Выбор AI движка (local/claude).
Синхронизация папки Personal.
Автоответ для новых контактов.
Карточки контактов с аватарами.

Использование:
    python -m bots.admin_bot
"""
import asyncio
import io
import logging
import os
import sys
from pathlib import Path

import asyncpg
from aiogram import Bot, Dispatcher, F
from telethon import TelegramClient
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import User
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputFile, FSInputFile, BufferedInputFile
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

# Telethon для синхронизации Personal
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
SESSION_DIR = Path(__file__).parent.parent / "sessions"
SESSION_PATH = str(SESSION_DIR / "worker")

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
telethon_client = None


class PromptState(StatesGroup):
    waiting_prompt = State()


class SystemPromptState(StatesGroup):
    waiting_system_prompt = State()


class NewContactState(StatesGroup):
    waiting_template = State()
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
            InlineKeyboardButton(text="⚙️ AI настройки", callback_data="ai_settings")
        ],
        [
            InlineKeyboardButton(text="📇 Синхронизация", callback_data="sync_personal"),
            InlineKeyboardButton(text="👤 Новые контакты", callback_data="newcontact_settings")
        ],
        [
            InlineKeyboardButton(text="🔍 Поиск", callback_data="search_help")
        ]
    ])


def back_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="menu")]
    ])


def ai_settings_keyboard(current_engine: str):
    """Клавиатура настроек AI"""
    local_icon = "✅" if current_engine == "local" else "⚪"
    claude_icon = "✅" if current_engine == "claude" else "⚪"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"{local_icon} Local", callback_data="engine:local"),
            InlineKeyboardButton(text=f"{claude_icon} Claude", callback_data="engine:claude")
        ],
        [
            InlineKeyboardButton(text="📝 System Prompt", callback_data="sys_prompt"),
            InlineKeyboardButton(text="🌡️ Temperature", callback_data="temp_menu")
        ],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="menu")]
    ])


def temp_keyboard(current_temp: float):
    """Клавиатура выбора температуры"""
    temps = [0.3, 0.5, 0.7, 0.9, 1.2]
    keyboard = []
    row = []
    for t in temps:
        icon = "✅" if abs(current_temp - t) < 0.05 else "⚪"
        row.append(InlineKeyboardButton(text=f"{icon} {t}", callback_data=f"temp:{t}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="ai_settings")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def newcontact_settings_keyboard(current_mode: str):
    """Клавиатура настроек для новых контактов"""
    mode_labels = {
        'off': '⚫ OFF',
        'template': '📝 Template',
        'ai': '🤖 AI'
    }

    mode_row = []
    for mode, label in mode_labels.items():
        icon = "✅" if current_mode == mode else "⚪"
        text = f"{icon} {label.split()[1]}" if icon == "✅" else label
        mode_row.append(InlineKeyboardButton(text=text, callback_data=f"nc_mode:{mode}"))

    return InlineKeyboardMarkup(inline_keyboard=[
        mode_row,
        [
            InlineKeyboardButton(text="✏️ Шаблон", callback_data="nc_template"),
            InlineKeyboardButton(text="📝 AI Промпт", callback_data="nc_prompt")
        ],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="menu")]
    ])


def peer_settings_keyboard(peer_id: int, has_rule: bool, in_personal: bool = False, reply_mode: str = None):
    """Клавиатура настроек контакта с выбором режима"""
    keyboard = []

    if has_rule and reply_mode:
        # Есть правило — показываем выбор режима
        mode_icons = {'ai': '🤖', 'template': '📝', 'off': '⚫'}
        mode_row = []
        for mode in ['ai', 'template', 'off']:
            icon = mode_icons[mode]
            is_active = (reply_mode == mode)
            text = f"{'✅' if is_active else icon} {mode.upper()}"
            mode_row.append(InlineKeyboardButton(text=text, callback_data=f"mode:{peer_id}:{mode}"))
        keyboard.append(mode_row)

        # Кнопка редактирования промпта
        keyboard.append([
            InlineKeyboardButton(text="✏️ Редактировать промпт", callback_data=f"prompt:{peer_id}")
        ])
    else:
        # Нет правила — показываем кнопку включения
        keyboard.append([
            InlineKeyboardButton(text="🟢 Включить автоответ", callback_data=f"rule_on:{peer_id}")
        ])

    # Статус Personal
    status_icon = "📍" if in_personal else "👤"
    status_text = "Personal" if in_personal else "Новый"
    keyboard.append([
        InlineKeyboardButton(text=f"{status_icon} {status_text}", callback_data="noop"),
        InlineKeyboardButton(text="🔄", callback_data=f"peer:{peer_id}")
    ])

    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="peers:0")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def peers_keyboard(peers: list, offset: int, total: int, max_new: int = 5):
    """Клавиатура со списком контактов с индикаторами"""
    keyboard = []

    for i in range(0, len(peers), 2):
        row = []
        for j in range(2):
            if i + j < len(peers):
                p = peers[i + j]
                name = p['first_name'] or p['username'] or "—"
                has_rule = p['has_rule']
                in_personal = p.get('in_personal', False)
                new_replies = p.get('new_replies', 0)

                # Формируем индикатор
                if has_rule:
                    if in_personal:
                        icon = "✅📍"  # правило + Personal
                    else:
                        icon = "✅👤"  # правило, но не в Personal
                else:
                    if in_personal:
                        icon = "⚪📍"  # нет правила, в Personal
                    else:
                        icon = f"⚪👤({new_replies}/{max_new})"  # новый контакт

                # Короткое имя
                display_name = name[:10]
                btn_text = f"{icon}{display_name}"[:20]

                row.append(InlineKeyboardButton(text=btn_text, callback_data=f"peer:{p['id']}"))
        if row:
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
    keyboard.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"peers:{offset}"),
        InlineKeyboardButton(text="◀️ Меню", callback_data="menu")
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ==================== HELPERS ====================

async def get_ai_settings() -> dict:
    """Получить текущие AI настройки из БД"""
    settings = {
        'ai_engine': 'local',
        'system_prompt': 'Ты Егор. Отвечаешь коротко, живо, по делу.',
        'temperature': 0.7,
        'max_tokens': 100
    }
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT key, value FROM settings
                WHERE key IN ('ai_engine', 'system_prompt', 'temperature', 'max_tokens')
            """)
            for row in rows:
                key = row['key']
                value = row['value']
                if key == 'temperature':
                    settings[key] = float(value)
                elif key == 'max_tokens':
                    settings[key] = int(value)
                else:
                    settings[key] = value
    except Exception as e:
        logger.error(f"Error getting AI settings: {e}")
    return settings


async def set_ai_setting(key: str, value: str):
    """Установить AI настройку в БД"""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES ($1, $2, now())
                ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now()
            """, key, value)
        logger.info(f"AI setting updated: {key}={value[:30]}...")
    except Exception as e:
        logger.error(f"Error setting AI setting: {e}")
        raise




# ==================== HANDLERS ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await state.clear()
    await message.answer("🤖 Auto-Reply v3.0", reply_markup=main_menu_keyboard())


@dp.message(Command("help"))
async def cmd_help(message: Message):
    if not is_admin(message.from_user.id):
        return
    text = (
        "📖 Команды\n\n"
        "/find <имя|@user|tg_id> — поиск\n"
        "/sync — синхронизировать Personal\n"
        "/newcontact — настройка для новых\n"
        "/engine — AI движок\n"
        "/prompt — system prompt\n"
        "/temp — temperature\n\n"
        "Нажми на контакт для настройки"
    )
    await message.answer(text, reply_markup=back_button())


@dp.message(Command("sync"))
async def cmd_sync(message: Message):
    """Перезапустить worker для синхронизации Personal"""
    if not is_admin(message.from_user.id):
        return

    status_msg = await message.answer("🔄 Перезапуск worker для синхронизации...")

    try:
        import subprocess
        result = subprocess.run(
            ["/usr/bin/sudo", "/usr/bin/systemctl", "restart", "worker"],
            capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            await status_msg.edit_text(
                "✅ Worker перезапущен!\n"
                "Синхронизация Personal выполняется при запуске.",
                reply_markup=back_button()
            )
        else:
            await status_msg.edit_text(
                f"❌ Ошибка перезапуска:\n{result.stderr}",
                reply_markup=back_button()
            )
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {e}", reply_markup=back_button())


# ==================== NEW CONTACT COMMANDS ====================

async def get_new_contact_settings() -> dict:
    """Получить настройки для новых контактов"""
    settings = {
        'new_contact_mode': 'off',
        'new_contact_template': 'Привет! Напомни откуда мы знакомы?',
        'new_contact_prompt': 'Незнакомый человек. Вежливо спроси кто это.'
    }
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT key, value FROM settings
                WHERE key IN ('new_contact_mode', 'new_contact_template', 'new_contact_prompt')
            """)
            for row in rows:
                settings[row['key']] = row['value']
    except Exception as e:
        logger.error(f"Error getting new contact settings: {e}")
    return settings


@dp.message(Command("newcontact"))
async def cmd_newcontact(message: Message, state: FSMContext):
    """Настройка автоответа для новых контактов"""
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    settings = await get_new_contact_settings()
    mode = settings['new_contact_mode']

    if len(parts) < 2:
        # Показать текущие настройки
        mode_icons = {'off': '🔴', 'template': '📝', 'ai': '🤖'}
        mode_names = {'off': 'Выключено', 'template': 'Шаблон', 'ai': 'AI ответ'}

        text = (
            f"👤 Новые контакты\n\n"
            f"Режим: {mode_icons.get(mode, '❓')} {mode_names.get(mode, mode)}\n\n"
        )

        if mode == 'template':
            text += f"📝 Шаблон:\n{settings['new_contact_template']}\n\n"
        elif mode == 'ai':
            text += f"🤖 AI промпт:\n{settings['new_contact_prompt']}\n\n"

        text += (
            "Изменить:\n"
            "/newcontact off — выключить\n"
            "/newcontact template — шаблон\n"
            "/newcontact ai — AI ответ"
        )
        await message.answer(text, reply_markup=back_button())
        return

    # Изменить режим
    new_mode = parts[1].strip().lower()

    if new_mode == 'off':
        await set_ai_setting('new_contact_mode', 'off')
        await message.answer("🔴 Автоответ для новых контактов выключен", reply_markup=back_button())

    elif new_mode == 'template':
        await state.set_state(NewContactState.waiting_template)
        current_template = settings['new_contact_template']
        await message.answer(
            f"📝 Введите шаблон ответа для новых контактов:\n\n"
            f"Текущий: {current_template}\n\n"
            f"Или /start для отмены"
        )

    elif new_mode == 'ai':
        await set_ai_setting('new_contact_mode', 'ai')
        await message.answer(
            f"🤖 AI режим для новых контактов включён\n\n"
            f"Промпт: {settings['new_contact_prompt']}\n\n"
            f"Изменить промпт: /newprompt <текст>",
            reply_markup=back_button()
        )

    else:
        await message.answer("❌ Доступные режимы: off, template, ai")


@dp.message(Command("newprompt"))
async def cmd_newprompt(message: Message):
    """Изменить AI промпт для новых контактов"""
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        settings = await get_new_contact_settings()
        await message.answer(
            f"🤖 AI промпт для новых контактов\n\n"
            f"Текущий: {settings['new_contact_prompt']}\n\n"
            f"Изменить: /newprompt <текст>",
            reply_markup=back_button()
        )
    else:
        new_prompt = parts[1].strip()
        await set_ai_setting('new_contact_prompt', new_prompt)
        await message.answer(f"✅ AI промпт обновлён:\n\n{new_prompt}", reply_markup=back_button())


@dp.message(NewContactState.waiting_template)
async def process_new_contact_template(message: Message, state: FSMContext):
    """Обработка введённого шаблона для новых контактов"""
    if not is_admin(message.from_user.id):
        return

    template = message.text.strip()

    try:
        await set_ai_setting('new_contact_template', template)
        await set_ai_setting('new_contact_mode', 'template')
        await state.clear()
        await message.answer(
            f"✅ Шаблон для новых контактов сохранён:\n\n📝 {template}",
            reply_markup=back_button()
        )
    except Exception as e:
        logger.error(f"Error saving template: {e}")
        await state.clear()
        await message.answer(f"❌ Ошибка: {e}")


# ==================== AI SETTINGS COMMANDS ====================

@dp.message(Command("engine"))
async def cmd_engine(message: Message):
    """Показать/изменить AI движок"""
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        # Показать текущий движок
        settings = await get_ai_settings()
        engine = settings['ai_engine']
        engine_name = "🖥️ Local (SambaLingo)" if engine == "local" else "☁️ Claude API"
        await message.answer(
            f"⚙️ AI движок\n\nТекущий: {engine_name}\n\n"
            f"Изменить:\n/engine local — локальный\n/engine claude — Claude API",
            reply_markup=back_button()
        )
    else:
        # Изменить движок
        new_engine = parts[1].strip().lower()
        if new_engine not in ('local', 'claude'):
            await message.answer("❌ Доступные значения: local, claude")
            return

        await set_ai_setting('ai_engine', new_engine)
        engine_name = "🖥️ Local (SambaLingo)" if new_engine == "local" else "☁️ Claude API"
        await message.answer(f"✅ AI движок изменён на: {engine_name}", reply_markup=back_button())


@dp.message(Command("prompt"))
async def cmd_prompt_global(message: Message, state: FSMContext):
    """Показать/изменить глобальный system prompt"""
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        # Показать текущий промпт
        settings = await get_ai_settings()
        prompt = settings['system_prompt']
        await message.answer(
            f"📝 System Prompt\n\nТекущий:\n{prompt}\n\n"
            f"Изменить:\n/prompt <новый промпт>",
            reply_markup=back_button()
        )
    else:
        # Изменить промпт
        new_prompt = parts[1].strip()
        await set_ai_setting('system_prompt', new_prompt)
        await message.answer(f"✅ System prompt обновлён:\n\n{new_prompt}", reply_markup=back_button())


@dp.message(Command("temp"))
async def cmd_temp(message: Message):
    """Показать/изменить temperature"""
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        # Показать текущую температуру
        settings = await get_ai_settings()
        temp = settings['temperature']
        await message.answer(
            f"🌡️ Temperature\n\nТекущая: {temp}\n\n"
            f"Изменить:\n/temp <0.0-2.0>\n\nПримеры:\n"
            f"• 0.3 — более предсказуемые ответы\n"
            f"• 0.7 — баланс (по умолчанию)\n"
            f"• 1.2 — более креативные ответы",
            reply_markup=back_button()
        )
    else:
        # Изменить температуру
        try:
            new_temp = float(parts[1].strip())
            if not 0.0 <= new_temp <= 2.0:
                raise ValueError("Out of range")
            await set_ai_setting('temperature', str(new_temp))
            await message.answer(f"✅ Temperature установлена: {new_temp}", reply_markup=back_button())
        except ValueError:
            await message.answer("❌ Введите число от 0.0 до 2.0")


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

        # Добавляем AI настройки в статус
        ai_settings = await get_ai_settings()
        engine = ai_settings['ai_engine']
        engine_name = "Local" if engine == "local" else "Claude"
        temp = ai_settings['temperature']

        text = (
            f"📊 Статус\n\n"
            f"{'🟢' if auto_on else '🔴'} Автоответ: {'Вкл' if auto_on else 'Выкл'}\n"
            f"{'🤖' if ai_on else '🚫'} AI: {'Вкл' if ai_on else 'Выкл'}\n"
            f"⚙️ Движок: {engine_name}\n"
            f"🌡️ Temp: {temp}\n\n"
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


async def get_new_contact_limits() -> dict:
    """Получить лимиты для новых контактов"""
    limits = {'new_contact_max_replies': 5, 'daily_max_replies': 50}
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT key, value FROM settings
                WHERE key IN ('new_contact_max_replies', 'daily_max_replies')
            """)
            for row in rows:
                try:
                    limits[row['key']] = int(row['value'])
                except ValueError:
                    pass
    except Exception as e:
        logger.error(f"Error getting limits: {e}")
    return limits


async def show_peers(target, offset: int = 0):
    try:
        limits = await get_new_contact_limits()
        max_new = limits['new_contact_max_replies']

        async with db_pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM peers WHERE is_bot = false")

            rows = await conn.fetch("""
                SELECT
                    p.id, p.tg_peer_id, p.username, p.first_name, p.in_personal,
                    EXISTS(SELECT 1 FROM auto_reply_rules WHERE peer_id = p.id AND account_id = $1 AND enabled = true) as has_rule,
                    COALESCE(rc.new_contact_replies, 0) as new_replies
                FROM peers p
                LEFT JOIN reply_counts rc ON rc.peer_id = p.id
                WHERE p.is_bot = false
                ORDER BY p.updated_at DESC
                LIMIT $2 OFFSET $3
            """, ACCOUNT_ID, PEERS_PER_PAGE, offset)

        peers = [dict(r) for r in rows]
        text = (
            f"👥 Контакты\n\n"
            f"✅📍 правило + Personal\n"
            f"⚪📍 нет правила, Personal\n"
            f"⚪👤 новый контакт (N/{max_new})"
        )

        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=peers_keyboard(peers, offset, total, max_new))
        else:
            await target.answer(text, reply_markup=peers_keyboard(peers, offset, total, max_new))
    except Exception as e:
        logger.error(f"Error: {e}")


@dp.message(Command("peers"))
async def cmd_peers(message: Message):
    if is_admin(message.from_user.id):
        await show_peers(message, 0)


async def show_peer_settings(target, peer_id: int):
    """Показать карточку контакта с детальной информацией и фото"""
    try:
        limits = await get_new_contact_limits()
        max_new = limits['new_contact_max_replies']
        max_daily = limits['daily_max_replies']

        async with db_pool.acquire() as conn:
            peer = await conn.fetchrow("""
                SELECT p.id, p.first_name, p.username, p.tg_peer_id, p.in_personal,
                       r.enabled, r.template, COALESCE(r.reply_mode, 'ai') as reply_mode,
                       COALESCE(rc.new_contact_replies, 0) as new_replies,
                       COALESCE(rc.daily_replies, 0) as daily_replies
                FROM peers p
                LEFT JOIN auto_reply_rules r ON r.peer_id = p.id AND r.account_id = $1
                LEFT JOIN reply_counts rc ON rc.peer_id = p.id
                WHERE p.id = $2
            """, ACCOUNT_ID, peer_id)

        if not peer:
            if isinstance(target, CallbackQuery):
                await target.answer("Не найден", show_alert=True)
            return

        name = peer['first_name'] or "—"
        username = f"@{peer['username']}" if peer['username'] else ""
        tg_id = peer['tg_peer_id']
        has_rule = peer['enabled'] or False
        in_personal = peer['in_personal'] or False
        prompt = peer['template'] or "Не задан"
        reply_mode = peer['reply_mode'] if has_rule else None
        new_replies = peer['new_replies']
        daily_replies = peer['daily_replies']

        # Режим ответа - если нет правила, показываем "Выключен"
        if has_rule:
            mode_labels = {'ai': '🤖 AI', 'template': '📝 Шаблон', 'off': '⚫ Выкл'}
            mode_status = mode_labels.get(reply_mode, reply_mode)
        else:
            mode_status = "⚪ Выключен"

        # Статус контакта
        if in_personal:
            contact_status = "📍 В папке Personal"
        else:
            contact_status = f"👤 Новый контакт ({new_replies}/{max_new})"

        # Формируем карточку
        text = (
            f"<b>👤 {name}</b> {username}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🆔 TG ID: <code>{tg_id}</code>\n"
            f"{contact_status}\n\n"
            f"<b>Режим:</b> {mode_status}\n"
            f"📝 Промпт: {prompt[:50]}{'...' if len(prompt) > 50 else ''}\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"   Сегодня: {daily_replies}/{max_daily}\n"
        )

        if not in_personal:
            text += f"   Как новый: {new_replies}/{max_new}\n"

        keyboard = peer_settings_keyboard(peer_id, has_rule, in_personal, reply_mode)

        # Пробуем скачать фото через Telethon
        photo_bytes = None
        if telethon_client and telethon_client.is_connected():
            try:
                photo_bytes = await telethon_client.download_profile_photo(tg_id, file=bytes)
            except Exception as e:
                logger.debug(f"Failed to download photo for {tg_id}: {e}")

        if isinstance(target, CallbackQuery):
            # Удаляем старое сообщение и отправляем новое с фото
            try:
                await target.message.delete()
            except:
                pass

            if photo_bytes:
                photo_file = BufferedInputFile(photo_bytes, filename="avatar.jpg")
                await bot.send_photo(
                    chat_id=target.message.chat.id,
                    photo=photo_file,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                await bot.send_message(
                    chat_id=target.message.chat.id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
        else:
            if photo_bytes:
                photo_file = BufferedInputFile(photo_bytes, filename="avatar.jpg")
                await target.answer_photo(
                    photo=photo_file,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                await target.answer(
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
    except Exception as e:
        logger.error(f"Error in show_peer_settings: {e}")
        import traceback
        traceback.print_exc()


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


# ==================== FSM: Ввод промпта для контакта ====================

@dp.message(PromptState.waiting_prompt)
async def process_prompt(message: Message, state: FSMContext):
    """Обработка введённого промпта для контакта"""
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


# ==================== FSM: Ввод system prompt ====================

@dp.message(SystemPromptState.waiting_system_prompt)
async def process_system_prompt(message: Message, state: FSMContext):
    """Обработка введённого system prompt"""
    if not is_admin(message.from_user.id):
        return

    new_prompt = message.text.strip()

    try:
        await set_ai_setting('system_prompt', new_prompt)
        await state.clear()
        await message.answer(f"✅ System prompt обновлён:\n\n{new_prompt}", reply_markup=back_button())
    except Exception as e:
        logger.error(f"Error saving system prompt: {e}")
        await state.clear()
        await message.answer(f"❌ Ошибка: {e}")


# ==================== CALLBACKS ====================

@dp.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text("🤖 Auto-Reply v3.3", reply_markup=main_menu_keyboard())
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


@dp.callback_query(F.data.startswith("mode:"))
async def cb_mode(callback: CallbackQuery):
    """Изменить режим ответа для контакта (ai/template/off)"""
    if not is_admin(callback.from_user.id):
        return

    parts = callback.data.split(":")
    peer_id = int(parts[1])
    new_mode = parts[2]

    mode_labels = {'ai': '🤖 AI', 'template': '📝 Шаблон', 'off': '⚫ Выкл'}

    try:
        async with db_pool.acquire() as conn:
            # Создаём правило если нет, или обновляем режим
            await conn.execute("""
                INSERT INTO auto_reply_rules (account_id, peer_id, enabled, template, reply_mode, min_interval_sec)
                VALUES ($1, $2, true, 'Отвечай коротко', $3, 0)
                ON CONFLICT (account_id, peer_id) DO UPDATE SET
                    reply_mode = $3,
                    enabled = true,
                    updated_at = now()
            """, ACCOUNT_ID, peer_id, new_mode)

        await callback.answer(f"✅ Режим: {mode_labels.get(new_mode, new_mode)}", show_alert=True)
        await show_peer_settings(callback, peer_id)
    except Exception as e:
        logger.error(f"Error setting mode: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@dp.callback_query(F.data.startswith("prompt:"))
async def cb_prompt(callback: CallbackQuery, state: FSMContext):
    """Начать ввод промпта для контакта"""
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


# ==================== AI SETTINGS CALLBACKS ====================

@dp.callback_query(F.data == "ai_settings")
async def cb_ai_settings(callback: CallbackQuery):
    """Показать настройки AI"""
    if not is_admin(callback.from_user.id):
        return

    settings = await get_ai_settings()
    engine = settings['ai_engine']
    engine_name = "🖥️ Local (SambaLingo)" if engine == "local" else "☁️ Claude API"
    temp = settings['temperature']
    prompt = settings['system_prompt'][:50] + "..." if len(settings['system_prompt']) > 50 else settings['system_prompt']

    text = (
        f"⚙️ AI Настройки\n\n"
        f"Движок: {engine_name}\n"
        f"🌡️ Temperature: {temp}\n"
        f"📝 Prompt: {prompt}"
    )

    await callback.message.edit_text(text, reply_markup=ai_settings_keyboard(engine))
    await callback.answer()


@dp.callback_query(F.data.startswith("engine:"))
async def cb_engine(callback: CallbackQuery):
    """Изменить AI движок"""
    if not is_admin(callback.from_user.id):
        return

    new_engine = callback.data.split(":")[1]
    await set_ai_setting('ai_engine', new_engine)

    engine_name = "🖥️ Local (SambaLingo)" if new_engine == "local" else "☁️ Claude API"
    await callback.answer(f"✅ Движок: {engine_name}", show_alert=True)

    # Обновляем меню
    settings = await get_ai_settings()
    temp = settings['temperature']
    prompt = settings['system_prompt'][:50] + "..." if len(settings['system_prompt']) > 50 else settings['system_prompt']

    text = (
        f"⚙️ AI Настройки\n\n"
        f"Движок: {engine_name}\n"
        f"🌡️ Temperature: {temp}\n"
        f"📝 Prompt: {prompt}"
    )

    await callback.message.edit_text(text, reply_markup=ai_settings_keyboard(new_engine))


@dp.callback_query(F.data == "sys_prompt")
async def cb_sys_prompt(callback: CallbackQuery, state: FSMContext):
    """Показать/изменить system prompt"""
    if not is_admin(callback.from_user.id):
        return

    settings = await get_ai_settings()
    prompt = settings['system_prompt']

    await state.set_state(SystemPromptState.waiting_system_prompt)

    await callback.message.edit_text(
        f"📝 System Prompt\n\nТекущий:\n{prompt}\n\n"
        f"Введите новый промпт или /start для отмены"
    )
    await callback.answer()


@dp.callback_query(F.data == "temp_menu")
async def cb_temp_menu(callback: CallbackQuery):
    """Меню выбора температуры"""
    if not is_admin(callback.from_user.id):
        return

    settings = await get_ai_settings()
    temp = settings['temperature']

    text = (
        f"🌡️ Temperature\n\n"
        f"Текущая: {temp}\n\n"
        f"• Низкая (0.3) — предсказуемые ответы\n"
        f"• Средняя (0.7) — баланс\n"
        f"• Высокая (1.2) — креативные ответы"
    )

    await callback.message.edit_text(text, reply_markup=temp_keyboard(temp))
    await callback.answer()


@dp.callback_query(F.data.startswith("temp:"))
async def cb_temp(callback: CallbackQuery):
    """Изменить температуру"""
    if not is_admin(callback.from_user.id):
        return

    new_temp = float(callback.data.split(":")[1])
    await set_ai_setting('temperature', str(new_temp))

    await callback.answer(f"✅ Temperature: {new_temp}", show_alert=True)

    text = (
        f"🌡️ Temperature\n\n"
        f"Текущая: {new_temp}\n\n"
        f"• Низкая (0.3) — предсказуемые ответы\n"
        f"• Средняя (0.7) — баланс\n"
        f"• Высокая (1.2) — креативные ответы"
    )

    await callback.message.edit_text(text, reply_markup=temp_keyboard(new_temp))


# ============ Синхронизация Personal ============

@dp.callback_query(F.data == "sync_personal")
async def cb_sync_personal(callback: CallbackQuery):
    """Показать статус синхронизации Personal (синхронизацию делает worker)"""
    if not is_admin(callback.from_user.id):
        return

    await callback.answer()

    try:
        async with db_pool.acquire() as conn:
            # Статистика из БД
            in_personal = await conn.fetchval("SELECT COUNT(*) FROM peers WHERE in_personal = true")
            total_peers = await conn.fetchval("SELECT COUNT(*) FROM peers")
            with_rules = await conn.fetchval(
                "SELECT COUNT(DISTINCT peer_id) FROM auto_reply_rules WHERE enabled = true"
            )

        text = (
            "📇 <b>Синхронизация Personal</b>\n\n"
            f"👥 В папке Personal: <b>{in_personal}</b>\n"
            f"📊 Всего в БД: <b>{total_peers}</b>\n"
            f"📋 С активными правилами: <b>{with_rules}</b>\n\n"
            "ℹ️ <i>Worker автоматически синхронизирует\n"
            "папку Personal каждый час.\n\n"
            "Для принудительной синхронизации\n"
            "перезапустите worker.</i>"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Перезапустить Worker", callback_data="restart_worker")],
            [InlineKeyboardButton(text="◀️ Меню", callback_data="menu")]
        ])

        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Sync status error: {e}")
        await callback.message.edit_text(f"❌ Ошибка: {e}", reply_markup=back_button())


@dp.callback_query(F.data == "restart_worker")
async def cb_restart_worker(callback: CallbackQuery):
    """Перезапуск worker сервиса"""
    if not is_admin(callback.from_user.id):
        return

    await callback.answer("🔄 Перезапуск...")

    try:
        import subprocess
        result = subprocess.run(
            ["/usr/bin/sudo", "/usr/bin/systemctl", "restart", "worker"],
            capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            await callback.message.edit_text(
                "✅ Worker перезапущен!\n\n"
                "Синхронизация Personal выполняется при запуске.",
                reply_markup=back_button()
            )
        else:
            await callback.message.edit_text(
                f"❌ Ошибка перезапуска:\n{result.stderr}",
                reply_markup=back_button()
            )

    except Exception as e:
        logger.error(f"Restart worker error: {e}")
        await callback.message.edit_text(f"❌ Ошибка: {e}", reply_markup=back_button())


# ============ Настройки новых контактов ============

@dp.callback_query(F.data == "newcontact_settings")
async def cb_newcontact_settings(callback: CallbackQuery):
    """Показать меню настроек новых контактов"""
    if not is_admin(callback.from_user.id):
        return

    settings = await get_new_contact_settings()
    mode = settings['new_contact_mode']
    template = settings['new_contact_template']
    prompt = settings['new_contact_prompt']

    mode_names = {'off': '⚫ Выключено', 'template': '📝 Шаблон', 'ai': '🤖 AI'}

    text = (
        f"👤 Новые контакты\n\n"
        f"Режим: {mode_names.get(mode, mode)}\n\n"
        f"📝 Шаблон:\n{template[:100]}...\n\n"
        f"🤖 AI промпт:\n{prompt[:100]}..."
    )

    await callback.message.edit_text(text, reply_markup=newcontact_settings_keyboard(mode))
    await callback.answer()


@dp.callback_query(F.data.startswith("nc_mode:"))
async def cb_nc_mode(callback: CallbackQuery):
    """Переключить режим новых контактов"""
    if not is_admin(callback.from_user.id):
        return

    new_mode = callback.data.split(":")[1]

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ('new_contact_mode', $1) "
            "ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = NOW()",
            new_mode
        )

    mode_names = {'off': '⚫ Выключено', 'template': '📝 Шаблон', 'ai': '🤖 AI'}
    await callback.answer(f"✅ Режим: {mode_names.get(new_mode, new_mode)}", show_alert=True)

    # Обновляем меню
    settings = await get_new_contact_settings()
    template = settings['new_contact_template']
    prompt = settings['new_contact_prompt']

    text = (
        f"👤 Новые контакты\n\n"
        f"Режим: {mode_names.get(new_mode, new_mode)}\n\n"
        f"📝 Шаблон:\n{template[:100]}...\n\n"
        f"🤖 AI промпт:\n{prompt[:100]}..."
    )

    await callback.message.edit_text(text, reply_markup=newcontact_settings_keyboard(new_mode))


@dp.callback_query(F.data == "nc_template")
async def cb_nc_template(callback: CallbackQuery, state: FSMContext):
    """Редактировать шаблон для новых контактов"""
    if not is_admin(callback.from_user.id):
        return

    settings = await get_new_contact_settings()
    current = settings['new_contact_template']

    await callback.message.edit_text(
        f"✏️ Введите новый шаблон для новых контактов:\n\n"
        f"Текущий:\n{current}\n\n"
        f"Отправьте новый текст или /cancel для отмены"
    )
    await state.set_state(NewContactState.waiting_template)
    await callback.answer()


@dp.callback_query(F.data == "nc_prompt")
async def cb_nc_prompt(callback: CallbackQuery, state: FSMContext):
    """Редактировать AI промпт для новых контактов"""
    if not is_admin(callback.from_user.id):
        return

    settings = await get_new_contact_settings()
    current = settings['new_contact_prompt']

    await callback.message.edit_text(
        f"📝 Введите новый AI промпт для новых контактов:\n\n"
        f"Текущий:\n{current}\n\n"
        f"Отправьте новый текст или /cancel для отмены"
    )
    await state.set_state(NewContactState.waiting_prompt)
    await callback.answer()


@dp.message(NewContactState.waiting_template)
async def process_nc_template(message: Message, state: FSMContext):
    """Обработка нового шаблона"""
    if not is_admin(message.from_user.id):
        return

    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=back_button())
        return

    new_template = message.text.strip()

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ('new_contact_template', $1) "
            "ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = NOW()",
            new_template
        )

    await state.clear()
    await message.answer(f"✅ Шаблон обновлён:\n\n{new_template}", reply_markup=back_button())


@dp.message(NewContactState.waiting_prompt)
async def process_nc_prompt(message: Message, state: FSMContext):
    """Обработка нового AI промпта"""
    if not is_admin(message.from_user.id):
        return

    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=back_button())
        return

    new_prompt = message.text.strip()

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ('new_contact_prompt', $1) "
            "ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = NOW()",
            new_prompt
        )

    await state.clear()
    await message.answer(f"✅ AI промпт обновлён:\n\n{new_prompt}", reply_markup=back_button())


@dp.message()
async def unknown(message: Message, state: FSMContext):
    if is_admin(message.from_user.id):
        current_state = await state.get_state()
        if current_state is None:
            await message.answer("❓ /start", reply_markup=back_button())


async def init_telethon():
    """Инициализация Telethon клиента для скачивания аватаров

    ВРЕМЕННО ОТКЛЮЧЕНО: конфликт сессий с worker.
    Worker использует тот же session файл, что приводит к ошибке 'database is locked'.
    Для включения нужна отдельная сессия для admin_bot.
    """
    global telethon_client
    # Отключаем Telethon временно из-за конфликта сессий
    logger.info("Telethon: disabled (session conflict with worker)")
    telethon_client = None
    return None

    # === Старый код (закомментирован) ===
    # if not API_ID or not API_HASH:
    #     logger.warning("Telethon: API_ID/API_HASH not set, avatars disabled")
    #     return None
    #
    # try:
    #     telethon_client = TelegramClient(SESSION_PATH, int(API_ID), API_HASH)
    #     await telethon_client.connect()
    #     if await telethon_client.is_user_authorized():
    #         me = await telethon_client.get_me()
    #         logger.info(f"Telethon connected as {me.first_name}")
    #         return telethon_client
    #     else:
    #         logger.warning("Telethon: session not authorized")
    #         return None
    # except Exception as e:
    #     logger.error(f"Telethon init error: {e}")
    #     return None


async def close_telethon():
    """Закрыть Telethon клиент"""
    global telethon_client
    if telethon_client:
        await telethon_client.disconnect()
        telethon_client = None


async def main():
    global telethon_client
    logger.info("Admin Bot v3.1")
    await init_db()
    await init_telethon()
    try:
        await dp.start_polling(bot)
    finally:
        await close_telethon()
        await close_db()
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
