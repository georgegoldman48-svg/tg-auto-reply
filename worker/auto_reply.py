"""
Auto-Reply Worker с AI интеграцией

Проверяет новые входящие сообщения и отправляет автоответы,
сгенерированные через локальный AI сервер или Claude API.

Поддерживает:
- Локальный AI (SambaLingo + LoRA) через SSH туннель
- Claude API (claude-sonnet-4-20250514)
- Фильтрация по папке Personal в Telegram
- Лимиты: 5 ответов для новых контактов, 50 в день

Использование:
    python -m worker.auto_reply
"""
import asyncio
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Set

import asyncpg
import aiohttp
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import User, Chat, Channel

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

# Claude API
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-3-5-haiku-20241022"

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

# Кэш Personal folder
personal_cache: Set[int] = set()  # tg_peer_ids из папки Personal
personal_cache_updated: Optional[datetime] = None
PERSONAL_CACHE_TTL_HOURS = 1  # Обновлять кэш раз в час


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


async def refresh_personal_cache() -> None:
    """
    Обновить кэш Personal folder из Telegram.
    Ищет папку по title='Personal', собирает user IDs.
    """
    global personal_cache, personal_cache_updated

    if not client or not client.is_connected():
        logger.warning("Cannot refresh Personal cache: client not connected")
        return

    try:
        result = await client(GetDialogFiltersRequest())
        filters = result if isinstance(result, list) else result.filters

        # Ищем Personal по title
        personal = None
        for f in filters:
            if hasattr(f, 'title') and f.title == 'Personal':
                personal = f
                break

        if not personal:
            logger.warning("Personal folder not found in Telegram")
            return

        # Собираем exclude IDs
        exclude_ids = set()
        for p in personal.exclude_peers:
            if hasattr(p, 'user_id'):
                exclude_ids.add(p.user_id)

        # Собираем user IDs из всех диалогов, соответствующих критериям Personal
        new_cache = set()
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, User):
                if entity.bot:  # bots=False в Personal
                    continue
                if entity.id in exclude_ids:
                    continue
                new_cache.add(entity.id)

        personal_cache = new_cache
        personal_cache_updated = datetime.now(timezone.utc)
        logger.info(f"Personal cache refreshed: {len(personal_cache)} users")

    except Exception as e:
        logger.error(f"Failed to refresh Personal cache: {e}")


async def sync_personal_to_db() -> int:
    """
    Синхронизировать Personal folder с БД.
    Обновляет поле in_personal для peers.
    Удаляет пользователей не в Personal и без активных правил.

    Returns:
        int: Количество пользователей в Personal
    """
    global db_pool

    if not personal_cache:
        logger.warning("Personal cache is empty, skipping DB sync")
        return 0

    try:
        async with db_pool.acquire() as conn:
            # Сбросить все
            await conn.execute("UPDATE peers SET in_personal = false")

            # Установить true для Personal
            if personal_cache:
                result = await conn.execute(
                    "UPDATE peers SET in_personal = true WHERE tg_peer_id = ANY($1::bigint[])",
                    list(personal_cache)
                )
                logger.info(f"Synced Personal to DB: {result}")

            # Удалить тех кто не в Personal и без активных правил
            deleted = await conn.execute("""
                DELETE FROM peers
                WHERE in_personal = false
                AND id NOT IN (SELECT peer_id FROM auto_reply_rules WHERE enabled = true)
            """)
            logger.info(f"Cleaned up peers not in Personal: {deleted}")

            # Вернуть количество в Personal
            count = await conn.fetchval("SELECT COUNT(*) FROM peers WHERE in_personal = true")
            return count

    except Exception as e:
        logger.error(f"Failed to sync Personal to DB: {e}")
        return 0


async def is_personal_cache_stale() -> bool:
    """Проверить, устарел ли кэш Personal"""
    if personal_cache_updated is None:
        return True
    age = datetime.now(timezone.utc) - personal_cache_updated
    return age > timedelta(hours=PERSONAL_CACHE_TTL_HOURS)


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


async def get_ai_settings(conn: asyncpg.Connection) -> Dict[str, Any]:
    """Получить настройки AI из БД"""
    rows = await conn.fetch("""
        SELECT key, value FROM settings
        WHERE key IN ('ai_engine', 'system_prompt', 'temperature', 'max_tokens', 'claude_api_key')
    """)

    settings = {
        'ai_engine': 'local',
        'system_prompt': 'Ты Егор. Отвечаешь коротко, живо, по делу.',
        'temperature': 0.7,
        'max_tokens': 150,
        'claude_api_key': None
    }

    for row in rows:
        key = row['key']
        value = row['value']
        if key == 'temperature':
            settings[key] = float(value)
        elif key == 'max_tokens':
            settings[key] = int(value)
        else:
            settings[key] = value

    return settings


