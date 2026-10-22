"""Парсер макротаблиц аналитики банка -> строки «показатель × период × значение» и сравнение прогнозов между документами.

Формат строк сайдкара: заголовок «... (годы 2019 | 2020 | ... | 2027П)» или «(столбцы: 2025 | 1П26 | Янв.26 | ... | Июл.26П)»,
затем строки «Показатель, единица: v1 | v2 | ...». «П» в конце периода = прогноз Альфа-Банка.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .models import Indicator
from .textutil import fold

_MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}
_PERIOD_TOKEN = re.compile(r"^(\d{4}П?|[1-4][КП]\d{2}|[А-Яа-я]{3,4}\.\d{2}П?)$")
_HEADER = re.compile(r"\((?:годы|столбцы:?)\s+([^)]+)\)")
_ROW = re.compile(r"^(?P<label>[^:|]{3,90}?):\s+(?P<vals>[-+−\d.,%*N/A\s|]+)$")

CANON = [
    (r"^инфляция.*дек", "inflation_dec_yoy"), (r"^инфляция.*среднегод", "inflation_avg_yoy"),
    (r"^ставка,\s*конец", "key_rate_eoy"), (r"^ставка,\s*среднегод", "key_rate_avg"),
    (r"^курс,.*руб\./\$", "usd_rub_eoy"), (r"^курс,.*юан", "cny_rub_eoy"),
    (r"темпы роста ввп", "gdp_growth"), (r"номинальный ввп", "gdp_nominal"),
    (r"валовое накопление", "investment_growth"),
    (r"об-?рот розн|оборот розн", "retail_turnover"),
    (r"пром\.?\s*произв|промышленное производство", "industrial_production"),
    (r"номин\.?\s*зарплат|номинальные зарплаты", "wages_nominal"),
    (r"реал\.?\s*зарплат|зарплат.*реал", "wages_real"),
    (r"безработиц", "unemployment"),
    (r"доходы бюджета", "budget_revenue"), (r"расходы бюджета", "budget_expenditure"), (r"баланс бюджета", "budget_balance"),
    (r"^экспорт", "export_usd"), (r"^импорт", "import_usd"), (r"счет текущих", "current_account"), (r"urals", "oil_urals"),
    (r"розничный кредитный портфель|розн\.?\s*кредит", "retail_credit_growth"),
    (r"ипотечный кредитный", "mortgage_growth"), (r"рынок розничных депозитов", "retail_deposits_growth"),
    (r"корпоративный кредитный", "corp_credit_growth"), (r"рынок корпоративных депозитов", "corp_deposits_growth"),
]


def normalize_period(tok: str) -> tuple[str, bool] | None:
    """'2026П' -> ('2026', True); 'Июл.26П' -> ('2026-07', True); '1П26' -> ('2026-H1', False); '1К26' -> ('2026-Q1', False)."""
    t = tok.strip()
    fc = t.endswith("П") and not re.fullmatch(r"[1-4]П\d{2}", t)
    base = t[:-1] if fc else t
    if re.fullmatch(r"\d{4}", base):
        return base, fc
    m = re.fullmatch(r"([1-4])([КП])(\d{2})", base)
    if m:
        n, kind, yy = m.groups()
        return (f"20{yy}-Q{n}" if kind == "К" else f"20{yy}-H{n}"), False
    m = re.fullmatch(r"([А-Яа-я]{3,4})\.(\d{2})", base)
    if m and m.group(1)[:3].lower() in _MONTHS:
        return f"20{m.group(2)}-{_MONTHS[m.group(1)[:3].lower()]:02d}", fc
    return None


def canonical_indicator(label: str) -> str:
    l = fold(label)
    for pat, key in CANON:
        if re.search(pat, l):
            return key
    slug = re.sub(r"[^a-zа-я0-9]+", "_", l).strip("_")[:60]
    return f"other:{slug}"


def _unit(label: str) -> str | None:
    parts = [p.strip() for p in label.split(",")[1:]]
    return ", ".join(parts) if parts else None


def _value(tok: str) -> float | None:
    t = tok.strip().replace("*", "").replace("−", "-").replace("%", "").replace(" ", "")
    if t in ("", "N/A", "-", "—"):
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def parse_tables(page_text: str, item_id: str, page: int | None, published_at: str | None) -> list[Indicator]:
    out: list[Indicator] = []
    periods: list[tuple[str, bool]] | None = None
    table_title: str | None = None
    for raw in page_text.splitlines():
        line = raw.strip()
        if not line:
            periods = None
            continue
        h = _HEADER.search(line)
        if h:
            toks = [t.strip() for t in h.group(1).split("|")]
            if toks and all(_PERIOD_TOKEN.match(t) for t in toks):
                periods = [normalize_period(t) for t in toks]  # type: ignore[misc]
                if all(periods):
                    table_title = line.split("(")[0].strip(" :")
                    continue
            periods = None
            continue
        if periods is None:
            continue
        m = _ROW.match(line)
        if not m:
            periods = None if not line.startswith("(") else periods
            continue
        vals = [v for v in m.group("vals").split("|")]
        if len(vals) != len(periods):
            continue
        label = m.group("label").strip()
        key = canonical_indicator(label)
        for (per, fc), v in zip(periods, vals):
            # «*» у значения = оценка/прогноз (в 1П26 расшифровано «* Прогноз»), считаем is_forecast
            out.append(Indicator(item_id=item_id, indicator=key, label=label, period=per, value=_value(v), unit=_unit(label),
                                 is_forecast=fc or ("*" in v), page=page, published_at=published_at, table=table_title))
    out.extend(parse_rate_paths(page_text, item_id, page, published_at))
    return out


_PATH_PT = re.compile(r"([А-Яа-я]{3}\.\d{2})\s+(\d{1,2}(?:[,.]\d{1,2})?)\s*%")


def parse_rate_paths(page_text: str, item_id: str, page: int | None, published_at: str | None) -> list[Indicator]:
    """Траектория ключевой ставки из подписей графика: «Рис.: ... ключевой ставки ...: янв.26 16,0%; ...; прогноз: окт.26 14,0%»."""
    out: list[Indicator] = []
    for line in page_text.splitlines():
        fl = fold(line)
        if "ставк" not in fl or not fl.lstrip().startswith(("рис", "график")):
            continue
        pts = list(_PATH_PT.finditer(line))
        if len(pts) < 4:
            continue
        mark = fl.find("прогноз:")
        for m in pts:
            per = normalize_period(m.group(1))
            if not per:
                continue
            is_fc = mark != -1 and fl.find(fold(m.group(0))) >= mark
            out.append(Indicator(item_id=item_id, indicator="key_rate_path", label="Ключевая ставка (траектория на графике)",
                                 period=per[0], value=float(m.group(2).replace(",", ".")), unit="%", is_forecast=is_fc,
                                 page=page, published_at=published_at, table="rate_path_chart"))
    return out


def compare_forecasts(rows: list[dict[str, Any]], only_forecast: bool = True) -> list[dict[str, Any]]:
    """Расхождения одного показателя/периода между документами. rows: dict(indicator, period, value, is_forecast, published_at, item_id).

    Возвращает [{indicator, period, values:[{value, published_at, item_id}], latest:{...}, spread}] только где значений > 1.
    Правило разрешения: действует значение из документа с самой поздней published_at (банк пересматривает прогноз).
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["value"] is None or (only_forecast and not r["is_forecast"]):
            continue
        groups[(r["indicator"], r["period"])].append(r)
    out = []
    for (ind, per), rs in sorted(groups.items()):
        distinct = {r["value"] for r in rs}
        if len(distinct) > 1:
            rs = sorted(rs, key=lambda r: (r["published_at"] or "", r["item_id"]))
            vals = [{"value": r["value"], "published_at": r["published_at"], "item_id": r["item_id"]} for r in rs]
            out.append({"indicator": ind, "period": per, "values": vals, "latest": vals[-1],
                        "spread": round(max(distinct) - min(distinct), 4)})
    return out


def latest_forecasts(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Для каждого (показатель, период) прогноза — действующее значение (из самого позднего документа) и список заменённых.

    Формат: {indicator: {period: {value, unit, published_at, item_id, page, superseded: [{value, published_at, item_id}]}}}.
    Это вход для участника 3: брать прогнозы банка отсюда, а не из отдельных документов (там могут быть устаревшие значения).
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["value"] is not None and r["is_forecast"]:
            groups[(r["indicator"], r["period"])].append(r)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for (ind_, per), rs in sorted(groups.items()):
        rs = sorted(rs, key=lambda r: (r["published_at"] or "", r["item_id"]))
        last = rs[-1]
        sup = [{"value": r["value"], "published_at": r["published_at"], "item_id": r["item_id"]} for r in rs[:-1] if r["value"] != last["value"]]
        out.setdefault(ind_, {})[per] = {"value": last["value"], "unit": last.get("unit"), "published_at": last["published_at"],
                                         "item_id": last["item_id"], "page": last.get("page"), "superseded": sup}
    return out
