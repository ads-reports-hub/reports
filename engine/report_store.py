"""
Хранилище готовых данных отчёта (числа + AI-тексты), отдельно от опубликованного
HTML. Нужно, чтобы apply_edits.py мог позже подгрузить уже посчитанный отчёт и
подправить в нём один текстовый кусок, не тратя новый вызов Meta API/Anthropic.

Лежит вне docs/, поэтому GitHub Pages это не публикует.
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "_data"
DOCS_DIR = REPO_ROOT / "docs"


def data_path(slug: str, period: str) -> Path:
    return DATA_DIR / slug / period / "data.json"


def save(slug: str, period: str, data: dict) -> None:
    path = data_path(slug, period)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load(slug: str, period: str) -> dict | None:
    path = data_path(slug, period)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
