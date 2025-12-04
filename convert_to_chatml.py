#!/usr/bin/env python3
"""
Конвертация диалогов в ChatML формат для Unsloth fine-tuning
"""
import json

INPUT_FILE = '/home/george/Downloads/tg-auto-reply/data/dialog_pairs.jsonl'
OUTPUT_FILE = '/home/george/Downloads/tg-auto-reply/data/train_data.jsonl'

SYSTEM_PROMPT = "Ты Егор. Отвечай коротко, неформально."

def to_chatml(user_msg, assistant_msg, system=None):
    """Конвертирует в ChatML формат"""
    text = ""
    if system:
        text += f"<|im_start|>system\n{system}<|im_end|>\n"
    text += f"<|im_start|>user\n{user_msg}<|im_end|>\n"
    text += f"<|im_start|>assistant\n{assistant_msg}<|im_end|>"
    return text

# Читаем диалоги
dialogs = []
with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    for line in f:
        if line.strip():
            dialogs.append(json.loads(line))

# Конвертируем
converted = []
for d in dialogs:
    user_msg = d['messages'][0]['content']
    assistant_msg = d['messages'][1]['content']
    
    chatml_text = to_chatml(user_msg, assistant_msg, SYSTEM_PROMPT)
    
    converted.append({
        "text": chatml_text
    })

# Сохраняем
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    for item in converted:
        f.write(json.dumps(item, ensure_ascii=False) + '\n')

print(f"=== Конвертация завершена ===")
print(f"Входной файл: {INPUT_FILE}")
print(f"Выходной файл: {OUTPUT_FILE}")
print(f"Всего примеров: {len(converted)}")
print(f"\n=== Пример записи ===")
print(converted[0]['text'])
print(f"\n=== Ещё 2 примера ===")
for i in [10, 50]:
    if i < len(converted):
        print(f"\n--- Пример {i} ---")
        print(converted[i]['text'])
