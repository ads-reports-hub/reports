"""
Тянет сырые данные из Meta Marketing API для одного клиента.

Переписано из прежнего engine/fetch_meta.py (CLI-скрипт) в импортируемую
функцию: токен и даты передаются параметрами (приходят из строки таблицы
клиентов, а не из локального файла), результат возвращается как словарь в
памяти, а не пишется на диск построчно. orchestrator.py вызывает fetch()
напрямую для каждого клиента из sheet_client.read_clients().

Превью креативов по-прежнему нужно сохранять локально (подписанные URL Meta
протухают через несколько дней) — но теперь сразу уменьшаются до ~140px
(Pillow, кроссплатформенно, работает и на GitHub Actions runner), потому что
на странице они показываются максимум в 200px, тянуть оригинал 512px незачем
и раздувает репозиторий с каждым новым месяцем на каждого клиента.
"""
import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

API = "https://graph.facebook.com/v20.0"
INSIGHT_FIELDS = "reach,impressions,frequency,spend,clicks,ctr,cpc,cpm,actions"
THUMB_MAX_WIDTH = 140
THUMB_JPEG_QUALITY = 55


class MetaFetchError(Exception):
    pass


def _get(path, token, **params):
    params["access_token"] = token
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(body)["error"]["message"]
        except Exception:
            message = body
        raise MetaFetchError(f"Meta API error on {path}: {message}") from e
    if "error" in data:
        raise MetaFetchError(f"Meta API error on {path}: {data['error'].get('message')}")
    return data


def _time_range(since, until):
    return json.dumps({"since": since, "until": until})


def fetch(token: str, account: str, since: str, until: str,
          prev_since: str | None, prev_until: str | None,
          assets_out_dir: Path) -> dict:
    """Возвращает {account, campaigns, adsets, ads, demographics, platforms,
    prev_account, creatives} — те же данные, что раньше писались в raw/*.json,
    только в памяти. Превью креативов уменьшаются и сохраняются в
    assets_out_dir (только для объявлений, которые реально были активны в
    периоде — то есть встречаются в ads['data'])."""
    tr = _time_range(since, until)

    result = {
        "account": _get(f"{account}/insights", token, level="account",
                         fields=INSIGHT_FIELDS, time_range=tr),
        "campaigns": _get(f"{account}/insights", token, level="campaign",
                           fields="campaign_name," + INSIGHT_FIELDS, time_range=tr, limit=100),
        "adsets": _get(f"{account}/insights", token, level="adset",
                        fields="campaign_name,adset_name," + INSIGHT_FIELDS, time_range=tr, limit=200),
        "ads": _get(f"{account}/insights", token, level="ad",
                     fields="campaign_name,adset_name,ad_name,ad_id," + INSIGHT_FIELDS,
                     time_range=tr, limit=200),
        "demographics": _get(f"{account}/insights", token, level="account",
                              fields="reach,impressions,spend,clicks,ctr",
                              breakdowns="age,gender", time_range=tr, limit=200),
        "platforms": _get(f"{account}/insights", token, level="account",
                           fields="reach,impressions,spend,clicks,ctr",
                           breakdowns="publisher_platform,platform_position",
                           time_range=tr, limit=100),
    }

    if prev_since and prev_until:
        result["prev_account"] = _get(f"{account}/insights", token, level="account",
                                       fields=INSIGHT_FIELDS,
                                       time_range=_time_range(prev_since, prev_until))

    creatives = _get(f"{account}/ads", token,
                      fields="id,name,creative.thumbnail_width(512).thumbnail_height(512){thumbnail_url}",
                      limit=200)
    result["creatives"] = creatives

    ad_ids = {r["ad_id"] for r in result["ads"]["data"]}
    assets_out_dir.mkdir(parents=True, exist_ok=True)
    for c in creatives.get("data", []):
        if c["id"] not in ad_ids:
            continue
        thumb_url = c.get("creative", {}).get("thumbnail_url")
        if not thumb_url:
            continue
        try:
            with urllib.request.urlopen(thumb_url, timeout=20) as r:
                raw_bytes = r.read()
            img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            if img.width > THUMB_MAX_WIDTH:
                new_h = round(img.height * THUMB_MAX_WIDTH / img.width)
                img = img.resize((THUMB_MAX_WIDTH, new_h), Image.LANCZOS)
            img.save(assets_out_dir / f"{c['id']}.jpg", "JPEG", quality=THUMB_JPEG_QUALITY)
        except Exception as e:
            print(f"[meta_client] could not fetch/resize thumbnail for ad {c['id']}: {e}", file=sys.stderr)

    return result