async def get_new_contact_settings(conn: asyncpg.Connection) -> Dict[str, Any]:
    """Получить настройки для новых контактов"""
    rows = await conn.fetch("""
        SELECT key, value FROM settings
        WHERE key IN ('new_contact_mode', 'new_contact_template', 'new_contact_prompt')
    """)

    settings = {
        'new_contact_mode': 'off',
        'new_contact_template': 'Привет! Напомни откуда мы знакомы?',
        'new_contact_prompt': 'Незнакомый человек. Вежливо спроси кто это.'
    }

    for row in rows:
        settings[row['key']] = row['value']

    return settings


async def get_reply_limits(conn: asyncpg.Connection) -> Dict[str, int]:
    """Получить лимиты из настроек"""
    rows = await conn.fetch("""
        SELECT key, value FROM settings
        WHERE key IN ('new_contact_max_replies', 'daily_max_replies')
    """)
    limits = {
        'new_contact_max_replies': 5,
        'daily_max_replies': 50
    }
    for row in rows:
        try:
            limits[row['key']] = int(row['value'])
        except ValueError:
            pass
    return limits


async def check_and_update_daily_limit(conn: asyncpg.Connection, peer_id: int) -> bool:
    """
    Проверить дневной лимит и обновить счётчик.
    Returns: True если можно отвечать, False если лимит исчерпан.
    """
    limits = await get_reply_limits(conn)
    max_daily = limits['daily_max_replies']
    today = datetime.now(timezone.utc).date()

    # Получаем/создаём запись
    row = await conn.fetchrow("""
        INSERT INTO reply_counts (peer_id, daily_replies, last_reply_date)
        VALUES ($1, 0, $2)
        ON CONFLICT (peer_id) DO UPDATE SET
            daily_replies = CASE
                WHEN reply_counts.last_reply_date != $2 THEN 0
                ELSE reply_counts.daily_replies
            END,
            last_reply_date = $2
        RETURNING daily_replies
    """, peer_id, today)

    current_count = row['daily_replies']

    if current_count >= max_daily:
        logger.warning(f"Daily limit reached for peer_id={peer_id}: {current_count}/{max_daily}")
        return False

    # Увеличиваем счётчик
    await conn.execute("""
        UPDATE reply_counts SET daily_replies = daily_replies + 1 WHERE peer_id = $1
    """, peer_id)

    return True


async def check_new_contact_limit(conn: asyncpg.Connection, peer_id: int) -> bool:
    """
    Проверить лимит для нового контакта.
    Returns: True если можно отвечать, False если лимит исчерпан.
    """
    limits = await get_reply_limits(conn)
    max_new = limits['new_contact_max_replies']

    row = await conn.fetchrow("""
        SELECT new_contact_replies FROM reply_counts WHERE peer_id = $1
    """, peer_id)

    if row and row['new_contact_replies'] >= max_new:
        logger.warning(f"New contact limit reached for peer_id={peer_id}: {row['new_contact_replies']}/{max_new}")
        return False

    return True


async def increment_new_contact_reply(conn: asyncpg.Connection, peer_id: int) -> int:
    """
    Увеличить счётчик ответов для нового контакта.
    Returns: Новое значение счётчика.
    """
    today = datetime.now(timezone.utc).date()
    row = await conn.fetchrow("""
        INSERT INTO reply_counts (peer_id, new_contact_replies, daily_replies, last_reply_date)
        VALUES ($1, 1, 1, $2)
        ON CONFLICT (peer_id) DO UPDATE SET
            new_contact_replies = reply_counts.new_contact_replies + 1,
            daily_replies = CASE
                WHEN reply_counts.last_reply_date != $2 THEN 1
                ELSE reply_counts.daily_replies + 1
            END,
            last_reply_date = $2
        RETURNING new_contact_replies
    """, peer_id, today)
    return row['new_contact_replies']


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

    Фильтрация:
    - ТОЛЬКО peers с активным правилом (enabled=true)
    - reply_mode != 'off' (если off — не отвечаем)
    - in_personal используется только для синхронизации, НЕ для автоответа
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
            p.in_personal,
            COALESCE(r.template, '') AS template,
            COALESCE(r.reply_mode, 'ai') AS reply_mode,
            COALESCE(r.min_interval_sec, 60) AS min_interval_sec,
            r.enabled AS rule_enabled,
            s.last_reply_time,
            s.last_message_id
        FROM messages m
        JOIN peers p ON p.id = m.peer_id
        JOIN auto_reply_rules r ON r.peer_id = m.peer_id AND r.account_id = $1 AND r.enabled = true
        LEFT JOIN auto_reply_state s ON s.peer_id = m.peer_id AND s.account_id = $1
        WHERE
            m.from_me = false
            AND m.date > now() - interval '5 minutes'
            AND COALESCE(r.reply_mode, 'ai') != 'off'
            AND (
                s.last_message_id IS NULL
                OR m.id > s.last_message_id
            )
            AND (
                s.last_reply_time IS NULL
                OR EXTRACT(EPOCH FROM (now() - s.last_reply_time)) >= COALESCE(r.min_interval_sec, 60)
            )
        ORDER BY m.id ASC
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


