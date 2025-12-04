#!/usr/bin/env python3
import re
import random

INPUT_FILE = '/home/george/Downloads/tg-auto-reply/my_messages_raw.txt'
OUTPUT_FILE = '/home/george/Downloads/tg-auto-reply/my_messages_clean.txt'

def is_junk(msg):
    msg_lower = msg.lower().strip()
    original = msg.strip()
    
    # Слишком короткие или длинные
    if len(original) < 5 or len(original) > 100:
        return True
    
    # Пустые и точки
    if re.match(r'^[\.\s\-_\!\?\,]+$', original):
        return True
    
    # Пароли, логины, credentials
    if re.search(r'(password|passwd|pass:|login:|username:|user:|pwd:|apikey|api_key|secret|token|bearer|auth)', msg_lower):
        return True
    
    # SSH ключи, seed фразы (12+ слов через пробел - мнемоники)
    words = msg.split()
    if len(words) >= 10 and all(re.match(r'^[a-z]+$', w) for w in words):
        return True
    
    # Номера карт (16 цифр)
    if re.search(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b', msg):
        return True
    
    # CVV
    if re.search(r'\bcvv\b|\bcvc\b', msg_lower):
        return True
    
    # Ссылки
    if re.search(r'https?://|t\.me/|\.onion|www\.|\.com/|\.ru/|\.org/', msg_lower):
        return True
    
    # Email
    if re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', msg):
        return True
    
    # Телефоны
    digits_only = re.sub(r'\D', '', msg)
    if len(digits_only) >= 9:
        return True
    
    # IP адреса
    if re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', msg):
        return True
    
    # Технические команды и термины
    tech_patterns = r'\b(sudo|ssh|curl|wget|bash|chmod|chown|apt|pip|npm|docker|git|systemctl|nginx|postgres|mysql|redis|json|xml|api|http|https|ssl|tls|dns|tcp|udp|port|server|client|host|domain|certificate|сертификат|encrypt|let\'?s?\s*encrypt|valid|bybit|trading|crypto)\b'
    if re.search(tech_patterns, msg_lower):
        return True
    
    # IMEI (15 цифр)
    if re.search(r'\b\d{15}\b', msg):
        return True
    
    # Серийные номера (длинные буквенно-цифровые)
    if re.search(r'\b[A-Z0-9]{8,}\b', msg):
        return True
    
    # Адреса (улицы с номерами)
    if re.search(r'\b(street|st\.|ave|avenue|road|rd\.|blvd|drive|dr\.|улица|ул\.|проспект|пр\.|переулок|пер\.)\b', msg_lower):
        return True
    
    # Почтовые индексы (ZIP) - 5-6 цифр подряд
    if re.search(r'\b\d{5,6}\b', msg):
        return True
    
    # Имена файлов
    if re.search(r'\.(mp4|mp3|avi|mkv|pdf|doc|docx|xls|xlsx|zip|rar|tar|gz|py|js|ts|sh|gguf|bin|exe|apk|jpg|jpeg|png|gif|webp|txt|log|conf|cfg|yaml|yml|sql|csv)(\s|$)', msg_lower):
        return True
    
    # @упоминания
    if re.search(r'@\w{3,}', msg):
        return True
    
    # Хеши и длинные hex строки
    if re.search(r'\b[a-f0-9]{16,}\b', msg_lower):
        return True
    
    # SSN формат
    if re.search(r'\b\d{3}[\s\-]?\d{2}[\s\-]?\d{4}\b', msg):
        return True
    
    # Преимущественно английский текст (>40% латиница)
    letters = re.findall(r'[a-zA-Zа-яёА-ЯЁ]', msg)
    if letters:
        latin = len([c for c in letters if re.match(r'[a-zA-Z]', c)])
        cyrillic = len([c for c in letters if re.match(r'[а-яёА-ЯЁ]', c)])
        if len(letters) >= 5 and latin > cyrillic * 0.6:  # Если латиницы >40%
            return True
    
    # JSON/код
    if re.search(r'[\{\}\[\]]', msg) or msg.count(':') >= 3:
        return True
    
    # Только цифры и знаки
    if re.match(r'^[\d\s\.\,\-\+\(\)\/]+$', original):
        return True
    
    # Команды с тире (--option, -flag)
    if re.search(r'\s\-\-?\w+', msg):
        return True
    
    # Пути к файлам
    if re.search(r'[/\\][\w\-\.]+[/\\]', msg):
        return True
    
    # Криптовалютные адреса
    if re.search(r'\b(0x[a-fA-F0-9]{40}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[a-zA-HJ-NP-Z0-9]{39,59})\b', msg):
        return True
    
    return False

# Читаем и обрабатываем
with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    raw_lines = f.readlines()

# Убираем переносы и фильтруем
clean_messages = []
for line in raw_lines:
    line = line.strip()
    if line and not is_junk(line):
        clean_messages.append(line)

# Убираем дубликаты, сохраняя порядок
seen = set()
unique_messages = []
for msg in clean_messages:
    normalized = msg.lower().strip()
    if normalized not in seen:
        seen.add(normalized)
        unique_messages.append(msg)

# Сохраняем
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    for msg in unique_messages:
        f.write(msg + '\n')

# Статистика
print(f"=== СТАТИСТИКА ===")
print(f"Было строк: {len(raw_lines)}")
print(f"После очистки: {len(clean_messages)}")
print(f"Уникальных: {len(unique_messages)}")
print(f"Удалено: {len(raw_lines) - len(unique_messages)} ({(len(raw_lines) - len(unique_messages)) * 100 / len(raw_lines):.1f}%)")
print(f"\nСохранено в: {OUTPUT_FILE}")

print(f"\n=== 30 ПРИМЕРОВ ЧИСТЫХ СООБЩЕНИЙ ===")
samples = random.sample(unique_messages, min(30, len(unique_messages)))
for i, msg in enumerate(samples, 1):
    print(f"{i:2}. {msg}")
