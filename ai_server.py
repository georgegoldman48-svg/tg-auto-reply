#!/usr/bin/env python3
"""
AI Server для Telegram Auto-Reply

Загружает SambaLingo-Russian-Chat + LoRA адаптер Егора
и отвечает на запросы от worker на VPS3.

Запуск:
    python ai_server.py

Затем SSH туннель:
    ssh -N -R 8080:localhost:8080 root@188.116.27.68

Endpoints:
    GET  /health   - проверка статуса
    POST /generate - генерация ответа
"""

import json
import logging
import random
import re
import torch
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import List, Dict, Any, Optional

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация
HOST = "0.0.0.0"
PORT = 8080
LORA_PATH = "/home/george/sambalingo-egor"
MAX_SEQ_LENGTH = 512
SYSTEM_PROMPT = "Ты Егор. Отвечаешь коротко, живо, по делу. Без воды и официоза."

# Fallback ответы для слишком коротких генераций
FALLBACK_RESPONSES = ["ага", "ок", "понял", "да", "ну да", "угу"]

# Специальные токены для очистки
SPECIAL_TOKENS = ["<|im_end|>", "<|im_start|>", "</s>", "<s>", "<|endoftext|>"]

# Глобальные переменные для модели
model = None
tokenizer = None


def load_model():
    """Загрузка модели с LoRA адаптером"""
    global model, tokenizer

    from unsloth import FastLanguageModel

    logger.info("=" * 60)
    logger.info("Загрузка SambaLingo + LoRA адаптер...")
    logger.info(f"LoRA path: {LORA_PATH}")
    logger.info("=" * 60)

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=LORA_PATH,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,
        load_in_4bit=True,
    )

    FastLanguageModel.for_inference(model)

    # Информация о GPU
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
        logger.info(f"GPU: {gpu_name} ({gpu_mem:.1f} GB)")

    logger.info("Модель загружена!")


def generate_response(
    prompt: str,
    history: Optional[List[Dict[str, Any]]] = None,
    max_new_tokens: int = 100,
    temperature: float = 0.7
) -> str:
    """
    Генерация ответа с учётом истории диалога.

    Args:
        prompt: Текущее сообщение пользователя
        history: История диалога [{"role": "user/assistant", "content": "..."}]
        max_new_tokens: Максимум токенов в ответе
        temperature: Температура генерации

    Returns:
        Сгенерированный ответ
    """
    # Формируем контекст с историей
    messages = []

    # Добавляем историю (последние сообщения)
    if history:
        # Берём последние N сообщений чтобы не превысить контекст
        recent_history = history[-10:]  # Последние 10 сообщений
        messages.extend(recent_history)

    # Добавляем текущий вопрос
    messages.append({"role": "user", "content": prompt})

    # Формируем промпт в ChatML формате
    input_text = f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"

    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        input_text += f"<|im_start|>{role}\n{content}<|im_end|>\n"

    input_text += "<|im_start|>assistant\n"

    # Токенизация
    inputs = tokenizer(input_text, return_tensors="pt").to("cuda")

    # Генерация
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
            repetition_penalty=1.1,
        )

    # Декодирование
    response = tokenizer.decode(outputs[0], skip_special_tokens=False)

    # Извлекаем только ответ ассистента
    if "<|im_start|>assistant" in response:
        answer = response.split("<|im_start|>assistant")[-1]
        answer = answer.split("<|im_end|>")[0].strip()
    else:
        answer = response

    # Обрезаем всё после первого <| (специальные токены)
    if '<|' in answer:
        answer = answer.split('<|')[0]

    # Убираем </s> и другие токены
    answer = answer.replace('</s>', '').replace('<s>', '')

    # Убираем возможные артефакты
    answer = answer.rstrip('<').strip()
    if answer.startswith("\n"):
        answer = answer[1:]

    # Fallback для слишком коротких ответов
    if len(answer) < 2:
        answer = random.choice(FALLBACK_RESPONSES)
        logger.info(f"Короткий ответ, используем fallback: {answer}")

    return answer


class AIRequestHandler(BaseHTTPRequestHandler):
    """HTTP обработчик запросов"""

    def log_message(self, format, *args):
        """Переопределяем логирование"""
        logger.info(f"{self.address_string()} - {args[0]}")

    def send_json_response(self, data: dict, status: int = 200):
        """Отправка JSON ответа"""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        """Обработка GET запросов"""
        if self.path == "/health":
            gpu_name = "N/A"
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)

            self.send_json_response({
                "status": "ok",
                "model": "SambaLingo-Russian-Chat + LoRA (Egor)",
                "gpu": gpu_name,
                "ready": model is not None
            })
        else:
            self.send_json_response({"error": "Not found"}, 404)

    def do_POST(self):
        """Обработка POST запросов"""
        if self.path == "/generate":
            try:
                # Читаем тело запроса
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(body)

                prompt = data.get("prompt", "")
                history = data.get("history", [])
                peer_id = data.get("peer_id", 0)

                if not prompt:
                    self.send_json_response({"error": "prompt is required"}, 400)
                    return

                logger.info(f"[peer:{peer_id}] Q: {prompt[:50]}...")

                # Генерируем ответ
                response = generate_response(prompt, history)

                logger.info(f"[peer:{peer_id}] A: {response[:50]}...")

                self.send_json_response({"response": response})

            except json.JSONDecodeError:
                self.send_json_response({"error": "Invalid JSON"}, 400)
            except Exception as e:
                logger.error(f"Generation error: {e}")
                self.send_json_response({"error": str(e)}, 500)
        else:
            self.send_json_response({"error": "Not found"}, 404)


def main():
    """Запуск сервера"""
    logger.info("=" * 60)
    logger.info("AI Server для Telegram Auto-Reply")
    logger.info("=" * 60)

    # Загружаем модель
    load_model()

    # Запускаем HTTP сервер
    server = HTTPServer((HOST, PORT), AIRequestHandler)

    logger.info("=" * 60)
    logger.info(f"Сервер запущен: http://{HOST}:{PORT}")
    logger.info("")
    logger.info("Endpoints:")
    logger.info(f"  GET  http://localhost:{PORT}/health")
    logger.info(f"  POST http://localhost:{PORT}/generate")
    logger.info("")
    logger.info("Для подключения к VPS3 запустите:")
    logger.info("  ssh -N -R 8080:localhost:8080 root@188.116.27.68")
    logger.info("")
    logger.info("Нажмите Ctrl+C для остановки")
    logger.info("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nОстановка сервера...")
        server.shutdown()
        logger.info("Сервер остановлен")


if __name__ == "__main__":
    main()
