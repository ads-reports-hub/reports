"""
Зовёт Anthropic API, чтобы дописать текстовые AI-поля в уже посчитанные
метрики (см. normalize.py) — то, что раньше в этом проекте писал я вручную
(вердикты по кампаниям, выводы, рекомендации, инсайт-абзац) на голосе Лизы.

Ретраит при невалидном JSON и при обнаружении em dash "—" (жёсткое правило
style-guide.md) — если модель всё равно вставила длинное тире, это не должно
тихо просочиться в опубликованный отчёт.
"""
import json
import re
from pathlib import Path

import anthropic

ENGINE_DIR = Path(__file__).parent
MODEL = "claude-sonnet-4-5"
MAX_ATTEMPTS = 3

EM_DASH = "—"


class CommentaryError(Exception):
    pass


def _load_prompt_template() -> str:
    return (ENGINE_DIR / "comment-prompt.md").read_text(encoding="utf-8")


def _load_style_guide() -> str:
    return (ENGINE_DIR / "style-guide.md").read_text(encoding="utf-8")


def _strip_ai_only_fields(data: dict) -> dict:
    """Отдаём модели только числовую часть — без ads[].thumb/adId и прочих
    технических полей, которые ей не нужны и только раздувают промпт."""
    slim_campaigns = []
    for c in data["campaigns"]:
        slim_campaigns.append({
            "name": c["name"], "goal_ru": c["goal_ru"], "goal_en": c["goal_en"],
            "audience": c["audience"], "reach": c["reach"], "impressions": c["impressions"],
            "frequency": c["frequency"], "spend": c["spend"], "clicks": c["clicks"],
            "ctr": c["ctr"], "cpc": c["cpc"], "postEngagement": c["postEngagement"],
            "videoViews": c["videoViews"],
        })
    slim = {
        "client": data["client"],
        "totals": data["totals"],
        "campaigns": slim_campaigns,
        "audiences": [{"name": a["name_ru"], "spend": a["spend"], "reach": a["reach"], "ctr_range": a["ctr_range"]} for a in data["audiences"]],
        "platforms": [{"label": p["label_ru"], "spend": p["spend"], "clicks": p["clicks"], "cpc": p["cpc"]} for p in data["platforms"]],
        "demographics_rows": data["demographics"]["rows"],
        "top_ads": [{"campaign": a["name_ru"], "badge": a["badge_ru"], "ctr": None} for a in data["topAds"]],
    }
    if data.get("showDynamics") and data.get("prevTotals"):
        slim["prevTotals"] = data["prevTotals"]
    return slim


def _contains_em_dash(obj) -> bool:
    if isinstance(obj, str):
        return EM_DASH in obj
    if isinstance(obj, list):
        return any(_contains_em_dash(x) for x in obj)
    if isinstance(obj, dict):
        return any(_contains_em_dash(v) for v in obj.values())
    return False


def _call_anthropic(client, prompt: str, error_context: str = "") -> dict:
    full_prompt = prompt if not error_context else f"{prompt}\n\n## Предыдущая попытка не подошла\n{error_context}\nПопробуй ещё раз, строго следуя формату и правилам."
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": full_prompt}],
    )
    text = resp.content[0].text.strip()
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)


