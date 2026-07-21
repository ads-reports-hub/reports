"""
Маленький помощник для apply_edits.py: Лиза пишет правки только по-русски,
здесь получаем английскую версию тем же вызовом Claude, с тем же жёстким
правилом "никакого длинного тире", что и в commentary.py.
"""
import anthropic

MODEL = "claude-sonnet-4-5"
MAX_ATTEMPTS = 3
EM_DASH = "—"


class TranslateError(Exception):
    pass


def translate_ru_to_en(text_ru: str, api_key: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    prompt_base = (
        "Переведи текст ниже с русского на английский для клиентского маркетингового "
        "отчёта. Сохрани тон и смысл, ничего от себя не добавляй. Никогда не используй "
        "символ длинного тире (—), вместо него запятая, точка или скобки. В ответе только "
        "перевод, без пояснений и без кавычек вокруг него.\n\n"
        f"Текст:\n{text_ru}"
    )
    last_error = ""
    for _attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = prompt_base if not last_error else (
            f"{prompt_base}\n\n(Предыдущий ответ отклонён: {last_error} Попробуй ещё раз.)"
        )
        resp = client.messages.create(model=MODEL, max_tokens=1024, messages=[{"role": "user", "content": prompt}])
        text = resp.content[0].text.strip()
        if EM_DASH in text:
            last_error = "В ответе найден запрещённый символ длинного тире (—)."
            continue
        return text

    raise TranslateError(f"Не удалось перевести текст за {MAX_ATTEMPTS} попыток: {last_error}")
