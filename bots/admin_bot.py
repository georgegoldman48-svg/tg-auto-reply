"""
Admin Bot v2.0

Telegram-бот для управления автоответчиком с AI.
Доступ только для администратора (ADMIN_USER_ID).

Команды:
    /start       - Главное меню
    /status      - Статус системы
    /auto_on     - Включить автоответы
    /auto_off    - Выключить автоответы
    /ai_on       - Включить AI
    /ai_off      - Выключить AI (только шаблоны)
    /rules       - Список правил
    /add         - Добавить правило
    /del         - Удалить правило
    /peers       - Список собеседников
    /stats       - Статистика
    /help        - Справка

Использование:
    python -m bots.admin_bot
"""
import asyncio
import logging
import os
import sys
from datetime import datetime

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from dotenv import load_dotenv

# Загрузка .env
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv('ADMIN_BOT_TOKEN')
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID')
DATABASE_URL = os.getenv('DATABASE_URL')

# MVP: фиксированный account_id
ACCOUNT_ID = 1

# Проверка переменных
if not all([BOT_TOKEN, ADMIN_USER_ID, DATABASE_URL]):
    logger.error(
        "Missing required environment variables. "
        "Please set ADMIN_BOT_TOKEN, ADMIN_USER_ID, DATABASE_URL in .env"
    )
    sys.exit(1)

try:
    ADMIN_USER_ID = int(ADMIN_USER_ID)
except ValueError:
    logger.error("ADMIN_USER_ID must be a number")
    sys.exit(1)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальный пул БД
db_pool = None


async def init_db():
    """Инициализация пула подключений к БД"""
    global db_pool
    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=2,
        max_size=5,
        command_timeout=60
    )
    logger.info("Database pool initialized")


async def close_db():
    """Закрытие пула подключений"""
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed")


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id == ADMIN_USER_ID


def main_menu_keyboard():
    """Главное меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статус", callback_data="status"),
            InlineKeyboardButton(text="📈 Статистика", callback_data="stats")
        ],
        [
            InlineKeyboardButton(text="🟢 Вкл авто", callback_data="auto_on"),
            InlineKeyboardButton(text="🔴 Выкл авто", callback_data="auto_off")
        ],
        [
            InlineKeyboardButton(text="🤖 Вкл AI", callback_data="ai_on"),
            InlineKeyboardButton(text="🚫 Выкл AI", callback_data="ai_off")
        ],
        [
            InlineKeyboardButton(text="📋 Правила", callback_data="rules"),
            InlineKeyboardButton(text="👥 Контакты", callback_data="peers")
        ],
        [
            InlineKeyboardButton(text="➕ Добавить правило", callback_data="add_help")
        ]
    ])


def back_button():
    """Кнопка назад"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="menu")]
    ])


# ==================== КОМАНДЫ ====================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Команда /start - главное меню"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён. Этот бот только для администратора.")
        logger.warning(f"Unauthorized access attempt from user {message.from_user.id}")
        return
    
    text = (
        "🤖 Auto-Reply Admin v2.0\n\n"
        "Управление автоответчиком с AI.\n"
        "Выберите действие:"
    )
    await message.answer(text, reply_markup=main_menu_keyboard())
    logger.info(f"Admin {message.from_user.id} started the bot")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Команда /help - справка"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    text = (
        "📖 Справка по командам\n\n"
        "Управление:\n"
        "/auto_on — включить автоответы\n"
        "/auto_off — выключить автоответы\n"
        "/ai_on — включить AI ответы\n"
        "/ai_off — выключить AI (только шаблоны)\n\n"
        "Правила:\n"
        "/add <peer_id> <prompt> — добавить правило\n"
        "/del <peer_id> — удалить правило\n"
        "/rules — список правил\n\n"
        "Информация:\n"
        "/status — статус системы\n"
        "/peers — список контактов\n"
        "/stats — статистика\n\n"
        "Пример добавления правила:\n"
        "/add 134 Отвечай коротко и дерзко"
    )
    await message.answer(text, reply_markup=back_button())


@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Команда /status - показать текущий статус"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    await show_status(message)


