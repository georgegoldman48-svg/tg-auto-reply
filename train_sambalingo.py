#!/usr/bin/env python3
"""
Fine-tuning SambaLingo-Russian-Chat с использованием Unsloth
Обучение на диалогах Егора для имитации стиля общения
"""

from unsloth import FastLanguageModel
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments
import torch

# ============== КОНФИГУРАЦИЯ ==============
MODEL_NAME = "sambanovasystems/SambaLingo-Russian-Chat"
DATASET_PATH = "/home/george/Downloads/tg-auto-reply/data/train_data.jsonl"
OUTPUT_DIR = "/home/george/sambalingo-egor"

# LoRA параметры
LORA_R = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05

# Обучение
MAX_SEQ_LENGTH = 512
BATCH_SIZE = 2
GRADIENT_ACCUMULATION = 4
EPOCHS = 3
LEARNING_RATE = 2e-4
WARMUP_STEPS = 50

# ============== ЗАГРУЗКА МОДЕЛИ ==============
print("=" * 60)
print("Загрузка модели SambaLingo-Russian-Chat...")
print("=" * 60)

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=MODEL_NAME,
    max_seq_length=MAX_SEQ_LENGTH,
    dtype=None,  # auto detect
    load_in_4bit=True,  # Квантизация для экономии памяти
)

# ============== НАСТРОЙКА LoRA ==============
print("\nНастройка LoRA адаптера...")

model = FastLanguageModel.get_peft_model(
    model,
    r=LORA_R,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj"
    ],
    lora_alpha=LORA_ALPHA,
    lora_dropout=LORA_DROPOUT,
    bias="none",
    use_gradient_checkpointing="unsloth",  # Экономия памяти
    random_state=42,
)

# ============== ЗАГРУЗКА ДАТАСЕТА ==============
print(f"\nЗагрузка датасета: {DATASET_PATH}")

dataset = load_dataset(
    "json",
    data_files=DATASET_PATH,
    split="train"
)

print(f"Размер датасета: {len(dataset)} примеров")
print(f"Пример данных:\n{dataset[0]['text'][:200]}...")

# ============== НАСТРОЙКА ОБУЧЕНИЯ ==============
print("\nНастройка параметров обучения...")

training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    num_train_epochs=EPOCHS,
    per_device_train_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=GRADIENT_ACCUMULATION,
    learning_rate=LEARNING_RATE,
    warmup_steps=WARMUP_STEPS,
    logging_steps=25,
    save_steps=500,
    save_total_limit=2,
    fp16=not torch.cuda.is_bf16_supported(),
    bf16=torch.cuda.is_bf16_supported(),
    optim="adamw_8bit",
    weight_decay=0.01,
    lr_scheduler_type="cosine",
    seed=42,
    report_to="none",  # Отключаем wandb
)

# ============== СОЗДАНИЕ ТРЕНЕРА ==============
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=MAX_SEQ_LENGTH,
    args=training_args,
    packing=False,  # Не объединяем короткие примеры
)

# ============== ОБУЧЕНИЕ ==============
print("\n" + "=" * 60)
print("НАЧАЛО ОБУЧЕНИЯ")
print("=" * 60)
print(f"Модель: {MODEL_NAME}")
print(f"LoRA r={LORA_R}, alpha={LORA_ALPHA}")
print(f"Epochs: {EPOCHS}")
print(f"Batch size: {BATCH_SIZE} x {GRADIENT_ACCUMULATION} = {BATCH_SIZE * GRADIENT_ACCUMULATION}")
print(f"Learning rate: {LEARNING_RATE}")
print(f"Max sequence length: {MAX_SEQ_LENGTH}")
print("=" * 60 + "\n")

trainer.train()

# ============== СОХРАНЕНИЕ ==============
print("\n" + "=" * 60)
print("Сохранение модели...")
print("=" * 60)

# Сохраняем LoRA адаптер
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)

print(f"\nАдаптер сохранён в: {OUTPUT_DIR}")

# ============== ТЕСТ ==============
print("\n" + "=" * 60)
print("БЫСТРЫЙ ТЕСТ")
print("=" * 60)

FastLanguageModel.for_inference(model)

test_prompts = [
    "Привет, как дела?",
    "Ты где?",
    "Скучаю по тебе",
]

for prompt in test_prompts:
    input_text = f"""<|im_start|>system
Ты Егор. Отвечай коротко, неформально.<|im_end|>
<|im_start|>user
{prompt}<|im_end|>
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
    # Извлекаем только ответ
    if "<|im_start|>assistant" in response:
        answer = response.split("<|im_start|>assistant")[-1]
        answer = answer.split("<|im_end|>")[0].strip()
    else:
        answer = response
    
    print(f"Q: {prompt}")
    print(f"A: {answer}\n")

print("=" * 60)
print("ГОТОВО!")
print(f"Адаптер: {OUTPUT_DIR}")
print("=" * 60)
