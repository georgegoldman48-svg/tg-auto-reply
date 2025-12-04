#!/usr/bin/env python3
"""Скрипт для очистки датасета dialog_pairs.jsonl - ФИНАЛЬНАЯ ВЕРСИЯ v3"""

import json
import re
from pathlib import Path
import random

def is_good_pair(question: str, response: str) -> tuple[bool, str]:
    """
    Проверяет, является ли пара вопрос-ответ качественной.
    Возвращает (True/False, причина)
    """
    q = question.strip()
    r = response.strip()
    q_lower = q.lower()
    r_lower = r.lower()

    # === ФИЛЬТРЫ МУСОРА ===

    # 1. Слишком короткий ответ
    if len(r) < 3:
        return False, "слишком короткий ответ"

    # 2. Явный бред
    garbage_phrases = [
        'владельцем костюма', 'вышепривед', 'мандалы атлантиды',
        'светлые ночи )', 'кфнэшн', 'каэшн', 'круио', 'навреное',
        'оль оль', 'здррово'
    ]
    for phrase in garbage_phrases:
        if phrase in r_lower:
            return False, f"мусорная фраза: {phrase}"

    # 3. Только смех без контекста (исключая случаи когда вопрос смешной)
    laugh_patterns = ['хаха', 'ахах', 'хехе', 'ржу', 'лол', 'ха-ха', 'аха-ха']
    funny_q = any(fp in q_lower for fp in laugh_patterns) or 'смешно' in q_lower or '😂' in q or '🤣' in q
    is_pure_laugh = re.match(r'^[ахэХАЭ\-\s]+$', r.replace('а', '').replace('х', '').replace('А', '').replace('Х', '').replace('-', '').replace(' ', ''))
    if is_pure_laugh and ('ха' in r_lower or 'аха' in r_lower):
        if not funny_q:
            return False, "только смех"

    # 4. Оборванные на служебном слове
    if re.search(r'\s(не|и|а|но|что|как|где|или|ни|чтобы|если)\s*$', r, re.I):
        return False, "оборванная фраза"

    # === ПРОВЕРКА СВЯЗНОСТИ ===

    # Приветствия
    greetings_q = ['привет', 'здравствуй', 'добрый день', 'доброе утро', 'добрый вечер', 'хай', 'здорово', 'приветик']
    greetings_r = ['привет', 'здравствуй', 'добр', 'хай', 'на связи', 'здорово', 'приветик', 'здрасте', 'доброе', 'добрый', 'как дела', 'как сам', 'как ты']
    if any(g in q_lower for g in greetings_q):
        if any(g in r_lower for g in greetings_r):
            return True, "приветствие"

    # Прощания
    bye_q = ['пока', 'спать', 'спокойной ночи', 'до свидания', 'увидимся', 'до завтра', 'доброй ночи']
    bye_r = ['пока', 'спокойной', 'увидимся', 'давай', 'до свидания', 'до завтра', 'бай', 'доброй', 'спокойной ночи', 'сна']
    if any(b in q_lower for b in bye_q):
        if any(b in r_lower for b in bye_r):
            return True, "прощание"

    # Спасибо
    if 'спасибо' in q_lower or 'благодар' in q_lower:
        thanks_r = ['пожалуйста', 'не за что', 'всегда', 'обращайся', 'рад', 'за что', 'спасибо', 'как сам', 'как ты']
        if any(t in r_lower for t in thanks_r):
            return True, "благодарность"

    # Как дела / как ты
    if 'как дела' in q_lower or 'как ты' in q_lower or 'как там' in q_lower:
        how_r = ['хорошо', 'нормально', 'отлично', 'так себе', 'плохо', 'устал', 'норм', 'неплохо', 'замечат', 'ничего', 'неважно', 'сносно', 'все', 'всё']
        if any(h in r_lower for h in how_r):
            return True, "как дела"

    # Ты тут/здесь?
    if 'ты тут' in q_lower or 'ты здесь' in q_lower:
        here_r = ['да', 'тут', 'здесь', 'на связи', 'всегда', 'я тут', 'я здесь']
        if any(h in r_lower for h in here_r):
            return True, "ты тут"

    # Вопросы с "?"
    if '?' in q:
        # Ответы да/нет/может в начале
        yes_no_starts = ('да', 'нет', 'конечно', 'возможно', 'наверное', 'точно', 'вряд', 'думаю', 'скорее', 'есть', 'был', 'была')
        if any(r_lower.startswith(s) for s in yes_no_starts):
            return True, "ответ да/нет"

        # Вопрос "где"
        if re.search(r'\bгде\b', q_lower):
            loc_r = ['дома', 'на работе', 'еду', 'иду', 'тут', 'здесь', 'рядом', 'недалеко', 'в ', 'у ']
            if any(l in r_lower for l in loc_r):
                return True, "вопрос о месте"

        # Вопрос "когда"
        if re.search(r'\bкогда\b', q_lower):
            time_r = ['скоро', 'через', 'минут', 'час', 'завтра', 'вечер', 'потом', 'позже', 'сейчас', 'сегодня', 'осень', 'зим', 'весн', 'лет', 'неделю']
            if any(t in r_lower for t in time_r):
                return True, "вопрос о времени"

        # Вопрос "что делаешь"
        if 'что делаешь' in q_lower or 'чем занят' in q_lower or 'чем занимаешься' in q_lower:
            doing_r = ['работаю', 'отдыхаю', 'сплю', 'ем', 'смотрю', 'играю', 'читаю', 'ничего', 'еду', 'иду', 'сижу', 'жду']
            if any(d in r_lower for d in doing_r):
                return True, "что делаешь"

        # Вопрос "сколько"
        if 'сколько' in q_lower:
            if re.search(r'\d', r):
                return True, "вопрос сколько"

        # Вопрос "какой/какая/какое" - строже, нужны общие слова
        if re.search(r'\bкак(ой|ая|ое|ие)\b', q_lower):
            q_words = set(re.findall(r'\b[а-яёa-z]{4,}\b', q_lower))
            r_words = set(re.findall(r'\b[а-яёa-z]{4,}\b', r_lower))
            if q_words & r_words:
                return True, "вопрос какой"

        # Вопрос "ты" с ответом "я" или "там"
        if re.search(r'\bты\b', q_lower):
            if r_lower.startswith('я ') or ' я ' in r_lower or 'там ' in r_lower:
                return True, "вопрос о тебе - ответ о себе"

    # Ответы на подтверждение/согласие
    confirm_q = ['хорошо?', 'ладно?', 'ок?', 'окей?', 'да?', 'понял?', 'договорились?', 'идёт?', 'идет?', 'пойдём?', 'пойдем?']
    if any(c in q_lower for c in confirm_q):
        confirm_r = ['да', 'хорошо', 'ок', 'окей', 'ладно', 'договорились', 'понял', 'принял', 'идет', 'конечно', 'идём', 'пойдем', 'пойдём']
        if any(c in r_lower for c in confirm_r):
            return True, "подтверждение"

    # Команды/просьбы (императив)
    commands = ['скинь', 'пришли', 'отправь', 'позвони', 'напиши', 'сделай', 'посмотри', 'проверь', 'набери', 'глянь', 'передай', 'возьми', 'купи', 'напечата', 'приезжай', 'приходи', 'сфоткай', 'скинула', 'скинул']
    if any(c in q_lower for c in commands):
        cmd_r = ['сейчас', 'секунду', 'минуту', 'сделаю', 'хорошо', 'ок', 'принял', 'уже', 'готово', 'понял', 'ща', 'передал', 'передам', 'куплю', 'возьму', 'сделано', 'спасибо', 'гляну', 'посмотрю']
        if any(c in r_lower for c in cmd_r):
            return True, "команда-выполнение"

    # Есть общие значимые слова (длиной >= 4 символов)
    stopwords = {'который', 'которая', 'которые', 'просто', 'только', 'можно', 'нужно', 'будет',
                 'может', 'почему', 'потому', 'когда', 'чтобы', 'вообще', 'сейчас', 'сегодня',
                 'завтра', 'всегда', 'никогда', 'ничего', 'вчера', 'именно', 'поэтому', 'такое',
                 'такой', 'такая', 'такие', 'наверное', 'правда', 'конечно', 'было', 'была',
                 'были', 'есть', 'этот', 'этого', 'этой', 'этим', 'этих', 'тоже', 'себя',
                 'себе', 'меня', 'тебя', 'него', 'неё', 'свой', 'своя', 'свою', 'твой',
                 'твоя', 'твою', 'очень', 'много', 'мало', 'чуть', 'ещё', 'какой', 'какая',
                 'какие', 'какое', 'через', 'после', 'перед', 'снова', 'опять', 'вроде'}

    q_words = set(re.findall(r'\b[а-яёa-z]{4,}\b', q_lower))
    r_words = set(re.findall(r'\b[а-яёa-z]{4,}\b', r_lower))
    common = (q_words & r_words) - stopwords
    if common:
        return True, f"общие слова: {', '.join(list(common)[:3])}"

    # Ответ на эмоцию/реакцию
    emotions_q = ['круто', 'офигеть', 'вау', 'супер', 'класс', 'ужас', 'кошмар', 'бесит', 'надоело', 'блин', 'жесть', 'охуеть']
    emotions_r = ['да уж', 'согласен', 'не то слово', 'именно', 'точно', 'понимаю', 'бывает', 'сочувствую', 'да', 'угу']
    if any(e in q_lower for e in emotions_q):
        if any(e in r_lower for e in emotions_r):
            return True, "эмоциональная реакция"

    # Ответ-вопрос (уточнение) - СТРОЖЕ: должны быть общие слова ИЛИ короткий вопрос + короткий ответ-вопрос
    if '?' in r:
        r_question_words = ['какой', 'какая', 'какие', 'какое', 'что', 'где', 'когда', 'почему', 'зачем', 'сколько', 'кто', 'как', 'куда', 'откуда']
        if any(w in r_lower for w in r_question_words):
            # Проверяем что это уточнение по теме
            q_words_4 = set(re.findall(r'\b[а-яёa-z]{4,}\b', q_lower))
            r_words_4 = set(re.findall(r'\b[а-яёa-z]{4,}\b', r_lower))
            common_4 = (q_words_4 & r_words_4) - stopwords
            if common_4:
                return True, "уточняющий вопрос по теме"
            # Или короткий вопрос и короткий ответ-вопрос
            if len(q.split()) <= 4 and len(r.split()) <= 5:
                return True, "уточняющий вопрос"

    # Числа в контексте
    if re.search(r'\d+', q) and re.search(r'\d+', r):
        return True, "числовой контекст"

    # Ответы "понял/принял/хорошо" на информационное сообщение
    info_responses = ['понял', 'принял', 'хорошо', 'ясно', 'понятно', 'ок', 'окей', 'ладно', 'спасибо', 'принято', 'гляну', 'посмотрю', 'заметил']
    for ir in info_responses:
        if ir in r_lower and len(r.split()) <= 4:
            # Проверяем что вопрос был информативный (не вопрос и не слишком короткий)
            if '?' not in q and len(q.split()) >= 2:
                return True, "подтверждение получения информации"

    # Ответ содержит продолжение мысли (есть союзы/связки)
    continuations = ['потому что', 'так как', 'поэтому', 'значит', 'следовательно']
    if any(c in r_lower for c in continuations):
        if len(r.split()) >= 3:
            return True, "продолжение мысли"

    # Реплики-реакции на угрозы/шутки
    threat_joke_q = ['убью', 'поставлю', 'накажу', 'отшлепаю', 'задам']
    threat_joke_r = ['если', 'а если', 'попробуй', 'не надо', 'пожалуйста', 'извини', 'а что', 'ой']
    if any(t in q_lower for t in threat_joke_q):
        if any(t in r_lower for t in threat_joke_r):
            return True, "реакция на угрозу/шутку"

    # Ответ "еще/ещё/скоро/пока" на вопрос о статусе
    status_q_words = ['приехал', 'пришел', 'готов', 'сделал', 'закончил', 'получил']
    status_r_words = ['еще', 'ещё', 'скоро', 'пока', 'уже', 'почти', 'сейчас', 'минут', 'выезжа']
    if any(s in q_lower for s in status_q_words):
        if any(s in r_lower for s in status_r_words):
            return True, "статус"

    # Ответ на жалобу/проблему
    problem_q = ['сломал', 'не работает', 'не получается', 'проблем', 'ошибка', 'глючит', 'не могу', 'ничего не получается']
    problem_r = ['попробуй', 'надо', 'нужно', 'давай', 'странно', 'почему', 'как проверить', 'ладно', 'не страшно', 'бывает']
    if any(p in q_lower for p in problem_q):
        if any(p in r_lower for p in problem_r):
            return True, "ответ на проблему"

    # Ответ на предложение
    offer_q = ['хочешь', 'будешь', 'давай', 'поехали', 'пойдем', 'пойдём']
    offer_r = ['да', 'нет', 'давай', 'конечно', 'не хочу', 'хочу', 'можно', 'поехали', 'пошли']
    if any(o in q_lower for o in offer_q):
        if any(o in r_lower for o in offer_r):
            return True, "ответ на предложение"

    # Ответы на новости/факты
    news_q = ['узнал', 'оказывается', 'выяснилось', 'написали', 'сказали', 'приехала', 'уехала', 'вернулся', 'нашел', 'нашла']
    news_r = ['когда', 'как', 'почему', 'зачем', 'круто', 'здорово', 'понял', 'интересно', 'гляну']
    if any(n in q_lower for n in news_q):
        if any(n in r_lower for n in news_r):
            return True, "реакция на новость"

    # Противопоставление (нет/есть, не/да)
    if 'нет' in q_lower or 'нету' in q_lower:
        if r_lower.startswith('есть') or 'есть!' in r_lower:
            return True, "противопоставление"

    # Ответ "да ладно" / "ну ладно" на утверждение
    surprise_r = ['да ладно', 'ну ладно', 'серьезно', 'правда', 'реально', 'ого', 'ничего себе']
    if any(sr in r_lower for sr in surprise_r):
        return True, "реакция удивления"

    return False, "нет связи между вопросом и ответом"


