"""Анализ влияния события на конкретную компанию: «линзы» (ставка, курс, ФОТ, спрос, отрасль, цепочка поставок, налоги и др.).

Каждая линза берёт признаки профиля (sensitivity_factors, ОКВЭД, регион, ВЭД), темы события и позиции/прогнозы банка и
возвращает Finding со ссылками на доказательства. Тексты собираются из проверяемых данных; числа берутся только из
доказательств (проверяется в agent.verify). Если данных не хватает — выводы помечаются гипотезой и снижается уверенность.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .evidence import EvidenceBook
from .textkit import (direction_hint, fold, fx_stance, key_rate_values, pct_values, rate_stance, ru_date, ru_num, short)

PRODUCT_RU = {"rko": "расчётно-кассовое обслуживание", "loans": "кредиты", "leasing": "лизинг", "deposits": "депозиты",
              "guarantees": "банковские гарантии", "factoring": "факторинг", "payroll_project": "зарплатный проект"}
SEV_ORDER = {"high": 3, "medium": 2, "low": 1}
FX_TOPICS = {"fx_rates", "foreign_trade", "sanctions", "export", "import_substitution"}
RATE_TOPICS = {"key_rate", "credit_conditions", "bond_market", "liquidity", "deposit_rates", "financial_regulation", "consumer_credit", "mortgage"}
MACRO_COMPANY_FEATURES = {"macro", "generic"}


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


def _act(title: str, text: str, kind: str = "analysis", product: str | None = None) -> dict:
    return {"title": title, "text": text, "kind": kind, "product": product}


def _ru_list(items: list[str]) -> str:
    return ", ".join(i if len(i) <= 3 else i.capitalize() for i in items)


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
    ratekey = c.has("key_rate", "bond_market")

    if rs_level in ("high", "medium"):
        sev = "high" if rs_level == "high" else "medium"
        evs = ev + c.news_ev() + ([e5] if e5 else []) + [x for x in (c.fev("rate_sensitivity"),) if x]
        base = (f"У компании есть продукты с процентной нагрузкой в банке ({', '.join(prod) or 'кредитные продукты'}). ")
        if stance == "hike":
            title = "Повышение ставки удорожает обслуживание долга"
            txt = base + ("Если ставка вырастет, проценты по плавающим кредитам и лизингу вырастут вслед за ней" +
                          (f"; сейчас банк прогнозирует {now}% до конца 2026 г." if now else "") + ". ")
            direction = "risk"
        elif stance == "cut":
            title = "Снижение ставки удешевляет заёмное финансирование"
            txt = base + "Снижение ставки уменьшит расходы на обслуживание плавающих кредитов и лизинга и улучшит условия рефинансирования. "
            direction, sev = "opportunity", "medium"
        elif ratekey:
            title = "Деньги остаются дорогими: нагрузка по кредитам не снизится"
            txt = base + (f"Банк ожидает, что ключевая ставка сохранится на уровне {now}% до конца 2026 г. и снизится до {nxt}% только к концу 2027 г.: " if now and nxt else "Ставка остаётся высокой: ") + \
                  "расходы на обслуживание кредитов и лизинга в ближайшие месяцы не уменьшатся. "
            direction = "risk"
        else:
            title = "Условия кредитования могут стать жёстче"
            txt = base + "Банки внимательнее оценивают кредитное качество и закредитованность заёмщиков: новые кредиты и рефинансирование могут стать дороже и потребовать больше обеспечения. "
            direction = "risk"
            a, ea = c.anchor("bank_credit_quality")
            b, eb = c.anchor("corp_credit_growth")
            evs += [x for x in (ea, eb) if x]
        if flo and ratekey:
            txt += "В банковской аналитике отмечено, что 67% корпоративных кредитов выдано по плавающей ставке, и процентный риск лежит на заёмщике. "
        calc = c.ev.calc("rate_100m", "Ориентир: 100 млн ₽ долга × 1 п.п. = 1 млн ₽ процентов в год", [100, 1])
        txt += "Ориентир для расчёта: на каждые 100 млн ₽ долга по плавающей ставке изменение ставки на 1 п.п. меняет проценты примерно на 1 млн ₽ в год (объём и тип ставки у компании в данных банка неизвестны, проверьте по договорам)."
        evs.append(calc)
        out.append(Finding("rate", direction, sev, title, txt, evs, [c.feat("rate_sensitivity")], "medium" if rs_level == "high" else "low",
                           "до конца 2026 г.", hypothesis=unconf, tags=["rate_risk"],
                           actions=[_act("Сверить тип ставки и график платежей по кредитам и лизингу", "Определить, какая часть долга привязана к ключевой ставке, и рассчитать нагрузку при ставке 14% до конца 2026 г. и 12% на конец 2027 г. (прогноз банка).", "analysis"),
                                    _act("Обсудить с менеджером фиксацию ставки или рефинансирование", "Если процентная нагрузка существенна для бюджета.", "product", "rate_risk")],
                           scenarios=[{"name": "Базовый (прогноз банка)", "condition": "Пауза 23 октября, ставка 14,0% до конца года", "effect": "Расходы на проценты остаются на текущем уровне"},
                                      {"name": "Ужесточение", "condition": "ЦБ сигнализирует о возможности повышения", "effect": "Рост процентных расходов по плавающей части долга"}]))
    di = c.level("deposit_income")
    if di in ("high", "medium") and c.has("key_rate", "deposit_rates", "bond_market", "liquidity"):
        a, ea = c.anchor("cbr_dates")
        evs = ev + c.news_ev() + [x for x in (ea, c.fev("deposit_income")) if x]
        txt = ("У компании есть депозитные продукты. Пока ключевая ставка остаётся высокой" + (f" ({now}%)" if now else "") +
               ", краткосрочные размещения свободных средств остаются доходными. Ближайшее заседание ЦБ — 23 октября, банк ждёт паузы: это ориентир для выбора срока размещения. "
               + (f"Если ставка снизится к концу 2027 г. до {nxt}% (прогноз банка), доходность новых размещений будет ниже, поэтому срок стоит согласовать с платёжным календарём." if nxt else ""))
        out.append(Finding("deposit", "opportunity", "medium" if di == "high" else "low", "Высокая ставка поддерживает доходность размещения средств", txt, evs,
                           [c.feat("deposit_income")], "medium", "до конца 2026 г.", tags=["deposit_opportunity"],
                           actions=[_act("Подобрать срок размещения свободных остатков", "Сопоставить срок с платёжным календарём и датой заседания ЦБ.", "product", "deposit_opportunity")]))
    if not out:
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
    sev = {"high": "high", "medium": "medium", "low": "low", "none": "low"}[lvl]
    if c.has("fx_rates") and lvl != "none":
        fc = (f"Банк прогнозирует USD/RUB {ru_num(u26['value'])} на конец 2026 г. и {ru_num(u27['value'])} на конец 2027 г., "
              f"CNY/RUB — {ru_num(c26['value'])} и {ru_num(c27['value'])}: ожидается постепенное ослабление рубля. " if (u26 and u27 and c26 and c27) else "")
        m = re.search(r"юан\w*[^.]{0,60}?(\d{1,2}[.,]\d+)", fold(c.title + " " + c.text))
        cross = ""
        if m and c26:
            v = float(m.group(1).replace(",", "."))
            if v > c26["value"] * 1.01:
                cross = f"Курс юаня из сообщения ({ru_num(v)}) уже выше прогноза банка на конец года ({ru_num(c26['value'])}), поэтому закладывать в расчёты стоит более слабый рубль. "
        head = ("Рубль слабеет: растёт стоимость импорта" if stance == "rub_weaker" else "Рубль укрепляется: импорт дешевеет" if stance == "rub_stronger" else "Курсовые изменения влияют на расчёты по ВЭД")
        txt = ("Компания присутствует в данных ФТС" + (f" (страны: {ctry})" if ctry else "") + ", но направление операций (импорт или экспорт) в данных не указано, поэтому знак эффекта зависит от структуры бизнеса. "
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
        china = any(x.upper() == "КИТАЙ" for x in c.countries)
        txt = ("Сообщается, что расчёты с китайскими контрагентами занимают дольше и дороже. " +
               ("Китай входит в страны внешней торговли компании. " if china else "Среди стран внешней торговли компании Китая в данных нет, поэтому эффект возможен лишь косвенно. ") +
               "Рост срока расчётов замораживает оборотный капитал и повышает риск срыва поставок; использование посредников увеличивает комиссии. ")
        out.append(Finding("fx_payments", "risk", "high" if china and lvl == "high" else "medium", "Задержки международных платежей могут сорвать графики поставок", txt,
                           c.news_ev() + ([e5] if e5 else []) + [x for x in (c.fev("fx_and_trade_exposure"),) if x], [c.feat("fx_and_trade_exposure")],
                           "medium" if china else "low", "1–2 месяца", hypothesis=not china, tags=["working_capital_risk", "contract_risk"],
                           actions=[_act("Пересмотреть график платежей и страховой запас", "Заложить увеличенный срок расчётов и проверить альтернативные каналы.", "analysis"),
                                    _act("Обсудить с менеджером решения для расчётов и оборотного капитала", "Факторинг и гарантии под контракты.", "product", "working_capital_risk")]))
    return out


# =========================================================================== фонд оплаты труда
def lens_payroll(c: Ctx) -> list[Finding]:
    if not c.has("labor_market", "wage_inflation"):
        return []
    lvl = c.level("payroll_exposure")
    if lvl == "none":
        return []
    w, e1 = c.ind("wages_nominal", "2026")
    u, e2 = c.ind("unemployment", "2026")
    a1, e3 = c.anchor("labor_market_tight")
    a2, e4 = c.anchor("real_wages")
    ev = [e for e in (e1, e2, e3, e4) if e] + c.news_ev() + [x for x in (c.fev("payroll_exposure"),) if x]
    reg = c.region_hit()
    txt = ("У компании " + (f"численность по данным ФНС: {c.pv['size']['workers_fns']}" if c.pv["size"].get("workers_fns") else "заметный фонд оплаты труда") +
           (" и зарплатный проект в банке" if "payroll_project" in c.products else "") + ". " +
           ("Событие относится к региону компании. " if reg else "") +
           (f"Банк прогнозирует рост номинальных зарплат в 2026 г. на {ru_num(w['value'], 1, strip=True)}%" + (f" при безработице около {ru_num(u['value'])}%" if u else "") + ": " if w else "") +
           "рынок труда остаётся напряжённым, давление на фонд оплаты труда сохранится, а конкуренция за персонал повышает расходы на найм.")
    sev = "high" if (lvl == "high" and reg) else {"high": "medium", "medium": "medium", "low": "low"}[lvl]
    return [Finding("payroll", "risk", sev, "Расходы на персонал продолжат расти", txt, ev, [c.feat("payroll_exposure")], "medium", "6–12 месяцев", tags=["payroll_risk"],
                    actions=[_act("Заложить индексацию ФОТ в бюджет на следующий период", "Использовать прогноз банка по зарплатам как верхний ориентир и сверить с планом найма.", "analysis"),
                             _act("Проверить условия зарплатного проекта и лимиты", "Если фонд оплаты труда растёт быстрее выручки.", "product", "payroll_risk")])]


# =========================================================================== потребительский спрос
def lens_demand(c: Ctx) -> list[Finding]:
    if not c.has("consumer_demand", "retail", "consumer_credit", "auto_market", "tourism"):
        return []
    lvl = c.level("consumer_exposure")
    consumer_div = c.in_division(["47", "56", "55", "45.1", "45.2"])
    if lvl in ("none", "low") and not consumer_div:
        return []
    a1, e1 = c.anchor("consumption_peak")
    a2, e2 = c.anchor("retail_july")
    rt, e3 = c.ind("retail_turnover", "2026")
    ev = [e for e in (e1, e2, e3) if e] + c.news_ev() + [x for x in (c.fev("consumer_exposure"),) if x]
    txt = ("Выручка компании зависит от потребительского спроса. Банк полагает, что потребление на пике, а к четвёртому кварталу 2026 г. рост спроса остановится около нуля; "
           "к охлаждению добавляются жёсткие условия потребительского кредитования. Это означает риск стагнации выручки и давление на чек, если расходы растут быстрее цен.")
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
    parts = []
    if g:
        parts.append(f"рост ВВП в 2026 г. — {ru_num(g['value'], 1)}%")
    if i:
        parts.append(f"инфляция по итогам года — {ru_num(i['value'], 1)}%")
    txt = ("Макрофон для бизнеса сдержанный: " + ", ".join(parts) + ". Слабый рост экономики и высокая инфляция удерживают ставку и ограничивают рост спроса; компаниям стоит планировать бюджет без ставки на быстрое удешевление денег." if parts else
           "Макрофон сдержанный: банк ожидает слабого роста экономики и сохранения высокой ставки.")
    return [Finding("macro", "neutral", "low", "Макрофон: слабый рост и высокая инфляция", txt, ev, [], "medium", "до конца 2026 г.", company_specific=False)]


# =========================================================================== отраслевые сценарии
PLAYBOOKS: list[dict[str, Any]] = [
    dict(id="auto_import_cost", divisions=["45", "29"], need=["auto_market"], any_of=["regulation", "foreign_trade"], direction="risk", severity="high",
         title="Удорожание ввоза комплектующих сожмёт маржу",
         text="Компания работает в автокомпонентах (ОКВЭД {okved}){countries_part}. По сообщениям, себестоимость ввоза может вырасти {pct_part}. Пока закупочные цены и условия контрактов не пересмотрены, маржа оптовой торговли сжимается; быстрее всех это почувствуют позиции с высокой долей импорта.",
         tags=["contract_risk", "fx_risk"], horizon="с 1 ноября",
         actions=[("Пересчитать закупочные цены и прайс на позиции с высокой долей импорта", "Оценить, какую часть роста себестоимости можно переложить на покупателей.", "analysis", None),
                  ("Согласовать с поставщиками условия и сроки до даты вступления изменений", "Рассмотреть увеличение закупок до роста сбора, если позволяют склад и оборотный капитал.", "analysis", None)]),
    dict(id="auto_secondary", divisions=["45"], need=["auto_market"], any_of=["regulation", "foreign_trade", "consumer_credit"], direction="opportunity", severity="medium",
         title="Дорогие новые автомобили могут поддержать спрос на запчасти вторичного рынка",
         text="Участники рынка ожидают, что удорожание новых автомобилей и дорогое автокредитование сместят спрос в сторону обслуживания старых машин. Для оптовой торговли запчастями это возможность нарастить обороты (гипотеза: данных о структуре продаж компании у банка нет).",
         hypothesis=True, confidence="low", horizon="3–6 месяцев",
         actions=[("Проверить складские остатки по ходовым позициям вторичного рынка", "Сопоставить с прогнозом спроса.", "analysis", None)]),
    dict(id="logistics_cost", divisions=["45", "46", "47", "17", "41", "42", "43", "10", "56"], need=[], any_of=["logistics", "fuel_prices"], direction="risk", severity="medium",
         title="Транспорт и доставка дорожают",
         text="В событии говорится о росте стоимости перевозок или топлива. Для компании с ОКВЭД {okved} это повышает расходы цепочки поставок{countries_part2}: если не удастся переложить рост на цены, снизится маржа, а сроки поставок могут увеличиться.",
         confidence="medium", horizon="1–3 месяца", need_hint="up",
         actions=[("Оценить долю транспортных расходов в себестоимости и пересмотреть тарифы", "Сопоставить с контрактами на доставку.", "analysis", None)]),
    dict(id="food_cost", divisions=["56"], need=["food_prices"], any_of=[], direction="risk", severity="high",
         title="Закупки продуктов дорожают быстрее выручки",
         text="Для ресторанного бизнеса продукты — основная статья переменных затрат. Рост оптовых цен на мясо, молочную продукцию и овощи повышает себестоимость блюд; повышать цены меню в условиях стагнации среднего чека рискованно, поэтому давление ляжет на маржу.",
         tags=["demand_risk"], horizon="1–3 месяца",
         actions=[("Пересчитать себестоимость меню и подобрать замены", "Определить позиции, где допустим пересмотр цены или рецептуры.", "analysis", None)]),
    dict(id="food_wholesale", divisions=["46"], need=["food_prices"], any_of=[], direction="mixed", severity="low",
         title="Рост цен на продукты: оборот в рублях растёт, объёмы под вопросом",
         text="Для оптовой торговли удорожание продовольствия увеличивает рублёвый оборот, но может снизить объёмы закупок покупателями и повысить потребность в оборотном капитале. Эффект зависит от доли продовольственных групп в ассортименте (в данных банка не раскрыта).",
         hypothesis=True, confidence="low", horizon="1–3 месяца", actions=[]),
    dict(id="construction_cost", divisions=["41", "42", "43"], need=[], any_of=["commodities", "metals", "construction"], direction="risk", severity="high",
         text_if="up", need_hint="up", title="Стройматериалы дорожают: смета и фиксированные цены контрактов под давлением",
         text="Компания работает в строительстве (ОКВЭД {okved}). Удорожание арматуры, цемента и металлопроката повышает себестоимость объектов, а договоры с фиксированной ценой не покрывают рост затрат. Подрядчики просят пересмотра условий — это повод пересчитать маржу по текущим проектам{region_part}.",
         tags=["contract_risk"], horizon="1–6 месяцев",
         actions=[("Пересчитать маржу по объектам с фиксированной ценой", "Определить контракты, где нужна индексация.", "analysis", None),
                  ("Обсудить гарантии и лимиты под новые контракты", "С учётом роста себестоимости.", "product", "contract_risk")]),
    dict(id="construction_demand", divisions=["41", "42", "43"], need=[], any_of=["mortgage", "real_estate", "construction"], direction="risk", severity="high",
         need_text=r"заморажив|сокращ|снижа|охлажд|упал|приостанав", title="Спрос на новостройки и объём заказов снижаются",
         text="Выдачи ипотеки и спрос на новостройки снижаются, застройщики откладывают проекты{region_part}. Для строительной компании это риск сокращения портфеля заказов в 2027 г. при сохранении высокой стоимости заёмных средств.",
         tags=["demand_risk"], horizon="6–12 месяцев",
         actions=[("Оценить портфель заказов на 2027 г. и зависимость от жилых проектов", "Проверить долю заказчиков с проектным финансированием.", "analysis", None)]),
    dict(id="packaging_inputs", divisions=["17"], need=["commodities"], any_of=[], direction="mixed", severity="medium",
         title="Сырьё для упаковки дорожает, но растут и отпускные цены",
         text="Макулатура и целлюлоза дорожают, а производители гофрокартона повышают отпускные цены. Для компании в производстве гофрированной бумаги и картона (ОКВЭД {okved}) итог зависит от того, насколько быстро удастся переложить рост сырья на покупателей: при задержке маржа сжимается, при успешном повышении цен и высокой загрузке — выигрыш.",
         confidence="medium", horizon="1–3 месяца",
         actions=[("Сопоставить рост цен на сырьё и график повышения отпускных цен", "Определить контракты с фиксированной ценой.", "analysis", None)]),
    dict(id="rental_up", divisions=["68"], need=["real_estate"], any_of=[], need_text=r"аренд|вакантност", direction="opportunity", severity="high",
         title="Дефицит складов и рост ставок поддерживают доходы арендодателя",
         text="Вакантность складских помещений ниже 1%, арендные ставки растут. Компания управляет нежилой недвижимостью (ОКВЭД {okved}){region_part}: это возможность индексировать ставки при продлении договоров. Сдерживающий фактор — дорогое заёмное финансирование нового строительства, которое поддерживает дефицит.",
         tags=["deposit_opportunity"], horizon="6–12 месяцев",
         actions=[("Пересмотреть индексацию арендных ставок при продлении договоров", "Сверить с рыночными ставками.", "analysis", None)]),
    dict(id="taxes_reporting", divisions=["*"], need=["taxes"], any_of=[], direction="risk", severity="medium",
         title="Изменение отчётности по НДС потребует доработки учёта",
         text="Меняются формат декларации и сроки отчётности с 2027 г. Бухгалтерии нужно обновить программное обеспечение и регламенты. Компании с большим числом контрагентов{fts_part} попадают под повышенное внимание при автоматической сверке данных.",
         horizon="до 2027 г.", role_boost=["chief_accountant", "cfo"],
         actions=[("Составить план обновления учётных систем и регламентов", "Проверить готовность к новому формату декларации.", "analysis", None)]),
    dict(id="gold_note", divisions=["*"], need=["gold"], any_of=[], direction="neutral", severity="low",
         title="Золото на максимумах: ориентир для политики резервов", company_specific=False, hypothesis=True, confidence="low",
         text="Для компании без операций с драгоценными металлами прямой эффект ограничен. Для казначейства это ориентир по защитным активам, но банк обращает внимание на риск ужесточения политики ФРС. Это справочная информация, а не рекомендация.",
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
        if pb.get("need_text") and not c.text_has(pb["need_text"]):
            continue
        pct = c.pct_phrase()
        txt = pb["text"].format(
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
        ev = c.news_ev()
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
    if not c.item:
        return out
    pref = c.item["industries"]["okved_prefixes"]
    direct = [p for p in pref if p in c.levels]
    if direct and not have_sector:
        txt = (f"Событие напрямую относится к отрасли компании (ОКВЭД {c.okved} входит в {max(direct, key=len)}). "
               "Готового отраслевого сценария для такого типа события нет, поэтому оценка общая: проверьте влияние на цены, контракты и спрос.")
        out.append(Finding("industry", "neutral", "medium", "Событие касается вашей отрасли", txt, c.news_ev(), [{"code": "industry", "level": c.okved, "rule_id": "okved_levels"}],
                           "low", "1–3 месяца", hypothesis=True))
    for m in c.supply[:1]:
        who = "поставщиков" if m["direction"] == "suppliers" else "покупателей"
        share = (m.get("share_of_known") or 0) * 100
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
            txt = ("Тема события входит в чувствительные для компании (" + ", ".join(t for t, _ in top) + "), но специального сценария для неё нет. "
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

    res.sort(key=lambda f: (-SEV_ORDER[f.severity], prio(f), f.direction != "risk"))
    return res
