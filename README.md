# Telegram Auto-Reply Service v2.2

> Интеллектуальный автоответчик для Telegram с AI интеграцией

Система автоматически отвечает на входящие личные сообщения в Telegram, используя AI (Claude API или локальную модель). Поддерживает индивидуальные настройки для каждого контакта, синхронизацию с папкой Personal и лимиты ответов.

## Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                         TELEGRAM                                 │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐                      │
│  │ Personal│    │  Users  │    │  Chats  │                      │
│  │ Folder  │    │  (DMs)  │    │ (skip)  │                      │
│  └────┬────┘    └────┬────┘    └─────────┘                      │
└───────┼──────────────┼──────────────────────────────────────────┘
        │              │
        ▼              ▼
┌───────────────────────────────────────────────────────────────┐
│                    VPS3 (188.116.27.68)                        │
│                                                                 │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐       │
│  │  Collector  │────▶│  PostgreSQL │◀────│   Worker    │       │
│  │  (Telethon) │     │             │     │  (Telethon) │       │
│  └─────────────┘     │  ┌───────┐  │     └──────┬──────┘       │
│                      │  │ peers │  │            │               │
│  ┌─────────────┐     │  │ msgs  │  │     ┌──────▼──────┐       │
│  │  Admin Bot  │────▶│  │ rules │  │     │   AI API    │       │
│  │  (aiogram)  │     │  │ state │  │     │ Claude/Local│       │
│  └─────────────┘     │  └───────┘  │     └─────────────┘       │
│                      └─────────────┘                            │
│  ┌─────────────┐                                                │
│  │  Core API   │  REST API для внешних интеграций              │
│  │  (FastAPI)  │                                                │
│  └─────────────┘                                                │
└─────────────────────────────────────────────────────────────────┘
```

## Компоненты

| Компонент | Версия | Файл | Описание |
|-----------|--------|------|----------|
| **Worker** | v2.12 | `worker/auto_reply.py` | Основной обработчик автоответов с AI |
| **Admin Bot** | v3.5 | `bots/admin_bot.py` | Telegram бот для управления |
| **Collector** | v1.0 | `collector/collector.py` | Сбор истории сообщений |
| **Core API** | v1.0 | `core/main.py` | REST API (FastAPI) |

## Потоки данных

### 1. Сбор сообщений (Collector)
```
Telegram DM → Collector → peers + messages таблицы
```
- Слушает новые входящие/исходящие сообщения
- Сохраняет только личные сообщения (is_private)
- Игнорирует ботов и группы/каналы

### 2. Автоответ (Worker)
```
                    ┌─── AI (Claude/Local) ──┐
                    │                        ▼
Новое сообщение → Worker → Проверки → Генерация → Отправка ответа
                    │                        │
                    └── template (fallback) ─┘
```

**Проверки перед ответом:**
1. Автоответ включён глобально (`auto_reply_enabled`)
2. Контакт в папке Personal ИЛИ есть правило
3. `reply_mode` != 'off'
4. Не превышены лимиты (daily/new_contact)
5. Прошёл интервал с прошлого ответа

### 3. Управление (Admin Bot)
```
Telegram Bot ←→ Admin Bot ←→ PostgreSQL
                   │
                   └─→ Restart Worker (systemctl)
