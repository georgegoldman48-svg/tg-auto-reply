#!/usr/bin/env python3
"""
Settings API для управления настройками AI автоответчика.

Запуск:
    python settings_api.py

Endpoints:
    GET  /api/settings  - получить все настройки
    POST /api/settings  - обновить настройки
    GET  /health        - проверка статуса

Порт: 8085
"""

import os
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import asyncpg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import uvicorn

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
PORT = 8085

# Пул подключений к БД
db_pool: Optional[asyncpg.Pool] = None


class SettingsUpdate(BaseModel):
    ai_engine: Optional[str] = None  # "local" или "claude"
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
    print(f"Database pool initialized")
    yield
    await db_pool.close()
    print("Database pool closed")


app = FastAPI(title="Settings API", lifespan=lifespan)

# CORS для доступа с локального Web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Проверка статуса API"""
    return {"status": "ok", "service": "settings-api"}


@app.get("/api/settings")
async def get_settings():
    """Получить все настройки AI"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT key, value FROM settings
            WHERE key IN ('ai_engine', 'system_prompt', 'temperature', 'max_tokens')
        """)

    settings = {}
    for row in rows:
        key = row['key']
        value = row['value']

        # Преобразуем типы
        if key == 'temperature':
            settings[key] = float(value)
        elif key == 'max_tokens':
            settings[key] = int(value)
        else:
            settings[key] = value

    return settings


@app.post("/api/settings")
async def update_settings(data: SettingsUpdate):
    """Обновить настройки AI"""
    updates = []

    if data.ai_engine is not None:
        if data.ai_engine not in ('local', 'claude'):
            raise HTTPException(400, "ai_engine must be 'local' or 'claude'")
        updates.append(('ai_engine', data.ai_engine))

    if data.system_prompt is not None:
        updates.append(('system_prompt', data.system_prompt))

    if data.temperature is not None:
        if not 0.0 <= data.temperature <= 2.0:
            raise HTTPException(400, "temperature must be between 0.0 and 2.0")
        updates.append(('temperature', str(data.temperature)))

    if data.max_tokens is not None:
        if not 10 <= data.max_tokens <= 4096:
            raise HTTPException(400, "max_tokens must be between 10 and 4096")
        updates.append(('max_tokens', str(data.max_tokens)))

    if not updates:
        raise HTTPException(400, "No settings to update")

    async with db_pool.acquire() as conn:
        for key, value in updates:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES ($1, $2, now())
                ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now()
            """, key, value)

    # Вернуть обновлённые настройки
    return await get_settings()


if __name__ == "__main__":
    print("=" * 50)
    print("Settings API")
    print("=" * 50)
    print(f"Port: {PORT}")
    print(f"Endpoints:")
    print(f"  GET  http://0.0.0.0:{PORT}/api/settings")
    print(f"  POST http://0.0.0.0:{PORT}/api/settings")
    print("=" * 50)

    uvicorn.run(app, host="0.0.0.0", port=PORT)