async def generate_local_response(
    prompt: str,
    peer_id: int,
    history: List[Dict[str, Any]],
    peer_prompt: str = None
) -> Optional[str]:
    """Получить ответ от локального AI сервера (SambaLingo + LoRA)"""
    try:
        payload = {
            "prompt": prompt,
            "peer_id": peer_id,
            "history": history
        }
        if peer_prompt:
            payload["peer_prompt"] = peer_prompt

        async with http_session.post(
            f"{AI_SERVER_URL}/generate",
            json=payload
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("response")
            else:
                logger.warning(f"Local AI server returned status {resp.status}")
                return None
    except aiohttp.ClientConnectorError:
        logger.warning("Local AI server unavailable (connection refused)")
        return None
    except asyncio.TimeoutError:
        logger.warning(f"Local AI server timeout ({AI_TIMEOUT}s)")
        return None
    except Exception as e:
        logger.error(f"Local AI request error: {e}")
        return None


async def generate_claude_response(
    prompt: str,
    history: List[Dict[str, Any]],
    settings: Dict[str, Any],
    peer_prompt: str = None
) -> Optional[str]:
    """Получить ответ от Claude API"""
    api_key = settings.get('claude_api_key')
    if not api_key:
        logger.error("Claude API key not configured")
        return None

    # Формируем system prompt
    system_prompt = settings.get('system_prompt', '')
    if peer_prompt:
        system_prompt = f"{system_prompt}\n\nДополнительно: {peer_prompt}"

    # Формируем сообщения для Claude
    messages = []
    for msg in history[-10:]:  # Последние 10 сообщений
        messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })
    messages.append({"role": "user", "content": prompt})

    try:
        async with http_session.post(
            CLAUDE_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": settings.get('max_tokens', 150),
                "system": system_prompt,
                "messages": messages
            }
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("content") and len(data["content"]) > 0:
                    return data["content"][0].get("text", "")
                return None
            else:
                error_text = await resp.text()
                logger.error(f"Claude API error {resp.status}: {error_text[:200]}")
                return None
    except asyncio.TimeoutError:
        logger.warning(f"Claude API timeout ({AI_TIMEOUT}s)")
        return None
    except Exception as e:
        logger.error(f"Claude API request error: {e}")
        return None


async def generate_ai_response(
    prompt: str,
    peer_id: int,
    history: List[Dict[str, Any]],
    settings: Dict[str, Any],
    peer_prompt: str = None
) -> Optional[str]:
    """
    Получить ответ от AI с учётом выбранного движка.

    ВАЖНО: Если выбран local и он недоступен — автоматически fallback на Claude.

    Args:
        prompt: Текущее сообщение от пользователя
        peer_id: ID собеседника
        history: История диалога из БД
        settings: Настройки AI из БД
        peer_prompt: Промпт для конкретного пира

    Returns:
        str: Ответ от AI или None если недоступен
    """
    engine = settings.get('ai_engine', 'local')

    if engine == 'claude':
        # Только Claude
        logger.info(f"Using Claude API (model: {CLAUDE_MODEL})")
        return await generate_claude_response(prompt, history, settings, peer_prompt)
    else:
        # Local с автоматическим fallback на Claude
        logger.info("Using local AI (Qwen + LoRA via SSH tunnel)")
        response = await generate_local_response(prompt, peer_id, history, peer_prompt)

        if response:
            return response

        # Local недоступен — fallback на Claude
        logger.warning("Local AI unavailable, falling back to Claude API")
        claude_response = await generate_claude_response(prompt, history, settings, peer_prompt)

        if claude_response:
            logger.info(f"Claude fallback response: {claude_response[:50]}...")
            return claude_response

        # Ни local, ни Claude не сработали
        logger.error("Both local AI and Claude API unavailable")
        return None


