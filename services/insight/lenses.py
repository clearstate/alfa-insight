"""Анализ влияния события на конкретную компанию: «линзы» (ставка, курс, ФОТ, спрос, отрасль, цепочка поставок, налоги и др.).

Каждая линза берёт признаки профиля (sensitivity_factors, ОКВЭД, регион, ВЭД), темы события и позиции/прогнозы банка и
возвращает Finding со ссылками на доказательства. Тексты собираются из проверяемых данных; числа берутся только из
доказательств (проверяется в agent.verify). Если данных не хватает — выводы помечаются гипотезой и снижается уверенность.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from services.company_profile.features import country_title

from .evidence import EvidenceBook
from .textkit import MARKET_SHIFT_RE, direction_hint, fold, fx_stance, lead, rate_stance, ru_date, ru_num, topics_ru

PRODUCT_RU = {"rko": "расчётно-кассовое обслуживание", "loans": "кредиты", "leasing": "лизинг", "deposits": "депозиты",
              "guarantees": "банковские гарантии", "factoring": "факторинг", "payroll_project": "зарплатный проект"}
SEV_ORDER = {"high": 3, "medium": 2, "low": 1}
FX_TOPICS = {"fx_rates", "foreign_trade", "sanctions", "export", "import_substitution"}
RATE_TOPICS = {"key_rate", "credit_conditions", "bond_market", "liquidity", "deposit_rates", "financial_regulation", "consumer_credit", "mortgage"}
SUPPLY_MIN_SHARE_PCT = 10            # минимальная доля известных платежей контрагентов отрасли для вывода о цепочке поставок


@dataclass
class Finding:
    lens: str
    direction: str                    # risk | opportunity | mixed | neutral
    severity: str                     # high | medium | low
    title: str
    text: str
    evidence: list[str] = field(default_factory=list)
    features: list[dict] = field(default_factory=list)
    confidence: str = "medium"        # high | medium | low
    horizon: str = "1–3 месяца"
    hypothesis: bool = False
    tags: list[str] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    scenarios: list[dict] = field(default_factory=list)
    company_specific: bool = True

    def as_dict(self) -> dict:
        return {"lens": self.lens, "direction": self.direction, "severity": self.severity, "title": self.title, "text": self.text,
                "evidence": self.evidence, "features": self.features, "confidence": self.confidence, "horizon": self.horizon,
                "hypothesis": self.hypothesis, "tags": self.tags, "scenarios": self.scenarios}


class Ctx:
    def __init__(self, kb, directory, company_id: str, role: str, item: dict | None, profile: dict, ev: EvidenceBook,
                 topics: dict[str, float] | None = None, supply: list[dict] | None = None):
        self.kb, self.dir, self.company_id, self.role = kb, directory, company_id, role
        self.item, self.profile, self.ev = item, profile, ev
        self.topics = topics if topics is not None else dict((item or {}).get("topic_scores") or {})
        self.pv = directory.prompt_view(profile)
        self.factors = {f["code"]: f for f in profile["sensitivity_factors"]}
        self.okved = profile["industry"]["okved_code"]["value"]
        self.levels: list[str] = profile["industry"]["okved_levels"]["value"] or []
        self.region = profile["geography"]["region"]["value"]
        self.countries: list[str] = profile["foreign_trade"]["countries"]["value"] or []
        self.products = {k for k, v in profile["bank_relationship"]["products"].items() if v["value"] is True}
        self.title = (item or {}).get("title", "")
        self.text = (item or {}).get("text", "")
        self.supply = supply or []
        self.used_anchors: list[dict] = []
        self.facts: list[str] = []          # evidence ids новостных фактов

    # ---- признаки
    def level(self, code: str) -> str:
        return (self.factors.get(code) or {}).get("level", "none")

    def fev(self, code: str) -> str | None:
        f = self.factors.get(code)
        return self.ev.company(code, f) if f else None

    def feat(self, code: str) -> dict:
        return {"code": code, "level": self.level(code), "rule_id": (self.factors.get(code) or {}).get("rule_id")}

    def in_division(self, prefixes: list[str]) -> bool:
        return "*" in prefixes or any(p in self.levels for p in prefixes)

    # ---- доказательства
    def ind(self, code: str, period: str) -> tuple[dict | None, str | None]:
        i = self.kb.indicator(code, period)
        return (i, self.ev.indicator(i)) if i else (None, None)

    def anchor(self, aid: str) -> tuple[dict | None, str | None]:
        a = next((x for x in self.kb.anchors if x["id"] == aid and not x["stale"]), None)
        if not a:
            return None, None
        self.used_anchors.append(a)
        return a, self.ev.anchor(a)

    def news_ev(self) -> list[str]:
        return list(self.facts)

    def pct_phrase(self) -> str | None:
        m = re.search(r"\d+\s*[–-]\s*\d+\s*%|\d+(?:[.,]\d+)?\s*%", self.text)
        return m.group(0).replace(" ", "") if m else None

    def has(self, *topics: str) -> bool:
        return any(t in self.topics for t in topics)

    def text_has(self, pattern: str) -> bool:
        return bool(re.search(pattern, fold(self.title + " " + self.text)))

    def hint(self) -> str:
        return direction_hint(self.title, self.text)

    def region_hit(self) -> bool:
        return bool(self.item and self.region and self.region in (self.item.get("regions") or []))

    def next_meeting(self) -> tuple[str | None, str | None]:
        """(дата ближайшего заседания ЦБ по ставке «23 октября», ожидание банка «банк ожидает паузы») из календаря материалов
        банка; (None, None), если будущих дат в материалах нет — тогда дата в тексте не называется."""
        ev = next(iter(self.kb.calendar()), None)
        if not ev:
            return None, None
        detail = ev.get("detail") or ""
        expect = detail.lower() if "ожидает" in detail else None      # «банк ожидает паузы»
        return ru_date(ev["date"]).rsplit(" ", 1)[0], expect


_TIGHT_RE = re.compile(r"ужесточ|жестч|жестк\w*\s+(услов|требован)|макропруденц|надбавк|повыш\w*\s+требован|отказ\w*\s+в\s+кредит|"
                       r"(кредит|заем|займ)\w*[^.]{0,40}(дорож|подорож)|сокращ\w*\s+кредитован")
_EASE_RE = re.compile(r"смягч|сниж\w*\s+(надбав|требован|нагрузк\w*\s+на\s+капитал)|эконом\w*\s+капитал|льготн|поддержк")
_RETAIL_CREDIT_RE = re.compile(r"потребит|розничн|населени|граждан|физическ\w*\s+лиц|ипотек|автокредит|кредитн\w*\s+карт|микрофин|\bмфо\b")


def _corporate_tightening(text: str) -> bool:
    """В тексте говорится об ужесточении условий кредитования бизнеса. Ужесточение потребительского кредитования и ипотеки
    (то же предложение) к корпоративному долгу компании не относится; смягчение/поддержка отменяет вывод."""
    if _EASE_RE.search(text):
        return False
    for m in _TIGHT_RE.finditer(text):
        a, b = text.rfind(".", 0, m.start()) + 1, text.find(".", m.end())
        if not _RETAIL_CREDIT_RE.search(text[a: b if b >= 0 else len(text)]):
            return True
    return False


def _act(title: str, text: str, kind: str = "analysis", product: str | None = None) -> dict:
    return {"title": title, "text": text, "kind": kind, "product": product}


def _lc(s: str) -> str:
    """Цитата позиции банка внутри предложения: первая буква строчная (кроме аббревиатур вроде «ЦБ»)."""
    return s if s[:2].isupper() else s[:1].lower() + s[1:]


def _ru_list(items: list[str]) -> str:
    return ", ".join(country_title(i) for i in items)


# =========================================================================== ставка / кредитование
def lens_rate(c: Ctx) -> list[Finding]:
    if not c.has(*RATE_TOPICS):
        return []
    out: list[Finding] = []
    stance = rate_stance(c.title + ". " + c.text) if c.has("key_rate", "bond_market", "deposit_rates") else None
    unconf = bool(c.item and c.item.get("unconfirmed"))
    kr26, e1 = c.ind("key_rate_eoy", "2026")
    kr27, e2 = c.ind("key_rate_eoy", "2027")
    hold, e3 = c.anchor("cbr_hold_sept11")
    plan, e4 = c.anchor("key_rate_hold")
    flo, e5 = c.anchor("floating_credit")
    ev = [e for e in (e1, e2, e3, e4) if e]
    now = ru_num(kr26["value"], 1) if kr26 else None
    nxt = ru_num(kr27["value"], 1) if kr27 else None
    rs_level = c.level("rate_sensitivity")
    prod = [PRODUCT_RU[p] for p in ("loans", "leasing", "guarantees", "factoring") if p in c.products]
    # вывод о ключевой ставке — только если она действительно обсуждается в событии (а не упомянуты облигации/ставки вкладов)
    # Вопрос о компании без события (ассистент: «как ставка влияет на мою компанию?») — оценка по прогнозу банка.
    ratekey = c.item is None or stance == "hold" or (c.has("key_rate") and c.text_has(r"ключев\w*\s+ставк|ставк\w*\s+(цб|банка\s+росси)"))
    # «условия кредитования ужесточаются» — только если об этом говорится в событии
    tightening = _corporate_tightening(fold(c.title + " " + c.text))

    if rs_level in ("high", "medium"):
        sev = "high" if rs_level == "high" else "medium"
        evs = ev + c.news_ev() + ([e5] if e5 else []) + [x for x in (c.fev("rate_sensitivity"),) if x]
        base = (f"У компании есть продукты с процентной нагрузкой в банке ({', '.join(prod) or 'кредитные продукты'}). ")
        # долг называется по продуктам компании: у компании только с лизингом нет «кредитов»
        loans, leasing = "loans" in c.products, "leasing" in c.products
        debt_dat = ("кредитам и лизингу" if loans and leasing else "кредитам" if loans else "лизингу" if leasing else "продуктам с процентной нагрузкой")
        debt_gen = ("кредитов и лизинга" if loans and leasing else "кредитов" if loans else "лизинга" if leasing else "продуктов с процентной нагрузкой")
        if stance == "hike":
            title = "Повышение ставки удорожает обслуживание долга"
            txt = base + (f"Если ставка вырастет, проценты по плавающей ставке ({debt_dat}) вырастут вслед за ней" +
                          (f"; сейчас банк прогнозирует {now}% до конца 2026 г. " if now else ". "))
            direction = "risk"
        elif stance == "cut":
            title = "Снижение ставки удешевляет заёмное финансирование"
            txt = base + f"Снижение ставки уменьшит расходы на обслуживание {debt_gen} по плавающей ставке и улучшит условия рефинансирования. "
            direction, sev = "opportunity", "medium"
        elif ratekey:
            title = f"Деньги остаются дорогими: нагрузка по {debt_dat if loans or leasing else 'долгу'} не снизится"
            txt = base + (f"Банк ожидает, что ключевая ставка сохранится на уровне {now}% до конца 2026 г. и снизится до {nxt}% только к концу 2027 г.: " if now and nxt else "Ставка остаётся высокой: ") + \
                  f"расходы на обслуживание {debt_gen} в ближайшие месяцы не уменьшатся. "
            direction = "risk"
        elif tightening:
            title = "Условия кредитования могут стать жёстче"
            q, eq = c.anchor("bank_credit_quality")
            txt = base + ("В событии говорится об ужесточении условий кредитования" +
                          (", и в аналитике банка отмечено, что банки строже оценивают кредитное качество заёмщиков" if q else "") +
                          ": новые кредиты и рефинансирование могут стать дороже и потребовать больше обеспечения. ")
            direction = "risk"
            evs += [eq] if eq else []
        else:
            title = None                  # событие не о ставке и не об ужесточении условий: процентный вывод не делаем
        if title is not None and flo and ratekey:
            txt += f"В аналитике банка отмечено: {_lc(flo['summary'])} "
    if rs_level in ("high", "medium") and title is not None:
        calc = c.ev.calc("rate_100m", "Ориентир: 100 млн ₽ долга × 1 п.п. = 1 млн ₽ процентов в год", [100, 1])
        txt += "Ориентир для расчёта: на каждые 100 млн ₽ долга по плавающей ставке изменение ставки на 1 п.п. меняет проценты примерно на 1 млн ₽ в год (объём и тип ставки у компании в данных банка неизвестны, проверьте по договорам)."
        evs.append(calc)
        out.append(Finding("rate", direction, sev, title, txt, evs, [c.feat("rate_sensitivity")], "medium" if rs_level == "high" else "low",
                           "до конца 2026 г.", hypothesis=unconf, tags=["rate_risk"],
                           actions=[_act(f"Сверить тип ставки и график платежей по {debt_dat}", "Определить, какая часть долга привязана к ключевой ставке, и рассчитать нагрузку"
                                         + (f" при ставке {now}% до конца 2026 г." if now else "") + (f" и {nxt}% на конец 2027 г." if nxt else "") + (" (прогноз банка)." if now else "."), "analysis"),
                                    _act("Обсудить с менеджером фиксацию ставки или рефинансирование", "Если процентная нагрузка существенна для бюджета.", "product", "rate_risk")],
                           scenarios=[{"name": "Базовый (прогноз банка)", "condition": (f"Ставка {now}% до конца года" if now else "Ставка без изменений до конца года"), "effect": "Расходы на проценты остаются на текущем уровне"},
                                      {"name": "Ужесточение", "condition": "ЦБ сигнализирует о возможности повышения", "effect": "Рост процентных расходов по плавающей части долга"}]))
    di = c.level("deposit_income")
    if di in ("high", "medium") and (ratekey or stance in ("hike", "cut") or c.has("deposit_rates")):
        a, ea = c.anchor("cbr_dates")
        evs = ev + c.news_ev() + [x for x in (ea, c.fev("deposit_income")) if x]
        meet, expect = c.next_meeting()
        txt = ("У компании есть депозитные продукты. Пока ключевая ставка остаётся высокой" + (f" ({now}%)" if now else "") +
               ", краткосрочные размещения свободных средств остаются доходными. "
               + (f"Ближайшее заседание ЦБ — {meet}" + (f", {expect}" if expect else "") + ": это ориентир для выбора срока размещения. " if meet else "")
               + (f"Если ставка снизится к концу 2027 г. до {nxt}% (прогноз банка), доходность новых размещений будет ниже, поэтому срок стоит согласовать с платёжным календарём." if nxt else ""))
        out.append(Finding("deposit", "opportunity", "medium" if di == "high" else "low", "Высокая ставка поддерживает доходность размещения средств", txt, evs,
                           [c.feat("deposit_income")], "medium", "до конца 2026 г.", tags=["deposit_opportunity"],
                           actions=[_act("Подобрать срок размещения свободных остатков", "Сопоставить срок с платёжным календарём и датой заседания ЦБ.", "product", "deposit_opportunity")]))
    if not out and rs_level not in ("high", "medium") and (ratekey or stance in ("hike", "cut")):
        txt = ("Прямой процентной нагрузки по кредитам в данных банка у компании не видно, поэтому влияние ставки косвенное: через стоимость финансирования контрагентов и спрос. "
               + (f"Банк ожидает ставку {now}% до конца 2026 г. " if now else ""))
        out.append(Finding("rate", "neutral", "low", "Ставка влияет на компанию косвенно", txt, ev + c.news_ev(), [c.feat("rate_sensitivity")], "low", "6–12 месяцев",
                           hypothesis=True, company_specific=False))
    return out


# =========================================================================== курс и внешняя торговля
def lens_fx(c: Ctx) -> list[Finding]:
    if not c.has(*FX_TOPICS):
        return []
    lvl = c.level("fx_and_trade_exposure")
    if lvl == "none" and not c.has("fx_rates"):
        return []
    out: list[Finding] = []
    stance = fx_stance(c.title + " " + c.text)
    u26, e1 = c.ind("usd_rub_eoy", "2026")
    u27, e2 = c.ind("usd_rub_eoy", "2027")
    c26, e3 = c.ind("cny_rub_eoy", "2026")
    c27, e4 = c.ind("cny_rub_eoy", "2027")
    fxa, e5 = c.anchor("import_growth")
    ev = [e for e in (e1, e2, e3, e4, e5) if e]
    ctry = _ru_list(c.countries) if c.countries else None
    sev = {"high": "high", "medium": "medium"}.get(lvl, "low")
    in_fts = bool(c.countries) or c.profile["foreign_trade"]["fts_flag"]["value"] is True
    fx_text = not (c.item and c.item.get("kind") == "news") or c.text_has(r"курс|рубл|доллар|юан|евро|валют")
    if c.has("fx_rates") and lvl not in ("none", "unknown") and fx_text:
        fc = ""
        if u26 and u27 and c26 and c27:
            trend = ("ожидается постепенное ослабление рубля" if u27["value"] > u26["value"] else
                     "ожидается укрепление рубля" if u27["value"] < u26["value"] else "курс ожидается стабильным")
            fc = (f"Банк прогнозирует USD/RUB {ru_num(u26['value'])} на конец 2026 г. и {ru_num(u27['value'])} на конец 2027 г., "
                  f"CNY/RUB — {ru_num(c26['value'])} и {ru_num(c27['value'])}: {trend}. ")
        m = re.search(r"юан\w*[^.]{0,60}?(\d{1,2}[.,]\d+)", fold(c.title + " " + c.text))
        cross = ""
        if m and c26:
            v = float(m.group(1).replace(",", "."))
            if v > c26["value"] * 1.01:
                cross = f"Курс юаня из сообщения ({ru_num(v)}) уже выше прогноза банка на конец года ({ru_num(c26['value'])}), поэтому закладывать в расчёты стоит более слабый рубль. "
        head = ("Рубль слабеет: растёт стоимость импорта" if stance == "rub_weaker" else "Рубль укрепляется: импорт дешевеет" if stance == "rub_stronger" else "Курсовые изменения влияют на расчёты по ВЭД")
        txt = (("Компания присутствует в данных ФТС" + (f" (страны: {ctry})" if ctry else "") + ", но направление операций (импорт или экспорт) в данных не указано, поэтому знак эффекта зависит от структуры бизнеса. "
                if in_fts else "Данных ФТС о внешней торговле компании нет, но форма собственности иностранная: возможна косвенная валютная экспозиция, знак эффекта зависит от структуры бизнеса. ")
               + fc + cross + "Если в бизнесе преобладает импорт (гипотеза), ослабление рубля повышает себестоимость закупок, при преобладании экспорта эффект обратный.")
        direction = "risk" if stance != "rub_stronger" else "opportunity"
        out.append(Finding("fx", direction, sev, head, txt, ev + c.news_ev() + [x for x in (c.fev("fx_and_trade_exposure"),) if x],
                           [c.feat("fx_and_trade_exposure")], "low" if stance is None else "medium", "до конца 2026 г.", hypothesis=True, tags=["fx_risk"],
                           scenarios=[{"name": "Преобладает импорт", "condition": "Закупки в валюте, продажи в рублях", "effect": "Рост себестоимости при ослаблении рубля"},
                                      {"name": "Преобладает экспорт", "condition": "Выручка в валюте", "effect": "Рост рублёвой выручки при ослаблении рубля"}],
                           actions=[_act("Проверить валютную позицию и сроки конверсии", "Оценить долю валютных закупок и выручки; сравнить текущие контракты с прогнозом курса банка.", "analysis"),
                                    _act("Согласовать с менеджером расчёты и защиту от курсовых колебаний", "Порядок валютного контроля, конверсии и инструменты хеджирования.", "product", "fx_risk")]))
    pay = c.text_has(r"платеж|расчет") and c.has("sanctions", "foreign_trade") and c.text_has(r"задержк|проверк")
    if pay and lvl in ("high", "medium"):
        about_china = c.text_has(r"китай|китае|юан|кнр")
        china = about_china and any(x.upper() == "КИТАЙ" for x in c.countries)
        txt = ((("Сообщается, что расчёты с китайскими контрагентами занимают дольше и дороже. " +
                 ("Китай входит в страны внешней торговли компании. " if china else "Среди стран внешней торговли компании Китая в данных нет, поэтому эффект возможен лишь косвенно. "))
                if about_china else "Сообщается о задержках или проверках международных расчётов. ") +
               "Рост срока расчётов замораживает оборотный капитал и повышает риск срыва поставок; использование посредников увеличивает комиссии. ")
        out.append(Finding("fx_payments", "risk", "high" if china and lvl == "high" else "medium", "Задержки международных платежей могут сорвать графики поставок", txt,
                           c.news_ev() + ([e5] if e5 else []) + [x for x in (c.fev("fx_and_trade_exposure"),) if x], [c.feat("fx_and_trade_exposure")],
                           "medium" if china else "low", "1–2 месяца", hypothesis=not china, tags=["working_capital_risk", "contract_risk"],
                           actions=[_act("Пересмотреть график платежей и страховой запас", "Заложить увеличенный срок расчётов и проверить альтернативные каналы.", "analysis"),
                                    _act("Обсудить с менеджером решения для расчётов и оборотного капитала", "Факторинг и гарантии под контракты.", "product", "working_capital_risk")]))
    return out


# =========================================================================== фонд оплаты труда
# признаки давления на фонд оплаты труда в тексте события; новость о сокращениях («Volvo сократит 2,5 тыс. рабочих мест»)
# тоже получает тему «рынок труда», но о росте зарплат в ней ничего нет — вывод «расходы на персонал растут» ей не подходит
_WAGE_PRESSURE_RE = re.compile(r"зарплат|заработн|оплат\w*\s+труда|\bфот\b|дефицит\w*\s+(кадр|персонал|работник|сотрудник)|"
                               r"нехватк\w*\s+(кадр|персонал|работник|сотрудник)|рын\w+\s+труда|безработиц|ваканси|найм|наем")


def lens_payroll(c: Ctx) -> list[Finding]:
    if not c.has("labor_market", "wage_inflation"):
        return []
    lvl = c.level("payroll_exposure")
    if lvl in ("none", "unknown"):
        return []
    if c.item and c.item.get("kind") == "news" and not _WAGE_PRESSURE_RE.search(fold(c.title + " " + c.text)):
        return []                          # внешняя новость без признаков роста зарплат или дефицита кадров
    w, e1 = c.ind("wages_nominal", "2026")
    u, e2 = c.ind("unemployment", "2026")
    a1, e3 = c.anchor("labor_market_tight")
    a2, e4 = c.anchor("real_wages")
    ev = [e for e in (e1, e2, e3, e4) if e] + c.news_ev() + [x for x in (c.fev("payroll_exposure"),) if x]
    reg = c.region_hit()
    txt = ("У компании " + (f"численность по данным ФНС: {c.pv['size']['workers_fns'][:1].lower()}{c.pv['size']['workers_fns'][1:]}" if c.pv["size"].get("workers_fns") else "заметный фонд оплаты труда") +
           (" и зарплатный проект в банке" if "payroll_project" in c.products else "") + ". " +
           ("Событие относится к региону компании. " if reg else "") +
           (f"Банк прогнозирует рост номинальных зарплат в 2026 г. на {ru_num(w['value'], 1, strip=True)}%" + (f" при безработице около {ru_num(u['value'])}%" if u else "") + ". " if w else "") +
           ("По оценке банка, рынок труда остаётся напряжённым: " if a1 else "") +
           "давление на фонд оплаты труда сохранится, а конкуренция за персонал повышает расходы на найм.")
    sev = "high" if (lvl == "high" and reg) else {"high": "medium", "medium": "medium", "low": "low"}[lvl]
    return [Finding("payroll", "risk", sev, "Расходы на персонал продолжат расти", txt, ev, [c.feat("payroll_exposure")], "medium", "6–12 месяцев", tags=["payroll_risk"],
                    actions=[_act("Заложить индексацию ФОТ в бюджет на следующий период", "Использовать прогноз банка по зарплатам как верхний ориентир и сверить с планом найма.", "analysis"),
                             _act("Проверить условия зарплатного проекта и лимиты", "Если фонд оплаты труда растёт быстрее выручки.", "product", "payroll_risk")])]


# =========================================================================== потребительский спрос
# о потребительском спросе должно говориться в самом событии: тема «туризм» у сообщения о штамме ковида или тема «розница»
# у кредитных каникул продавцов маркетплейса — не повод для вывода «спрос охлаждается»
_DEMAND_RE = re.compile(r"(?<![а-я])спрос|потреблен|потребител|покупательск|розничн\w*\s+(торгов|продаж)|средн\w*\s+чек|"
                        r"трат\w*\s+(населени|граждан|потребител|покупател)|оборот\w*\s+(рознич|ресторан|общепит|торговл)|"
                        r"турпоток|туристическ\w*\s+поток|загрузк\w*\s+(отел|гостиниц)|продаж\w*\s+(автомобил|машин|авто)")
# тема события должна относиться к рынку компании: авторынок — автодилерам и автосервису, туризм — гостиницам, общепиту и турагентствам
_DEMAND_TOPIC_DIV = {"auto_market": ["45.1", "45.2", "45.3", "29"], "tourism": ["55", "56", "79", "93"]}


def lens_demand(c: Ctx) -> list[Finding]:
    if not c.has("consumer_demand", "retail", "consumer_credit", "auto_market", "tourism"):
        return []
    if c.item and c.item.get("kind") == "news":
        if not _DEMAND_RE.search(lead(c.title, c.text)):
            return []
        relevant = [t for t in ("consumer_demand", "retail", "consumer_credit", "auto_market", "tourism")
                    if c.has(t) and (t not in _DEMAND_TOPIC_DIV or c.in_division(_DEMAND_TOPIC_DIV[t]))]
        if not relevant:
            return []                     # Volvo сокращает продажи — не про спрос на продукты в магазине у дома
    lvl = c.level("consumer_exposure")
    consumer_div = c.in_division(["47", "56", "55", "45.1", "45.2"])
    if lvl in ("none", "low") and not consumer_div:
        return []
    a1, e1 = c.anchor("consumption_peak")
    a2, e2 = c.anchor("retail_july")
    rt, e3 = c.ind("retail_turnover", "2026")
    if not a1:                        # вывод «спрос охлаждается» держится на оценке банка; без неё его не делаем
        return []
    ev = [e for e in (e1, e2, e3) if e] + c.news_ev() + [x for x in (c.fev("consumer_exposure"),) if x]
    txt = ("Выручка компании зависит от потребительского спроса. По оценке банка, потребление на пике, а к четвёртому кварталу 2026 г. "
           "рост спроса остановится около нуля" + (f"; прогноз банка по росту розничного оборота в 2026 г. — {ru_num(rt['value'], 1, strip=True)}%" if rt else "") +
           ". Это риск стагнации выручки и давления на средний чек, если расходы растут быстрее цен.")
    return [Finding("demand", "risk", "high" if lvl == "high" else "medium", "Потребительский спрос охлаждается", txt, ev, [c.feat("consumer_exposure")],
                    "medium", "3–6 месяцев", tags=["demand_risk"],
                    actions=[_act("Пересмотреть прогноз выручки на 4 квартал", "Заложить сценарий нулевого роста потребления и проверить точку безубыточности.", "analysis")])]


# =========================================================================== макрофон
def lens_macro(c: Ctx) -> list[Finding]:
    if not c.has("gdp", "inflation", "business_activity"):
        return []
    g, e1 = c.ind("gdp_growth", "2026")
    i, e2 = c.ind("inflation_dec_yoy", "2026")
    a, e3 = c.anchor("gdp_cut")
    a2, e4 = c.anchor("inflation_75")
    ev = [e for e in (e1, e2, e3, e4) if e] + c.news_ev()
    if not (g or i):
        return []                         # без прогнозов банка оценка макрофона ничем не подкреплена
    parts = [p for p in (f"рост ВВП в 2026 г. — {ru_num(g['value'], 1)}%" if g else None,
                         f"инфляция по итогам года — {ru_num(i['value'], 1)}%" if i else None) if p]
    txt = "Прогноз банка: " + ", ".join(parts) + ". "
    # качественная оценка выводится из самих чисел: рост ниже 1,5% — слабый, инфляция выше цели ЦБ (4%) — высокая
    weak, high_infl = bool(g and g["value"] < 1.5), bool(i and i["value"] > 4.0)
    if weak or high_infl:
        cause = " и ".join(x for x, ok in (("слабый рост экономики", weak), ("высокая инфляция", high_infl)) if ok)
        txt += cause[0].upper() + cause[1:] + " сдерживают снижение ставки и рост спроса: бюджет стоит планировать без расчёта на быстрое удешевление денег."
    return [Finding("macro", "neutral", "low", "Макрофон по прогнозам банка", txt, ev, [], "medium", "до конца 2026 г.", company_specific=False)]


# =========================================================================== отраслевые сценарии
UP_RE = r"(подорож|дорож|рост|вырос|повыш|увелич)"
DOWN_RE = r"(сниж|сокращ|упал|паден|охлажд|заморо|приостан|отклад)"
FOOD_UP_RE = (r"(мяс|молоч|овощ|продукт|продовольств|сахар|круп|подсолнечн)\w*[^.]{0,60}" + UP_RE + "|" + UP_RE
              + r"\w*\s+цен[^.]{0,60}(мяс|молоч|овощ|продукт|продовольств)")
# Каждый сценарий срабатывает, только если его утверждения опираются на текст события (need_text — все выражения должны
# найтись в заголовке или тексте); формулировки ссылаются на событие («в событии говорится…»), а не вводят внешние факты.
PLAYBOOKS: list[dict[str, Any]] = [
    dict(id="auto_import_cost", divisions=["45", "29"], need=["auto_market"], any_of=["regulation", "foreign_trade"], direction="risk", severity="high",
         need_text=[r"утил\w*\s*сбор|утильсбор|пошлин|ввоз|растамож|импорт\w*\s+(авто|комплект|запчаст)"],
         title="Удорожание ввоза комплектующих сожмёт маржу",
         text="Компания работает в автокомпонентах (ОКВЭД {okved}){countries_part}. По сообщениям, себестоимость ввоза может вырасти {pct_part}. Пока закупочные цены и условия контрактов не пересмотрены, маржа оптовой торговли сжимается; быстрее всех это почувствуют позиции с высокой долей импорта.",
         tags=["contract_risk", "fx_risk"], horizon="по срокам из сообщения",
         actions=[("Пересчитать закупочные цены и прайс на позиции с высокой долей импорта", "Оценить, какую часть роста себестоимости можно переложить на покупателей.", "analysis", None),
                  ("Согласовать с поставщиками условия и сроки до даты вступления изменений", "Рассмотреть увеличение закупок до роста сбора, если позволяют склад и оборотный капитал.", "analysis", None)]),
    dict(id="auto_secondary", divisions=["45"], need=["auto_market"], any_of=["regulation", "foreign_trade", "consumer_credit"], direction="opportunity", severity="medium",
         need_text=[r"(удорож|подорож|дорожа)\w*[^.]{0,40}(нов\w*\s+)?(автомобил|машин)|(автомобил|машин)\w*[^.]{0,40}(подорож|дорожа)|"
                    r"автокредит\w*[^.]{0,60}(ужесточ|лимит|дорож|сниж|сократ)|(ужесточ|лимит|дорож|сниж|сократ)\w*[^.]{0,60}автокредит"],
         title="Дорогие новые автомобили могут поддержать спрос на запчасти вторичного рынка",
         text="В событии говорится об удорожании новых автомобилей или об ужесточении условий автокредитования: это может сместить спрос в сторону обслуживания старых машин. Для оптовой торговли запчастями это возможность нарастить обороты (гипотеза: данных о структуре продаж компании у банка нет).",
         hypothesis=True, confidence="low", horizon="3–6 месяцев",
         actions=[("Проверить складские остатки по ходовым позициям вторичного рынка", "Сопоставить с прогнозом спроса.", "analysis", None)]),
    dict(id="logistics_cost", divisions=["45", "46", "47", "17", "41", "42", "43", "10", "56"], need=[], any_of=["logistics", "fuel_prices"], direction="risk", severity="medium",
         need_text=[r"перевоз|доставк|логист|фрахт|тариф\w*\s+(ржд|на\s+перевоз|на\s+грузо)|бензин|дизел|моторн\w*\s+топлив|цен\w*\s+на\s+топлив",
                    r"(цен|стоимост|тариф)\w*[^.]{0,60}" + UP_RE + "|" + UP_RE + r"\w*[^.]{0,30}(цен|стоимост|тариф)|подорож|дорожа|индексир"],
         title="Транспорт и доставка дорожают",
         text="В событии говорится о росте стоимости перевозок или топлива. Для компании с ОКВЭД {okved} это повышает расходы цепочки поставок{countries_part2}: если не удастся переложить рост на цены, снизится маржа, а сроки поставок могут увеличиться.",
         confidence="medium", horizon="1–3 месяца", need_hint="up",
         actions=[("Оценить долю транспортных расходов в себестоимости и пересмотреть тарифы", "Сопоставить с контрактами на доставку.", "analysis", None)]),
    dict(id="food_cost", divisions=["56"], need=["food_prices"], any_of=[], direction="risk", severity="high", need_text=[FOOD_UP_RE],
         title="Закупки продуктов дорожают быстрее выручки",
         text="Для ресторанного бизнеса продукты — основная статья переменных затрат. Рост цен на продукты, о котором говорится в событии, повышает себестоимость блюд; если спрос не позволяет поднять цены меню, давление ляжет на маржу.",
         tags=["demand_risk"], horizon="1–3 месяца",
         actions=[("Пересчитать себестоимость меню и подобрать замены", "Определить позиции, где допустим пересмотр цены или рецептуры.", "analysis", None)]),
    dict(id="food_wholesale", divisions=["46"], need=["food_prices"], any_of=[], direction="mixed", severity="low", need_text=[FOOD_UP_RE],
         title="Рост цен на продукты: оборот в рублях растёт, объёмы под вопросом",
         text="Для оптовой торговли удорожание продовольствия, о котором говорится в событии, увеличивает рублёвый оборот, но может снизить объёмы закупок покупателями и повысить потребность в оборотном капитале. Эффект зависит от доли продовольственных групп в ассортименте (в данных банка не раскрыта).",
         hypothesis=True, confidence="low", horizon="1–3 месяца", actions=[]),
    dict(id="construction_cost", divisions=["41", "42", "43"], need=[], any_of=["commodities", "metals", "construction"], direction="risk", severity="high",
         need_hint="up", need_text=[r"арматур|цемент|металлопрокат|стройматериал|строительн\w*\s+материал|бетон|кирпич"],
         title="Стройматериалы дорожают: смета и фиксированные цены контрактов под давлением",
         text="В событии говорится об удорожании строительных материалов. Компания работает в строительстве (ОКВЭД {okved}): рост цен на материалы повышает себестоимость объектов, а договоры с фиксированной ценой его не покрывают — это повод пересчитать маржу по текущим проектам{region_part}.",
         tags=["contract_risk"], horizon="1–6 месяцев",
         actions=[("Пересчитать маржу по объектам с фиксированной ценой", "Определить контракты, где нужна индексация.", "analysis", None),
                  ("Обсудить гарантии и лимиты под новые контракты", "С учётом роста себестоимости.", "product", "contract_risk")]),
    dict(id="construction_demand", divisions=["41", "42", "43"], need=[], any_of=["mortgage", "real_estate", "construction"], direction="risk", severity="high",
         need_text=[r"(ипотек|новостро|жиль|застройщик|девелопер|продаж\w*\s+квартир)\w*[^.]{0,80}" + DOWN_RE + "|" + DOWN_RE + r"\w*[^.]{0,80}(ипотек|новостро|спрос\w*\s+на\s+жиль|продаж\w*\s+квартир)"],
         title="Спрос на новостройки и объём заказов снижаются",
         text="В событии говорится о снижении спроса на жильё, выдач ипотеки или активности застройщиков{region_part}. Для строительной компании это риск сокращения портфеля заказов при сохранении высокой стоимости заёмных средств.",
         tags=["demand_risk"], horizon="6–12 месяцев",
         actions=[("Оценить портфель заказов и зависимость от жилых проектов", "Проверить долю заказчиков с проектным финансированием.", "analysis", None)]),
    dict(id="packaging_inputs", divisions=["17"], need=["commodities"], any_of=[], direction="mixed", severity="medium",
         need_text=[r"макулатур|целлюлоз|гофро|картон"],
         title="Сырьё для упаковки дорожает, но растут и отпускные цены",
         text="В событии говорится о ценах на сырьё для упаковки. Для компании в производстве гофрированной бумаги и картона (ОКВЭД {okved}) итог зависит от того, насколько быстро удастся переложить рост сырья на покупателей: при задержке маржа сжимается, при успешном повышении цен и высокой загрузке — выигрыш.",
         confidence="medium", horizon="1–3 месяца",
         actions=[("Сопоставить рост цен на сырьё и график повышения отпускных цен", "Определить контракты с фиксированной ценой.", "analysis", None)]),
    dict(id="rental_up", divisions=["68"], need=["real_estate"], any_of=[], direction="opportunity", severity="high",
         need_text=[r"вакантн|дефицит\w*\s+(склад|площад|офис|помещен)|арендн\w*\s+ставк[^.]{0,60}" + UP_RE + "|" + UP_RE + r"\w*[^.]{0,40}арендн\w*\s+ставк"],
         title="Рост арендных ставок может поддержать доходы арендодателя",
         text="В событии говорится о дефиците площадей или росте арендных ставок. Компания управляет недвижимостью (ОКВЭД {okved}){region_part}: если тенденция касается её сегмента, это возможность индексировать ставки при продлении договоров. Сдерживающий фактор — дорогое заёмное финансирование нового строительства.",
         tags=["deposit_opportunity"], horizon="6–12 месяцев",
         actions=[("Пересмотреть индексацию арендных ставок при продлении договоров", "Сверить с рыночными ставками.", "analysis", None)]),
    dict(id="taxes_reporting", divisions=["*"], need=["taxes"], any_of=[], direction="risk", severity="medium",
         need_text=[r"\bндс\b|налогов\w*\s+деклар|налогов\w*\s+отчетн|деклараци",
                    r"(нов\w*|измен\w*|поправк|законопроект|вводит|вступ\w*\s+в\s+силу|формат)[^.]{0,80}(ндс|деклар|отчетн)|(ндс|деклар|отчетн)\w*[^.]{0,80}(измен|поправк|нов\w*\s+формат|вступ)"],
         title="Изменения в налоговой отчётности потребуют доработки учёта",
         text="В событии говорится об изменениях в налоговой отчётности. Бухгалтерии стоит проверить, затрагивают ли они компанию, и при необходимости обновить учётные системы и регламенты. Компании с большим числом контрагентов{fts_part} чаще попадают под автоматическую сверку данных.",
         horizon="по срокам из сообщения", role_boost=["chief_accountant", "cfo"],
         actions=[("Составить план обновления учётных систем и регламентов", "Проверить готовность к изменениям, о которых говорится в событии.", "analysis", None)]),
    dict(id="gold_note", divisions=["*"], need=["gold"], any_of=[], direction="neutral", severity="low", need_text=[r"золот"], anchor="gold_fed",
         title="Рынок золота: ориентир для политики резервов", company_specific=False, hypothesis=True, confidence="low",
         text="Для компании без операций с драгоценными металлами прямой эффект ограничен. Для казначейства это ориентир по защитным активам{anchor_part}. Это справочная информация, а не рекомендация.",
         horizon="справочно", actions=[]),
]


def lens_playbooks(c: Ctx) -> list[Finding]:
    out = []
    hint = c.hint()
    for pb in PLAYBOOKS:
        if not c.in_division(pb["divisions"]):
            continue
        if pb["need"] and not all(t in c.topics for t in pb["need"]):
            continue
        if pb["any_of"] and not c.has(*pb["any_of"]):
            continue
        if pb.get("need_hint") and hint != pb["need_hint"]:
            continue
        need_text = pb.get("need_text") or []
        if any(not c.text_has(p) for p in ([need_text] if isinstance(need_text, str) else need_text)):
            continue                      # утверждения сценария должны опираться на текст самого события
        pct = c.pct_phrase()
        anc, eanc = c.anchor(pb["anchor"]) if pb.get("anchor") else (None, None)
        txt = pb["text"].format(
            anchor_part=(f"; в обзоре банка: {_lc(anc['summary']).rstrip('.')}" if anc else ""),
            okved=c.okved, region=c.region or "", pct_part=f"на {pct}" if pct else "заметно",
            countries_part=(f"; в данных ФТС у неё есть торговля со странами: {_ru_list(c.countries)}" if c.countries else ""),
            countries_part2=(f" (в том числе импорт из стран: {_ru_list(c.countries)})" if c.countries else ""),
            region_part=(f"; событие относится к региону компании ({c.region})" if c.region_hit() else ""),
            fts_part=(" и операциями внешней торговли" if c.countries else ""))
        sev = pb["severity"]
        if pb.get("role_boost") and c.role in pb["role_boost"] and sev != "high":
            sev = "high" if c.role == "chief_accountant" else sev
        if c.region_hit() and sev == "medium":
            sev = "high"
        ev = c.news_ev() + ([eanc] if eanc else [])
        feats = [{"code": "industry", "level": c.okved, "rule_id": pb["id"]}]
        if pb["id"] == "auto_import_cost" and c.level("fx_and_trade_exposure") != "none":
            feats.append(c.feat("fx_and_trade_exposure"))
            fe = c.fev("fx_and_trade_exposure")
            ev = ev + ([fe] if fe else [])
        out.append(Finding("sector:" + pb["id"], pb["direction"], sev, pb["title"], txt, ev, feats, pb.get("confidence", "medium"), pb.get("horizon", "1–3 месяца"),
                           hypothesis=pb.get("hypothesis", False), tags=pb.get("tags", []),
                           actions=[_act(*a) for a in pb.get("actions", [])], company_specific=pb.get("company_specific", True)))
    return out


# =========================================================================== прямое касание отрасли и цепочка поставок
def lens_industry(c: Ctx, have_sector: bool) -> list[Finding]:
    out = []
    if not c.item or (c.item.get("kind") == "news" and not c.item.get("econ", True)):
        return out                        # упоминание отрасли без экономической сути («уничтожено N автомобилей») — не вывод
    pref = c.item["industries"]["okved_prefixes"]
    direct = [p for p in pref if p in c.levels]
    # сдвиг на рынке отрасли (цены, спрос, выпуск, поставки), а не её упоминание: «очередь грузовиков на границе» — не новость
    # для автодилера, «бумаги в Ломбардном списке» — не новость для оптовиков топлива
    shift = c.item.get("kind") != "news" or bool(MARKET_SHIFT_RE.search(lead(c.title, c.text)))
    if direct and not have_sector and shift:
        txt = (f"Событие напрямую относится к отрасли компании (ОКВЭД {c.okved} входит в {max(direct, key=len)}). "
               "Готового отраслевого сценария для такого типа события нет, поэтому оценка общая: проверьте влияние на цены, контракты и спрос.")
        out.append(Finding("industry", "neutral", "medium", "Событие касается вашей отрасли", txt, c.news_ev(), [{"code": "industry", "level": c.okved, "rule_id": "okved_levels"}],
                           "low", "1–3 месяца", hypothesis=True))
    for m in (c.supply[:1] if shift else []):
        share = (m.get("share_of_known") or 0) * 100
        if share < SUPPLY_MIN_SHARE_PCT:
            continue                      # доля в пару процентов оборота — не повод для отдельного вывода
        who = "поставщиков" if m["direction"] == "suppliers" else "покупателей"
        txt = (f"По платежам, видимым банку, {ru_num(share, 0)}% известного оборота приходится на {who} из отрасли ОКВЭД {m['okved_code']}, которой касается событие. "
               f"Если отрасль {who} столкнётся с ростом затрат или перебоями, возможны изменения цен, сроков поставок или оплаты (гипотеза: характер связей по платежам определить нельзя).")
        ev = c.news_ev() + [x for x in (c.fev("supply_chain_industries"),) if x] + [c.ev.calc(f"sc_{m['okved_code']}_{m['direction']}", f"{ru_num(share, 0)}% известных платежей — {who}, ОКВЭД {m['okved_code']}", [round(share), share])]
        out.append(Finding("supply_chain", "risk", "medium" if share >= 30 else "low", "Событие затрагивает отрасль ваших контрагентов", txt, ev,
                           [c.feat("supply_chain_industries")], "low", "3–6 месяцев", hypothesis=True, tags=["counterparty"],
                           actions=[_act("Проверить зависимость от крупнейших контрагентов отрасли", "Оценить сроки оплаты и альтернативных поставщиков.", "analysis")]))
    return out


LENSES = [lens_rate, lens_fx, lens_payroll, lens_demand, lens_macro]


def run_lenses(c: Ctx) -> list[Finding]:
    res: list[Finding] = []
    for lens in LENSES:
        res.extend(lens(c))
    sector = lens_playbooks(c)
    res.extend(sector)
    res.extend(lens_industry(c, bool(sector)))
    # общий резерв: тема входит в чувствительные для компании, но специального сценария нет
    if not any(f.company_specific for f in res) and c.item:
        top = sorted(((t, w) for t, w in ((x["topic"], x["weight"]) for x in c.profile["topics"]) if t in c.topics), key=lambda x: -x[1])[:2]
        if top:
            txt = ("Тема события входит в чувствительные для компании (" + topics_ru(t for t, _ in top) + "), но специального сценария для неё нет. "
                   "Прямое влияние по имеющимся данным оценить нельзя: рекомендуем проверить, как событие отражается на ценах, контрактах и спросе в вашем бизнесе.")
            res.append(Finding("generic", "neutral", "low", "Тема важна для компании, оценка общая", txt, c.news_ev(), [], "low", "—", hypothesis=True))
    top_topic = max(c.topics, key=lambda t: c.topics[t]) if c.topics else None
    trig = {"rate": RATE_TOPICS, "deposit": RATE_TOPICS, "fx": FX_TOPICS, "fx_payments": FX_TOPICS, "payroll": {"labor_market", "wage_inflation"},
            "demand": {"consumer_demand", "retail", "consumer_credit", "auto_market", "tourism"}}

    def prio(f: Finding) -> int:
        base = f.lens.split(":")[0]
        if base == "sector":
            return 0
        if base in trig:
            return 1 if top_topic in trig[base] else 2
        return 3 if base in ("macro", "generic") else 2

    # Линза сработала на побочной теме материала (не из двух главных) — вывод вторичный: значимость на ступень ниже,
    # и он не определяет тип карточки. Иначе почти любой обзор с упоминанием ставки становится «риском».
    mx = max(c.topics.values()) if c.topics else 0.0
    down = {"high": "medium", "medium": "low", "low": "low"}
    for f in res:
        base = f.lens.split(":")[0]
        if c.item and base in trig and mx:
            strength = max((c.topics.get(t, 0) / mx for t in trig[base]), default=0)
            if strength < 0.6:
                f.severity = down[f.severity]
                f.tags.append("secondary")
    res.sort(key=lambda f: (-SEV_ORDER[f.severity], prio(f), f.direction != "risk"))
    return res
