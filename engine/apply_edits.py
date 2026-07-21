"""
Точка входа для ручных правок Лизы. Вызывается из
.github/workflows/check-edits.yml по расписанию (раз в час), либо вручную.

Читает вкладку "Правки" в той же гугл-таблице, для каждой ещё не обработанной
строки: находит slug клиента, загружает уже посчитанный data.json из
_data/<slug>/<период>/ (сохранённый orchestrator.py при первой генерации),
патчит insight_ru/en и/или liza_comment_ru/en, перерендеривает страницу в
docs/<slug>/<период>/ тем же шаблоном - без повторного похода в Meta API - и
пишет статус обратно в таблицу.

Одна плохая строка не должна ронять остальные, как и в orchestrator.py:
try/except на строку, статус "ошибка" с причиной пишется в саму таблицу.

Ручной тест: python engine/apply_edits.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import render
import report_store
import sheet_client
import translate


def apply_one(edit: dict, api_key: str) -> None:
    client = edit["client"]
    period_text = edit["period_text"]
    period = edit["period"]

    if not client:
        raise ValueError("не указан клиент")
    if not period:
        raise ValueError(f"не распознан месяц '{period_text}' (пример правильного формата: июнь 2026)")

    slug = sheet_client.resolve_slug(client)
    if not slug:
        raise ValueError(f"клиент '{client}' не найден в таблице")

    data = report_store.load(slug, period)
    if data is None:
        raise ValueError(f"отчёт за {period_text} для '{client}' ещё не был сгенерирован")

    if edit["intro_override"]:
        data["insight_ru"] = edit["intro_override"]
        data["insight_en"] = translate.translate_ru_to_en(edit["intro_override"], api_key)

    if edit["extra_comment"]:
        data["liza_comment_ru"] = edit["extra_comment"]
        data["liza_comment_en"] = translate.translate_ru_to_en(edit["extra_comment"], api_key)

    out_dir = report_store.DOCS_DIR / slug / period
    render.render_report(data, out_dir, assets_src_dir=None)
    report_store.save(slug, period, data)


def main():
    api_key = os.environ["ANTHROPIC_API_KEY"]
    edits = sheet_client.read_edits()
    print(f"[apply_edits] {len(edits)} pending edit(s)")

    failures = []
    for edit in edits:
        label = f"{edit['client']} / {edit['period_text']}"
        print(f"--- {label} ---")
        try:
            apply_one(edit, api_key)
            sheet_client.write_edit_status(edit["client"], edit["period_text"], "применено")
            print(f"[apply_edits] {label}: OK")
        except Exception as e:
            print(f"[apply_edits] {label}: FAILED - {e}", file=sys.stderr)
            sheet_client.write_edit_status(edit["client"], edit["period_text"], "ошибка", str(e))
            failures.append((label, str(e)))

    print("\n=== summary ===")
    print(f"succeeded: {len(edits) - len(failures)}/{len(edits)}")
    for label, err in failures:
        print(f"FAILED: {label}: {err}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
