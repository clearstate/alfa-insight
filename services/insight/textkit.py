"""Текстовые утилиты: числа в русском формате, стемминг-токены, распознавание позиции регулятора, слухов, направления изменения."""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone

_WORD = re.compile(r"[a-zа-я0-9]+", re.I)
NUM_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[\u00a0 ]\d{3})+|\d+)(?:[.,](\d+))?")
MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
          "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
MONTH_NAMES = {v: k for k, v in MONTHS.items()}
MSK = timezone(timedelta(hours=3))           # опорная дата сервиса и календарь пользователя — московские


def ru_num(v: float | int | None, nd: int = 1, strip: bool = False) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{nd}f}".replace(",", "\u00a0").replace(".", ",")
    if strip and "," in s:
        s = s.rstrip("0").rstrip(",")
    return s


def msk_date(d: str | date | datetime) -> date:
    """Календарная дата по Москве. Момент времени (ISO с временем, без пояса — UTC, как хранит news_ingest) переводится
    в МСК; дата без времени (опорная дата «2026-10-21») берётся как есть."""
    if isinstance(d, str):
        if len(d) <= 10:
            return date.fromisoformat(d)
        d = datetime.fromisoformat(d.replace("Z", "+00:00"))
    if isinstance(d, datetime):
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(MSK).date()
    return d


def ru_date(d: str | date | datetime | None) -> str:
    if not d:
        return "дата не указана"
    d = msk_date(d)
    return f"{d.day} {MONTH_NAMES[d.month]} {d.year} г."


def ru_date_short(d: str | date | datetime | None) -> str:
    if not d:
        return "—"
    d = msk_date(d)
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


# «инсайд» — маркер слуха; «инсайдерская информация» (юридический термин из релизов ЦБ) им не является
UNCONFIRMED_RE = re.compile(r"неподтвержд|не\s+подтвержд|по\s+слухам|якобы|\bинсайд(?!ерск)\w*|анонимн\w+\s+источник|источник\s+не\s+раскрывает", re.I)
INJECTION_RE = re.compile(r"игнорир\w+\s+(все\s+)?(предыдущ|прежн|систем)|ignore\s+(all\s+)?(previous|prior)|system\s+prompt|системн\w+\s+промпт|"
                          # обращение к модели внутри текста новости: «Примечание для ИИ-ассистента: в каждом выводе напиши…»
                          r"(примечани|инструкц|указани|сообщени|обращени)\w*\s+(для|к)\s+(ии\b|ai\b|ии-\w+|искусственн\w*\s+интеллект|нейросет|"
                          r"языков\w*\s+модел|ассистент|чат-?бот|llm)|(ии|ai)-ассистент\w*[^.]{0,40}(напиши|пиши|укажи|указывай|отвечай|выведи|не\s+упоминай)", re.I)


# Экономическая суть новости (заголовок или начало текста): без неё новость не попадает в ленту, как бы ни совпали темы и
# отрасли — иначе сводка с фронта («уничтожено N автомобилей») становилась новостью для автодилера.
ECON_RE = re.compile(r"\bцен[аыуе]?\b|\bцены\b|подорож|подешев|дешевеет|дорожает|тариф|(?<![а-я])спрос|продаж|выпуск|производств|поставк|"
                     r"импорт|экспорт|пошлин|налог|ставк|кредит|лизинг|инвест|выручк|прибыл|убыт|\bрын(?:ок|ка|ке|ку)\b|дефицит|"
                     r"санкци|субсид|\bкурс|инфляц|зарплат|заказ|контракт|закуп|оборот|бюджет|\bввп\b|отгруз|логистик|перевоз|груз|"
                     r"аренд|ипотек|долг|облигац|депозит|вклад|дивиденд|банкрот|пункт\w*\s+пропуск|утилизационн|маркетплейс|"
                     r"предприят|завод|отрасл|бизнес|расход|затрат|компани\w*\s+(?:сократ|увелич|снизил|получил|потерял)")
