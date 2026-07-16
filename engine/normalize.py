"""
Превращает сырые данные из meta_client.fetch() в ЧИСЛОВУЮ часть отчёта
(всё, что соответствует report.schema.json, КРОМЕ полей, помеченных как
AI-ПОЛЕ). Раньше эти вычисления и группировки я делал вручную построчно по
JSON — здесь та же логика, зафиксированная кодом, чтобы результат был
одинаково надёжным для любого клиента и любого месяца.

commentary.py дополняет результат этой функции текстовыми AI-полями
(verdict_ru/en, insight_ru/en, findings_ru/en, recommendations_ru/en,
audiences[].note_ru/en, demographics.note_ru/en, platforms_note_ru/en,
topAds[].reason_ru/en) — сам normalize.py текст не придумывает.

ИЗВЕСТНОЕ ОГРАНИЧЕНИЕ: campaigns[].goal_ru/en и campaigns[].audience
определяются эвристикой по названиям кампаний/групп объявлений (ключевые
слова вроде "direct"/"reels"/"followers"). Для клиентов с другими
соглашениями об именовании кампаний эвристику может понадобиться расширить
в GOAL_KEYWORDS ниже — это осознанный компромисс, не попытка притвориться,
что определение цели кампании по имени работает идеально для всех.
"""
from collections import defaultdict

GOAL_KEYWORDS = [
    (["direct", "директ", "message", "переписк"], "переписки в директ", "Direct messages"),
    (["follower", "подписч", "profile", "профил"], "рост подписчиков / вовлечённость", "Follower growth / engagement"),
    (["traffic", "трафик"], "трафик на сайт/профиль", "Traffic"),
    (["reels"], "вовлечённость (Reels)", "Engagement (Reels)"),
]


def _guess_goal(campaign_name: str) -> tuple[str, str]:
    low = campaign_name.lower()
    for keywords, ru, en in GOAL_KEYWORDS:
        if any(k in low for k in keywords):
            return ru, en
    return "переписки в директ", "Direct messages"


def _actions_map(actions_list):
    m = {}
    for a in actions_list or []:
        m[a["action_type"]] = float(a["value"])
    return m


def _row_totals(row: dict) -> dict:
    actions = _actions_map(row.get("actions"))
    return {
        "spend": round(float(row.get("spend", 0)), 2),
        "reach": int(float(row.get("reach", 0))),
        "impressions": int(float(row.get("impressions", 0))),
        "frequency": round(float(row.get("frequency", 0)), 2) if row.get("frequency") else None,
        "clicks": int(float(row.get("clicks", 0))),
        "ctr": round(float(row.get("ctr", 0)), 2),
        "cpc": round(float(row.get("cpc", 0)), 2) if row.get("clicks") else 0,
        "linkClicks": int(actions.get("link_click", 0)),
        "postEngagement": int(actions.get("post_engagement", 0)),
        "videoViews": int(actions.get("video_view", 0)),
        "reactions": int(actions.get("post_reaction", 0)),
        "comments": int(actions.get("comment", 0)),
        "saves": int(actions.get("onsite_conversion.post_save", 0)),
    }


def build_totals(account_raw: dict) -> dict:
    row = account_raw["data"][0]
    return _row_totals(row)


def build_prev_totals(prev_account_raw: dict | None) -> dict | None:
    if not prev_account_raw or not prev_account_raw.get("data"):
        return None
    row = prev_account_raw["data"][0]
    t = _row_totals(row)
    return {k: t[k] for k in ("spend", "reach", "impressions", "frequency", "clicks", "ctr", "cpc")}


