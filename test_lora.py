#!/usr/bin/env python3
"""Тестирование обученной LoRA модели"""

from unsloth import FastLanguageModel
import torch

# Загрузка модели с LoRA адаптером
print("Загрузка модели с LoRA адаптером...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="/home/george/sambalingo-egor",
    max_seq_length=512,
    dtype=None,
    load_in_4bit=True,
)

FastLanguageModel.for_inference(model)

SYSTEM_PROMPT = "Ты Егор. Отвечаешь коротко, живо, по делу. Без воды и официоза."

test_questions = [
    "Привет, как дела?",
    "Ты где?",
    "Что делаешь?",
    "Можешь говорить?",
    "Когда освободишься?",
    "Скучаю по тебе",
    "Ты бот?",
    "Перезвонишь?",
    "Во сколько встретимся?",
    "Как тебя зовут?",
    "Хэллоу",
    "наврал с три короба",
    "а чем тебе эпл не угодил?",
]

print("\n" + "=" * 60)
print("ТЕСТИРОВАНИЕ ОБУЧЕННОЙ МОДЕЛИ (LoRA)")
print("=" * 60)

for q in test_questions:
    input_text = f"""<|im_start|>system
{SYSTEM_PROMPT}<|im_end|>
<|im_start|>user
{q}<|im_end|>
<|im_start|>assistant
"""
    inputs = tokenizer(input_text, return_tensors="pt").to("cuda")

    outputs = model.generate(
        **inputs,
        max_new_tokens=50,
        temperature=0.7,
        do_sample=True,
        pad_token_id=tokenizer.eos_token_id,
    )

    response = tokenizer.decode(outputs[0], skip_special_tokens=False)
    if "<|im_start|>assistant" in response:
        answer = response.split("<|im_start|>assistant")[-1]
        answer = answer.split("<|im_end|>")[0].strip()
    else:
        answer = response

    print(f"Q: {q}")
    print(f"A: {answer}")
    print("-" * 40)

print("\nГотово!")
