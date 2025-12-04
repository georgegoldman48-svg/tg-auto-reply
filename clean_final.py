#!/usr/bin/env python3
import re
import random

INPUT_FILE = '/home/george/Downloads/tg-auto-reply/my_messages_clean.txt'
OUTPUT_FILE = '/home/george/Downloads/tg-auto-reply/my_messages_final.txt'

def is_junk(msg):
    msg_lower = msg.lower().strip()
    original = msg.strip()
    
    # Длина: 5-80 символов
    if len(original) < 5 or len(original) > 80:
        return True
    
    # Всё техническое
    tech = r'(vpn|впн|dpi|wireguard|wg\b|quic|proxy|прокси|сервер|server|порт|port|tunnel|туннель|sing-?box|xray|vless|vmess|trojan|shadowsocks|cloudflare|nginx|docker|linux|ubuntu|debian|windows|macos|android|ios|config|конфиг|настрой|install|apt\b|pip\b|npm|github|код\b|code|script|скрипт|api\b|json|database|база данн|sql|postgres|mysql|redis|backup|бэкап|ssh|ssl|tls|https|http|dns\b|tcp|udp|ip\s|ipv[46]|firewall|iptables|ufw|router|роутер|nat\b|vps|hosting|хостинг|domain|домен|certificate|сертификат|encrypt|decrypt|hash|token|auth\b|login|пароль|password|root|admin|sudo|chmod|systemctl|journalctl|grep|curl|wget|ping\b|traceroute|netstat|коннект|connect|трафик|traffic|протокол|protocol|интерфейс|interface|модуль|module|депозит|deposit|торг|trade|бирж|exchang|ноут|laptop|комп\b|pc\b|браузер|browser|приложени|app\b|апп\b|телеграм|telegram|viber|whatsapp|discord|zoom|скайп|skype|чат\b|chat\b|бот\b|bot\b|канал\b|channel|подписк|subscri|аккаунт|account|регистр|register|верифик|verif|логин|signin|signup|инст[ау]|instagram|фейс\b|facebook|ютуб|youtube|тикток|tiktok)'
    if re.search(tech, msg_lower):
        return True
    
    # Контент
    if re.search(r'\(\d{4}\)', msg):
        return True
    if re.search(r'(фильм|кино|сериал|книга|роман|автор|режисс|актер|актриса|трейлер|сезон\b|серия\b|эпизод|глава|том\s|ролик|видео|стать[яюи]|пост\b|лент[ау])', msg_lower):
        return True
    
    # Эмодзи и списки
    if re.search(r'[🟦🟩🟨⬜️✅❌📌📍🔴🟢⚪️1️⃣2️⃣3️⃣4️⃣5️⃣📱💻🔧⚙️🛠️]', msg):
        return True
    if re.search(r'^[\-\•\*]\s', original):
        return True
    if re.search(r'^\d+[\.\)]\s', original):
        return True
    
    # Финансы/крипто
    if re.search(r'(ерип|ибокс|ibox|расчет|оплат|банк\b|карт[аыу]|visa|mastercard|платеж|перевод|реквизит|счет\b|счёт\b|invoice|баланс|balance|кредит|credit|дебет|debit|транзакц|transaction|bitcoin|btc|биток|битк|ethereum|eth|usdt|tether|crypto|крипт|биткоин|binance|бинанс|bybit|trading|трейд|биржа|токен|wallet|кошел[её]к|майн|mining|блокчейн|blockchain|nft|стейкинг|staking|кэшап|cashapp|вывел|вывод)', msg_lower):
        return True
    
    # Коды и номера
    if re.search(r'[a-z]\d{4,}', msg_lower):
        return True
    if re.search(r'\b\d{3,}\b', msg):
        return True
    
    # Английский (2+ слова)
    eng_words = re.findall(r'\b[a-zA-Z]{3,}\b', msg)
    if len(eng_words) >= 2:
        return True
    
    # Только латиница
    if re.match(r'^[a-zA-Z\s\.\,\!\?\-\'\:]+$', original):
        return True
    
    # Адреса
    if re.search(r'(адрес|индекс|город\b|област|район\b|улица|дом\s*\d|кв\s*\d|офис\s*\d)', msg_lower):
        return True
    
    # Даты
    if re.search(r'\d{1,2}[\.\/]\d{1,2}[\.\/]\d{2,4}', msg):
        return True
    
    # Ссылки
    if re.search(r'(ссылк|линк|link|url|http|www\.|\.[a-z]{2,3}/)', msg_lower):
        return True
    
    # Длинные слова
    if re.search(r'[а-яёa-z]{14,}', msg_lower):
        return True
    
    # Рабочее/бизнес
    if re.search(r'(заявк|виз[аыу]\b|документ|контракт|contract|договор|офици|official|менеджер|manager|клиент\b|client|заказ\b|order\b|доставк|delivery|курьер|courier|ордер)', msg_lower):
        return True
    
    # Тюремное/криминал/юрид
    if re.search(r'(зон[аеу]\b|тюрьм|тюремн|лагер[яь]|срок\b|этап\b|барак|камер[аыу]\b|надзиратель|мент\b|опер\b|следак|прокурор|адвокат|суд\b|судь|приговор|статья\b|деанон|анонимн|обвинител|заключен|нелегальн)', msg_lower):
        return True
    
    # Спец слова
    if re.search(r'(конверт|индус\b|белави)', msg_lower):
        return True
    
    return False

# Читаем
with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    lines = [line.strip() for line in f.readlines()]

# Фильтруем
clean = [msg for msg in lines if msg and not is_junk(msg)]

# Дедупликация
seen = set()
unique = []
for msg in clean:
    key = msg.lower().strip()
    if key not in seen:
        seen.add(key)
        unique.append(msg)

# Сохраняем
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    for msg in unique:
        f.write(msg + '\n')

# Статистика
print(f"=== ФИНАЛЬНАЯ СТАТИСТИКА ===")
print(f"Было: {len(lines)}")
print(f"Осталось: {len(unique)}")
print(f"Удалено: {len(lines) - len(unique)} ({(len(lines) - len(unique)) * 100 / len(lines):.1f}%)")
print(f"\nФайл: {OUTPUT_FILE}")

lengths = [len(m) for m in unique]
print(f"\n=== РАСПРЕДЕЛЕНИЕ ПО ДЛИНЕ ===")
print(f"5-15 симв:  {len([l for l in lengths if 5 <= l <= 15]):5} ({len([l for l in lengths if 5 <= l <= 15])*100/len(unique):.1f}%)")
print(f"16-30 симв: {len([l for l in lengths if 16 <= l <= 30]):5} ({len([l for l in lengths if 16 <= l <= 30])*100/len(unique):.1f}%)")
print(f"31-50 симв: {len([l for l in lengths if 31 <= l <= 50]):5} ({len([l for l in lengths if 31 <= l <= 50])*100/len(unique):.1f}%)")
print(f"51-80 симв: {len([l for l in lengths if 51 <= l <= 80]):5} ({len([l for l in lengths if 51 <= l <= 80])*100/len(unique):.1f}%)")

print(f"\n=== 50 ПРИМЕРОВ ЧИСТЫХ СООБЩЕНИЙ ===")
samples = random.sample(unique, min(50, len(unique)))
for i, msg in enumerate(samples, 1):
    print(f"{i:2}. {msg}")