async def show_status(message_or_callback):
    """Показать статус"""
    try:
        async with db_pool.acquire() as conn:
            # Статус автоответа
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = 'auto_reply_enabled'"
            )
            auto_enabled = row is not None and row['value'] == '1'
            
            # Статус AI
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = 'ai_enabled'"
            )
            ai_enabled = row is not None and row['value'] == '1'
            
            # Количество правил
            rules_count = await conn.fetchval(
                "SELECT COUNT(*) FROM auto_reply_rules WHERE account_id = $1",
                ACCOUNT_ID
            )
            
            # Количество активных правил
            active_rules = await conn.fetchval(
                "SELECT COUNT(*) FROM auto_reply_rules WHERE account_id = $1 AND enabled = true",
                ACCOUNT_ID
            )
            
            # Количество peers
            peers_count = await conn.fetchval(
                "SELECT COUNT(*) FROM peers WHERE is_bot = false"
            )
            
            # Всего сообщений
            total_messages = await conn.fetchval("SELECT COUNT(*) FROM messages")
        
        auto_emoji = "🟢" if auto_enabled else "🔴"
        auto_text = "Вкл" if auto_enabled else "Выкл"
        ai_emoji = "🤖" if ai_enabled else "🚫"
        ai_text = "Вкл" if ai_enabled else "Выкл"
        
        text = (
            f"📊 Статус системы\n\n"
            f"{auto_emoji} Автоответ: {auto_text}\n"
            f"{ai_emoji} AI режим: {ai_text}\n\n"
            f"📋 Правил: {active_rules}/{rules_count} активных\n"
            f"👥 Контактов: {peers_count}\n"
            f"💬 Сообщений: {total_messages}"
        )
        
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=back_button())
        else:
            await message_or_callback.answer(text, reply_markup=back_button())
        
    except Exception as e:
        logger.error(f"Error in status: {e}")
        text = f"❌ Ошибка: {e}"
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=back_button())
        else:
            await message_or_callback.answer(text)


@dp.message(Command("auto_on"))
async def cmd_auto_on(message: Message):
    """Команда /auto_on - включить автоответы"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    await toggle_setting(message, 'auto_reply_enabled', '1', "🟢 Автоответы включены")


@dp.message(Command("auto_off"))
async def cmd_auto_off(message: Message):
    """Команда /auto_off - выключить автоответы"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    await toggle_setting(message, 'auto_reply_enabled', '0', "🔴 Автоответы выключены")


@dp.message(Command("ai_on"))
async def cmd_ai_on(message: Message):
    """Команда /ai_on - включить AI"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    await toggle_setting(message, 'ai_enabled', '1', "🤖 AI режим включен\n\nОтветы генерируются нейросетью.")


@dp.message(Command("ai_off"))
async def cmd_ai_off(message: Message):
    """Команда /ai_off - выключить AI"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    await toggle_setting(message, 'ai_enabled', '0', "🚫 AI режим выключен\n\nИспользуются шаблоны из правил.")


async def toggle_setting(message_or_callback, key: str, value: str, response_text: str):
    """Переключить настройку"""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES ($1, $2, now())
                ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now()
            """, key, value)
        
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(response_text, reply_markup=back_button())
        else:
            await message_or_callback.answer(response_text, reply_markup=back_button())
        
        logger.info(f"Setting {key} set to {value}")
        
    except Exception as e:
        logger.error(f"Error toggling {key}: {e}")
        text = f"❌ Ошибка: {e}"
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=back_button())
        else:
            await message_or_callback.answer(text)


@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    """Команда /rules - показать список правил"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    await show_rules(message)