async def send_reply(tg_peer_id: int, text: str, reply_to_msg_id: int = None) -> bool:
    """Отправить ответ через Telethon."""
    try:
        await client.send_message(tg_peer_id, text, reply_to=reply_to_msg_id)
        return True
    except Exception as e:
        logger.error(f"Failed to send message to {tg_peer_id}: {e}")
        return False


async def process_new_contact(tg_peer_id: int, message_text: str, tg_msg_id: int) -> bool:
    """
    Обработать сообщение от нового контакта.
    Создаёт запись в peers и отвечает согласно настройкам new_contact_mode.
    Лимит: max 5 ответов для нового контакта, после чего не отвечаем.
    """
    async with db_pool.acquire() as conn:
        # Проверяем настройки для новых контактов
        nc_settings = await get_new_contact_settings(conn)
        mode = nc_settings['new_contact_mode']

        if mode == 'off':
            logger.info(f"New contact {tg_peer_id}: ignored (mode=off)")
            return False

        # Получаем информацию о пользователе из Telegram
        try:
            entity = await client.get_entity(tg_peer_id)
            first_name = getattr(entity, 'first_name', None) or ''
            last_name = getattr(entity, 'last_name', None) or ''
            username = getattr(entity, 'username', None)
            is_bot = getattr(entity, 'bot', False)
        except Exception as e:
            logger.error(f"Failed to get entity for {tg_peer_id}: {e}")
            first_name = ''
            last_name = ''
            username = None
            is_bot = False

        # Создаём/обновляем запись в peers
        peer_id = await conn.fetchval("""
            INSERT INTO peers (tg_peer_id, first_name, last_name, username, is_bot, in_personal)
            VALUES ($1, $2, $3, $4, $5, false)
            ON CONFLICT (tg_peer_id) DO UPDATE SET
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                username = EXCLUDED.username,
                updated_at = now()
            RETURNING id
        """, tg_peer_id, first_name, last_name, username, is_bot)

        display_name = first_name or username or f"ID:{tg_peer_id}"
        logger.info(f"New contact created: {display_name} (peer_id={peer_id})")

        # Проверяем лимит для нового контакта (max 5)
        if not await check_new_contact_limit(conn, peer_id):
            logger.info(f"New contact {display_name}: limit reached, not replying")
            return False

        # Определяем текст ответа
        if mode == 'template':
            reply_text = nc_settings['new_contact_template']
            logger.info(f"New contact reply (template): {reply_text[:30]}...")
        elif mode == 'ai':
            # Получаем настройки AI
            ai_settings = await get_ai_settings(conn)
            nc_prompt = nc_settings['new_contact_prompt']

            # Формируем промпт с контекстом
            ai_settings_copy = ai_settings.copy()
            ai_settings_copy['system_prompt'] = f"{ai_settings['system_prompt']}\n\n{nc_prompt}"

            # Получаем ответ от AI
            reply_text = await generate_ai_response(
                message_text, peer_id, [], ai_settings_copy, nc_prompt
            )
            if not reply_text:
                reply_text = nc_settings['new_contact_template']  # Fallback
                logger.info(f"AI unavailable, using template fallback")
            else:
                logger.info(f"New contact reply (AI): {reply_text[:30]}...")
        else:
            return False

        # Отправляем ответ
        if await send_reply(tg_peer_id, reply_text, reply_to_msg_id=tg_msg_id):
            # Увеличиваем счётчик ответов для нового контакта
            count = await increment_new_contact_reply(conn, peer_id)
            limits = await get_reply_limits(conn)
            logger.info(f"✓ New contact reply sent to {display_name} ({count}/{limits['new_contact_max_replies']})")
            return True
        else:
            logger.error(f"✗ Failed to send new contact reply to {display_name}")
            return False


