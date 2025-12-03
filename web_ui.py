#!/usr/bin/env python3
"""
Web UI для тестирования AI автоответчика.

Запуск:
    python web_ui.py

Открыть в браузере:
    http://localhost:8081
"""

import json
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

AI_SERVER = "http://localhost:8080"
PORT = 8081

# Текущие настройки (можно менять через UI)
current_settings = {
    "system_prompt": "Ты Егор. Отвечаешь коротко, живо, по делу. Без воды и официоза.",
    "temperature": 0.7,
    "max_tokens": 100
}

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
            height: 400px;
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
        .settings textarea, .settings input {
            width: 100%;
            padding: 10px;
            border: none;
            border-radius: 6px;
            background: #0f0f23;
            color: #fff;
            margin-bottom: 15px;
            font-family: inherit;
        }
        .settings textarea { height: 100px; resize: vertical; }
        .settings input[type="range"] { padding: 0; }

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
                <h2>Настройки</h2>

                <label>System Prompt:</label>
                <textarea id="systemPrompt">Ты Егор. Отвечаешь коротко, живо, по делу. Без воды и официоза.</textarea>

                <label>Temperature:</label>
                <div class="range-row">
                    <input type="range" id="temperature" min="0.1" max="1.5" step="0.1" value="0.7" oninput="updateTempDisplay()">
                    <span class="range-value" id="tempValue">0.7</span>
                </div>

                <label>Max Tokens:</label>
                <div class="range-row">
                    <input type="range" id="maxTokens" min="20" max="200" step="10" value="100" oninput="updateTokensDisplay()">
                    <span class="range-value" id="tokensValue">100</span>
                </div>

                <div class="btn-row">
                    <button onclick="saveSettings()">Сохранить</button>
                    <button class="btn-secondary" onclick="clearChat()">Очистить чат</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        let chatHistory = [];

        async function checkHealth() {
            const statusEl = document.getElementById('status');
            try {
                const resp = await fetch('/api/health');
                const data = await resp.json();
                if (data.ready) {
                    statusEl.textContent = `Online: ${data.model} | GPU: ${data.gpu}`;
                    statusEl.className = 'status online';
                } else {
                    statusEl.textContent = 'Модель загружается...';
                    statusEl.className = 'status offline';
                }
            } catch (e) {
                statusEl.textContent = 'AI сервер недоступен';
                statusEl.className = 'status offline';
            }
        }

        function addMessage(text, role, time_ms = null) {
            const chatBox = document.getElementById('chatBox');
            const div = document.createElement('div');
            div.className = `message ${role}`;
            let html = text;
            if (time_ms !== null) {
                html += `<div class="meta">${time_ms}ms</div>`;
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
                        max_tokens: parseInt(document.getElementById('maxTokens').value)
                    })
                });
                const data = await resp.json();
                const time_ms = Date.now() - start;

                if (data.response) {
                    addMessage(data.response, 'assistant', time_ms);
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
                system_prompt: document.getElementById('systemPrompt').value,
                temperature: parseFloat(document.getElementById('temperature').value),
                max_tokens: parseInt(document.getElementById('maxTokens').value)
            };
            try {
                await fetch('/api/settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(settings)
                });
                alert('Настройки сохранены!');
            } catch (e) {
                alert('Ошибка сохранения');
            }
        }

        function clearChat() {
            chatHistory = [];
            document.getElementById('chatBox').innerHTML = '';
        }

        async function loadSettings() {
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
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        if self.path == "/api/generate":
            try:
                data = json.loads(body)

                # Отправляем запрос к AI серверу
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
                    self.send_json(result)

            except urllib.error.URLError as e:
                self.send_json({"error": f"AI сервер недоступен: {e}"}, 500)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif self.path == "/api/settings":
            try:
                data = json.loads(body)

                # Отправляем настройки на AI сервер (глобально для всех)
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
        else:
            self.send_json({"error": "Not found"}, 404)


def main():
    print(f"=" * 50)
    print(f"Web UI для Egor AI")
    print(f"=" * 50)
    print(f"Открой в браузере: http://localhost:{PORT}")
    print(f"AI Server: {AI_SERVER}")
    print(f"=" * 50)

    server = HTTPServer(("0.0.0.0", PORT), WebUIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка...")
        server.shutdown()


if __name__ == "__main__":
    main()
