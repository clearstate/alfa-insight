"""Производные признаки (sensitivity_factors) — детерминированные правила из feature_rules.yaml.

Каждый признак: code, level, claim_type="inference", rule_id, rationale, based_on (поля-источники),
confidence, topics, details. LLM здесь не используется.
level: high | medium | low | none | unknown | info (info — описательный признак без шкалы).
Признаки описывают *через что* событие может касаться компании, а не утверждают ущерб или выгоду.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .attrs import evidence
from .okved import OkvedDirectory, OkvedInfo, matches_prefix

CONFIG_DIR = Path(__file__).parent / "config"
_LEVEL_ORDER = {"unknown": -1, "none": 0, "low": 1, "medium": 2, "high": 3}
_DOWNGRADE = {"high": "medium", "medium": "low", "low": "low"}


def _pct(share: float | None) -> str:
    return "нет данных" if share is None else f"{share * 100:.0f}%"


def country_title(name: str) -> str:
    """Страна из FTS_COUNTRY_NAME для текста: «КИТАЙ» -> «Китай», «ЮЖНАЯ КОРЕЯ» -> «Южная Корея»,
    «БОСНИЯ И ГЕРЦЕГОВИНА» -> «Босния и Герцеговина»; аббревиатуры (ОАЭ, США) — как есть."""
    if len(name) <= 3:
        return name
    if name == "КОТ Д'ИВУАР":
        return "Кот-д’Ивуар"
    return " ".join(w.lower() if w == "И" else "-".join(p.capitalize() for p in w.split("-")) for w in name.split())




# продукты в текстах обоснований (коды продуктов — в details.products_present)
PRODUCT_TITLES_RU = {"rko": "расчётно-кассовое обслуживание", "loans": "кредиты", "leasing": "лизинг", "deposits": "депозиты",
                     "payroll_project": "зарплатный проект", "guarantees": "банковские гарантии", "factoring": "факторинг"}


def load_rules(path: str | Path | None = None) -> dict:
    path = Path(path) if path else CONFIG_DIR / "feature_rules.yaml"
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class EdgeInfo:
    counterparty_id: str
    pay_amt: float
    pay_cnt: int
    share: float
    known: bool
    okved: OkvedInfo | None
    region: str | None
    source_line: int


@dataclass
class DirectionSummary:
    total_amt: float = 0.0
    total_cnt: int = 0
    n_counterparties: int = 0
    known_amt: float = 0.0
    edges: list[EdgeInfo] = field(default_factory=list)

    @property
    def known_coverage(self) -> float | None:
        return None if self.total_amt <= 0 else self.known_amt / self.total_amt


@dataclass
class CompanyInput:
    company_id: str
    row: dict[str, Any]
    line: int
    companies_file: str
    payments_file: str
    okved: OkvedInfo | None
    issue_codes: set[str]
    incoming: DirectionSummary
    outgoing: DirectionSummary


class FeatureEngine:
    def __init__(self, rules: dict):
        self.rules = rules
        self.thr = rules["thresholds"]
        self.fcfg = rules["factors"]
        self.products = rules["products"]  # CSV field -> code
        self.product_field = {v: k for k, v in self.products.items()}
        self.okved_dir = OkvedDirectory(rules["okved_sections"])
        self.industry_rules = rules.get("industry_topics", [])
        self.ownership = {k: set(v) for k, v in rules.get("ownership", {}).items()}

    # --- отрасль ------------------------------------------------------------
    def industry_topics(self, okved: OkvedInfo | None) -> list[dict]:
        if okved is None:
            return []
        out = []
        for rule in self.industry_rules:
            hit = matches_prefix(okved.levels, rule["okved_prefixes"])
            if hit:
                out.append({"rule_id": rule["id"], "matched_prefixes": hit, "topics": list(rule["topics"])})
        return out

    def ownership_type(self, okfs: str | None) -> str | None:
        if okfs is None:
            return None
        for kind, names in self.ownership.items():
            if okfs in names:
                return kind
        return None

    # --- признаки -----------------------------------------------------------
    def compute(self, c: CompanyInput) -> list[dict]:
        return [
            self._rate_sensitivity(c),
            self._deposit_income(c),
            self._fx_and_trade(c),
            self._payroll(c),
            self._consumer(c),
            self._concentration(c),
            self._supply_chain(c),
        ]

    def _ev(self, c: CompanyInput, fld: str) -> dict:
        return evidence(c.companies_file, c.line, fld, c.row.get(fld))

    def _product_confidence(self, c: CompanyInput) -> str:
        # Смысл флагов продуктов у PROSPECT/CLOSE_CLIENT не подтверждён (вопрос 5 к организаторам).
        return "medium" if c.row.get("CL_TYPE") == "CLIENT" else "low"

    def _factor(self, code: str, level: str, rationale: str, based_on: list[dict], confidence: str,
                topics: list[str] | None = None, details: dict | None = None) -> dict:
        cfg = self.fcfg[code]
        return {
            "code": code,
            "level": level,
            "claim_type": "inference",
            "rule_id": cfg["rule_id"],
            "rationale": rationale,
            "based_on": based_on,
            "confidence": confidence,
            "topics": list(cfg.get("topics", [])) if topics is None else topics,
            "details": details or {},
        }

    def _products_state(self, c: CompanyInput, codes: list[str]) -> dict[str, bool | None]:
        return {code: c.row.get(self.product_field[code]) for code in codes}

    def _rate_sensitivity(self, c: CompanyInput) -> dict:
        cfg = self.fcfg["rate_sensitivity"]
        high, medium = cfg["high_if_any"], cfg["medium_if_any"]
        state = self._products_state(c, high + medium)
        ev = [self._ev(c, self.product_field[p]) for p in high + medium]
        present = [p for p, v in state.items() if v is True]
        if any(state[p] is True for p in high):
            level = "high"
        elif any(state[p] is True for p in medium):
            level = "medium"
        elif all(v is False for v in state.values()):
            level = "none"
        else:
            level = "unknown"
        if level in ("high", "medium"):
            why = (f"Есть продукты с процентной/кредитной составляющей ({', '.join(PRODUCT_TITLES_RU.get(p, p) for p in present)}): изменения ключевой "
                   "ставки и условий кредитования влияют на стоимость обслуживания и рефинансирования. "
                   "Тип ставки (фиксированная/плавающая) и объём долга в данных неизвестны.")
        elif level == "none":
            why = "Кредитных, лизинговых, гарантийных и факторинговых продуктов в данных нет."
        else:
            why = "Часть флагов продуктов не заполнена — чувствительность к ставке не определена."
        return self._factor("rate_sensitivity", level, why, ev, self._product_confidence(c),
                            details={"products_present": present})

    def _deposit_income(self, c: CompanyInput) -> dict:
        v = c.row.get(self.product_field["deposits"])
        level = {True: "medium", False: "none"}.get(v, "unknown")
        why = {
            "medium": "Есть депозитные продукты: изменение ставок по депозитам меняет процентный доход.",
            "none": "Депозитных продуктов в данных нет.",
            "unknown": "Флаг депозитов не заполнен.",
        }[level]
        return self._factor("deposit_income", level, why, [self._ev(c, "CL_PRODUCT_DEP_MARK")],
                            self._product_confidence(c))

    def _countries(self, c: CompanyInput) -> list[str]:
        raw = c.row.get("FTS_COUNTRY_NAME")
        if not raw:
            return []
        return [x.strip() for x in str(raw).split(",") if x.strip()]

    def _fx_and_trade(self, c: CompanyInput) -> dict:
        cfg = self.fcfg["fx_and_trade_exposure"]
        flag = c.row.get("FTS_FLAG")
        countries = self._countries(c)
        own = self.ownership_type(c.row.get("OKFS_NAME"))
        ev = [self._ev(c, "FTS_FLAG"), self._ev(c, "FTS_COUNTRY_NAME"), self._ev(c, "OKFS_NAME")]
        inconsistent = "fts_inconsistent" in c.issue_codes
        if flag is True or countries:
            level = "high"
            why = ("Компания есть в данных ФТС (внешнеэкономическая деятельность)"
                   + (f", страны: {', '.join(country_title(x) for x in countries)}" if countries else "")
                   + ": курсы валют, санкции и логистика могут влиять на расчёты и поставки. "
                     "Направление (импорт/экспорт) в данных неизвестно.")
        elif own == "foreign":
            level = cfg.get("foreign_ownership_level", "low")
            why = "Данных ФТС нет, но форма собственности иностранная — возможна косвенная валютная экспозиция."
        elif flag is False:
            level = "none"
            why = "Данных о ВЭД в ФТС нет."
        else:
            level = "unknown"
            why = "Флаг ФТС не заполнен."
        conf = "low" if inconsistent else "medium"
        if inconsistent:
            why += " Внимание: флаг ФТС и список стран в данных противоречат друг другу."
        return self._factor("fx_and_trade_exposure", level, why, ev, conf,
                            details={"countries": countries, "direction": None, "fts_inconsistent": inconsistent,
                                     "ownership_type": own})

    def _payroll(self, c: CompanyInput) -> dict:
        cfg = self.fcfg["payroll_exposure"]
        grade = c.row.get("AMOUNT_WORKERS_FNS_GRADATION")
        zpp = c.row.get("CL_PRODUCT_ZPP_MARK")
        ev = [self._ev(c, "AMOUNT_WORKERS_FNS_GRADATION"), self._ev(c, "CL_PRODUCT_ZPP_MARK")]
        base = cfg["workers_levels"].get(grade) if grade else None
        if base is None:
            return self._factor("payroll_exposure", "unknown", "Численность по ФНС не заполнена или не распознана.",
                                ev, "low", details={"workers_fns": grade, "payroll_project": zpp})
        level = base if zpp is True else _DOWNGRADE[base]
        why = (f"Численность по ФНС: {grade[:1].lower() + grade[1:]}"         # «Более 251» -> «более 251»
               + ("; есть зарплатный проект" if zpp is True else "")
               + ". Рынок труда и рост зарплат влияют на фонд оплаты труда.")
        return self._factor("payroll_exposure", level, why, ev, "medium",
                            details={"workers_fns": grade, "payroll_project": zpp})

    def _consumer(self, c: CompanyInput) -> dict:
        cfg = self.fcfg["consumer_exposure"]
        ev = [self._ev(c, "MAINOKVED_CODE")]
        if c.okved is None:
            return self._factor("consumer_exposure", "unknown", "Код ОКВЭД отсутствует или некорректен.", ev, "low")
        hit = matches_prefix(c.okved.levels, cfg["okved_prefixes"])
        if hit:
            why = (f"Основной ОКВЭД {c.okved.code} относится к потребительскому сектору: "
                   "динамика потребительского спроса и инфляции может существенно влиять на выручку.")
            return self._factor("consumer_exposure", "high", why, ev, "medium", details={"matched_prefixes": hit})
        return self._factor("consumer_exposure", "none",
                            "Основной ОКВЭД не относится к потребительскому сектору (по правилам конфига).", ev,
                            "medium")

    def _direction_concentration(self, d: DirectionSummary) -> dict:
        thr = self.thr["concentration"]
        if d.n_counterparties == 0 or d.total_amt <= 0:
            return {"level": "unknown", "n_counterparties": 0, "top1_share": None, "top1_counterparty_id": None}
        top = d.edges[0]
        if d.n_counterparties < thr["min_counterparties"]:
            level = "unknown"
        elif top.share >= thr["top1_share_high"]:
            level = "high"
        elif top.share >= thr["top1_share_medium"]:
            level = "medium"
        else:
            level = "low"
        return {"level": level, "n_counterparties": d.n_counterparties, "top1_share": round(top.share, 4),
                "top1_counterparty_id": top.counterparty_id}

    def _concentration(self, c: CompanyInput) -> dict:
        thr = self.thr["concentration"]
        inc, out = self._direction_concentration(c.incoming), self._direction_concentration(c.outgoing)
        levels = [x["level"] for x in (inc, out)]
        level = max(levels, key=lambda lv: _LEVEL_ORDER[lv])
        ev = [{"source_file": c.payments_file, "source_row_id": None, "source_field": "PAY_AMT",
               "value": "суммы по контрагентам, переводы самой себе исключены"}]
        if level == "unknown":
            why = (f"Видимых банку контрагентов меньше {thr['min_counterparties']} или платежей нет — "
                   "концентрацию оценить нельзя.")
        else:
            why = ("Эвристика: доля крупнейшего контрагента в видимом банку обороте "
                   f"(входящие: {_pct(inc['top1_share'])}, исходящие: {_pct(out['top1_share'])}). "
                   "Это не доказательство зависимости: банк видит только часть платежей (с 1 января, дата среза неизвестна).")
        return self._factor("counterparty_concentration", level, why, ev, "low",
                            details={"incoming": inc, "outgoing": out,
                                     "thresholds": {k: thr[k] for k in ("top1_share_high", "top1_share_medium",
                                                                       "min_counterparties")}})

    def _industry_mix(self, d: DirectionSummary) -> list[dict]:
        """Сводка по классам ОКВЭД (2 цифры) — формат 0.2.0 сохранён без изменений."""
        by_div: dict[str, dict] = {}
        for e in d.edges:
            if not e.known or e.okved is None:
                continue
            key = e.okved.division
            item = by_div.setdefault(key, {"okved_division": key, "okved_section": e.okved.section,
                                           "okved_section_name": e.okved.section_name, "pay_amt": 0.0,
                                           "n_counterparties": 0, "example_okved_codes": []})
            item["pay_amt"] += e.pay_amt
            item["n_counterparties"] += 1
            if len(item["example_okved_codes"]) < 3 and e.okved.code not in item["example_okved_codes"]:
                item["example_okved_codes"].append(e.okved.code)
        total_known = sum(x["pay_amt"] for x in by_div.values())
        items = sorted(by_div.values(), key=lambda x: (-x["pay_amt"], x["okved_division"]))
        items = items[: self.thr["supply_chain"]["top_industries"]]
        for x in items:
            x["share_of_known"] = round(x["pay_amt"] / total_known, 4) if total_known else None
        return items

    @staticmethod
    def _known_with_okved(d: DirectionSummary) -> list[EdgeInfo]:
        return [e for e in d.edges if e.known and e.okved is not None]

    def _code_mix(self, d: DirectionSummary) -> dict:
        """Детализация по полным кодам ОКВЭД контрагентов (с 0.3.0). Агрегация по коду, без id контрагентов."""
        edges = self._known_with_okved(d)
        total = sum(e.pay_amt for e in edges)
        by_code: dict[str, dict] = {}
        for e in edges:
            item = by_code.setdefault(e.okved.code, {
                "okved_code": e.okved.code, "okved_levels": list(e.okved.levels),
                "okved_division": e.okved.division, "okved_section": e.okved.section,
                "pay_amt": 0.0, "pay_cnt": 0, "n_counterparties": 0,
            })
            item["pay_amt"] += e.pay_amt
            item["pay_cnt"] += e.pay_cnt
            item["n_counterparties"] += 1
        items = sorted(by_code.values(), key=lambda x: (-x["pay_amt"], x["okved_code"]))
        for x in items:
            x["share_of_known"] = round(x["pay_amt"] / total, 4) if total else None
        limit = self.thr["supply_chain"]["top_codes"]
        kept = items[:limit]
        omitted_amt = sum(x["pay_amt"] for x in items[limit:])
        return {
            "codes": kept,
            "n_codes": len(items),
            "truncated": len(items) > limit,
            "omitted_share_of_known": round(omitted_amt / total, 4) if total else None,
        }

    def _rule_shares(self, d: DirectionSummary) -> dict[str, float]:
        """Доля известного оборота, у которой ОКВЭД контрагента совпал с префиксами правила (по уровням)."""
        edges = self._known_with_okved(d)
        total = sum(e.pay_amt for e in edges)
        if total <= 0:
            return {}
        out = {}
        for rule in self.industry_rules:
            amt = sum(e.pay_amt for e in edges if matches_prefix(e.okved.levels, rule["okved_prefixes"]))
            if amt > 0:
                out[rule["id"]] = amt / total
        return out

    def _supply_chain(self, c: CompanyInput) -> dict:
        min_cov = self.thr["supply_chain"]["min_known_coverage"]
        min_share = self.thr["supply_chain"]["min_share_for_topics"]
        suppliers, customers = self._industry_mix(c.outgoing), self._industry_mix(c.incoming)
        sup_codes, cus_codes = self._code_mix(c.outgoing), self._code_mix(c.incoming)
        cov_out, cov_in = c.outgoing.known_coverage, c.incoming.known_coverage
        rule_topics = {r["id"]: r["topics"] for r in self.industry_rules}
        rule_shares: dict[str, float] = {}
        for d in (c.outgoing, c.incoming):
            for rid, share in self._rule_shares(d).items():
                rule_shares[rid] = max(rule_shares.get(rid, 0.0), share)
        topic_shares: dict[str, float] = {}
        for rid, share in rule_shares.items():
            if share < min_share:
                continue
            for t in rule_topics[rid]:
                topic_shares[t] = max(topic_shares.get(t, 0.0), share)
        topics = sorted(topic_shares, key=lambda t: (-topic_shares[t], t))
        ev = [{"source_file": c.payments_file, "source_row_id": None, "source_field": "PAYER/BENEFICIARY",
               "value": "ОКВЭД контрагента из файла юрлиц"}]
        details = {
            "suppliers": suppliers, "customers": customers,
            "supplier_codes": sup_codes["codes"], "customer_codes": cus_codes["codes"],
            "supplier_codes_meta": {k: v for k, v in sup_codes.items() if k != "codes"},
            "customer_codes_meta": {k: v for k, v in cus_codes.items() if k != "codes"},
            "rule_shares": {k: round(v, 4) for k, v in sorted(rule_shares.items())},
            "topic_shares": {t: round(v, 4) for t, v in topic_shares.items()},
            "known_coverage_outgoing": None if cov_out is None else round(cov_out, 4),
            "known_coverage_incoming": None if cov_in is None else round(cov_in, 4),
        }
        if not suppliers and not customers:
            return self._factor("supply_chain_industries", "unknown",
                                "Нет контрагентов с известным ОКВЭД — отрасли цепочки поставок неизвестны.", ev,
                                "low", topics=[], details=details)
        low_cov = any(cv is not None and cv < min_cov for cv in (cov_out, cov_in))
        why = ("Отрасли контрагентов по ОКВЭД (получатели исходящих платежей — вероятные поставщики, "
               "плательщики входящих — вероятные покупатели). Новости этих отраслей могут касаться компании "
               "через цепочку поставок. Учтены только контрагенты, присутствующие в данных.")
        return self._factor("supply_chain_industries", "info", why, ev, "low" if low_cov else "medium",
                            topics=topics, details=details)