def clean_dataset(input_path: str, output_path: str):
    """Очищает датасет и сохраняет результат"""

    input_file = Path(input_path)
    output_file = Path(output_path)

    total = 0
    kept = 0
    removed_reasons = {}

    good_pairs = []
    removed_pairs = []

    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            total += 1
            try:
                data = json.loads(line.strip())
                messages = data.get('messages', [])

                if len(messages) != 2:
                    reason = "неверный формат"
                    removed_reasons[reason] = removed_reasons.get(reason, 0) + 1
                    continue

                question = messages[0].get('content', '')
                response = messages[1].get('content', '')

                is_good, reason = is_good_pair(question, response)

                if is_good:
                    good_pairs.append(data)
                    kept += 1
                else:
                    removed_reasons[reason] = removed_reasons.get(reason, 0) + 1
                    removed_pairs.append((question, response, reason))

            except json.JSONDecodeError:
                reason = "ошибка JSON"
                removed_reasons[reason] = removed_reasons.get(reason, 0) + 1
                continue

    # Сохраняем очищенный датасет
    with open(output_file, 'w', encoding='utf-8') as f:
        for pair in good_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + '\n')

    # Статистика
    print("=" * 70)
    print("СТАТИСТИКА ОЧИСТКИ ДАТАСЕТА")
    print("=" * 70)
    print(f"Было пар:              {total}")
    print(f"Стало пар:             {kept}")
    print(f"Удалено всего:         {total - kept} ({(total-kept)/total*100:.1f}%)")
    print()
    print("Причины удаления:")
    for reason, count in sorted(removed_reasons.items(), key=lambda x: -x[1]):
        print(f"  - {reason}: {count}")
    print("=" * 70)

    # Показываем примеры хороших пар
    print("\n30 ПРИМЕРОВ ХОРОШИХ ПАР:")
    print("-" * 70)

    samples = random.sample(good_pairs, min(30, len(good_pairs)))

    for i, pair in enumerate(samples, 1):
        q = pair['messages'][0]['content']
        a = pair['messages'][1]['content']
        print(f"{i:2}. Q: {q[:60]}{'...' if len(q) > 60 else ''}")
        print(f"    A: {a[:60]}{'...' if len(a) > 60 else ''}")
        print()

    # Примеры удаленных
    print("\n10 ПРИМЕРОВ УДАЛЁННЫХ ПАР:")
    print("-" * 70)
    removed_samples = random.sample(removed_pairs, min(10, len(removed_pairs)))
    for i, (q, a, reason) in enumerate(removed_samples, 1):
        print(f"{i:2}. Q: {q[:50]}{'...' if len(q) > 50 else ''}")
        print(f"    A: {a[:50]}{'...' if len(a) > 50 else ''}")
        print(f"    [Причина: {reason}]")
        print()

    return kept, total


if __name__ == '__main__':
    random.seed(42)
    input_path = '/home/george/Downloads/tg-auto-reply/data/dialog_pairs.jsonl'
    output_path = '/home/george/Downloads/tg-auto-reply/data/dialog_pairs_clean.jsonl'

    clean_dataset(input_path, output_path)
