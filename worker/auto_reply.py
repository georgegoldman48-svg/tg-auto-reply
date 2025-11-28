"""
Auto-Reply Worker с AI интеграцией

Проверяет новые входящие сообщения и отправляет автоответы,
сгенерированные через локальный AI сервер с учётом истории диалога.

Если AI недоступен — отправляет fallback сообщение.

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
import aiohttp
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

# AI сервер (через SSH туннель)
AI_SERVER_URL = os.getenv('AI_SERVER_URL', 'http://localhost:8080')

# Fallback сообщение если AI недоступен
FALLBACK_MESSAGE = os.getenv('FALLBACK_MESSAGE', 'Сейчас занят')

# Сколько сообщений из истории отправлять в AI
HISTORY_LIMIT = int(os.getenv('HISTORY_LIMIT', '20'))

# Интервал проверки (секунды)
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '5'))

# Таймаут для AI запросов (секунды)
AI_TIMEOUT = int(os.getenv('AI_TIMEOUT', '60'))

# MVP: фиксированный account_id
ACCOUNT_ID = 1

# Путь к сессии
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
http_session: Optional[aiohttp.ClientSession] = None


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


async def init_http() -> aiohttp.ClientSession:
    """Инициализация HTTP сессии"""
    global http_session
    timeout = aiohttp.ClientTimeout(total=AI_TIMEOUT)
    http_session = aiohttp.ClientSession(timeout=timeout)
    logger.info("HTTP session initialized")
    return http_session


async def close_http() -> None:
    """Закрытие HTTP сессии"""
    global http_session
    if http_session:
        await http_session.close()
        http_session = None
        logger.info("HTTP session closed")


async def is_auto_reply_enabled(conn: asyncpg.Connection) -> bool:
    """Проверить, включен ли автоответ глобально"""
    row = await conn.fetchrow(
        "SELECT value FROM settings WHERE key = 'auto_reply_enabled'"
    )
    return row is not None and row['value'] == '1'


async def is_ai_enabled(conn: asyncpg.Connection) -> bool:
    """Проверить, включен ли AI режим"""
    row = await conn.fetchrow(
        "SELECT value FROM settings WHERE key = 'ai_enabled'"
    )
    return row is not None and row['value'] == '1'


async def get_conversation_history(conn: asyncpg.Connection, peer_id: int) -> List[Dict[str, Any]]:
    """
    Получить историю диалога с peer из БД.
    
    Возвращает последние HISTORY_LIMIT сообщений в хронологическом порядке.
    """
    rows = await conn.fetch("""
        SELECT 
            from_me,
            text,
            date
        FROM messages
        WHERE peer_id = $1 AND text IS NOT NULL AND text != ''
        ORDER BY date DESC
        LIMIT $2
    """, peer_id, HISTORY_LIMIT)
    
    # Переворачиваем чтобы был хронологический порядок (старые → новые)
    history = []
    for row in reversed(rows):
        history.append({
            "role": "assistant" if row["from_me"] else "user",
            "content": row["text"]
        })
    
    return history


async def get_candidates_for_reply(conn: asyncpg.Connection) -> List[Dict[str, Any]]:
    """
    Найти сообщения-кандидаты для автоответа.
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