```

## База данных

### Таблицы

#### `peers` - Контакты
| Поле | Тип | Описание |
|------|-----|----------|
| id | BIGINT PK | Внутренний ID |
| tg_peer_id | BIGINT UNIQUE | Telegram user_id |
| username | TEXT | @username |
| first_name | TEXT | Имя |
| in_personal | BOOLEAN | В папке Personal |
| is_bot | BOOLEAN | Это бот |

#### `messages` - История сообщений
| Поле | Тип | Описание |
|------|-----|----------|
| id | BIGINT PK | ID сообщения |
| peer_id | BIGINT FK | Ссылка на peers |
| tg_message_id | BIGINT | Telegram message_id |
| from_me | BOOLEAN | Исходящее сообщение |
| text | TEXT | Текст сообщения |
| date | TIMESTAMPTZ | Дата/время |

#### `auto_reply_rules` - Правила автоответа
| Поле | Тип | Описание |
|------|-----|----------|
| id | BIGINT PK | ID правила |
| peer_id | BIGINT FK | Ссылка на peers |
| enabled | BOOLEAN | Правило активно |
| template | TEXT | Промпт для AI или текст шаблона |
| reply_mode | VARCHAR(10) | `ai` / `template` / `off` |
| min_interval_sec | INTEGER | Мин. интервал между ответами |

#### `settings` - Глобальные настройки
| Ключ | Описание | Значения |
|------|----------|----------|
| auto_reply_enabled | Автоответ вкл/выкл | `0` / `1` |
| ai_enabled | AI вкл/выкл | `0` / `1` |
| ai_engine | AI движок | `local` / `claude` |
| system_prompt | Системный промпт | текст |
| temperature | Температура AI | `0.0` - `2.0` |
| new_contact_mode | Режим для новых | `off` / `template` / `ai` |
| new_contact_max_replies | Лимит для новых | число (5) |
| daily_max_replies | Дневной лимит | число (50) |

#### `reply_counts` - Счётчики ответов
| Поле | Тип | Описание |
|------|-----|----------|
| peer_id | BIGINT PK | Ссылка на peers |
| new_contact_replies | INT | Ответов как новому |
| daily_replies | INT | Ответов сегодня |
| last_reply_date | DATE | Дата сброса daily |

#### `auto_reply_state` - Состояние
| Поле | Тип | Описание |
|------|-----|----------|
| peer_id | BIGINT | Контакт |
| last_reply_time | TIMESTAMPTZ | Когда отвечали |
| last_message_id | BIGINT | На какое сообщение |

## Команды Admin Bot

### Главное меню
| Кнопка | Действие |
|--------|----------|
| Статус | Показать текущий статус системы |
| Авто ON/OFF | Включить/выключить автоответы |
| AI ON/OFF | Включить/выключить AI |
| Правила | Список активных правил |
| Контакты | Список контактов с настройками |
| AI настройки | Выбор движка, промпт, температура |
| Синхронизация | Синхр. папки Personal |
| Новые контакты | Настройка для новых |

### Карточка контакта
- **Режим**: AI / Template / Off
- **Промпт**: Индивидуальный промпт для AI
- **Статистика**: Ответов сегодня, как новому

### Slash-команды
```
/start     - Главное меню
/status    - Статус системы
/find      - Поиск контакта
/sync      - Синхронизация Personal
/engine    - AI движок
/prompt    - System prompt
/temp      - Temperature
```

## Установка

### 1. Клонирование
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
```env
DATABASE_URL=postgresql://aiuser:password@localhost:5432/ai_tg_core
API_ID=12345678
API_HASH=abcdef...
PHONE_NUMBER=+79991234567
ADMIN_BOT_TOKEN=123456:ABC...
ADMIN_USER_ID=123456789
```

### 3. База данных
```bash
sudo -u postgres createdb ai_tg_core
psql -d ai_tg_core < docs/DB_SCHEMA.sql
```

### 4. Первый запуск (авторизация)
```bash
python -m collector.collector
# Введите код из Telegram
```

### 5. Systemd сервисы
```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable collector worker admin-bot core
sudo systemctl start collector worker admin-bot core
```

## Логика автоответа

```python
# Псевдокод
for message in incoming_messages:
    if not settings.auto_reply_enabled:
        continue

    peer = get_peer(message.sender)
    rule = get_rule(peer)

    # Определяем режим
    if rule and rule.reply_mode:
        mode = rule.reply_mode  # ai/template/off
    elif peer.in_personal:
        mode = 'ai'  # По умолчанию для Personal
    else:
        mode = settings.new_contact_mode  # Для новых

    if mode == 'off':
        continue

    # Проверка лимитов
    if not peer.in_personal:
        if reply_counts.new_contact >= 5:
            continue
    if reply_counts.daily >= 50:
        continue

    # Генерация ответа
    if mode == 'ai' and settings.ai_enabled:
        response = ai.generate(
            history=last_20_messages,
            prompt=rule.template or settings.system_prompt
        )
    else:
        response = rule.template or settings.default_template

    send_reply(peer, response)
    update_counters(peer)
