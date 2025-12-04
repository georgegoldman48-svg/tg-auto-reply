"""
Telegram Message Collector

Собирает историю и новые сообщения из личных чатов Telegram.
Записывает в PostgreSQL: таблицы peers и messages.

Использование:
    python -m collector.collector

Первый запуск потребует ввода кода подтверждения из Telegram.
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import asyncpg
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import User

# Загрузка .env
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Конфигурация из .env
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
PHONE = os.getenv('PHONE_NUMBER')
DATABASE_URL = os.getenv('DATABASE_URL')

# Путь к сессии
SESSION_DIR = Path(__file__).parent.parent / "sessions"
SESSION_DIR.mkdir(exist_ok=True)
SESSION_PATH = str(SESSION_DIR / "collector")

# Лимит сообщений при синхронизации истории на один диалог
HISTORY_LIMIT_PER_PEER = int(os.getenv('HISTORY_LIMIT_PER_PEER', '1000'))

# Проверка обязательных переменных
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


async def ensure_peer(conn: asyncpg.Connection, entity: User) -> int:
    """
    Создать или обновить запись о собеседнике в таблице peers.
    
    Args:
        conn: Соединение с БД
        entity: Telegram User entity
        
    Returns:
        int: Внутренний peer_id (peers.id)
    """
    row = await conn.fetchrow("""
        INSERT INTO peers (tg_peer_id, tg_access_hash, peer_type, username, first_name, last_name, is_bot)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (tg_peer_id) DO UPDATE SET
            tg_access_hash = COALESCE(EXCLUDED.tg_access_hash, peers.tg_access_hash),
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            updated_at = now()
        RETURNING id
    """,
        entity.id,
        getattr(entity, 'access_hash', None),
        'user',
        getattr(entity, 'username', None),
        getattr(entity, 'first_name', None),
        getattr(entity, 'last_name', None),
        getattr(entity, 'bot', False)
    )
    return row['id']


async def save_message(conn: asyncpg.Connection, peer_id: int, msg) -> bool:
    """
    Сохранить сообщение в таблицу messages.
    
    Args:
        conn: Соединение с БД
        peer_id: Внутренний ID из таблицы peers
        msg: Telethon Message object
        
    Returns:
        bool: True если сообщение новое, False если уже существовало
    """
    # Определяем тип медиа
    has_media = msg.media is not None
    media_type = None
    if has_media:
        media_type = type(msg.media).__name__
    
    # Получаем reply_to_msg_id если есть
    reply_to_id = None
    if msg.reply_to:
        reply_to_id = getattr(msg.reply_to, 'reply_to_msg_id', None)
    
    try:
        result = await conn.execute("""
            INSERT INTO messages (peer_id, tg_message_id, from_me, date, text, reply_to_id, has_media, media_type, raw_json)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (peer_id, tg_message_id) DO NOTHING
        """,
            peer_id,
            msg.id,
            msg.out,  # True если я отправитель
            msg.date,
            msg.message,  # текст сообщения (может быть None)
            reply_to_id,
            has_media,
            media_type,
            json.dumps(msg.to_dict(), default=str, ensure_ascii=False)
        )
        # "INSERT 0 1" означает успешную вставку новой записи
        return "INSERT 0 1" in result
    except Exception as e:
        logger.error(f"Error saving message {msg.id}: {e}")
        return False


async def sync_history() -> None:
    """
    Синхронизация истории сообщений из личных диалогов.
    Вызывается один раз при старте для загрузки существующей истории.
    """
    logger.info("=" * 50)
    logger.info("Starting history synchronization...")
    logger.info(f"Limit per peer: {HISTORY_LIMIT_PER_PEER} messages")
    logger.info("=" * 50)
    
    total_dialogs = 0
    total_messages = 0
    
    async with db_pool.acquire() as conn:
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            
            # Фильтр: только личные диалоги с пользователями (не боты, не группы, не каналы)
            if not isinstance(entity, User):
                continue
            if getattr(entity, 'bot', False):
                continue
            
            total_dialogs += 1
            peer_id = await ensure_peer(conn, entity)
            
            # Имя для логов
            display_name = entity.first_name or entity.username or f"ID:{entity.id}"
            
            dialog_messages = 0
            try:
                async for msg in client.iter_messages(entity, limit=HISTORY_LIMIT_PER_PEER):
                    if await save_message(conn, peer_id, msg):
                        dialog_messages += 1
                        total_messages += 1
                    
                    # Логируем прогресс каждые 100 сообщений
                    if dialog_messages > 0 and dialog_messages % 100 == 0:
                        logger.info(f"  [{display_name}] {dialog_messages} messages saved...")
            except Exception as e:
                logger.error(f"Error syncing dialog with {display_name}: {e}")
                continue
            
            if dialog_messages > 0:
                logger.info(f"[{display_name}] Total: {dialog_messages} new messages")
    
    logger.info("=" * 50)
    logger.info(f"History sync complete: {total_dialogs} dialogs, {total_messages} new messages")
    logger.info("=" * 50)


async def handle_new_message(event) -> None:
    """
    Обработчик новых входящих сообщений.
    Автоматически вызывается Telethon при получении нового сообщения.
    """
    # Только личные сообщения (не группы/каналы)
    if not event.is_private:
        return

    msg = event.message

    try:
        sender = await event.get_sender()

        # Пропускаем не-пользователей и ботов
        if not isinstance(sender, User):
            return
        if getattr(sender, 'bot', False):
            return
        
        async with db_pool.acquire() as conn:
            peer_id = await ensure_peer(conn, sender)
            is_new = await save_message(conn, peer_id, msg)
            
            if is_new:
                display_name = sender.first_name or sender.username or f"ID:{sender.id}"
                text_preview = (msg.message or "[media]")[:50]
                logger.info(f"[IN] {display_name}: {text_preview}")
    
    except Exception as e:
        logger.error(f"Error handling incoming message: {e}")


async def handle_outgoing_message(event) -> None:
    """
    Обработчик исходящих сообщений (моих ответов).
    Нужен для полноты истории переписки.
    """
    # Только личные сообщения (не группы/каналы)
    if not event.is_private:
        return

    msg = event.message

    try:
        # Для исходящих сообщений получаем чат (receiver)
        chat = await event.get_chat()

        # Пропускаем не-пользователей и ботов
        if not isinstance(chat, User):
            return
        if getattr(chat, 'bot', False):
            return
        
        async with db_pool.acquire() as conn:
            peer_id = await ensure_peer(conn, chat)
            is_new = await save_message(conn, peer_id, msg)
            
            if is_new:
                display_name = chat.first_name or chat.username or f"ID:{chat.id}"
                text_preview = (msg.message or "[media]")[:50]
                logger.info(f"[OUT] -> {display_name}: {text_preview}")
    
    except Exception as e:
        logger.error(f"Error handling outgoing message: {e}")


async def main() -> None:
    """Главная функция collector"""
    global client
    
    logger.info("=" * 60)
    logger.info("Telegram Collector v1.0")
    logger.info("=" * 60)
    logger.info(f"Session path: {SESSION_PATH}")
    logger.info(f"Phone: {PHONE}")
    logger.info("=" * 60)
    
    # Инициализация БД
    await init_db()
    logger.info("Database connected")
    
    # Инициализация Telethon клиента
    client = TelegramClient(SESSION_PATH, int(API_ID), API_HASH)
    
    # Регистрация обработчиков событий
    client.add_event_handler(
        handle_new_message,
        events.NewMessage(incoming=True)
    )
    client.add_event_handler(
        handle_outgoing_message,
        events.NewMessage(outgoing=True)
    )
    
    # Подключение к Telegram
    await client.start(phone=PHONE)
    logger.info("Telegram client connected")
    
    # Информация о текущем аккаунте
    me = await client.get_me()
    logger.info(f"Logged in as: {me.first_name} (@{me.username or 'no username'}) [ID: {me.id}]")
    
    # Синхронизация истории (раскомментируй при первом запуске)
    # await sync_history()
    
    logger.info("=" * 60)
    logger.info("Collector started. Listening for new messages...")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal...")
    finally:
        await close_db()
        logger.info("Collector stopped")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
