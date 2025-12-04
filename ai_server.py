#!/usr/bin/env python3
"""
AI Server для Telegram Auto-Reply

Использует обученную модель egor:latest через Ollama API.
FastAPI сервер с endpoints /health и /generate.

Запуск:
    python ai_server.py

Затем SSH туннель:
    ssh -N -R 8080:localhost:8080 root@188.116.27.68

Endpoints:
    GET  /health   - проверка статуса
    POST /generate - генерация ответа
    GET  /settings - текущие настройки
    POST /settings - обновить настройки
"""

import asyncio
import logging
import os
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

# Отключаем прокси для localhost
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)
os.environ.pop('ALL_PROXY', None)
os.environ.pop('all_proxy', None)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Egor AI Server", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Конфигурация
OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "egor:latest"

# Глобальные настройки (можно менять через /settings)
current_settings = {
    "system_prompt": "Ты Жора (Егор). Отвечай коротко, живо, неформально.",
    "temperature": 0.7,
    "max_tokens": 100
}


class GenerateRequest(BaseModel):
    prompt: str
    history: Optional[List[Dict[str, Any]]] = None
    peer_id: Optional[int] = 0
    peer_prompt: Optional[str] = None
    system_prompt: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None


class GenerateResponse(BaseModel):
    response: str
    model: Optional[str] = None
    tokens_used: Optional[int] = None


class HealthResponse(BaseModel):
    status: str
    model: str
    ollama_status: str
    ready: bool


class SettingsRequest(BaseModel):
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Проверка здоровья сервера и модели"""
    try:
        # proxy=None чтобы не использовать системные прокси для localhost
        async with httpx.AsyncClient(timeout=10.0, proxy=None) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            if resp.status_code != 200:
                return HealthResponse(
                    status="degraded",
                    model=MODEL_NAME,
                    ollama_status="unavailable",
                    ready=False
                )

            models = resp.json().get("models", [])
            model_found = any(m.get("name") == MODEL_NAME for m in models)

            if not model_found:
                return HealthResponse(
                    status="degraded",
                    model=MODEL_NAME,
                    ollama_status=f"model {MODEL_NAME} not found",
                    ready=False
                )

            return HealthResponse(
                status="healthy",
                model=MODEL_NAME,
                ollama_status="connected",
                ready=True
            )
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return HealthResponse(
            status="unhealthy",
            model=MODEL_NAME,
            ollama_status=f"error: {str(e)}",
            ready=False
        )


@app.get("/settings")
async def get_settings():
    """Получить текущие настройки"""
    return current_settings


@app.post("/settings")
async def update_settings(request: SettingsRequest):
    """Обновить настройки"""
    if request.system_prompt is not None:
        current_settings["system_prompt"] = request.system_prompt
    if request.temperature is not None:
        current_settings["temperature"] = request.temperature
    if request.max_tokens is not None:
        current_settings["max_tokens"] = request.max_tokens

    logger.info(f"Settings updated: temp={current_settings['temperature']}, "
                f"max={current_settings['max_tokens']}, "
                f"prompt={current_settings['system_prompt'][:30]}...")

    return {"status": "ok", "settings": current_settings}


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest):
    """Генерация ответа с помощью модели"""
    peer_id = request.peer_id or 0
    logger.info(f"[peer:{peer_id}] Q: {request.prompt[:50]}...")

    # Берём настройки из запроса или из глобальных
    system_prompt = request.system_prompt or current_settings["system_prompt"]
    temperature = request.temperature or current_settings["temperature"]
    max_tokens = request.max_tokens or current_settings["max_tokens"]

    # Добавляем peer_prompt если есть
    if request.peer_prompt:
        system_prompt = f"{system_prompt}\n\nДополнительно: {request.peer_prompt}"

    try:
        # proxy=None чтобы не использовать системные прокси для localhost
        async with httpx.AsyncClient(timeout=60.0, proxy=None) as client:
            payload = {
                "model": MODEL_NAME,
                "prompt": request.prompt,
                "system": system_prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "stop": ["<|im_start|>", "<|im_end|>", "\n\n"]
                }
            }

            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json=payload
            )

            if resp.status_code != 200:
                logger.error(f"Ollama error: {resp.status_code} - {resp.text}")
                raise HTTPException(
                    status_code=502,
                    detail=f"Ollama API error: {resp.status_code}"
                )

            data = resp.json()
            response_text = data.get("response", "").strip()

            # Убираем возможные артефакты
            if "<|" in response_text:
                response_text = response_text.split("<|")[0].strip()
            response_text = response_text.replace("</s>", "").replace("<s>", "").strip()

            logger.info(f"[peer:{peer_id}] A: {response_text[:50]}...")

            return GenerateResponse(
                response=response_text,
                model=MODEL_NAME,
                tokens_used=data.get("eval_count")
            )

    except httpx.TimeoutException:
        logger.error("Ollama timeout")
        raise HTTPException(status_code=504, detail="Generation timeout")
    except Exception as e:
        logger.error(f"Generate error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    """Информация о сервере"""
    return {
        "name": "Egor AI Server",
        "version": "2.0.0",
        "model": MODEL_NAME,
        "endpoints": ["/health", "/generate", "/settings"]
    }


if __name__ == "__main__":
    import uvicorn
    logger.info("=" * 60)
    logger.info("AI Server для Telegram Auto-Reply")
    logger.info(f"Model: {MODEL_NAME}")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Для подключения к VPS3 запустите:")
    logger.info("  ssh -N -R 8080:localhost:8080 root@188.116.27.68")
    logger.info("")
    uvicorn.run(app, host="0.0.0.0", port=8080)