```

## Troubleshooting

### Сервис не запускается
```bash
sudo journalctl -u worker -f
sudo journalctl -u admin-bot -f
```

### Нет ответов
1. Проверить `auto_reply_enabled = 1`
2. Проверить `ai_enabled = 1` (если режим AI)
3. Проверить лимиты в `reply_counts`
4. Проверить `reply_mode` в правиле

### AI не отвечает
1. Проверить `ai_engine` (local/claude)
2. Для Claude: проверить `claude_api_key`
3. Для Local: проверить SSH туннель на порт 8080

## Local AI Setup (опционально)

Для использования локальной модели (Qwen + LoRA) вместо Claude:

### 1. На локальном компьютере (с GPU)
```bash
# Установить Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Создать модель из обученного LoRA
cd ~/qwen-egor-merged
ollama create egor -f Modelfile

# Запустить AI сервер
cd ~/Downloads/tg-auto-reply
python ai_server.py
# Сервер на порту 8080
```

### 2. SSH туннель к VPS
```bash
ssh -N -R 8080:localhost:8080 root@188.116.27.68
```

### 3. Проверить с VPS
```bash
curl http://localhost:8080/health
# {"status":"healthy","model":"egor:latest","ready":true}
```

### Auto-fallback
Если Local AI недоступен (выключен компьютер, оборвался туннель), Worker автоматически использует Claude API как fallback. Настройка `ai_engine=local` предпочитает Local, но не блокирует работу при его недоступности

### Контакт не в списке
1. Должен быть в папке Personal ИЛИ написать вам в ЛС
2. Синхронизировать: Admin Bot → Синхронизация

### База заблокирована (database is locked)
- Telethon сессии конфликтуют
- Решение: разные session файлы для разных сервисов

## Файловая структура

```
tg-auto-reply/
├── bots/
│   ├── __init__.py
│   └── admin_bot.py       # Admin Bot v3.3
├── worker/
│   ├── __init__.py
│   └── auto_reply.py      # Worker v2.11
├── collector/
│   ├── __init__.py
│   └── collector.py       # Collector v1.0
├── core/
│   ├── __init__.py
│   ├── main.py            # FastAPI app
│   ├── router.py          # API endpoints
│   ├── schemas.py         # Pydantic models
│   └── db.py              # DB connection
├── docs/
│   └── DB_SCHEMA.sql      # PostgreSQL schema
├── sessions/              # Telethon sessions (gitignore)
├── systemd/
│   ├── admin-bot.service
│   ├── collector.service
│   ├── core.service
│   └── worker.service
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## API Endpoints (Core)

```
GET  /health                    - Health check
GET  /peers                     - Список контактов
GET  /peers/by-tg-id/{tg_id}   - Поиск по Telegram ID
GET  /rules                     - Список правил
POST /rules                     - Создать правило
PUT  /rules/{peer_id}          - Обновить правило
DELETE /rules/{peer_id}        - Удалить правило
GET  /settings/{key}           - Получить настройку
PUT  /settings/{key}           - Установить настройку
GET  /stats                    - Статистика
```

## Changelog

### v2.2 (2024-12-10)
- **Chat Triggers**: Поддержка автоответов в групповых чатах
  - Триггеры: @mention, reply, keywords, random
  - Cooldown и дневные лимиты для чатов
  - Управление через Admin Bot
- **Bug fixes**:
  - Фильтрация системных сообщений Telegram (ID 777000)
  - Фильтрация сообщений от владельца аккаунта (Saved Messages)
- **Admin Bot v3.5**: Раздел "Чаты" для управления триггерами

### v2.1 (2024-12-05)
- **Local AI**: Поддержка обученной модели Qwen + LoRA через SSH туннель
- **Auto-fallback**: Если Local AI недоступен → автоматический fallback на Claude API
- **Admin Bot v3.3**:
  - Кнопка "Помощь" с полным руководством
  - Кнопка отмены при вводе промптов/шаблонов
  - Цветовая индикация режимов (🟢 AI, 🟡 Шаблон, ⚪ Выкл)
  - Объединённые разделы Статус + Настройки системы
- **AI Server v2.0**: FastAPI сервер для Local AI с Ollama backend

### v2.0 (2024-12)
- AI интеграция (Claude API + Local)
- Per-contact reply_mode (ai/template/off)
- Personal folder синхронизация
- Лимиты для новых контактов
- Admin Bot v3.0 с карточками контактов

### v1.0 (2024-11)
- MVP автоответчик
- Базовые шаблоны ответов
- Admin Bot базовый

## Лицензия

MIT
