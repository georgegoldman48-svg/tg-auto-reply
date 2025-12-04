#!/usr/bin/env python3
import json
import re
import random

# Загружаем чистые ответы Егора для фильтрации
CLEAN_ANSWERS_FILE = '/home/george/Downloads/tg-auto-reply/my_messages_final.txt'
OUTPUT_FILE = '/home/george/Downloads/tg-auto-reply/data/dialog_pairs.jsonl'

def load_clean_answers():
    with open(CLEAN_ANSWERS_FILE, 'r', encoding='utf-8') as f:
        return set(line.strip().lower() for line in f if line.strip())

def is_valid_incoming(msg):
    if not msg or len(msg) < 5 or len(msg) > 150:
        return False
    # Должна быть кириллица
    if not re.search(r'[а-яёА-ЯЁ]', msg):
        return False
    # Без мусора
    if re.search(r'(https?://|t\.me/|@\w{3,}|password|login|pass:|www\.)', msg.lower()):
        return False
    # Без email
    if re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', msg):
        return False
    # Без длинных чисел
    if re.search(r'\b\d{6,}\b', msg):
        return False
    return True

def is_similar(answer, clean_set):
    """Проверяем точное или похожее совпадение"""
    answer_lower = answer.strip().lower()
    if answer_lower in clean_set:
        return True
    # Проверяем без пунктуации
    answer_clean = re.sub(r'[^\w\s]', '', answer_lower)
    for clean in clean_set:
        clean_stripped = re.sub(r'[^\w\s]', '', clean)
        if answer_clean == clean_stripped:
            return True
    return False

# Загружаем чистые ответы
clean_answers = load_clean_answers()
print(f"Загружено {len(clean_answers)} чистых ответов")

# Читаем диалоги из stdin (переданные из SQL)
import sys
pairs = []
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        # Формат: incoming|outgoing
        parts = line.split('|', 1)
        if len(parts) != 2:
            continue
        incoming, outgoing = parts
        incoming = incoming.strip()
        outgoing = outgoing.strip()
        
        if not incoming or not outgoing:
            continue
            
        if not is_valid_incoming(incoming):
            continue
            
        if not is_similar(outgoing, clean_answers):
            continue
        
        pairs.append({
            "messages": [
                {"role": "user", "content": incoming},
                {"role": "assistant", "content": outgoing}
            ]
        })
    except Exception as e:
        continue

# Убираем дубликаты по паре
seen = set()
unique_pairs = []
for p in pairs:
    key = (p["messages"][0]["content"].lower(), p["messages"][1]["content"].lower())
    if key not in seen:
        seen.add(key)
        unique_pairs.append(p)

# Сохраняем
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    for p in unique_pairs:
        f.write(json.dumps(p, ensure_ascii=False) + '\n')

print(f"\n=== СТАТИСТИКА ===")
print(f"Всего пар после фильтра: {len(pairs)}")
print(f"Уникальных пар: {len(unique_pairs)}")
print(f"Сохранено: {OUTPUT_FILE}")

print(f"\n=== 20 ПРИМЕРОВ ===")
samples = random.sample(unique_pairs, min(20, len(unique_pairs)))
for i, p in enumerate(samples, 1):
    user = p["messages"][0]["content"]
    assistant = p["messages"][1]["content"]
    print(f"{i:2}. [{user[:50]}...] → [{assistant[:50]}...]" if len(user) > 50 or len(assistant) > 50 else f"{i:2}. [{user}] → [{assistant}]")