def generate(normalized: dict, api_key: str) -> dict:
    """normalized: выход normalize.normalize(). Возвращает словарь с
    AI-полями, готовыми для слияния в normalized перед рендером."""
    client = anthropic.Anthropic(api_key=api_key)

    show_dynamics = bool(normalized.get("showDynamics"))
    dynamics_instruction = (
        "Клиент явно попросил НЕ упоминать сравнение с прошлым месяцем ни в каком виде "
        "(ни цифрами, ни словами вроде \"выросло\"/\"снизилось\"/\"по сравнению с\"). "
        "Пиши только про то, что произошло в текущем периоде: какие аудитории и площадки "
        "сработали лучше других ВНУТРИ этого месяца."
        if not show_dynamics else
        "Клиент хочет видеть сравнение с прошлым периодом там, где это уместно и есть "
        "prevTotals во входных данных — можно упоминать рост/падение метрик и вероятные причины."
    )

    slim = _strip_ai_only_fields(normalized)
    prompt = (
        _load_prompt_template()
        .replace("{{DYNAMICS_INSTRUCTION}}", dynamics_instruction)
        .replace("{{SHOW_DYNAMICS}}", "да" if show_dynamics else "нет")
        .replace("{{METRICS_JSON}}", json.dumps(slim, ensure_ascii=False, indent=2))
    )

    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = _call_anthropic(client, prompt, last_error)
        except json.JSONDecodeError as e:
            last_error = f"Ответ не был валидным JSON: {e}"
            continue

        if _contains_em_dash(result):
            last_error = "В ответе найден запрещённый символ длинного тире (—). Перепиши без него."
            continue

        n_campaigns = len(normalized["campaigns"])
        if len(result.get("campaign_verdicts", [])) != n_campaigns:
            last_error = f"Ожидалось {n_campaigns} campaign_verdicts, получено {len(result.get('campaign_verdicts', []))}."
            continue

        return result

    raise CommentaryError(f"Не удалось получить валидный комментарий за {MAX_ATTEMPTS} попыток: {last_error}")


def merge(normalized: dict, ai: dict) -> dict:
    """Сливает AI-текст обратно в normalized, возвращает готовый data.json
    (полностью соответствующий report.schema.json, готовый к render.render_report)."""
    data = dict(normalized)
    data["insight_ru"] = ai["insight_ru"]
    data["insight_en"] = ai["insight_en"]

    verdicts_by_index = {v["index"]: v for v in ai["campaign_verdicts"]}
    for i, c in enumerate(data["campaigns"], start=1):
        v = verdicts_by_index[i]
        c["verdict_ru"] = v["verdict_ru"]
        c["verdict_en"] = v["verdict_en"]

    notes_by_index = {n["index"]: n for n in ai.get("audience_notes", [])}
    for i, a in enumerate(data["audiences"], start=1):
        n = notes_by_index.get(i)
        a["note_ru"] = n["note_ru"] if n else ""
        a["note_en"] = n["note_en"] if n else ""
        a["badge_ru"] = a.get("badge_ru")  # выставляется отдельно, только у "лучшей" аудитории (см. orchestrator)
        a["badge_en"] = a.get("badge_en")

    data["platforms_note_ru"] = ai.get("platforms_note_ru", "")
    data["platforms_note_en"] = ai.get("platforms_note_en", "")

    data["demographics"]["note_ru"] = ai.get("demographics_note_ru", "")
    data["demographics"]["note_en"] = ai.get("demographics_note_en", "")

    reasons_by_index = {r["index"]: r for r in ai.get("top_ads_reasons", [])}
    for i, a in enumerate(data["topAds"], start=1):
        r = reasons_by_index.get(i)
        a["reason_ru"] = r["reason_ru"] if r else ""
        a["reason_en"] = r["reason_en"] if r else ""

    data["findings_ru"] = ai["findings_ru"]
    data["findings_en"] = ai["findings_en"]
    data["recommendations_ru"] = ai["recommendations_ru"]
    data["recommendations_en"] = ai["recommendations_en"]

    data["euNote_ru"] = (
        "Важно знать: в рекламных кабинетах ЕС Meta не показывает число начатых переписок "
        "в директ. Кампании «IG direct» реально приводят людей в сообщения, но эта цифра "
        "в отчёте технически недоступна. Реальное число обращений видно только вручную "
        "(в директе или через учёт менеджеров)."
    )
    data["euNote_en"] = (
        "Worth knowing: in EU ad accounts Meta does not report the number of started Direct "
        "conversations. The IG direct campaigns do bring people into messages, but that number "
        "is technically unavailable in reporting. The real count of inquiries is only visible "
        "manually (in Direct or via a managers' log)."
    )
    return data
