"""
Главное FastAPI приложение - TG Auto-Reply Core API
"""
from fastapi import FastAPI
from contextlib import asynccontextmanager
import os
import logging
from dotenv import load_dotenv

from .db import init_db_pool, close_db_pool, get_db_connection
from .router import router as rules_router, peers_router

# Загрузка .env
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    logger.info("Starting Core API...")
    try:
        await init_db_pool()
        logger.info("Core API started successfully")
    except Exception as e:
        logger.error(f"Failed to start Core API: {e}")
        raise
    
    yield
    
    logger.info("Shutting down Core API...")
    await close_db_pool()
    logger.info("Core API shut down successfully")


app = FastAPI(
    title="TG Auto-Reply Core API",
    version="1.0.0",
    description="REST API для управления автоответчиком Telegram",
    lifespan=lifespan
)

# Подключаем роутеры
app.include_router(rules_router)
app.include_router(peers_router)


@app.get("/health")
async def health():
    """Проверка здоровья сервиса"""
    return {"status": "ok", "service": "core-api", "version": "1.0.0"}


@app.get("/")
async def root():
    """Корневой эндпоинт"""
    return {
        "service": "TG Auto-Reply Core API",
        "version": "1.0.0",
        "status": "MVP - Single Account",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "rules": "/rules",
            "peers": "/peers",
            "settings": "/settings"
        }
    }


@app.get("/settings/{key}")
async def get_setting(key: str):
    """Получить значение настройки"""
    try:
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                "SELECT value, updated_at FROM settings WHERE key = $1",
                key
            )
            if not row:
                return {"key": key, "value": None, "exists": False}
            return {"key": key, "value": row['value'], "updated_at": row['updated_at'], "exists": True}
    except Exception as e:
        logger.error(f"Failed to get setting {key}: {e}")
        return {"key": key, "error": str(e)}


@app.put("/settings/{key}")
async def set_setting(key: str, value: str):
    """Установить значение настройки"""
    try:
        async with get_db_connection() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES ($1, $2, now())
                ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now()
            """, key, value)
            logger.info(f"Setting {key} updated to {value}")
            return {"key": key, "value": value, "status": "updated"}
    except Exception as e:
        logger.error(f"Failed to set setting {key}: {e}")
        return {"key": key, "error": str(e)}


@app.get("/stats")
async def get_stats():
    """Получить статистику системы"""
    try:
        async with get_db_connection() as conn:
            total_messages = await conn.fetchval("SELECT COUNT(*) FROM messages")
            total_peers = await conn.fetchval("SELECT COUNT(*) FROM peers WHERE is_bot = false")
            total_rules = await conn.fetchval("SELECT COUNT(*) FROM auto_reply_rules WHERE account_id = 1")
            active_rules = await conn.fetchval(
                "SELECT COUNT(*) FROM auto_reply_rules WHERE account_id = 1 AND enabled = true"
            )
            today_messages = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE date >= CURRENT_DATE"
            )
            auto_reply_enabled = await conn.fetchval(
                "SELECT value FROM settings WHERE key = 'auto_reply_enabled'"
            )
            
            return {
                "total_messages": total_messages or 0,
                "total_peers": total_peers or 0,
                "total_rules": total_rules or 0,
                "active_rules": active_rules or 0,
                "today_messages": today_messages or 0,
                "auto_reply_enabled": auto_reply_enabled == '1'
            }
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return {"error": str(e)}