async def show_rules(message_or_callback):
    """Показать правила"""
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    r.id,
                    r.peer_id,
                    r.enabled,
                    r.template,
                    r.min_interval_sec,
                    p.first_name,
                    p.username,
                    p.tg_peer_id
                FROM auto_reply_rules r
                JOIN peers p ON p.id = r.peer_id
                WHERE r.account_id = $1
                ORDER BY r.created_at DESC
                LIMIT 20
            """, ACCOUNT_ID)
        
        if not rows:
            text = "📋 Нет правил автоответа\n\nДобавить: /add <peer_id> <prompt>"
        else:
            text = "📋 Правила автоответа:\n\n"
            for row in rows:
                status = "✅" if row['enabled'] else "❌"
                name = row['first_name'] or row['username'] or f"ID:{row['tg_peer_id']}"
                template_preview = (row['template'] or '')[:30]
                if len(row['template'] or '') > 30:
                    template_preview += "..."
                
                text += f"{status} {name}\n"
                text += f"   ID: {row['peer_id']} | ⏱ {row['min_interval_sec']}с\n"
                text += f"   📝 {template_preview}\n\n"
            
            text += "Удалить: /del <peer_id>"
        
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=back_button())
        else:
            await message_or_callback.answer(text, reply_markup=back_button())
        
    except Exception as e:
        logger.error(f"Error in rules: {e}")
        text = f"❌ Ошибка: {e}"
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=back_button())
        else:
            await message_or_callback.answer(text)


@dp.message(Command("add"))
async def cmd_add(message: Message):
    """Команда /add - добавить правило"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    # Парсим аргументы: /add <peer_id> <prompt>
    parts = message.text.split(maxsplit=2)
    
    if len(parts) < 2:
        text = (
            "➕ Добавление правила\n\n"
            "Формат: /add <peer_id> [prompt]\n\n"
            "peer_id — ID контакта из /peers\n"
            "prompt — инструкция для AI (опционально)\n\n"
            "Примеры:\n"
            "/add 134\n"
            "/add 134 Отвечай коротко\n"
            "/add 134 Будь вежлив и формален"
        )
        await message.answer(text, reply_markup=back_button())
        return
    
    try:
        peer_id = int(parts[1])
    except ValueError:
        await message.answer("❌ peer_id должен быть числом\n\nИспользуйте /peers чтобы найти ID")
        return
    
    # Prompt (шаблон) — опционально
    template = parts[2] if len(parts) > 2 else "Сейчас занят"
    
    try:
        async with db_pool.acquire() as conn:
            # Проверяем существует ли peer
            peer = await conn.fetchrow("SELECT id, first_name, username FROM peers WHERE id = $1", peer_id)
            if not peer:
                await message.answer(f"❌ Контакт с ID {peer_id} не найден\n\nИспользуйте /peers")
                return
            
            # Создаём правило
            await conn.execute("""
                INSERT INTO auto_reply_rules (account_id, peer_id, enabled, template, min_interval_sec)
                VALUES ($1, $2, true, $3, 60)
                ON CONFLICT (account_id, peer_id) DO UPDATE SET
                    template = $3,
                    enabled = true,
                    updated_at = now()
            """, ACCOUNT_ID, peer_id, template)
        
        name = peer['first_name'] or peer['username'] or f"ID:{peer_id}"
        text = (
            f"✅ Правило добавлено\n\n"
            f"👤 {name}\n"
            f"📝 {template}\n"
            f"⏱ Интервал: 60 сек"
        )
        await message.answer(text, reply_markup=back_button())
        logger.info(f"Rule added for peer {peer_id}")
        
    except Exception as e:
        logger.error(f"Error adding rule: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("del"))
async def cmd_del(message: Message):
    """Команда /del - удалить правило"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    parts = message.text.split()
    
    if len(parts) < 2:
        await message.answer("❌ Формат: /del <peer_id>\n\nИспользуйте /rules чтобы увидеть ID")
        return
    
    try:
        peer_id = int(parts[1])
    except ValueError:
        await message.answer("❌ peer_id должен быть числом")
        return
    
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM auto_reply_rules 
                WHERE account_id = $1 AND peer_id = $2
            """, ACCOUNT_ID, peer_id)
        
        if "DELETE 1" in result:
            await message.answer(f"✅ Правило для peer {peer_id} удалено", reply_markup=back_button())
            logger.info(f"Rule deleted for peer {peer_id}")
        else:
            await message.answer(f"❌ Правило для peer {peer_id} не найдено")
        
    except Exception as e:
        logger.error(f"Error deleting rule: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("peers"))
async def cmd_peers(message: Message):
    """Команда /peers - показать список собеседников"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    await show_peers(message)


async def show_peers(message_or_callback):
    """Показать контакты"""
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    p.id,
                    p.tg_peer_id,
                    p.username,
                    p.first_name,
                    p.last_name,
                    (SELECT COUNT(*) FROM messages WHERE peer_id = p.id) as msg_count,
                    EXISTS(SELECT 1 FROM auto_reply_rules WHERE peer_id = p.id AND account_id = $1) as has_rule
                FROM peers p
                WHERE p.is_bot = false
                ORDER BY p.updated_at DESC
                LIMIT 25
            """, ACCOUNT_ID)
        
        if not rows:
            text = "👥 Нет контактов в базе"
        else:
            text = "👥 Контакты:\n\n"
            for row in rows:
                name = row['first_name'] or row['username'] or "—"
                username = f"@{row['username']}" if row['username'] else ""
                rule_mark = "✅" if row['has_rule'] else ""
                
                text += f"{rule_mark} {name} {username}\n"
                text += f"   ID: {row['id']} | 💬 {row['msg_count']}\n\n"
            
            text += "✅ = есть правило\nДобавить: /add <ID>"
        
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=back_button())
        else:
            await message_or_callback.answer(text, reply_markup=back_button())
        
    except Exception as e:
        logger.error(f"Error in peers: {e}")
        text = f"❌ Ошибка: {e}"
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=back_button())
        else:
            await message_or_callback.answer(text)


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Команда /stats - показать статистику"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    await show_stats(message)


