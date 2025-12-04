#!/usr/bin/env python3
"""
Синхронизация папки Personal с БД.
Обновляет поле in_personal для пользователей из папки.
"""
import asyncio
import os
from dotenv import load_dotenv
import asyncpg
from telethon import TelegramClient
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import User

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

async def main():
    # Подключение к Telegram
    client = TelegramClient(
        '/home/aiuser/tg-auto-reply/sessions/worker',
        int(os.getenv('API_ID')),
        os.getenv('API_HASH')
    )
    await client.connect()

    if not await client.is_user_authorized():
        print('Session not authorized!')
        return

    print('=== Синхронизация папки Personal ===')

    # Получаем папки
    result = await client(GetDialogFiltersRequest())
    filters = result if isinstance(result, list) else result.filters

    # Ищем Personal по title
    personal = None
    for f in filters:
        if hasattr(f, 'title') and f.title == 'Personal':
            personal = f
            print(f'Найдена папка Personal (id={f.id})')
            break

    if not personal:
        print('Папка Personal не найдена!')
        await client.disconnect()
        return

    # Собираем exclude IDs
    exclude_ids = set()
    for p in personal.exclude_peers:
        if hasattr(p, 'user_id'):
            exclude_ids.add(p.user_id)
    print(f'Исключённые пользователи: {len(exclude_ids)}')

    # Собираем все user IDs из Personal
    personal_ids = set()
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, User):
            if entity.bot:  # bots=False в Personal
                continue
            if entity.id in exclude_ids:
                continue
            personal_ids.add(entity.id)

    print(f'Пользователей в Personal: {len(personal_ids)}')

    # Подключение к БД
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)

    async with pool.acquire() as conn:
        # Сбросить все
        await conn.execute("UPDATE peers SET in_personal = false")

        # Установить true для Personal
        if personal_ids:
            result = await conn.execute(
                "UPDATE peers SET in_personal = true WHERE tg_peer_id = ANY($1::bigint[])",
                list(personal_ids)
            )
            print(f'Обновлено записей: {result}')

        # Статистика
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM peers WHERE in_personal = true"
        )
        print(f'Пользователей с in_personal=true: {count}')

        # Показать кого обновили
        rows = await conn.fetch(
            "SELECT tg_peer_id, first_name, username FROM peers WHERE in_personal = true LIMIT 10"
        )
        print('\nПримеры (первые 10):')
        for r in rows:
            name = r['first_name'] or 'N/A'
            user = f"@{r['username']}" if r['username'] else ''
            print(f"  {r['tg_peer_id']}: {name} {user}")

    await pool.close()
    await client.disconnect()
    print('\n=== Синхронизация завершена ===')

if __name__ == '__main__':
    asyncio.run(main())
