-- TG Auto-Reply Database Schema v1.0
-- PostgreSQL 14+

-- ==================== TABLES ====================

-- Собеседники (пользователи Telegram)
CREATE TABLE IF NOT EXISTS peers (
    id              BIGSERIAL PRIMARY KEY,
    tg_peer_id      BIGINT NOT NULL UNIQUE,    -- Telegram user_id
    tg_access_hash  BIGINT,                     -- Telethon access_hash
    peer_type       TEXT NOT NULL DEFAULT 'user',
    username        TEXT,
    first_name      TEXT,
    last_name       TEXT,
    is_bot          BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Сообщения
CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    peer_id         BIGINT NOT NULL REFERENCES peers(id) ON DELETE CASCADE,
    tg_message_id   BIGINT NOT NULL,            -- Telegram message_id
    from_me         BOOLEAN NOT NULL,           -- true если я отправитель
    date            TIMESTAMPTZ NOT NULL,
    text            TEXT,
    reply_to_id     BIGINT,                     -- tg_message_id ответа
    has_media       BOOLEAN DEFAULT FALSE,
    media_type      TEXT,
    raw_json        JSONB,                      -- полные данные сообщения
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (peer_id, tg_message_id)
);

-- Правила автоответа
CREATE TABLE IF NOT EXISTS auto_reply_rules (
    id              BIGSERIAL PRIMARY KEY,
    account_id      INT NOT NULL DEFAULT 1,     -- MVP: всегда 1
    peer_id         BIGINT NOT NULL REFERENCES peers(id) ON DELETE CASCADE,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    template        TEXT NOT NULL DEFAULT 'Сейчас не могу ответить, напишу позже.',
    min_interval_sec INT NOT NULL DEFAULT 3600, -- минимум между ответами (сек)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, peer_id)
);

-- Состояние автоответов (последний ответ каждому peer)
CREATE TABLE IF NOT EXISTS auto_reply_state (
    id              SERIAL PRIMARY KEY,
    account_id      INT NOT NULL DEFAULT 1,
    peer_id         BIGINT NOT NULL REFERENCES peers(id) ON DELETE CASCADE,
    last_reply_time TIMESTAMPTZ,
    last_message_id BIGINT REFERENCES messages(id),
    UNIQUE (account_id, peer_id)
);

-- Глобальные настройки
CREATE TABLE IF NOT EXISTS settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ==================== INITIAL DATA ====================

INSERT INTO settings (key, value) VALUES 
    ('auto_reply_enabled', '0'),
    ('default_template', 'Сейчас не могу ответить, напишу позже.')
ON CONFLICT (key) DO NOTHING;

-- ==================== INDEXES ====================

CREATE INDEX IF NOT EXISTS idx_messages_peer_date ON messages(peer_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_messages_from_me ON messages(from_me, date DESC);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date DESC);
CREATE INDEX IF NOT EXISTS idx_peers_username ON peers(username) WHERE username IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_peers_tg_id ON peers(tg_peer_id);
CREATE INDEX IF NOT EXISTS idx_auto_reply_rules_account ON auto_reply_rules(account_id);
CREATE INDEX IF NOT EXISTS idx_auto_reply_rules_enabled ON auto_reply_rules(account_id, enabled) WHERE enabled = true;

-- ==================== TRIGGERS ====================

-- Функция для автообновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Триггер для peers
DROP TRIGGER IF EXISTS update_peers_updated_at ON peers;
CREATE TRIGGER update_peers_updated_at 
    BEFORE UPDATE ON peers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Триггер для auto_reply_rules
DROP TRIGGER IF EXISTS update_rules_updated_at ON auto_reply_rules;
CREATE TRIGGER update_rules_updated_at 
    BEFORE UPDATE ON auto_reply_rules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ==================== COMMENTS ====================

COMMENT ON TABLE peers IS 'Собеседники (пользователи Telegram)';
COMMENT ON TABLE messages IS 'История сообщений';
COMMENT ON TABLE auto_reply_rules IS 'Правила автоответа. В MVP account_id = 1';
COMMENT ON TABLE auto_reply_state IS 'Состояние последнего автоответа каждому peer';
COMMENT ON TABLE settings IS 'Глобальные настройки системы';

COMMENT ON COLUMN peers.tg_peer_id IS 'Telegram user_id';
COMMENT ON COLUMN messages.from_me IS 'true если сообщение исходящее (от нас)';
COMMENT ON COLUMN auto_reply_rules.min_interval_sec IS 'Минимальный интервал между автоответами (секунды)';