async def process_auto_replies() -> int:
    """
    Основной цикл обработки автоответов.
    Лимит: max 50 ответов в день на каждого пользователя.
    """
    sent_count = 0

    async with db_pool.acquire() as conn:
        # Проверяем глобальный флаг
        if not await is_auto_reply_enabled(conn):
            return 0

        # Проверяем включен ли AI
        ai_enabled = await is_ai_enabled(conn)

        # Получаем настройки AI из БД
        ai_settings = await get_ai_settings(conn)

        # Получаем кандидатов для ответа
        candidates = await get_candidates_for_reply(conn)

        if candidates:
            logger.info(f"Found {len(candidates)} candidate(s) for auto-reply")

        for candidate in candidates:
            peer_id = candidate['peer_id']
            tg_peer_id = candidate['tg_peer_id']
            template = candidate['template']
            reply_mode = candidate.get('reply_mode', 'ai')
            message_text = candidate['message_text'] or ""
            display_name = candidate['first_name'] or candidate['username'] or f"ID:{tg_peer_id}"
            message_preview = message_text[:30] if message_text else "[media]"

            logger.info(f"Processing: {display_name} (mode={reply_mode}) - \"{message_preview}...\"")

            # Проверяем дневной лимит (max 50)
            if not await check_and_update_daily_limit(conn, peer_id):
                logger.info(f"Skipping {display_name}: daily limit reached")
                continue

            # Определяем текст ответа по reply_mode
            if reply_mode == 'template':
                # Режим template — отправляем шаблон как есть (без AI)
                reply_text = template if template else FALLBACK_MESSAGE
                logger.info(f"Template mode: {reply_text[:50]}...")

            elif reply_mode == 'ai' and ai_enabled and message_text:
                # Режим AI — генерируем через AI
                history = await get_conversation_history(conn, peer_id)
                logger.info(f"Loaded {len(history)} messages from history")

                peer_prompt = template  # template как дополнительные инструкции для AI
                reply_text = await generate_ai_response(message_text, peer_id, history, ai_settings, peer_prompt)

                if reply_text:
                    logger.info(f"AI response: {reply_text[:50]}...")
                else:
                    # AI недоступен — используем fallback
                    reply_text = FALLBACK_MESSAGE
                    logger.info(f"AI unavailable, using fallback: {reply_text}")

            elif reply_mode == 'ai' and not ai_enabled:
                # Режим AI, но AI глобально выключен — используем template
                reply_text = template if template else FALLBACK_MESSAGE
                logger.info(f"AI disabled globally, using template: {reply_text[:50]}...")

            else:
                # Fallback
                reply_text = template if template else FALLBACK_MESSAGE

            # Отправляем ответ (reply_to для привязки к сообщению)
            tg_msg_id = candidate['tg_message_id']
            logger.info(f"Sending reply to tg_peer_id={tg_peer_id}, reply_to={tg_msg_id}")
            if await send_reply(tg_peer_id, reply_text, reply_to_msg_id=tg_msg_id):
                await update_reply_state(conn, peer_id, candidate['message_id'])
                sent_count += 1
                logger.info(f"✓ Reply sent to {display_name} (reply_to={tg_msg_id})")
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


# ============================================
# CHAT TRIGGERS SUPPORT
# ============================================

async def get_chat_triggers(chat_tg_id: int) -> Optional[Dict[str, Any]]:
    """
    Получить триггеры для чата из БД.

    Args:
        chat_tg_id: Telegram ID чата (группы/канала)

    Returns:
        Dict с настройками триггеров или None если чат не настроен
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                ct.id,
                ct.peer_id,
                ct.enabled,
                ct.trigger_mention,
                ct.trigger_reply,
                ct.trigger_keywords,
                ct.trigger_random,
                ct.keywords,
                ct.random_interval_min,
                ct.random_interval_max,
                ct.last_random_time,
                ct.cooldown_sec,
                ct.daily_limit,
                ct.daily_count,
                ct.last_count_reset,
                p.tg_peer_id,
                p.first_name,
                p.username
            FROM chat_triggers ct
            JOIN peers p ON p.id = ct.peer_id
            WHERE p.tg_peer_id = $1 AND ct.enabled = true AND ct.account_id = $2
        """, chat_tg_id, ACCOUNT_ID)

        if row:
            return dict(row)
        return None


async def check_chat_triggers(
    chat_tg_id: int,
    message_text: str,
    is_mention: bool,
    is_reply_to_me: bool,
    my_username: str
) -> Optional[str]:
    """
    Проверить, нужно ли отвечать на сообщение в чате.

    Args:
        chat_tg_id: Telegram ID чата
        message_text: Текст сообщения
        is_mention: Упомянули ли нас (@username)
        is_reply_to_me: Это ответ на наше сообщение
        my_username: Наш username

    Returns:
        str: Причина срабатывания ('mention', 'reply', 'keyword') или None
    """
    triggers = await get_chat_triggers(chat_tg_id)

    if not triggers:
        return None

    # Проверяем лимиты
    if not await check_chat_limits(triggers['peer_id']):
        logger.debug(f"Chat {chat_tg_id}: daily limit reached")
        return None

    # Проверяем cooldown
    if triggers.get('cooldown_sec') and triggers.get('last_random_time'):
        now = datetime.now(timezone.utc)
        last_time = triggers['last_random_time']
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        elapsed = (now - last_time).total_seconds()
        if elapsed < triggers['cooldown_sec']:
            logger.debug(f"Chat {chat_tg_id}: cooldown active ({elapsed:.0f}/{triggers['cooldown_sec']}s)")
            return None

    # Проверяем триггеры по приоритету

    # 1. Упоминание (@username)
    if triggers['trigger_mention'] and is_mention:
        logger.info(f"Chat {chat_tg_id}: triggered by mention")
        return 'mention'

    # 2. Ответ на наше сообщение
    if triggers['trigger_reply'] and is_reply_to_me:
        logger.info(f"Chat {chat_tg_id}: triggered by reply")
        return 'reply'

    # 3. Ключевые слова
    if triggers['trigger_keywords'] and triggers.get('keywords'):
        keywords = [kw.strip().lower() for kw in triggers['keywords'].split(',') if kw.strip()]
        message_lower = message_text.lower()
        for keyword in keywords:
            if keyword in message_lower:
                logger.info(f"Chat {chat_tg_id}: triggered by keyword '{keyword}'")
                return 'keyword'

    return None


