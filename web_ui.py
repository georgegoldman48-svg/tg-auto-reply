#!/usr/bin/env python3
"""
Web UI для тестирования AI автоответчика.

Запуск:
    python web_ui.py

Открыть в браузере:
    http://localhost:8081

Поддерживает:
- Выбор AI движка (local SambaLingo / Claude API)
- Настройки system prompt, temperature
- Тестирование через локальный AI сервер
"""

import json
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

AI_SERVER = "http://localhost:8080"  # Локальный AI сервер
VPS3_SETTINGS_API = "http://188.116.27.68:8085"  # Settings API на VPS3
PORT = 8081

HTML_PAGE = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Egor AI - Тест</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
        }
        h1 {
            text-align: center;
            margin-bottom: 20px;
            color: #00d4ff;
        }
        .status {
            text-align: center;
            padding: 10px;
            margin-bottom: 20px;
            border-radius: 8px;
            background: #16213e;
        }
        .status.online { border-left: 4px solid #00ff88; }
        .status.offline { border-left: 4px solid #ff4444; }

        .panels {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }
        @media (max-width: 768px) {
            .panels { grid-template-columns: 1fr; }
        }

        .panel {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
        }
        .panel h2 {
            color: #00d4ff;
            margin-bottom: 15px;
            font-size: 1.1em;
        }

        .chat-box {
            height: 350px;
            overflow-y: auto;
            background: #0f0f23;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
        }
        .message {
            margin-bottom: 12px;
            padding: 10px 14px;
            border-radius: 12px;
            max-width: 85%;
        }
        .message.user {
            background: #0066cc;
            margin-left: auto;
            border-bottom-right-radius: 4px;
        }
        .message.assistant {
            background: #333;
            border-bottom-left-radius: 4px;
        }
        .message.claude {
            background: #6b4c9a;
        }
        .message .meta {
            font-size: 0.75em;
            color: #888;
            margin-top: 4px;
        }

        .input-row {
            display: flex;
            gap: 10px;
        }
        #messageInput {
            flex: 1;
            padding: 12px 16px;
            border: none;
            border-radius: 8px;
            background: #0f0f23;
            color: #fff;
            font-size: 1em;
        }
        #messageInput:focus { outline: 2px solid #00d4ff; }

        button {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            background: #00d4ff;
            color: #000;
            font-weight: bold;
            cursor: pointer;
            transition: background 0.2s;
        }
        button:hover { background: #00b8e6; }
        button:disabled { background: #444; color: #888; cursor: not-allowed; }

        .settings label {
            display: block;
            margin-bottom: 5px;
            color: #aaa;
            font-size: 0.9em;
        }
        .settings textarea, .settings input[type="text"] {
            width: 100%;
            padding: 10px;
            border: none;
            border-radius: 6px;
            background: #0f0f23;
            color: #fff;
            margin-bottom: 15px;
            font-family: inherit;
        }
        .settings textarea { height: 80px; resize: vertical; }
        .settings input[type="range"] { padding: 0; }

        .engine-toggle {
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
        }
        .engine-btn {
            flex: 1;
            padding: 10px;
            border: 2px solid #333;
            border-radius: 8px;
            background: #0f0f23;
            color: #888;
            cursor: pointer;
            transition: all 0.2s;
            text-align: center;
        }
        .engine-btn:hover { border-color: #555; }
        .engine-btn.active {
            border-color: #00d4ff;
            color: #00d4ff;
            background: rgba(0, 212, 255, 0.1);
        }
        .engine-btn.active.claude {
            border-color: #9b59b6;
            color: #9b59b6;
            background: rgba(155, 89, 182, 0.1);
        }

        .range-row {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 15px;
        }
        .range-row input { flex: 1; }
        .range-value {
            background: #0f0f23;
            padding: 5px 10px;
            border-radius: 4px;
            min-width: 50px;
            text-align: center;
        }

        .btn-row {
            display: flex;
            gap: 10px;
        }
        .btn-secondary {
            background: #333;
            color: #fff;
        }
        .btn-secondary:hover { background: #444; }

        .examples {
            margin-top: 15px;
        }
        .example-btn {
            display: inline-block;
            padding: 6px 12px;
            margin: 4px;
            background: #333;
            border-radius: 20px;
            font-size: 0.85em;
            cursor: pointer;
            transition: background 0.2s;
        }
        .example-btn:hover { background: #444; }

        .sync-status {
            font-size: 0.75em;
            color: #888;
            margin-top: 10px;
            text-align: center;
        }
        .sync-status.success { color: #00ff88; }
        .sync-status.error { color: #ff4444; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Egor AI</h1>

        <div class="status" id="status">Проверка подключения...</div>

        <div class="panels">
            <div class="panel">
                <h2>Чат</h2>
                <div class="chat-box" id="chatBox"></div>
                <div class="input-row">
                    <input type="text" id="messageInput" placeholder="Напиши сообщение..." onkeypress="if(event.key==='Enter')sendMessage()">
                    <button onclick="sendMessage()" id="sendBtn">Отправить</button>
                </div>
                <div class="examples">
                    <span style="color:#888;font-size:0.85em;">Примеры:</span>
                    <span class="example-btn" onclick="setExample('Привет, как дела?')">Привет</span>
                    <span class="example-btn" onclick="setExample('Ты где?')">Ты где?</span>
                    <span class="example-btn" onclick="setExample('Что делаешь?')">Что делаешь?</span>
                    <span class="example-btn" onclick="setExample('Можешь говорить?')">Можешь говорить?</span>
                    <span class="example-btn" onclick="setExample('Во сколько встретимся?')">Встреча</span>
                </div>
            </div>

            <div class="panel settings">
                <h2>Настройки AI</h2>

                <label>AI Движок:</label>
                <div class="engine-toggle">
                    <div class="engine-btn" id="engineLocal" onclick="setEngine('local')">
                        <div>Local</div>
                        <div style="font-size:0.75em;color:#666;">SambaLingo</div>
                    </div>
                    <div class="engine-btn" id="engineClaude" onclick="setEngine('claude')">
                        <div>Claude</div>
                        <div style="font-size:0.75em;color:#666;">API</div>
                    </div>
                </div>

                <label>System Prompt:</label>
                <textarea id="systemPrompt">Ты Егор. Отвечаешь коротко, живо, по делу. Без воды и официоза.</textarea>

                <label>Temperature:</label>
                <div class="range-row">
                    <input type="range" id="temperature" min="0.1" max="1.5" step="0.1" value="0.7" oninput="updateTempDisplay()">
                    <span class="range-value" id="tempValue">0.7</span>
                </div>

                <label>Max Tokens:</label>
                <div class="range-row">
                    <input type="range" id="maxTokens" min="20" max="500" step="10" value="100" oninput="updateTokensDisplay()">
                    <span class="range-value" id="tokensValue">100</span>
                </div>

                <div class="btn-row">
                    <button onclick="saveSettings()">Сохранить</button>
                    <button class="btn-secondary" onclick="loadVPS3Settings()">Загрузить</button>
                    <button class="btn-secondary" onclick="clearChat()">Очистить</button>
                </div>

                <div class="sync-status" id="syncStatus"></div>
            </div>
        </div>
    </div>

    <script>
        let chatHistory = [];
        let currentEngine = 'local';

        async function checkHealth() {
            const statusEl = document.getElementById('status');
            try {
                const resp = await fetch('/api/health');
                const data = await resp.json();
                if (data.ready) {
                    const engineInfo = currentEngine === 'claude' ? 'Claude API' : `Local: ${data.model}`;
                    statusEl.textContent = `${engineInfo} | GPU: ${data.gpu}`;
                    statusEl.className = 'status online';
                } else {
                    statusEl.textContent = 'Модель загружается...';
                    statusEl.className = 'status offline';
                }
            } catch (e) {
                statusEl.textContent = currentEngine === 'claude' ? 'Claude API (локальный AI недоступен)' : 'AI сервер недоступен';
                statusEl.className = currentEngine === 'claude' ? 'status online' : 'status offline';
            }
        }

        function setEngine(engine) {
            currentEngine = engine;
            document.getElementById('engineLocal').className = engine === 'local' ? 'engine-btn active' : 'engine-btn';
            document.getElementById('engineClaude').className = engine === 'claude' ? 'engine-btn active claude' : 'engine-btn';
            checkHealth();
        }

        function addMessage(text, role, time_ms = null, engine = null) {
            const chatBox = document.getElementById('chatBox');
            const div = document.createElement('div');
            let className = `message ${role}`;
            if (role === 'assistant' && engine === 'claude') {
                className += ' claude';
            }
            div.className = className;
            let html = text;
            if (time_ms !== null) {
                const engineLabel = engine ? ` (${engine})` : '';
                html += `<div class="meta">${time_ms}ms${engineLabel}</div>`;
            }
            div.innerHTML = html;
            chatBox.appendChild(div);
            chatBox.scrollTop = chatBox.scrollHeight;
        }

        async function sendMessage() {
            const input = document.getElementById('messageInput');
            const btn = document.getElementById('sendBtn');
            const text = input.value.trim();
            if (!text) return;

            addMessage(text, 'user');
            chatHistory.push({role: 'user', content: text});
            input.value = '';
            btn.disabled = true;

            try {
                const start = Date.now();
                const resp = await fetch('/api/generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        prompt: text,
                        history: chatHistory.slice(-10),
                        system_prompt: document.getElementById('systemPrompt').value,
                        temperature: parseFloat(document.getElementById('temperature').value),
                        max_tokens: parseInt(document.getElementById('maxTokens').value),
                        engine: currentEngine
                    })
                });
                const data = await resp.json();
                const time_ms = Date.now() - start;

                if (data.response) {
                    addMessage(data.response, 'assistant', time_ms, data.engine || currentEngine);
                    chatHistory.push({role: 'assistant', content: data.response});
                } else if (data.error) {
                    addMessage(`Ошибка: ${data.error}`, 'assistant');
                }
            } catch (e) {
                addMessage(`Ошибка: ${e.message}`, 'assistant');
            }

            btn.disabled = false;
            input.focus();
        }

        function setExample(text) {
            document.getElementById('messageInput').value = text;
            document.getElementById('messageInput').focus();
        }

        function updateTempDisplay() {
            document.getElementById('tempValue').textContent = document.getElementById('temperature').value;
        }

        function updateTokensDisplay() {
            document.getElementById('tokensValue').textContent = document.getElementById('maxTokens').value;
        }

        async function saveSettings() {
            const settings = {
                ai_engine: currentEngine,
                system_prompt: document.getElementById('systemPrompt').value,
                temperature: parseFloat(document.getElementById('temperature').value),
                max_tokens: parseInt(document.getElementById('maxTokens').value)
            };

            const syncStatus = document.getElementById('syncStatus');

            try {
                // Сохраняем на VPS3 (глобально для Telegram)
                const resp = await fetch('/api/vps3/settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(settings)
                });
                const data = await resp.json();

                if (data.error) {
                    syncStatus.textContent = 'Ошибка сохранения на VPS3: ' + data.error;
                    syncStatus.className = 'sync-status error';
                } else {
                    syncStatus.textContent = 'Настройки сохранены на VPS3';
                    syncStatus.className = 'sync-status success';

                    // Также синхронизируем с локальным AI сервером
                    try {
                        await fetch('/api/settings', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                system_prompt: settings.system_prompt,
                                temperature: settings.temperature,
                                max_tokens: settings.max_tokens
                            })
                        });
                    } catch (e) {
                        // Игнорируем ошибки локального сервера
                    }
                }
            } catch (e) {
                syncStatus.textContent = 'Ошибка: ' + e.message;
                syncStatus.className = 'sync-status error';
            }

            setTimeout(() => { syncStatus.textContent = ''; }, 5000);
        }

        async function loadVPS3Settings() {
            const syncStatus = document.getElementById('syncStatus');

            try {
                const resp = await fetch('/api/vps3/settings');
                const data = await resp.json();

                if (data.error) {
                    syncStatus.textContent = 'Ошибка загрузки: ' + data.error;
                    syncStatus.className = 'sync-status error';
                    return;
                }

                if (data.ai_engine) {
                    setEngine(data.ai_engine);
                }
                if (data.system_prompt) {
                    document.getElementById('systemPrompt').value = data.system_prompt;
                }
                if (data.temperature) {
                    document.getElementById('temperature').value = data.temperature;
                    updateTempDisplay();
                }
                if (data.max_tokens) {
                    document.getElementById('maxTokens').value = data.max_tokens;
                    updateTokensDisplay();
                }

                syncStatus.textContent = 'Настройки загружены с VPS3';
                syncStatus.className = 'sync-status success';
            } catch (e) {
                syncStatus.textContent = 'Ошибка: ' + e.message;
                syncStatus.className = 'sync-status error';
            }

            setTimeout(() => { syncStatus.textContent = ''; }, 5000);
        }

        function clearChat() {
            chatHistory = [];
            document.getElementById('chatBox').innerHTML = '';
        }

        async function loadSettings() {
            // Сначала пробуем загрузить с VPS3
            try {
                const resp = await fetch('/api/vps3/settings');
                const data = await resp.json();

                if (!data.error) {
                    if (data.ai_engine) {
                        setEngine(data.ai_engine);
                    }
                    if (data.system_prompt) {
                        document.getElementById('systemPrompt').value = data.system_prompt;
                    }
                    if (data.temperature) {
                        document.getElementById('temperature').value = data.temperature;
                        updateTempDisplay();
                    }
                    if (data.max_tokens) {
                        document.getElementById('maxTokens').value = data.max_tokens;
                        updateTokensDisplay();
                    }
                    return;
                }
            } catch (e) {
                console.error('Failed to load VPS3 settings:', e);
            }

            // Fallback: загружаем с локального AI сервера
            try {
                const resp = await fetch('/api/settings');
                const data = await resp.json();
                if (data.system_prompt) {
                    document.getElementById('systemPrompt').value = data.system_prompt;
                }
                if (data.temperature) {
                    document.getElementById('temperature').value = data.temperature;
                    updateTempDisplay();
                }
                if (data.max_tokens) {
                    document.getElementById('maxTokens').value = data.max_tokens;
                    updateTokensDisplay();
                }
            } catch (e) {
                console.error('Failed to load settings:', e);
            }
        }

        // Инициализация
        setEngine('local');
        checkHealth();
        loadSettings();
        setInterval(checkHealth, 10000);
    </script>
</body>
</html>
'''


class WebUIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Тихий режим

    def send_html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_html(HTML_PAGE)
        elif self.path == "/api/health":
            try:
                req = urllib.request.Request(f"{AI_SERVER}/health")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    self.send_json(data)
            except Exception as e:
                self.send_json({"error": str(e), "ready": False})
        elif self.path == "/api/settings":
            try:
                req = urllib.request.Request(f"{AI_SERVER}/settings")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    self.send_json(data)
            except Exception as e:
                self.send_json({"error": str(e)})
        elif self.path == "/api/vps3/settings":
            try:
                req = urllib.request.Request(f"{VPS3_SETTINGS_API}/api/settings")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    self.send_json(data)
            except Exception as e:
                self.send_json({"error": str(e)})
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        if self.path == "/api/generate":
            try:
                data = json.loads(body)

                # Отправляем запрос к AI серверу (только local движок тестируем здесь)
                payload = json.dumps({
                    "prompt": data.get("prompt", ""),
                    "history": data.get("history", []),
                    "peer_id": 0
                }).encode("utf-8")

                req = urllib.request.Request(
                    f"{AI_SERVER}/generate",
                    data=payload,
                    headers={"Content-Type": "application/json"}
                )

                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read().decode())
                    result["engine"] = "local"
                    self.send_json(result)

            except urllib.error.URLError as e:
                self.send_json({"error": f"AI сервер недоступен: {e}"}, 500)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif self.path == "/api/settings":
            try:
                data = json.loads(body)

                # Отправляем настройки на локальный AI сервер
                payload = json.dumps(data).encode("utf-8")
                req = urllib.request.Request(
                    f"{AI_SERVER}/settings",
                    data=payload,
                    headers={"Content-Type": "application/json"}
                )

                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read().decode())
                    self.send_json(result)

            except urllib.error.URLError as e:
                self.send_json({"error": f"AI сервер недоступен: {e}"}, 500)
            except Exception as e:
                self.send_json({"error": str(e)}, 400)

        elif self.path == "/api/vps3/settings":
            try:
                data = json.loads(body)

                # Отправляем настройки на VPS3 Settings API
                payload = json.dumps(data).encode("utf-8")
                req = urllib.request.Request(
                    f"{VPS3_SETTINGS_API}/api/settings",
                    data=payload,
                    headers={"Content-Type": "application/json"}
                )

                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read().decode())
                    self.send_json(result)

            except urllib.error.URLError as e:
                self.send_json({"error": f"VPS3 недоступен: {e}"}, 500)
            except Exception as e:
                self.send_json({"error": str(e)}, 400)

        else:
            self.send_json({"error": "Not found"}, 404)


def main():
    print(f"=" * 50)
    print(f"Web UI для Egor AI")
    print(f"=" * 50)
    print(f"Открой в браузере: http://localhost:{PORT}")
    print(f"AI Server: {AI_SERVER}")
    print(f"VPS3 Settings: {VPS3_SETTINGS_API}")
    print(f"=" * 50)

    server = HTTPServer(("0.0.0.0", PORT), WebUIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка...")
        server.shutdown()


if __name__ == "__main__":
    main()
