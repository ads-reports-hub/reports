"""
Рендерит нормализованный отчёт (соответствующий report.schema.json) в
клиентскую HTML-страницу через templates/report.html.jinja.

Раньше эту страницу каждый месяц вручную переписывал ИИ-агент под конкретное
число кампаний. Теперь это чистая функция: одинаковый шаблон, разное число
элементов в массивах data.json. Ничего в этом файле не должно знать про
конкретного клиента или конкретный месяц.
"""
import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

ENGINE_DIR = Path(__file__).parent
TEMPLATE_DIR = ENGINE_DIR.parent / "templates"

# Метрики выше "ниже = лучше" (например CPC); всё остальное в KPI_METRICS
# считается "выше = лучше", если не указано иное.
LOWER_IS_BETTER = {"cpc"}
NEUTRAL_METRICS = {"spend", "frequency"}

# (i18n-ключ, поле в totals, знаков после запятой, суффикс, ключ доп. подписи)
KPI_METRICS = [
    ("kpi.spend",  "spend",          0, "Kč", None),
    ("kpi.reach",  "reach",          0, None, None),
    ("kpi.impr",   "impressions",    0, None, None),
    ("kpi.clicks", "clicks",         0, None, None),
    ("kpi.ctr",    "ctr",            2, "%",  None),
    ("kpi.cpc",    "cpc",            2, "Kč", None),
    ("kpi.freq",   "frequency",      2, None, "kpi.freq.sub"),
    ("kpi.eng",    "postEngagement", 0, None, "kpi.eng.sub"),
    ("kpi.video",  "videoViews",     0, None, "kpi.video.sub"),
]

GLOSSARY_KEYS = ["term1", "term2", "term3", "term4", "term5", "term6", "term7"]


def fmt_ru(value, dec):
    if value is None:
        return ""
    f = f"{abs(float(value)):.{dec}f}"
    intp, _, frac = f.partition(".")
    intp = "{:,}".format(int(intp)).replace(",", " ")
    out = intp + ("," + frac if dec > 0 else "")
    return ("-" + out) if value < 0 else out


def fmt_en(value, dec):
    if value is None:
        return ""
    f = f"{abs(float(value)):,.{dec}f}"
    return ("-" + f) if value < 0 else f


def build_kpi_defs(totals, prev_totals, show_dynamics):
    defs = []
    for key, field, dec, suffix, sub_key in KPI_METRICS:
        raw = totals.get(field)
        entry = {
            "key": key,
            "raw": raw if raw is not None else 0,
            "dec": dec,
            "suffix": suffix,
            "display_ru": fmt_ru(raw, dec),
            "sub_key": sub_key,
            "delta": None,
        }
        if show_dynamics and prev_totals and prev_totals.get(field):
            prev = prev_totals[field]
            if prev:
                pct = (raw - prev) / prev * 100
                arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
                if field in NEUTRAL_METRICS:
                    cls = "neutral"
                elif field in LOWER_IS_BETTER:
                    cls = "good" if pct < 0 else ("watch" if pct > 0 else "neutral")
                else:
                    cls = "good" if pct > 0 else ("watch" if pct < 0 else "neutral")
                prev_str = fmt_ru(prev, dec) + (f" {suffix}" if suffix and suffix != "%" else ("%" if suffix == "%" else ""))
                entry["delta"] = {
                    "cls": cls,
                    "arrow": arrow,
                    "text_ru": f"{abs(round(pct))}%",
                    "text_en": f"{abs(round(pct))}%",
                    "prev_ru": f"пред. {prev_str}",
                    "prev_en": f"prev. {prev_str}",
                }
        defs.append(entry)
    return defs


def campaign_tag_kind(campaign):
    goal = (campaign.get("goal_ru") or "").lower()
    if "подписч" in goal or "трафик" in goal or "profile" in (campaign.get("goal_en") or "").lower():
        return "traffic"
    return "direct"


def build_ad_key_map(campaigns):
    """Глобальная сквозная нумерация объявлений: campAd1, campAd2, ... как в
    прежних вручную собранных отчётах, чтобы ключи i18n были предсказуемы."""
    mapping = {}
    counter = 0
    for ci, camp in enumerate(campaigns, start=1):
        for ai, _ad in enumerate(camp.get("ads", []), start=1):
            counter += 1
            mapping[(ci, ai)] = f"campAd{counter}"
    return mapping