async def show_stats(message_or_callback):
    """Показать статистику"""
    try:
        async with db_pool.acquire() as conn:
            total_messages = await conn.fetchval("SELECT COUNT(*) FROM messages")
            today_messages = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE date >= CURRENT_DATE"
            )
            incoming_today = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE date >= CURRENT_DATE AND from_me = false"
            )
            outgoing_today = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE date >= CURRENT_DATE AND from_me = true"
            )
            unique_peers = await conn.fetchval(
                "SELECT COUNT(*) FROM peers WHERE is_bot = false"
            )
            auto_replies_today = await conn.fetchval("""
                SELECT COUNT(*) FROM auto_reply_state 
                WHERE last_reply_time >= CURRENT_DATE
            """)
        
        text = (
            f"📈 Статистика\n\n"
            f"💬 Сообщения:\n"
            f"   Всего: {total_messages}\n"
            f"   Сегодня: {today_messages}\n"
            f"   Входящих: {incoming_today}\n"
            f"   Исходящих: {outgoing_today}\n\n"
            f"👥 Контактов: {unique_peers}\n"
            f"🤖 Автоответов сегодня: {auto_replies_today or 0}"
        )
        
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=back_button())
        else:
            await message_or_callback.answer(text, reply_markup=back_button())
        
    except Exception as e:
        logger.error(f"Error in stats: {e}")
        text = f"❌ Ошибка: {e}"
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=back_button())
        else:
            await message_or_callback.answer(text)


# ==================== CALLBACK HANDLERS ====================

@dp.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery):
    """Вернуться в меню"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    text = (
        "🤖 Auto-Reply Admin v2.0\n\n"
        "Управление автоответчиком с AI.\n"
        "Выберите действие:"
    )
    await callback.message.edit_text(text, reply_markup=main_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "status")
async def cb_status(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    await show_status(callback)
    await callback.answer()


@dp.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    await show_stats(callback)
    await callback.answer()


@dp.callback_query(F.data == "auto_on")
async def cb_auto_on(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    await toggle_setting(callback, 'auto_reply_enabled', '1', "🟢 Автоответы включены")
    await callback.answer("Включено")


@dp.callback_query(F.data == "auto_off")
async def cb_auto_off(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    await toggle_setting(callback, 'auto_reply_enabled', '0', "🔴 Автоответы выключены")
    await callback.answer("Выключено")


@dp.callback_query(F.data == "ai_on")
async def cb_ai_on(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    await toggle_setting(callback, 'ai_enabled', '1', "🤖 AI режим включен\n\nОтветы генерируются нейросетью.")
    await callback.answer("AI включен")


@dp.callback_query(F.data == "ai_off")
async def cb_ai_off(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    await toggle_setting(callback, 'ai_enabled', '0', "🚫 AI режим выключен\n\nИспользуются шаблоны из правил.")
    await callback.answer("AI выключен")


@dp.callback_query(F.data == "rules")
async def cb_rules(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    await show_rules(callback)
    await callback.answer()


@dp.callback_query(F.data == "peers")
async def cb_peers(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    await show_peers(callback)
    await callback.answer()


@dp.callback_query(F.data == "add_help")
async def cb_add_help(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    text = (
        "➕ Добавление правила\n\n"
        "Формат: /add <peer_id> [prompt]\n\n"
        "1. Найдите ID контакта в /peers\n"
        "2. Отправьте команду:\n\n"
        "/add 134\n"
        "/add 134 Отвечай коротко\n\n"
        "prompt — инструкция для AI"
    )
    await callback.message.edit_text(text, reply_markup=back_button())
    await callback.answer()


@dp.message()
async def unknown_command(message: Message):
    """Обработчик неизвестных сообщений"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    await message.answer(
        "❓ Неизвестная команда\n\n/start — меню\n/help — справка",
        reply_markup=back_button()
    )


async def main():
    """Главная функция бота"""
    logger.info("=" * 60)
    logger.info("Admin Bot v2.0")
    logger.info("=" * 60)
    logger.info(f"Admin user ID: {ADMIN_USER_ID}")
    logger.info("=" * 60)
    
    await init_db()
    
    logger.info("Bot started. Press Ctrl+C to stop")
    
    try:
        await dp.start_polling(bot)
    finally:
        await close_db()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