def build_campaigns(campaigns_raw: dict, adsets_raw: dict, ads_raw: dict) -> list[dict]:
    adset_by_campaign = defaultdict(list)
    for row in adsets_raw.get("data", []):
        adset_by_campaign[row["campaign_name"]].append(row["adset_name"])

    ads_by_campaign = defaultdict(list)
    for row in ads_raw.get("data", []):
        ads_by_campaign[row["campaign_name"]].append(row)

    campaigns = []
    for row in campaigns_raw.get("data", []):
        name = row["campaign_name"]
        totals = _row_totals(row)
        goal_ru, goal_en = _guess_goal(name)
        adset_names = adset_by_campaign.get(name, [])
        audience = adset_names[0] if adset_names else ""

        ads = []
        for i, ad_row in enumerate(ads_by_campaign.get(name, []), start=1):
            ad_totals = _row_totals(ad_row)
            ad_name = ad_row.get("ad_name") or str(i)
            ads.append({
                "adId": ad_row["ad_id"],
                "thumb": f"assets/{ad_row['ad_id']}.jpg",
                "label_ru": f"Объявление {ad_name}",
                "label_en": f"Ad {ad_name}",
                "audience_ru": ad_row.get("adset_name", audience),
                "audience_en": ad_row.get("adset_name", audience),
                "spend": ad_totals["spend"],
                "clicks": ad_totals["clicks"],
                "ctr": ad_totals["ctr"],
                "cpc": ad_totals["cpc"],
            })

        campaigns.append({
            "name": name,
            "date": "",
            "goal_ru": goal_ru,
            "goal_en": goal_en,
            "reach": totals["reach"],
            "impressions": totals["impressions"],
            "frequency": totals["frequency"],
            "spend": totals["spend"],
            "clicks": totals["clicks"],
            "ctr": totals["ctr"],
            "cpc": totals["cpc"],
            "linkClicks": totals["linkClicks"],
            "postEngagement": totals["postEngagement"],
            "videoViews": totals["videoViews"],
            "audience": audience,
            "ads": ads,
        })
    return campaigns


def build_audiences(adsets_raw: dict) -> list[dict]:
    grouped = defaultdict(lambda: {"spend": 0.0, "reach": 0, "ctrs": []})
    for row in adsets_raw.get("data", []):
        g = grouped[row["adset_name"]]
        g["spend"] += float(row.get("spend", 0))
        g["reach"] += int(float(row.get("reach", 0)))
        g["ctrs"].append(round(float(row.get("ctr", 0)), 2))

    result = []
    for name, g in sorted(grouped.items(), key=lambda kv: kv[1]["spend"], reverse=True):
        ctrs = sorted(g["ctrs"])
        ctr_range = f"{ctrs[0]}%" if len(ctrs) == 1 else f"{ctrs[0]}–{ctrs[-1]}%".replace(".", ",")
        result.append({
            "name_ru": name, "name_en": name,
            "spend": round(g["spend"], 2), "reach": g["reach"],
            "ctr_range": ctr_range, "_max_ctr": ctrs[-1],
        })

    # Аудитория с лучшим CTR получает бейдж "Лучшая аудитория" — только если
    # их больше одной (иначе бейдж бессмысленен, это единственный вариант).
    if len(result) > 1:
        best = max(result, key=lambda a: a["_max_ctr"])
        best["badge_ru"] = "Лучшая аудитория"
        best["badge_en"] = "Best audience"
    for a in result:
        a.pop("_max_ctr", None)
        a.setdefault("badge_ru", None)
        a.setdefault("badge_en", None)
    return result


PLATFORM_LABELS = {
    ("facebook", "feed"): ("Facebook · лента", "Facebook · feed"),
    ("instagram", "feed"): ("Instagram · лента", "Instagram · feed"),
    ("instagram", "instagram_stories"): ("Instagram · сторис", "Instagram · stories"),
    ("facebook", "facebook_stories"): ("Facebook · сторис", "Facebook · stories"),
    ("instagram", "instagram_reels"): ("Instagram · Reels", "Instagram · Reels"),
    ("facebook", "facebook_reels"): ("Facebook · Reels", "Facebook · Reels"),
}


def build_platforms(platforms_raw: dict) -> list[dict]:
    rows = []
    for row in platforms_raw.get("data", []):
        key = (row.get("publisher_platform", ""), row.get("platform_position", ""))
        if key not in PLATFORM_LABELS:
            continue  # площадки с исчезающе малым охватом (explore grid и т.п.) не выносим отдельной строкой
        label_ru, label_en = PLATFORM_LABELS[key]
        spend = float(row.get("spend", 0))
        clicks = int(float(row.get("clicks", 0)))
        rows.append({
            "key": f"{key[0]}_{key[1]}".replace("instagram_instagram_", "instagram_").replace("facebook_facebook_", "facebook_"),
            "label_ru": label_ru, "label_en": label_en,
            "reach": int(float(row.get("reach", 0))),
            "spend": round(spend, 2),
            "clicks": clicks,
            "cpc": round(spend / clicks, 2) if clicks else 0,
        })
    rows.sort(key=lambda r: r["spend"], reverse=True)
    return rows


