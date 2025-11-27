"""
Admin Bot

Telegram-бот для управления автоответчиком.
Доступ только для администратора (ADMIN_USER_ID).

Команды:
    /start       - Начало работы, список команд
    /status      - Текущий статус системы
    /auto_on     - Включить автоответы
    /auto_off    - Выключить автоответы
    /rules       - Список правил автоответа
    /peers       - Список собеседников
    /stats       - Статистика

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
from aiogram.types import Message
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


# ==================== КОМАНДЫ ====================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Команда /start - приветствие и список команд"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён. Этот бот только для администратора.")
        logger.warning(f"Unauthorized access attempt from user {message.from_user.id}")
        return
    
    help_text = """
🤖 *Admin Bot для Auto-Reply*

*Управление:*
/status — текущий статус системы
/auto\\_on — включить автоответы
/auto\\_off — выключить автоответы

*Информация:*
/rules — список правил автоответа
/peers — список собеседников
/stats — статистика

*Версия:* 1.0.0
"""
    await message.answer(help_text, parse_mode="Markdown")
    logger.info(f"Admin {message.from_user.id} started the bot")


@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Команда /status - показать текущий статус"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    try:
        async with db_pool.acquire() as conn:
            # Статус автоответа
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = 'auto_reply_enabled'"
            )
            enabled = row is not None and row['value'] == '1'
            
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
        
        status_emoji = "🟢" if enabled else "🔴"
        status_text = "Включен" if enabled else "Выключен"
        
        text = f"""
📊 *Статус системы*

{status_emoji} Автоответ: *{status_text}*

📋 Всего правил: {rules_count}
✅ Активных: {active_rules}
👥 Собеседников: {peers_count}
"""
        await message.answer(text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in /status: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("auto_on"))
async def cmd_auto_on(message: Message):
    """Команда /auto_on - включить автоответы"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES ('auto_reply_enabled', '1', now())
                ON CONFLICT (key) DO UPDATE SET value = '1', updated_at = now()
            """)
        
        await message.answer("🟢 Автоответы *включены*", parse_mode="Markdown")
        logger.info(f"Auto-reply enabled by admin {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Error in /auto_on: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("auto_off"))
async def cmd_auto_off(message: Message):
    """Команда /auto_off - выключить автоответы"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES ('auto_reply_enabled', '0', now())
                ON CONFLICT (key) DO UPDATE SET value = '0', updated_at = now()
            """)
        
        await message.answer("🔴 Автоответы *выключены*", parse_mode="Markdown")
        logger.info(f"Auto-reply disabled by admin {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Error in /auto_off: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    """Команда /rules - показать список правил"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
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
            await message.answer("📋 Нет настроенных правил автоответа")
            return
        
        text = "📋 *Правила автоответа:*\n\n"
        for row in rows:
            status = "✅" if row['enabled'] else "❌"
            name = row['first_name'] or row['username'] or f"ID:{row['tg_peer_id']}"
            template_preview = (row['template'] or '')[:40]
            if len(row['template'] or '') > 40:
                template_preview += "..."
            
            text += f"{status} *{name}* (peer\\_id: {row['peer_id']})\n"
            text += f"   📝 {template_preview}\n"
            text += f"   ⏱ Интервал: {row['min_interval_sec']}с\n\n"
        
        await message.answer(text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in /rules: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("peers"))
async def cmd_peers(message: Message):
    """Команда /peers - показать список собеседников"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    id,
                    tg_peer_id,
                    username,
                    first_name,
                    last_name
                FROM peers
                WHERE is_bot = false
                ORDER BY updated_at DESC
                LIMIT 20
            """)
        
        if not rows:
            await message.answer("👥 Нет собеседников в базе")
            return
        
        text = "👥 *Собеседники:*\n\n"
        for row in rows:
            name = row['first_name'] or row['username'] or "—"
            username = f"@{row['username']}" if row['username'] else "—"
            
            text += f"• *{name}* ({username})\n"
            text += f"  ID: `{row['id']}` | TG: `{row['tg_peer_id']}`\n\n"
        
        await message.answer(text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in /peers: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Команда /stats - показать статистику"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    try:
        async with db_pool.acquire() as conn:
            # Общее количество сообщений
            total_messages = await conn.fetchval("SELECT COUNT(*) FROM messages")
            
            # Сообщений за сегодня
            today_messages = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE date >= CURRENT_DATE"
            )
            
            # Входящих за сегодня
            incoming_today = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE date >= CURRENT_DATE AND from_me = false"
            )
            
            # Исходящих за сегодня
            outgoing_today = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE date >= CURRENT_DATE AND from_me = true"
            )
            
            # Количество уникальных собеседников
            unique_peers = await conn.fetchval(
                "SELECT COUNT(*) FROM peers WHERE is_bot = false"
            )
            
            # Автоответов сегодня
            auto_replies_today = await conn.fetchval("""
                SELECT COUNT(*) FROM auto_reply_state 
                WHERE last_reply_time >= CURRENT_DATE
            """)
        
        text = f"""
📊 *Статистика*

💬 *Сообщения:*
   Всего: {total_messages:,}
   Сегодня: {today_messages}
   ├ Входящих: {incoming_today}
   └ Исходящих: {outgoing_today}

👥 Собеседников: {unique_peers}
🤖 Автоответов сегодня: {auto_replies_today or 0}
"""
        await message.answer(text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in /stats: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@dp.message()
async def unknown_command(message: Message):
    """Обработчик неизвестных сообщений"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    await message.answer(
        "❓ Неизвестная команда. Используйте /start для списка команд."
    )


async def main():
    """Главная функция бота"""
    logger.info("=" * 60)
    logger.info("Admin Bot v1.0")
    logger.info("=" * 60)
    logger.info(f"Admin user ID: {ADMIN_USER_ID}")
    logger.info("=" * 60)
    
    # Инициализация БД
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