def render_report(data: dict, out_dir: Path, assets_src_dir: Path | None = None) -> Path:
    """
    data: словарь, соответствующий engine/report.schema.json, УЖЕ дополненный
          AI-полями (verdict_ru/en, findings_ru/en, insight_ru/en и т.д.) из
          commentary.py. render.py ничего не придумывает, только форматирует.
    out_dir: например docs/garden-bar/2026-07/
    assets_src_dir: откуда скопировать превью креативов (raw/assets из meta_client),
                    если задан — копируется в out_dir/assets/.
    """
    with open(TEMPLATE_DIR / "i18n_static.json", encoding="utf-8") as f:
        i18n_static = json.load(f)

    show_dynamics = bool(data.get("showDynamics"))
    totals = data["totals"]
    prev_totals = data.get("prevTotals") or {}
    campaigns = data.get("campaigns", [])

    kpi_defs = build_kpi_defs(totals, prev_totals, show_dynamics)
    ad_key_map = build_ad_key_map(campaigns)

    # ---- собираем полные RU/EN словари: статичные строки интерфейса + контент ----
    i18n_ru = dict(i18n_static["ru"])
    i18n_en = dict(i18n_static["en"])

    i18n_ru["header.dates"] = data["period"]["label_ru"]
    i18n_en["header.dates"] = data["period"]["label_en"]

    i18n_ru["insight.text"] = data["insight_ru"]
    i18n_en["insight.text"] = data.get("insight_en", data["insight_ru"])

    if data.get("liza_comment_ru"):
        i18n_ru["liza.comment"] = data["liza_comment_ru"]
        i18n_en["liza.comment"] = data.get("liza_comment_en", data["liza_comment_ru"])

    for kd in kpi_defs:
        if kd["delta"]:
            i18n_ru[f"{kd['key']}.delta"] = f"{kd['delta']['arrow']} {kd['delta']['text_ru']}"
            i18n_en[f"{kd['key']}.delta"] = f"{kd['delta']['arrow']} {kd['delta']['text_en']}"
            i18n_ru[f"{kd['key']}.prev"] = kd["delta"]["prev_ru"]
            i18n_en[f"{kd['key']}.prev"] = kd["delta"]["prev_en"]

    for ci, camp in enumerate(campaigns, start=1):
        tag_kind = campaign_tag_kind(camp)
        camp["tag_kind"] = tag_kind
        i18n_ru[f"camp{ci}.tag"] = camp.get("date") or ""
        i18n_en[f"camp{ci}.tag"] = camp.get("date") or ""
        i18n_ru[f"camp{ci}.aud"] = camp.get("audience", "")
        i18n_en[f"camp{ci}.aud"] = camp.get("audience", "")
        i18n_ru[f"camp{ci}.verdict"] = camp["verdict_ru"]
        i18n_en[f"camp{ci}.verdict"] = camp["verdict_en"]

        for ai, ad in enumerate(camp.get("ads", []), start=1):
            adKey = ad_key_map[(ci, ai)]
            ad["met_ru"] = f"{fmt_ru(ad['clicks'], 0)} кликов · CTR {fmt_ru(ad['ctr'], 2)}% · CPC <b>{fmt_ru(ad['cpc'], 2)} Kč</b>"
            ad["met_en"] = f"{fmt_en(ad['clicks'], 0)} clicks · CTR {fmt_en(ad['ctr'], 2)}% · CPC <b>{fmt_en(ad['cpc'], 2)} Kč</b>"
            i18n_ru[f"{adKey}.name"] = ad["label_ru"]
            i18n_en[f"{adKey}.name"] = ad["label_en"]
            i18n_ru[f"{adKey}.aud"] = ad["audience_ru"]
            i18n_en[f"{adKey}.aud"] = ad["audience_en"]
            i18n_ru[f"{adKey}.met"] = ad["met_ru"]
            i18n_en[f"{adKey}.met"] = ad["met_en"]

    # cpc pill: самый дешёвый клик среди кампаний -> good, самый дорогой -> watch
    if campaigns:
        cpcs = [c["cpc"] for c in campaigns if c.get("clicks")]
        if cpcs:
            min_cpc, max_cpc = min(cpcs), max(cpcs)
            for camp in campaigns:
                if not camp.get("clicks"):
                    camp["cpc_pill"] = None
                elif camp["cpc"] == min_cpc and min_cpc != max_cpc:
                    camp["cpc_pill"] = "good"
                elif camp["cpc"] == max_cpc and min_cpc != max_cpc:
                    camp["cpc_pill"] = "watch"
                else:
                    camp["cpc_pill"] = None

    audiences = data.get("audiences", [])
    for i, aud in enumerate(audiences, start=1):
        aud["discovery"] = bool(aud.get("badge_ru"))
        i18n_ru[f"aud{i}.name"] = aud["name_ru"]; i18n_en[f"aud{i}.name"] = aud["name_en"]
        i18n_ru[f"aud{i}.ctr"] = f"CTR {aud['ctr_range']}"; i18n_en[f"aud{i}.ctr"] = f"CTR {aud['ctr_range']}"
        i18n_ru[f"aud{i}.stats"] = f"{fmt_ru(aud['spend'], 0)} Kč · охват {fmt_ru(aud['reach'], 0)}"
        i18n_en[f"aud{i}.stats"] = f"{fmt_en(aud['spend'], 0)} Kč · reach {fmt_en(aud['reach'], 0)}"
        i18n_ru[f"aud{i}.note"] = aud["note_ru"]; i18n_en[f"aud{i}.note"] = aud["note_en"]
        if aud.get("badge_ru"):
            i18n_ru[f"aud{i}.badge"] = aud["badge_ru"]; i18n_en[f"aud{i}.badge"] = aud.get("badge_en", "")

    platforms = data.get("platforms", [])
    if platforms:
        max_spend = max(p["spend"] for p in platforms) or 1
        for i, p in enumerate(platforms, start=1):
            p["bar_pct"] = round(p["spend"] / max_spend * 100, 2)
            i18n_ru[f"plat{i}.label"] = p["label_ru"]; i18n_en[f"plat{i}.label"] = p["label_en"]
            stat_ru = f"{fmt_ru(p['spend'], 0)} Kč · {fmt_ru(p['clicks'], 0)} кликов · клик {fmt_ru(p['cpc'], 2)} Kč"
            stat_en = f"{fmt_en(p['spend'], 0)} Kč · {fmt_en(p['clicks'], 0)} clicks · {fmt_en(p['cpc'], 2)} Kč per click"
            i18n_ru[f"plat{i}.stat"] = stat_ru; i18n_en[f"plat{i}.stat"] = stat_en
        i18n_ru["plat.note"] = data.get("platforms_note_ru", "")
        i18n_en["plat.note"] = data.get("platforms_note_en", "")

    demo = data.get("demographics")
    if demo:
        rows_sorted = sorted(demo["rows"], key=lambda r: r["spend"], reverse=True)
        top_ctr = sorted(demo["rows"], key=lambda r: r["ctr"], reverse=True)[:3]
        hot_keys = {(r["gender"], r["age"]) for r in top_ctr}
        gender_ru = {"male": "М", "female": "Ж"}
        gender_en = {"male": "M", "female": "F"}
        for i, r in enumerate(rows_sorted, start=1):
            r["hot"] = (r["gender"], r["age"]) in hot_keys
            r["label_ru"] = f"{gender_ru[r['gender']]} {r['age']}"
            r["label_en"] = f"{gender_en[r['gender']]} {r['age']}"
            r["bar_pct"] = round(r["spend"] / rows_sorted[0]["spend"] * 100, 2) if rows_sorted[0]["spend"] else 0
            i18n_ru[f"demo.r{i}.label"] = r["label_ru"]; i18n_en[f"demo.r{i}.label"] = r["label_en"]
            stat_ru = f"{fmt_ru(r['spend'], 0)} Kč · CTR {fmt_ru(r['ctr'], 2)}%"
            stat_en = f"{fmt_en(r['spend'], 0)} Kč · CTR {fmt_en(r['ctr'], 2)}%"
            i18n_ru[f"demo.r{i}.stat"] = stat_ru; i18n_en[f"demo.r{i}.stat"] = stat_en
        demo["rows_sorted"] = rows_sorted
        i18n_ru["demo.note"] = demo["note_ru"]; i18n_en["demo.note"] = demo["note_en"]

    top_ads = data.get("topAds", [])
    for i, ad in enumerate(top_ads, start=1):
        i18n_ru[f"ad{i}.badge"] = ad["badge_ru"]; i18n_en[f"ad{i}.badge"] = ad["badge_en"]
        i18n_ru[f"ad{i}.name"] = ad["name_ru"]; i18n_en[f"ad{i}.name"] = ad["name_en"]
        i18n_ru[f"ad{i}.metric"] = ad["metric_ru"]; i18n_en[f"ad{i}.metric"] = ad["metric_en"]
        i18n_ru[f"ad{i}.reason"] = ad["reason_ru"]; i18n_en[f"ad{i}.reason"] = ad["reason_en"]

    for i, txt in enumerate(data.get("findings_ru", []), start=1):
        i18n_ru[f"find.{i}"] = txt
    for i, txt in enumerate(data.get("findings_en", []), start=1):
        i18n_en[f"find.{i}"] = txt
    for i, txt in enumerate(data.get("recommendations_ru", []), start=1):
        i18n_ru[f"rec.{i}"] = txt
    for i, txt in enumerate(data.get("recommendations_en", []), start=1):
        i18n_en[f"rec.{i}"] = txt

    if data.get("euNote_ru"):
        i18n_ru["eu.body"] = data["euNote_ru"]
        i18n_en["eu.body"] = data.get("euNote_en", "")

    footer_ru = f"Данные: Meta Marketing API · рекламный кабинет {data['client']} · период {data['period']['label_ru']}"
    footer_en = f"Data: Meta Marketing API · {data['client']} ad account · {data['period']['label_en']}"
    data["footer_ru"] = footer_ru
    i18n_ru["footer.text"] = footer_ru
    i18n_en["footer.text"] = footer_en

    data["client_initials"] = "".join(w[0] for w in data["client"].split()[:2]).upper()

    # ---- графики: только текущий период, по кампаниям ----
    chart_labels_ru = [[c["name"].split("·")[0].strip(), " ".join(c["name"].split("·")[1:]).strip()] for c in campaigns]
    pink, pink_deep, burgundy = "#faa1d4", "#f17fc0", "#a62e3e"
    max_clicks = max((c["clicks"] for c in campaigns), default=0)
    clicks_colors = [pink if c["clicks"] == max_clicks and max_clicks else pink_deep for c in campaigns]
    cpc_colors = []
    for c in campaigns:
        if c.get("cpc_pill") == "watch":
            cpc_colors.append(burgundy)
        elif c.get("cpc_pill") == "good":
            cpc_colors.append(pink)
        else:
            cpc_colors.append(pink_deep)

    context = {
        "data": data,
        "i18n_static": i18n_static,
        "kpi_defs": kpi_defs,
        "ad_key_map": ad_key_map,
        "glossary_keys": GLOSSARY_KEYS,
        "i18n_ru_json": json.dumps(i18n_ru, ensure_ascii=False),
        "i18n_en_json": json.dumps(i18n_en, ensure_ascii=False),
        "chart_labels_ru": json.dumps(chart_labels_ru, ensure_ascii=False),
        "chart_labels_en": json.dumps(chart_labels_ru, ensure_ascii=False),  # переводы кампаний не критичны на графике
        "chart_clicks_data": json.dumps([c["clicks"] for c in campaigns]),
        "chart_clicks_colors": json.dumps(clicks_colors),
        "chart_cpc_data": json.dumps([c["cpc"] for c in campaigns]),
        "chart_cpc_colors": json.dumps(cpc_colors),
    }

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    env.filters["fmt_ru"] = fmt_ru
    template = env.get_template("report.html.jinja")
    html = template.render(**context)

    # проверка на запрещённое тире, на случай если оно просочилось из AI-текстов
    if "—" in html:
        raise ValueError("Em dash (—) found in rendered HTML — check commentary output before publishing.")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    if assets_src_dir and assets_src_dir.exists():
        assets_out = out_dir / "assets"
        assets_out.mkdir(exist_ok=True)
        for f in assets_src_dir.glob("*.jpg"):
            shutil.copy(f, assets_out / f.name)

    return out_dir / "index.html"
