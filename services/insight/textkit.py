"""Текстовые утилиты: числа в русском формате, стемминг-токены, распознавание позиции регулятора, слухов, направления изменения."""
from __future__ import annotations

import math
import re
from datetime import date, datetime

_WORD = re.compile(r"[a-zа-я0-9]+", re.I)
NUM_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[\u00a0 ]\d{3})+|\d+)(?:[.,](\d+))?")
MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
          "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
MONTH_NAMES = {v: k for k, v in MONTHS.items()}


def ru_num(v: float | int | None, nd: int = 1, strip: bool = False) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{nd}f}".replace(",", "\u00a0").replace(".", ",")
    if strip and "," in s:
        s = s.rstrip("0").rstrip(",")
    return s


def ru_date(d: str | date | datetime | None) -> str:
    if not d:
        return "дата не указана"
    if isinstance(d, str):
        d = datetime.fromisoformat(d[:10]).date()
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day} {MONTH_NAMES[d.month]} {d.year} г."


def ru_date_short(d: str | date | datetime | None) -> str:
    if not d:
        return "—"
    if isinstance(d, str):
        d = datetime.fromisoformat(d[:10]).date()
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day} {MONTH_NAMES[d.month]}"


def fold(s: str) -> str:
    return (s or "").lower().replace("ё", "е")


def tokens(text: str) -> list[str]:
    """Токены со «стеммингом» по первым 5 символам (без внешних лемматизаторов)."""
    out = []
    for w in _WORD.findall(fold(text)):
        out.append(w[:5] if len(w) > 5 else w)
    return out


STOP = set("и в во не на с со что как по к а но или для это от из за при же бы то у о об до так его ее их эти этот мы нас наш наша наше нам вы вас был была были есть будет может также уже еще все всех всего".split())


def content_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in STOP and len(t) > 2]


def numbers(text: str) -> list[float]:
    """Числа из текста как float: «4 400» -> 4400, «14,0» -> 14.0."""
    out: list[float] = []
    for m in NUM_RE.finditer(text or ""):
        ip = re.sub(r"[\u00a0 ]", "", m.group(1))
        try:
            out.append(float(ip + ("." + m.group(2) if m.group(2) else "")))
        except ValueError:
            continue
    return out


def significant_numbers(text: str) -> list[float]:
    """Числа, которые стоит проверять на «заземлённость»: дробные, проценты и крупные (не годы, не даты, не № пунктов)."""
    out: list[float] = []
    for m in NUM_RE.finditer(text or ""):
        ip = re.sub(r"[\u00a0 ]", "", m.group(1))
        frac = m.group(2)
        try:
            val = float(ip + ("." + frac if frac else ""))
        except ValueError:
            continue
        tail = (text or "")[m.end(): m.end() + 2]
        is_pct = tail.strip().startswith("%") or tail.startswith(" %")
        if frac is not None or is_pct or (val >= 100 and not (1990 <= val <= 2100)):
            out.append(val)
    return out


UNCONFIRMED_RE = re.compile(r"неподтвержд|не\s+подтвержд|по\s+слухам|якобы|инсайд|анонимн\w+\s+источник|источник\s+не\s+раскрывает", re.I)
INJECTION_RE = re.compile(r"игнорир\w+\s+(все\s+)?(предыдущ|прежн|систем)|ignore\s+(all\s+)?(previous|prior)|system\s+prompt|системн\w+\s+промпт", re.I)


def is_unconfirmed(text: str) -> bool:
    return bool(UNCONFIRMED_RE.search(text or ""))


_UP = re.compile(r"подорожа|вырос|выросл|вырастет|повысил|повышен|повышает|повысят|рост\w*|ускорил|увеличил|увелич|ослаб\w*\s+рубл|максимум|превысил|дорожа", re.I)
_DOWN = re.compile(r"подешевел|снизил|снижен|снижает|сократил|упал|упали|замедл|укрепил|ослаб(ли|ла)\b|снизится|минимальн", re.I)


def direction_hint(title: str, text: str) -> str:
    t, b = fold(title), fold(text)
    up = 2 * len(_UP.findall(t)) + len(_UP.findall(b))
    dn = 2 * len(_DOWN.findall(t)) + len(_DOWN.findall(b))
    if up > dn * 1.2:
        return "up"
    if dn > up * 1.2:
        return "down"
    return "mixed"