async def check_chat_limits(peer_id: int) -> bool:
    """
    Проверить лимиты для чата.

    Args:
        peer_id: Внутренний ID чата из peers

    Returns:
        bool: True если можно отвечать, False если лимит исчерпан
    """
    async with db_pool.acquire() as conn:
        today = datetime.now(timezone.utc).date()

        row = await conn.fetchrow("""
            SELECT daily_count, daily_limit, last_count_reset
            FROM chat_triggers
            WHERE peer_id = $1 AND account_id = $2
        """, peer_id, ACCOUNT_ID)

        if not row:
            return False

        # Сброс счётчика если новый день
        if row['last_count_reset'] != today:
            await conn.execute("""
                UPDATE chat_triggers
                SET daily_count = 0, last_count_reset = $1
                WHERE peer_id = $2 AND account_id = $3
            """, today, peer_id, ACCOUNT_ID)
            return True

        # Проверяем лимит
        if row['daily_count'] >= row['daily_limit']:
            return False

        return True


async def update_chat_counters(peer_id: int) -> None:
    """
    Обновить счётчики после отправки ответа в чат.

    Args:
        peer_id: Внутренний ID чата из peers
    """
    async with db_pool.acquire() as conn:
        today = datetime.now(timezone.utc).date()

        await conn.execute("""
            UPDATE chat_triggers
            SET
                daily_count = CASE
                    WHEN last_count_reset != $1 THEN 1
                    ELSE daily_count + 1
                END,
                last_count_reset = $1,
                last_random_time = now(),
                updated_at = now()
            WHERE peer_id = $2 AND account_id = $3
        """, today, peer_id, ACCOUNT_ID)


async def get_or_create_chat_peer(conn, chat_tg_id: int, title: str = None) -> int:
    """
    Получить или создать запись peer для чата.

    Args:
        conn: Соединение с БД
        chat_tg_id: Telegram ID чата
        title: Название чата

    Returns:
        int: Внутренний peer_id
    """
    row = await conn.fetchrow("""
        INSERT INTO peers (tg_peer_id, first_name, peer_type, is_bot)
        VALUES ($1, $2, 'chat', false)
        ON CONFLICT (tg_peer_id) DO UPDATE SET
            first_name = COALESCE(EXCLUDED.first_name, peers.first_name),
            updated_at = now()
        RETURNING id
    """, chat_tg_id, title)

    return row['id']


async def process_chat_message(
    chat_tg_id: int,
    chat_title: str,
    message_text: str,
    tg_msg_id: int,
    trigger_reason: str,
    peer_id: int
) -> bool:
    """
    Обработать сообщение в чате и отправить ответ.

    Args:
        chat_tg_id: Telegram ID чата
        chat_title: Название чата
        message_text: Текст сообщения
        tg_msg_id: ID сообщения для reply
        trigger_reason: Причина срабатывания (mention/reply/keyword)
        peer_id: Внутренний ID чата из peers

    Returns:
        bool: True если ответ отправлен
    """
    async with db_pool.acquire() as conn:
        # Проверяем глобальный флаг
        if not await is_auto_reply_enabled(conn):
            return False

        # Проверяем AI
        ai_enabled = await is_ai_enabled(conn)
        ai_settings = await get_ai_settings(conn)

        # Формируем контекст для AI
        context_prompt = f"Сообщение в групповом чате '{chat_title}'. "
        if trigger_reason == 'mention':
            context_prompt += "Тебя упомянули по имени. "
        elif trigger_reason == 'reply':
            context_prompt += "Это ответ на твоё сообщение. "
        elif trigger_reason == 'keyword':
            context_prompt += "В сообщении есть ключевое слово. "
        context_prompt += "Отвечай кратко и по делу."

        # Генерируем ответ
        if ai_enabled:
            reply_text = await generate_ai_response(
                message_text,
                peer_id,
                [],  # Нет истории для чатов
                ai_settings,
                context_prompt
            )
            if not reply_text:
                reply_text = FALLBACK_MESSAGE
        else:
            reply_text = FALLBACK_MESSAGE

        # Отправляем ответ
        if await send_reply(chat_tg_id, reply_text, reply_to_msg_id=tg_msg_id):
            await update_chat_counters(peer_id)
            logger.info(f"✓ Chat reply sent to '{chat_title}' (trigger: {trigger_reason})")
            return True
        else:
            logger.error(f"✗ Failed to send chat reply to '{chat_title}'")
            return False