async def generate_ai_response(prompt: str, peer_id: int, history: List[Dict[str, Any]]) -> Optional[str]:
    """
    Получить ответ от AI сервера с учётом истории диалога.
    
    Args:
        prompt: Текущее сообщение от пользователя
        peer_id: ID собеседника (для кэширования на стороне AI сервера)
        history: История диалога из БД
    
    Returns:
        str: Ответ от AI или None если сервер недоступен
    """
    try:
        async with http_session.post(
            f"{AI_SERVER_URL}/generate",
            json={
                "prompt": prompt,
                "peer_id": peer_id,
                "history": history
            }
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("response")
            else:
                logger.warning(f"AI server returned status {resp.status}")
                return None
    except aiohttp.ClientConnectorError:
        logger.warning("AI server unavailable (connection refused)")
        return None
    except asyncio.TimeoutError:
        logger.warning(f"AI server timeout ({AI_TIMEOUT}s)")
        return None
    except Exception as e:
        logger.error(f"AI request error: {e}")
        return None


async def send_reply(tg_peer_id: int, text: str) -> bool:
    """Отправить ответ через Telethon."""
    try:
        await client.send_message(tg_peer_id, text)
        return True
    except Exception as e:
        logger.error(f"Failed to send message to {tg_peer_id}: {e}")
        return False


async def process_auto_replies() -> int:
    """
    Основной цикл обработки автоответов.
    """
    sent_count = 0
    
    async with db_pool.acquire() as conn:
        # Проверяем глобальный флаг
        if not await is_auto_reply_enabled(conn):
            return 0
        
        # Проверяем включен ли AI
        ai_enabled = await is_ai_enabled(conn)
        
        # Получаем кандидатов для ответа
        candidates = await get_candidates_for_reply(conn)
        
        if candidates:
            logger.info(f"Found {len(candidates)} candidate(s) for auto-reply")
        
        for candidate in candidates:
            peer_id = candidate['peer_id']
            tg_peer_id = candidate['tg_peer_id']
            template = candidate['template']
            message_text = candidate['message_text'] or ""
            display_name = candidate['first_name'] or candidate['username'] or f"ID:{tg_peer_id}"
            message_preview = message_text[:30] if message_text else "[media]"
            
            logger.info(f"Processing: {display_name} - \"{message_preview}...\"")
            
            # Определяем текст ответа
            if ai_enabled and message_text:
                # Получаем историю диалога из БД
                history = await get_conversation_history(conn, peer_id)
                logger.info(f"Loaded {len(history)} messages from history")
                
                # Пробуем получить ответ от AI
                reply_text = await generate_ai_response(message_text, peer_id, history)
                
                if reply_text:
                    logger.info(f"AI response: {reply_text[:50]}...")
                else:
                    # AI недоступен — используем fallback
                    reply_text = FALLBACK_MESSAGE
                    logger.info(f"AI unavailable, using fallback: {reply_text}")
            else:
                # AI выключен — используем шаблон из правила
                reply_text = template
            
            # Отправляем ответ
            if await send_reply(tg_peer_id, reply_text):
                await update_reply_state(conn, peer_id, candidate['message_id'])
                sent_count += 1
                logger.info(f"✓ Reply sent to {display_name}")
            else:
                logger.error(f"✗ Failed to send reply to {display_name}")
    
    return sent_count


async def check_ai_server() -> bool:
    """Проверить доступность AI сервера"""
    try:
        async with http_session.get(f"{AI_SERVER_URL}/health") as resp:
            if resp.status == 200:
                data = await resp.json()
                logger.info(f"AI server: {data.get('model', 'unknown')} on {data.get('gpu', 'unknown')}")
                return True
    except:
        pass
    return False


async def main() -> None:
    """Главная функция worker"""
    global client
    
    logger.info("=" * 60)
    logger.info("Auto-Reply Worker v2.0 (with AI + History)")
    logger.info("=" * 60)
    logger.info(f"Check interval: {CHECK_INTERVAL} seconds")
    logger.info(f"AI server: {AI_SERVER_URL}")
    logger.info(f"AI timeout: {AI_TIMEOUT} seconds")
    logger.info(f"History limit: {HISTORY_LIMIT} messages")
    logger.info(f"Fallback message: {FALLBACK_MESSAGE}")
    logger.info(f"Session path: {SESSION_PATH}")
    logger.info("=" * 60)
    
    # Инициализация БД
    await init_db()
    logger.info("Database connected")
    
    # Инициализация HTTP
    await init_http()
    
    # Проверка AI сервера
    if await check_ai_server():
        logger.info("✓ AI server is available")
    else:
        logger.warning("✗ AI server is not available (will use fallback)")
    
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
        await close_http()
        await close_db()
        logger.info(f"Worker stopped. Total replies sent: {total_sent}")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
