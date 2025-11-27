# Telegram Auto-Reply Service

> **v1.0** — Полнофункциональный автоответчик для Telegram

## 🎯 Возможности

- ✅ Сбор истории сообщений из личных чатов
- ✅ Real-time слушатель новых сообщений
- ✅ Автоматические ответы по настроенным правилам
- ✅ Управление через Telegram-бота
- ✅ REST API для интеграции
- ✅ Готов к production (systemd)

## 📦 Компоненты

| Компонент | Описание | Файл |
|-----------|----------|------|
| **Core API** | REST API для управления | `core/main.py` |
| **Collector** | Сбор сообщений (Telethon) | `collector/collector.py` |
| **Worker** | Отправка автоответов | `worker/auto_reply.py` |
| **Admin Bot** | Управление через Telegram | `bots/admin_bot.py` |

## 🚀 Быстрый старт

### 1. Клонирование и установка

```bash
git clone https://github.com/georgegoldman48-svg/tg-auto-reply.git
cd tg-auto-reply

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Конфигурация

```bash
cp .env.example .env
nano .env
```

Заполните:
- `DATABASE_URL` — строка подключения к PostgreSQL
- `API_ID`, `API_HASH` — с [my.telegram.org](https://my.telegram.org)
- `PHONE_NUMBER` — ваш номер телефона
- `ADMIN_BOT_TOKEN` — токен от [@BotFather](https://t.me/botfather)
- `ADMIN_USER_ID` — ваш Telegram user_id

### 3. База данных

```bash
# Создание базы
sudo -u postgres createdb ai_tg_core

# Применение схемы
psql -d ai_tg_core < docs/DB_SCHEMA.sql
```

### 4. Первый запуск Collector

```bash
# Авторизация в Telegram (один раз)
python -m collector.collector

# При первом запуске введите код из Telegram
# После успешного входа можно использовать Ctrl+C
```

### 5. Запуск всех сервисов

```bash
# Терминал 1: Core API
uvicorn core.main:app --host 0.0.0.0 --port 8000

# Терминал 2: Collector
python -m collector.collector

# Терминал 3: Worker
python -m worker.auto_reply

# Терминал 4: Admin Bot
python -m bots.admin_bot
```

## 🤖 Команды Admin Bot

| Команда | Описание |
|---------|----------|
| `/start` | Список команд |
| `/status` | Статус системы |
| `/auto_on` | Включить автоответы |
| `/auto_off` | Выключить автоответы |
| `/rules` | Список правил |
| `/peers` | Список собеседников |
| `/stats` | Статистика |

## 📡 API Endpoints

После запуска Core API документация доступна на `http://localhost:8000/docs`

```bash
# Health check
GET /health

# Правила автоответа
GET    /rules                 # Список правил
GET    /rules/{peer_id}       # Получить правило
POST   /rules                 # Создать правило
PUT    /rules/{peer_id}       # Обновить правило
DELETE /rules/{peer_id}       # Удалить правило

# Собеседники
GET /peers                     # Список peers
GET /peers/by-tg-id/{tg_id}   # Найти по Telegram ID

# Настройки
GET /settings/{key}           # Получить настройку
PUT /settings/{key}?value=... # Установить настройку

# Статистика
GET /stats                    # Общая статистика
```

### Создание правила автоответа

```bash
# 1. Найдите peer_id собеседника
curl http://localhost:8000/peers

# 2. Создайте правило
curl -X POST http://localhost:8000/rules \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "peer_id": 42,
    "enabled": true,
    "template": "Привет! Сейчас не могу ответить, напишу позже.",
    "min_interval_sec": 3600
  }'

# 3. Включите автоответы
curl -X PUT "http://localhost:8000/settings/auto_reply_enabled?value=1"
```

## 🔧 Production (systemd)

```bash
# Копирование сервисов
sudo cp systemd/*.service /etc/systemd/system/

# Перезагрузка systemd
sudo systemctl daemon-reload

# Включение автозапуска
sudo systemctl enable core collector worker admin-bot

# Запуск
sudo systemctl start core collector worker admin-bot

# Проверка статуса
sudo systemctl status core collector worker admin-bot

# Просмотр логов
sudo journalctl -u collector -f
```

## 📁 Структура проекта

```
tg-auto-reply/
├── core/                   # FastAPI backend
│   ├── __init__.py
│   ├── main.py            # Главное приложение
│   ├── router.py          # API эндпоинты
│   ├── schemas.py         # Pydantic модели
│   └── db.py              # Подключение к БД
├── collector/              # Telethon сборщик
│   ├── __init__.py
│   └── collector.py
├── worker/                 # Автоответчик
│   ├── __init__.py
│   └── auto_reply.py
├── bots/                   # Telegram боты
│   ├── __init__.py
│   └── admin_bot.py
├── docs/
│   └── DB_SCHEMA.sql      # Схема PostgreSQL
├── sessions/               # Telethon сессии (gitignore)
├── systemd/               # Systemd сервисы
│   ├── core.service
│   ├── collector.service
│   ├── worker.service
│   └── admin-bot.service
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## ⚠️ Важно

### peer_id vs tg_peer_id

- `tg_peer_id` — это Telegram user_id (например, 123456789)
- `peer_id` — это внутренний ID в таблице `peers`
- В API используется `peer_id`, не `tg_peer_id`

### Telethon сессии

- При первом запуске Collector/Worker создаётся файл `.session`
- Этот файл содержит авторизацию — **не удаляйте его**
- Файлы сессий в `.gitignore`

### MVP ограничения

- Поддерживается один аккаунт (`account_id = 1`)
- Заглушки вместо AI (LLaMA в v2.0)

## 🗺️ Roadmap

- [x] v1.0: MVP автоответчик
- [ ] v1.1: Синхронизация истории по команде из бота
- [ ] v2.0: Multi-tenant + интеграция LLaMA
- [ ] v3.0: Обучение на истории переписок

## 📝 Лицензия

MIT
