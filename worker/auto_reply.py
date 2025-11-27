"""
Auto-Reply Worker

Проверяет новые входящие сообщения и отправляет автоответы
согласно настроенным правилам.

Использование:
    python -m worker.auto_reply
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

import asyncpg
from dotenv import load_dotenv
from telethon import TelegramClient

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
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
PHONE = os.getenv('PHONE_NUMBER')
DATABASE_URL = os.getenv('DATABASE_URL')

# Интервал проверки (секунды)
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '5'))

# MVP: фиксированный account_id
ACCOUNT_ID = 1

# Путь к сессии (можно использовать ту же, что и collector, или отдельную)
SESSION_DIR = Path(__file__).parent.parent / "sessions"
SESSION_DIR.mkdir(exist_ok=True)
SESSION_PATH = str(SESSION_DIR / "worker")

# Проверка переменных
if not all([API_ID, API_HASH, PHONE, DATABASE_URL]):
    logger.error(
        "Missing required environment variables. "
        "Please set API_ID, API_HASH, PHONE_NUMBER, DATABASE_URL in .env"
    )
    sys.exit(1)

# Глобальные переменные
db_pool: Optional[asyncpg.Pool] = None
client: Optional[TelegramClient] = None


async def init_db() -> asyncpg.Pool:
    """Инициализация пула подключений к БД"""
    global db_pool
    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=2,
        max_size=10,
        command_timeout=60
    )
    logger.info("Database pool initialized")
    return db_pool


async def close_db() -> None:
    """Закрытие пула подключений"""
    global db_pool
    if db_pool:
        await db_pool.close()
        db_pool = None
        logger.info("Database pool closed")


async def is_auto_reply_enabled(conn: asyncpg.Connection) -> bool:
    """Проверить, включен ли автоответ глобально"""
    row = await conn.fetchrow(
        "SELECT value FROM settings WHERE key = 'auto_reply_enabled'"
    )
    return row is not None and row['value'] == '1'


async def get_candidates_for_reply(conn: asyncpg.Connection) -> List[Dict[str, Any]]:
    """
    Найти сообщения-кандидаты для автоответа.
    
    Критерии:
    1. Сообщение входящее (from_me = false)
    2. Сообщение недавнее (последние 5 минут)
    3. Есть включенное правило для этого peer
    4. Прошло достаточно времени с последнего автоответа (min_interval_sec)
    5. Мы ещё не отвечали на это или более позднее сообщение
    """
    rows = await conn.fetch("""
        SELECT 
            m.id AS message_id,
            m.peer_id,
            m.tg_message_id,
            m.text AS message_text,
            m.date AS message_date,
            p.tg_peer_id,
            p.first_name,
            p.username,
            r.template,
            r.min_interval_sec,
            s.last_reply_time,
            s.last_message_id
        FROM messages m
        JOIN peers p ON p.id = m.peer_id
        JOIN auto_reply_rules r ON r.peer_id = m.peer_id AND r.account_id = $1
        LEFT JOIN auto_reply_state s ON s.peer_id = m.peer_id AND s.account_id = $1
        WHERE 
            m.from_me = false
            AND m.date > now() - interval '5 minutes'
            AND r.enabled = true
            AND (
                s.last_reply_time IS NULL 
                OR m.date > s.last_reply_time
            )
            AND (
                s.last_reply_time IS NULL
                OR EXTRACT(EPOCH FROM (now() - s.last_reply_time)) >= r.min_interval_sec
            )
        ORDER BY m.date ASC
        LIMIT 10
    """, ACCOUNT_ID)
    
    return [dict(row) for row in rows]


async def update_reply_state(conn: asyncpg.Connection, peer_id: int, message_id: int) -> None:
    """Обновить состояние автоответа после отправки"""
    await conn.execute("""
        INSERT INTO auto_reply_state (account_id, peer_id, last_reply_time, last_message_id)
        VALUES ($1, $2, now(), $3)
        ON CONFLICT (account_id, peer_id) DO UPDATE SET
            last_reply_time = now(),
            last_message_id = $3
    """, ACCOUNT_ID, peer_id, message_id)


async def send_reply(tg_peer_id: int, text: str) -> bool:
    """
    Отправить ответ через Telethon.
    
    Args:
        tg_peer_id: Telegram user_id получателя
        text: Текст сообщения
        
    Returns:
        bool: True если успешно отправлено
    """
    try:
        await client.send_message(tg_peer_id, text)
        return True
    except Exception as e:
        logger.error(f"Failed to send message to {tg_peer_id}: {e}")
        return False


async def process_auto_replies() -> int:
    """
    Основной цикл обработки автоответов.
    
    Returns:
        int: Количество отправленных ответов
    """
    sent_count = 0
    
    async with db_pool.acquire() as conn:
        # Проверяем глобальный флаг
        if not await is_auto_reply_enabled(conn):
            return 0
        
        # Получаем кандидатов для ответа
        candidates = await get_candidates_for_reply(conn)
        
        if candidates:
            logger.info(f"Found {len(candidates)} candidate(s) for auto-reply")
        
        for candidate in candidates:
            peer_id = candidate['peer_id']
            tg_peer_id = candidate['tg_peer_id']
            template = candidate['template']
            display_name = candidate['first_name'] or candidate['username'] or f"ID:{tg_peer_id}"
            message_preview = (candidate['message_text'] or "[media]")[:30]
            
            logger.info(f"Processing: {display_name} - \"{message_preview}...\"")
            
            # Отправляем ответ
            if await send_reply(tg_peer_id, template):
                # Обновляем состояние
                await update_reply_state(conn, peer_id, candidate['message_id'])
                sent_count += 1
                logger.info(f"✓ Auto-reply sent to {display_name}")
            else:
                logger.error(f"✗ Failed to send auto-reply to {display_name}")
    
    return sent_count


async def main() -> None:
    """Главная функция worker"""
    global client
    
    logger.info("=" * 60)
    logger.info("Auto-Reply Worker v1.0")
    logger.info("=" * 60)
    logger.info(f"Check interval: {CHECK_INTERVAL} seconds")
    logger.info(f"Account ID: {ACCOUNT_ID}")
    logger.info(f"Session path: {SESSION_PATH}")
    logger.info("=" * 60)
    
    # Инициализация БД
    await init_db()
    logger.info("Database connected")
    
    # Инициализация Telethon клиента
    client = TelegramClient(SESSION_PATH, int(API_ID), API_HASH)
    await client.start(phone=PHONE)
    
    # Информация о текущем аккаунте
    me = await client.get_me()
    logger.info(f"Logged in as: {me.first_name} (@{me.username or 'no username'}) [ID: {me.id}]")
    
    logger.info("=" * 60)
    logger.info("Worker started. Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    total_sent = 0
    iterations = 0
    
    try:
        while True:
            iterations += 1
            
            try:
                sent = await process_auto_replies()
                total_sent += sent
                
                if sent > 0:
                    logger.info(f"Iteration {iterations}: Sent {sent} reply(ies). Total: {total_sent}")
                    
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
            
            await asyncio.sleep(CHECK_INTERVAL)
    
    except KeyboardInterrupt:
        logger.info("Received shutdown signal...")
    finally:
        await client.disconnect()
        await close_db()
        logger.info(f"Worker stopped. Total replies sent: {total_sent}")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