async def random_chat_task(tg_client):
    """Фоновая задача для рандомных сообщений в чатах.
    Проверяет раз в минуту, нужно ли отправить рандомное сообщение.

    Условия отправки:
    - trigger_random включён для чата
    - Прошёл интервал random_interval_min..random_interval_max минут
    - Не превышен daily_limit
    - Последнее сообщение в чате НЕ от меня
    """
    logger.info("Random chat task started")
    me = await tg_client.get_me()
    my_id = me.id

    while True:
        try:
            await asyncio.sleep(60)

            async with db_pool.acquire() as conn:
                chats = await conn.fetch("""
                    SELECT ct.*, p.tg_peer_id, p.first_name as chat_name
                    FROM chat_triggers ct
                    JOIN peers p ON p.id = ct.peer_id
                    WHERE ct.enabled = true
                      AND ct.trigger_random = true
                      AND ct.daily_count < ct.daily_limit
                      AND (
                          ct.last_random_time IS NULL
                          OR EXTRACT(EPOCH FROM (now() - ct.last_random_time)) / 60 >= ct.random_interval_min
                      )
                """)

                for chat in chats:
                    try:
                        # Проверка рандомного интервала
                        if chat['last_random_time']:
                            minutes_passed = (datetime.now(timezone.utc) - chat['last_random_time']).total_seconds() / 60
                            random_interval = chat['random_interval_min'] + random.random() * (chat['random_interval_max'] - chat['random_interval_min'])
                            if minutes_passed < random_interval:
                                continue

                        # ВАЖНО: Если последнее сообщение от меня — пропускаем
                        last_messages = await tg_client.get_messages(chat['tg_peer_id'], limit=1)
                        if last_messages and last_messages[0].sender_id == my_id:
                            logger.debug(f"Skip {chat['chat_name']}: last message is mine")
                            continue

                        # Загружаем контекст (30 сообщений)
                        context_messages = await tg_client.get_messages(chat['tg_peer_id'], limit=30)
                        context = "\n".join([
                            f"{getattr(m.sender, 'first_name', 'User')}: {m.text}"
                            for m in reversed(context_messages) if m and m.text
                        ])

                        # Генерируем сообщение через AI
                        ai_settings = await get_ai_settings(conn)
                        random_prompt = f"Контекст чата:\n{context}\n\nНапиши короткое уместное сообщение в этот чат. Не задавай вопросов, просто участвуй в разговоре."
                        response = await generate_ai_response(
                            random_prompt,
                            chat['peer_id'],
                            [],
                            ai_settings,
                            None
                        )

                        if response:
                            await tg_client.send_message(chat['tg_peer_id'], response)
                            await update_chat_counters(chat['peer_id'])
                            logger.info(f"🎲 Random message sent to chat {chat['chat_name']}")

                        await asyncio.sleep(5)

                    except Exception as e:
                        logger.error(f"Random message error for chat {chat['tg_peer_id']}: {e}")

        except Exception as e:
            logger.error(f"Random chat task error: {e}")
            await asyncio.sleep(60)


