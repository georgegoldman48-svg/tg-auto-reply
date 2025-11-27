"""
Модуль подключения к базе данных
"""
import asyncpg
import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger(__name__)

db_pool: Optional[asyncpg.Pool] = None


async def init_db_pool() -> asyncpg.Pool:
    """Инициализация пула соединений"""
    global db_pool
    
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Please set it in .env file or environment variables."
        )
    
    if db_pool is None:
        try:
            db_pool = await asyncpg.create_pool(
                dsn,
                min_size=5,
                max_size=20,
                command_timeout=60
            )
            logger.info("Database pool initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise
    
    return db_pool


async def close_db_pool() -> None:
    """Закрытие пула соединений"""
    global db_pool
    if db_pool:
        await db_pool.close()
        db_pool = None
        logger.info("Database pool closed")


def get_db_pool() -> asyncpg.Pool:
    """Получить пул соединений"""
    if db_pool is None:
        raise RuntimeError(
            "Database pool not initialized. "
            "Make sure the application lifespan has started."
        )
    return db_pool


@asynccontextmanager
async def get_db_connection():
    """Контекстный менеджер для получения соединения из пула"""
    pool = get_db_pool()
    async with pool.acquire() as connection:
        yield connection
