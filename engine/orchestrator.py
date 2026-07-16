"""
Точка входа месячного прогона. Вызывается из .github/workflows/monthly-report.yml
(по расписанию 1-го числа, либо вручную через workflow_dispatch).

Для каждого активного клиента из гугл-таблицы:
  читает токен/ID кабинета из строки -> тянет метрики Meta за прошлый
  календарный месяц -> считает числовую часть отчёта -> зовёт ИИ на тексты ->
  рендерит страницу в docs/<slug>/<период>/ -> дописывает ссылку в таблицу.

Один клиент падает — остальные всё равно обрабатываются (try/except на
клиента). В конце печатается сводка и скрипт завершается ненулевым кодом,
если хоть один клиент не обработался, чтобы GitHub Actions показал прогон
красным и это было заметно.

Ручной тест конкретного клиента/периода:
  python engine/orchestrator.py --client garden-bar --since 2026-06-01 --until 2026-06-30
"""
import argparse
import calendar
import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import commentary
import meta_client
import normalize
import render
import sheet_client

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "docs"
PAGES_BASE_URL = os.environ.get("PAGES_BASE_URL", "https://ads-reports-hub.github.io/reports")

MONTHS_RU = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]
MONTHS_EN = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def previous_calendar_month(today: datetime.date | None = None):
    today = today or datetime.date.today()
    first_of_this_month = today.replace(day=1)
    last_day_prev = first_of_this_month - datetime.timedelta(days=1)
    since = last_day_prev.replace(day=1)
    until = last_day_prev
    prev_last_day = since - datetime.timedelta(days=1)
    prev_since = prev_last_day.replace(day=1)
    prev_until = prev_last_day
    return since, until, prev_since, prev_until


def period_label(since: datetime.date, until: datetime.date) -> tuple[str, str]:
    if since.month == until.month:
        label_ru = f"1 – {until.day} {MONTHS_RU[since.month]}"
        label_en = f"{MONTHS_EN[since.month]} 1 – {until.day}"
    else:
        label_ru = f"{since.day} {MONTHS_RU[since.month]} – {until.day} {MONTHS_RU[until.month]}"
        label_en = f"{MONTHS_EN[since.month]} {since.day} – {MONTHS_EN[until.month]} {until.day}"
    return label_ru, label_en


def period_slug(since: datetime.date) -> str:
    return since.strftime("%Y-%m")


def run_one_client(client_row: dict, since: datetime.date, until: datetime.date,
                    prev_since: datetime.date, prev_until: datetime.date,
                    api_key: str) -> str:
    """Возвращает публичную ссылку на опубликованный отчёт."""
    slug = client_row["slug"]
    period = period_slug(since)
    out_dir = DOCS_DIR / slug / period

    raw = meta_client.fetch(
        token=client_row["meta_token"],
        account=client_row["account_id"],
        since=since.isoformat(), until=until.isoformat(),
        prev_since=prev_since.isoformat(), prev_until=prev_until.isoformat(),
        assets_out_dir=out_dir / "assets",
    )

    normalized = normalize.normalize(
        client=client_row["client"], account_id=client_row["account_id"],
        since=since.isoformat(), until=until.isoformat(),
        prev_since=prev_since.isoformat(), prev_until=prev_until.isoformat(),
        show_dynamics=client_row["show_dynamics"], raw=raw,
    )
    label_ru, label_en = period_label(since, until)
    normalized["period"]["label_ru"] = label_ru
    normalized["period"]["label_en"] = label_en
    if normalized.get("prevPeriod"):
        prev_label_ru, prev_label_en = period_label(prev_since, prev_until)
        normalized["prevPeriod"]["label_ru"] = prev_label_ru
        normalized["prevPeriod"]["label_en"] = prev_label_en

    ai = commentary.generate(normalized, api_key)
    data = commentary.merge(normalized, ai)
    data["meta"] = {"generatedAt": datetime.datetime.utcnow().isoformat() + "Z", "generatedBy": "automation"}

    # ассеты уже лежат в out_dir/assets (meta_client писал их прямо туда)
    render.render_report(data, out_dir, assets_src_dir=None)

    return f"{PAGES_BASE_URL}/{slug}/{period}/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", help="ограничить прогон одним слагом клиента (для ручного теста)")
    ap.add_argument("--since", help="переопределить начало периода (YYYY-MM-DD), для ручного теста")
    ap.add_argument("--until", help="переопределить конец периода (YYYY-MM-DD), для ручного теста")
    args = ap.parse_args()

    api_key = os.environ["ANTHROPIC_API_KEY"]

    if args.since and args.until:
        since = datetime.date.fromisoformat(args.since)
        until = datetime.date.fromisoformat(args.until)
        prev_until = since - datetime.timedelta(days=1)
        prev_since = prev_until.replace(day=1)
    else:
        since, until, prev_since, prev_until = previous_calendar_month()

    clients = sheet_client.read_clients()
    if args.client:
        clients = [c for c in clients if c["slug"] == args.client]
        if not clients:
            sys.exit(f"No active client with slug '{args.client}' found in the sheet")

    print(f"[orchestrator] period {since} .. {until}, {len(clients)} active client(s)")

    failures = []
    for row in clients:
        label = row["client"]
        print(f"--- {label} ---")
        try:
            link = run_one_client(row, since, until, prev_since, prev_until, api_key)
            print(f"[orchestrator] {label}: published {link}")
            period_label_ru, _ = period_label(since, until)
            sheet_client.write_result(label, period_label_ru, link)
        except Exception as e:
            print(f"[orchestrator] {label}: FAILED - {e}", file=sys.stderr)
            failures.append((label, str(e)))

    print("\n=== summary ===")
    print(f"succeeded: {len(clients) - len(failures)}/{len(clients)}")
    for label, err in failures:
        print(f"FAILED: {label}: {err}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
