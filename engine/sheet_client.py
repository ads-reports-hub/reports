"""
Чтение списка клиентов и запись ссылки на готовый отчёт обратно в гугл-таблицу
"Список клиентов на старт".

Чтение: публичный gviz CSV-эндпоинт таблицы, без авторизации (таблица открыта
на чтение по ссылке, это уже проверялось в этом проекте раньше).

Запись: POST в Apps Script Web App, привязанный к самой таблице (см.
apps-script/Code.gs). Секрет и URL приходят из переменных окружения, никогда
не хардкодятся.
"""
import csv
import io
import json
import os
import urllib.request
import urllib.parse

SHEET_ID = os.environ.get("CLIENTS_SHEET_ID", "1J6UEwPBQetR3hLvfAMgo2QBuT1sdYNypQFMnx7LMVzc")
SHEET_TAB_NAME = os.environ.get("CLIENTS_SHEET_TAB", "Список клиентов на старт")

REQUIRED_COLUMNS = ["client", "slug", "meta_token", "account_id"]

# Некоторые заголовки в самой таблице исторически на русском (Лиза их уже
# видит и понимает), сюда добавляются только реальные варианты написания,
# встреченные в этой таблице, а не общий словарь на все случаи жизни.
HEADER_ALIASES = {
    "клиент": "client",
    "клиент:": "client",
    "токен": "meta_token",
}


def _truthy(cell: str) -> bool:
    return (cell or "").strip().lower() in ("да", "yes", "true", "1", "y")


def read_clients() -> list[dict]:
    """
    Возвращает список активных клиентов из таблицы. Ожидаемые колонки (имена
    заголовков в самой таблице могут быть по-русски, здесь ключи после
    парсинга нормализуются): client, slug, meta_token, account_id,
    show_dynamics (да/нет), active (да/нет), last_report_link, last_updated.

    Строки без active=да пропускаются. Строки без meta_token или account_id
    пропускаются с предупреждением в stdout (а не падением), чтобы одна
    незаполненная строка не ломала весь месячный прогон.
    """
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq"
        f"?tqx=out:csv&sheet={urllib.parse.quote(SHEET_TAB_NAME)}"
    )
    with urllib.request.urlopen(url) as r:
        raw = r.read().decode("utf-8")

    rows = list(csv.DictReader(io.StringIO(raw)))
    clients = []
    for row in rows:
        norm = {}
        for k, v in row.items():
            key = k.strip().lower().replace(" ", "_")
            key = HEADER_ALIASES.get(key, key)
            norm[key] = (v or "").strip()
        if not _truthy(norm.get("active", "да")):
            continue
        if not norm.get("meta_token") or not norm.get("account_id"):
            print(f"[sheet_client] skipping row for '{norm.get('client', '?')}': missing token or account_id")
            continue
        clients.append({
            "client": norm.get("client", ""),
            "slug": norm.get("slug") or _slugify(norm.get("client", "")),
            "meta_token": norm["meta_token"],
            "account_id": norm["account_id"],
            "show_dynamics": _truthy(norm.get("show_dynamics", "нет")),
        })
    return clients


def _slugify(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")


def write_result(client: str, period_label: str, link: str) -> None:
    """POST в Apps Script Web App, чтобы дописать ссылку в таблицу напротив
    строки клиента. Тихо логирует и НЕ бросает исключение при сетевой ошибке,
    чтобы отсутствие связи с Google не обрушивало остальной прогон (ссылка
    в таком случае просто не попадёт в таблицу в этот раз, отчёт всё равно
    опубликован — см. orchestrator.py, который это тоже логирует в сводке)."""
    webapp_url = os.environ.get("SHEET_WEBAPP_URL")
    secret = os.environ.get("SHEET_SHARED_SECRET")
    if not webapp_url or not secret:
        print("[sheet_client] SHEET_WEBAPP_URL / SHEET_SHARED_SECRET not set, skipping write-back")
        return

    payload = json.dumps({
        "secret": secret,
        "client": client,
        "period": period_label,
        "link": link,
    }).encode("utf-8")
    req = urllib.request.Request(webapp_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode("utf-8"))
            if not resp.get("ok"):
                print(f"[sheet_client] write-back rejected for '{client}': {resp}")
    except Exception as e:
        print(f"[sheet_client] write-back failed for '{client}': {e}")