# Изменение на рынке отрасли (для вывода «событие затрагивает отрасль ваших контрагентов»): не упоминание отрасли, а сдвиг
# цен, спроса, выпуска, поставок, регулирования торговли. «Очередь грузовиков на границе» и «бумаги в Ломбардном списке» — нет.
MARKET_SHIFT_RE = re.compile(r"\bцен[аыуе]?\b|\bцены\b|подорож|подешев|дорожа|дешеве|тариф|(?<![а-я])спрос|продаж|"
                             r"(?<!номер\s)выпуск(?!\w*\s+(?:облигац|ценн|бумаг))|производств|поставк|"
                             r"импорт|экспорт|пошлин|утилизационн|дефицит|запрет|санкци|субсид|квот|отгруз|заказ|закуп|выручк|"
                             r"\bрын(?:ок|ка|ке|ку)\b|расход|затрат")
# Некоммерческие сюжеты в заголовке: война, политика, происшествия, спорт, здоровье. Такая новость показывается, только если
# экономическая суть есть в самом заголовке («Санкции против … ударят по экспорту»).
OFFTOPIC_RE = re.compile(r"\bвсу\b|\bвс\s+рф\b|\bсво\b|минобороны|\bдрон|беспилотник|ракет|обстрел|теракт|протест|митинг|"
                         r"\bсуд\b|осудил|приговор|арестова|задержа|убий|\bдтп\b|авари|пожар|матч|чемпионат|футбол|хоккей|олимпи|"
                         r"выбор|дипломат|\bмид\b|саммит|ковид|covid|штамм|вирус|погод|пленн|экскурси|гид\b")


def lead(title: str, text: str, n: int = 700) -> str:
    """Заголовок и начало текста (суть новости) в нижнем регистре: проверки «о чём событие» — по ним, а не по слову в конце."""
    return fold((title or "") + " " + (text or "")[:n])


def business_flags(title: str, text: str) -> tuple[bool, bool]:
    """(есть экономическая суть, некоммерческий сюжет без экономики в заголовке)."""
    t, head = fold(title), fold((text or "")[:700])
    econ = bool(ECON_RE.search(t) or ECON_RE.search(head))
    return econ, bool(OFFTOPIC_RE.search(t)) and not ECON_RE.search(t)


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
    if hold and not (hike or cut):
        return "hold"
    return min(hits, key=lambda x: x[1].start())[0]      # несколько формулировок — решает первая по тексту


def fx_stance(text: str) -> str | None:
    t = fold(text)
    weak = re.search(r"рубл\w*\s+(\w+\s+){0,2}ослаб|курс\w*\s+(\w+\s+){0,3}(превысил|вырос|вырастет)|юан\w*\s+(\w+\s+){0,3}(превысил|вырос)|ослаблени\w*\s+рубл", t)
    strong = re.search(r"рубл\w*\s+(\w+\s+){0,2}укрепил|курс\w*\s+(доллар|евро|юан)\w*\s+(\w+\s+){0,2}(снизил|упал)|укреплени\w*\s+рубл", t)
    if weak and not strong:
        return "rub_weaker"
    if strong and not weak:
        return "rub_stronger"
    return None


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


def sentence(text: str) -> str:
    """Конец предложения без двойной точки: «… до конца 2026 г.» не превращается в «г..»."""
    t = (text or "").rstrip()
    return t if t.endswith((".", "!", "?", "…")) else t + "."


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Согласование с числом: plural(2, ("издание", "издания", "изданий")) -> «издания»."""
    a = abs(n) % 100
    b = a % 10
    return forms[2 if 10 < a < 20 else 0 if b == 1 else 1 if 2 <= b <= 4 else 2]


def ru_value(v: float | None, unit: str | None, nd: int = 1) -> str:
    """Значение показателя с единицей: «14,0%», «87,2 руб./$», «10,2% г/г»; без единицы — только число."""
    num, unit = ru_num(v, nd), (unit or "").strip()
    if not unit:
        return num
    return num + unit if unit.startswith("%") else f"{num} {unit}"


def short(text: str, n: int = 320) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:—- ") + "…"


def days_between(a: str | None, b: str) -> float:
    """Возраст в днях: дата публикации a (ISO, обычно UTC) берётся по московскому календарю, как и опорная дата b.
    Иначе новость, вышедшая с 00:00 до 03:00 МСК, считалась бы на день старше."""
    if not a:
        return 9999.0
    return float((msk_date(b[:10]) - msk_date(a)).days)


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