async def main() -> None:
    """Главная функция worker"""
    global client
    
    logger.info("=" * 60)
    logger.info("Auto-Reply Worker v2.13 (random chat messages)")
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
    my_id = me.id
    my_username = me.username or ""
    logger.info(f"Logged in as: {me.first_name} (@{my_username or 'no username'}) [ID: {my_id}]")

    # Обработчик новых входящих сообщений (личные + чаты)
    @client.on(events.NewMessage(incoming=True))
    async def handle_new_message(event):
        """
        Обработка входящих сообщений:
        1. Личные сообщения от новых контактов
        2. Сообщения в чатах с настроенными триггерами
        """
        try:
            message_text = event.message.text or ""
            tg_msg_id = event.message.id

            # === ОБРАБОТКА ГРУППОВЫХ ЧАТОВ ===
            if not event.is_private:
                chat = await event.get_chat()
                if not isinstance(chat, (Chat, Channel)):
                    return

                chat_tg_id = chat.id
                chat_title = getattr(chat, 'title', '') or f"Chat:{chat_tg_id}"

                # Проверяем: упомянули ли нас
                is_mention = False
                if my_username and f"@{my_username.lower()}" in message_text.lower():
                    is_mention = True

                # Проверяем: это ответ на наше сообщение
                is_reply_to_me = False
                if event.message.reply_to:
                    try:
                        reply_msg = await event.message.get_reply_message()
                        if reply_msg and reply_msg.sender_id == my_id:
                            is_reply_to_me = True
                    except:
                        pass

                # Проверяем триггеры
                trigger_reason = await check_chat_triggers(
                    chat_tg_id,
                    message_text,
                    is_mention,
                    is_reply_to_me,
                    my_username
                )

                if trigger_reason:
                    # Получаем peer_id для чата
                    triggers = await get_chat_triggers(chat_tg_id)
                    if triggers:
                        peer_id = triggers['peer_id']
                        await process_chat_message(
                            chat_tg_id,
                            chat_title,
                            message_text,
                            tg_msg_id,
                            trigger_reason,
                            peer_id
                        )
                return

            # === ОБРАБОТКА ЛИЧНЫХ СООБЩЕНИЙ ===
            sender = await event.get_sender()
            if not sender or not isinstance(sender, User):
                return

            # Пропускаем ботов
            if sender.bot:
                return

            tg_peer_id = sender.id

            # Проверяем: это "новый контакт" или уже обрабатывается основным циклом?
            async with db_pool.acquire() as conn:
                # Проверяем: в Personal или есть активное правило?
                row = await conn.fetchrow("""
                    SELECT p.id, p.in_personal,
                           EXISTS(SELECT 1 FROM auto_reply_rules r
                                  WHERE r.peer_id = p.id AND r.enabled = true) as has_rule
                    FROM peers p WHERE p.tg_peer_id = $1
                """, tg_peer_id)

                if row:
                    # Пользователь есть в peers
                    if row['in_personal'] or row['has_rule']:
                        # В Personal или есть правило — обрабатывается основным циклом
                        return
                    # Не в Personal и нет правила — это "новый контакт", продолжаем
                    logger.info(f"📨 Message from non-Personal contact: {sender.first_name} (@{sender.username})")
                else:
                    # Совсем новый (нет в peers)
                    logger.info(f"🆕 New contact: {sender.first_name} (@{sender.username}) [ID: {tg_peer_id}]")

                # Обрабатываем нового контакта (создаст peer если нет, и ответит)
                result = await process_new_contact(tg_peer_id, message_text, tg_msg_id)
                if result:
                    logger.info(f"✓ New contact handled: {sender.first_name}")

        except Exception as e:
            logger.error(f"Error handling new message: {e}")

    # Первичная загрузка Personal folder
    logger.info("Loading Personal folder cache...")
    await refresh_personal_cache()
    await sync_personal_to_db()
    logger.info(f"Personal cache: {len(personal_cache)} users")

    logger.info("=" * 60)
    logger.info("Worker started. Press Ctrl+C to stop")
    logger.info("=" * 60)

    # Фоновая задача для периодической обработки автоответов
    async def polling_loop():
        total_sent = 0
        iterations = 0

        while True:
            iterations += 1

            # Обновляем кэш Personal раз в час
            if await is_personal_cache_stale():
                logger.info("Refreshing Personal folder cache...")
                await refresh_personal_cache()
                await sync_personal_to_db()

            try:
                sent = await process_auto_replies()
                total_sent += sent

                if sent > 0:
                    logger.info(f"Iteration {iterations}: Sent {sent} reply(ies). Total: {total_sent}")

            except Exception as e:
                logger.error(f"Error in processing loop: {e}")

            await asyncio.sleep(CHECK_INTERVAL)

    # Запускаем polling loop как фоновую задачу
    polling_task = asyncio.create_task(polling_loop())

    # Запускаем random chat task для рандомных сообщений в чатах
    random_task = asyncio.create_task(random_chat_task(client))

    try:
        # run_until_disconnected для обработки событий Telethon
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal...")
    finally:
        polling_task.cancel()
        random_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
        try:
            await random_task
        except asyncio.CancelledError:
            pass
        await client.disconnect()
        await close_http()
        await close_db()
        logger.info("Worker stopped.")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