def build_demographics(demographics_raw: dict) -> dict:
    rows = []
    for row in demographics_raw.get("data", []):
        if row.get("gender") not in ("male", "female"):
            continue
        rows.append({
            "gender": row["gender"], "age": row["age"],
            "reach": int(float(row.get("reach", 0))),
            "spend": round(float(row.get("spend", 0)), 2),
            "ctr": round(float(row.get("ctr", 0)), 2),
        })
    return {"rows": rows}  # note_ru/en добавляет commentary.py


def build_top_ads(campaigns: list[dict]) -> list[dict]:
    """3 фиксированных слота, вычисленных детерминированно: лучший CTR,
    самый дешёвый клик среди объявлений с заметным объёмом, наибольшая
    вовлечённость. Тексты reason_ru/en дополняет commentary.py."""
    all_ads = []
    for camp in campaigns:
        for ad in camp["ads"]:
            all_ads.append({**ad, "_campaign_name": camp["name"], "_postEngagement": camp["postEngagement"] if len(camp["ads"]) == 1 else None})

    if not all_ads:
        return []

    meaningful = [a for a in all_ads if a["clicks"] >= 10] or all_ads
    best_ctr = max(meaningful, key=lambda a: a["ctr"])
    cheapest = min([a for a in meaningful if a["clicks"] > 0], key=lambda a: a["cpc"], default=best_ctr)
    engagement = max(
        [a for a in all_ads if a.get("_postEngagement") is not None],
        key=lambda a: a["_postEngagement"], default=best_ctr,
    )

    picks = []
    seen_ids = set()
    for ad, badge_ru, badge_en, is_best in [
        (best_ctr, "Лучший отклик", "Best response", True),
        (cheapest, "Самый дешёвый клик", "Cheapest click", False),
        (engagement, "Магнит вовлечённости", "Engagement magnet", False),
    ]:
        if ad["adId"] in seen_ids:
            continue
        seen_ids.add(ad["adId"])
        metric_en = f"CTR {ad['ctr']}% · CPC {ad['cpc']} Kč"
        picks.append({
            "adId": ad["adId"], "thumb": ad["thumb"],
            "name_ru": ad["_campaign_name"], "name_en": ad["_campaign_name"],
            "badge_ru": badge_ru, "badge_en": badge_en,
            "metric_ru": metric_en.replace("·", "·"), "metric_en": metric_en,
            "best": is_best,
        })
    return picks


def normalize(client: str, account_id: str, since: str, until: str,
              prev_since: str | None, prev_until: str | None,
              show_dynamics: bool, raw: dict) -> dict:
    """Собирает всё, кроме AI-текстовых полей, в структуру report.schema.json."""
    campaigns = build_campaigns(raw["campaigns"], raw["adsets"], raw["ads"])
    return {
        "client": client,
        "accountId": account_id,
        "period": {"since": since, "until": until, "label_ru": "", "label_en": ""},  # заполняет orchestrator (знает формат дат целиком)
        "prevPeriod": {"since": prev_since, "until": prev_until, "label_ru": "", "label_en": ""} if prev_since else None,
        "platform": "Meta Ads (Instagram / Facebook)",
        "currency": "Kč",
        "source": "Meta Marketing API",
        "showDynamics": show_dynamics,
        "totals": build_totals(raw["account"]),
        "prevTotals": build_prev_totals(raw.get("prev_account")),
        "campaigns": campaigns,
        "audiences": build_audiences(raw["adsets"]),
        "platforms": build_platforms(raw["platforms"]),
        "demographics": build_demographics(raw["demographics"]),
        "topAds": build_top_ads(campaigns),
    }