def rate_stance(text: str) -> str | None:
    """Позиция по ключевой ставке из текста: hold | hike | cut | None."""
    t = fold(text)
    if not re.search(r"ставк", t) or not re.search(r"ключев|банк\w*\s+росси|\bцб\b", t):
        return None            # ставка по лизингу/ипотеке/депозитам — не решение по ключевой ставке
    hold = re.search(r"сохран\w*\s+(\w+\s+){0,4}ставк|ставк\w*\s+(\w+\s+){0,4}(сохран|без\s+изменени|неизменн)|пауз|оставил\w*\s+(\w+\s+){0,3}ставк", t)
    hike = re.search(r"(повыс\w+|ужесточ\w+)\s+(\w+\s+){0,5}ставк|ставк\w*\s+(\w+\s+){0,5}(повысит|повышен|вырастет|повышать)|повысить\s+ключев", t)
    cut = re.search(r"(снизил\w*|снизит\w*|смягч\w+)\s+(\w+\s+){0,5}ставк|ставк\w*\s+(\w+\s+){0,5}(снизит|снижен|снижать)", t)
    hits = [(n, m) for n, m in (("hike", hike), ("cut", cut), ("hold", hold)) if m]
    if not hits:
        return None
    return sorted(hits, key=lambda x: x[1].start())[0][0] if len(hits) > 1 and not hold else (("hold" if hold and not (hike or cut) else sorted(hits, key=lambda x: x[1].start())[0][0]))


def fx_stance(text: str) -> str | None:
    t = fold(text)
    weak = re.search(r"рубл\w*\s+(\w+\s+){0,2}ослаб|курс\w*\s+(\w+\s+){0,3}(превысил|вырос|вырастет)|юан\w*\s+(\w+\s+){0,3}(превысил|вырос)|ослаблени\w*\s+рубл", t)
    strong = re.search(r"рубл\w*\s+(\w+\s+){0,2}укрепил|курс\w*\s+(доллар|евро|юан)\w*\s+(\w+\s+){0,2}(снизил|упал)|укреплени\w*\s+рубл", t)
    if weak and not strong:
        return "rub_weaker"
    if strong and not weak:
        return "rub_stronger"
    return None


def pct_values(text: str) -> list[float]:
    return [float(f"{a}.{b}" if b else a) for a, b in re.findall(r"(\d+)(?:[.,](\d+))?\s*%", text or "")]


def key_rate_values(text: str) -> list[float]:
    """Значения ключевой ставки, прозвучавшие в тексте («ставку до 17%», «ставки на уровне 14%»)."""
    out = []
    for m in re.finditer(r"(?:ключев\w*\s+ставк\w*|ставк\w*\s+(?:цб|банка\s+росси\w*))[^.%]{0,60}?(\d{1,2}(?:[.,]\d+)?)\s*%", fold(text)):
        try:
            out.append(float(m.group(1).replace(",", ".")))
        except ValueError:
            pass
    return out


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def short(text: str, n: int = 320) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:—- ") + "…"


def days_between(a: str | None, b: str) -> float:
    if not a:
        return 9999.0
    da = datetime.fromisoformat(a[:19]).date()
    db = datetime.fromisoformat(b[:10]).date()
    return float((db - da).days)


def exp_decay(age_days: float, half_life: float) -> float:
    return math.pow(0.5, max(0.0, age_days) / half_life)


TOPIC_RU = {
    "agro": "сельское хозяйство", "auto_market": "авторынок", "bond_market": "рынок облигаций", "business_activity": "деловая активность",
    "chemicals": "химия", "commodities": "сырьё", "construction": "строительство", "consumer_credit": "потребительское кредитование",
    "consumer_demand": "потребительский спрос", "counterparty_risk": "риски контрагентов", "credit_conditions": "условия кредитования",
    "deposit_rates": "ставки по депозитам", "export": "экспорт", "financial_regulation": "финансовое регулирование", "food_prices": "цены на продукты",
    "foreign_trade": "внешняя торговля", "fuel_prices": "цены на топливо", "fx_rates": "курсы валют", "gdp": "ВВП", "gold": "золото",
    "import_substitution": "импортозамещение", "inflation": "инфляция", "it": "IT", "key_rate": "ключевая ставка", "labor_market": "рынок труда",
    "liquidity": "ликвидность", "logistics": "логистика", "metals": "металлы", "mortgage": "ипотека", "oil_gas": "нефть и газ", "real_estate": "недвижимость",
    "retail": "розница", "sanctions": "санкции", "tourism": "туризм", "wage_inflation": "рост зарплат", "wholesale_trade": "оптовая торговля",
    "taxes": "налоги", "regulation": "регулирование",
}


def topics_ru(codes) -> str:
    return ", ".join(TOPIC_RU.get(c, c) for c in codes)
