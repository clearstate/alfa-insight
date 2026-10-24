"""Сборка company_profile и связанных ответов API.

Источник данных — PostgreSQL (схема company_profile, загружается ETL) или напрямую CSV (локальная разработка, тесты).
При старте нормализованные таблицы читаются в память (pandas + индексы); бизнес-логика одна для обоих источников.
Данные статичны между загрузками, поэтому профиль кешируется после первой сборки.
"""

from __future__ import annotations

import hashlib
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .access import AccessDenied, UserContext, UserStore, authorize, load_roles
from .attrs import fact, inference, row_id, unknown
from .features import CONFIG_DIR, CompanyInput, DirectionSummary, EdgeInfo, FeatureEngine, load_rules
from .loader import load_raw
from .okved import OkvedInfo
from .relationships import RelationshipIndex
from .validation import CleanData, validate

SCHEMA_VERSION = "0.3.0"
log = logging.getLogger("company_profile")


# Выручка: рубли за отчётный 2025 год (ответ организаторов, вебинар, вопрос 14).
REVENUE_PERIOD = "2025"
REVENUE_CONFIRMED = "Подтверждено организаторами кейса (вебинар, вопрос 14): выручка за отчётный 2025 год, в рублях"
# Платежи: суммы и число операций с 1 января (вебинар, вопрос 20); дата среза в данных не указана.
PAYMENTS_PERIOD = "с 1 января (дата среза не указана)"


class CompanyNotFound(Exception):
    pass


class CompanyQuarantined(Exception):
    pass


def _clean(v: Any) -> Any:
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def rules_hash(rules_path: str | Path | None = None) -> str:
    """sha256 файла правил: фиксирует, на каких правилах построена загрузка."""
    path = Path(rules_path) if rules_path else CONFIG_DIR / "feature_rules.yaml"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


class ProfileService:
    def __init__(self, data: CleanData, rules: dict, users: UserStore | None = None,
                 now: Callable[[], datetime] | None = None, *, data_run_id: str | None = None,
                 storage: str = "csv", rules_digest: str | None = None, etl_rules_digest: str | None = None):
        self.data = data
        self.rules = rules
        self.engine = FeatureEngine(rules)
        self.index = RelationshipIndex(data)
        self.users = users or UserStore([])
        self.data_run_id = data_run_id
        self.storage = storage
        self.rules_digest = rules_digest or rules_hash()
        self.etl_rules_digest = etl_rules_digest
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._okved_cache: dict[str, OkvedInfo | None] = {}
        self._profile_cache: dict[str, dict] = {}
        self._group_rev_cache: dict[str, tuple[float | None, int]] = {}

    @classmethod
    def from_data_dir(cls, data_dir: str | Path, rules_path: str | Path | None = None,
                      users_path: str | Path | None = None, roles_path: str | Path | None = None) -> "ProfileService":
        data = validate(load_raw(data_dir))
        users = UserStore.from_json(users_path, load_roles(roles_path)) if users_path else None
        return cls(data, load_rules(rules_path), users, rules_digest=rules_hash(rules_path))

    @classmethod
    def from_store(cls, store, rules_path: str | Path | None = None,
                   roles_path: str | Path | None = None) -> "ProfileService":
        """Загрузка из PostgreSQL/SQLite (последний успешный ETL-прогон)."""
        run = store.latest_run()
        if run is None:
            raise RuntimeError("В хранилище нет успешной загрузки данных: сначала запустите ETL")
        data = store.load_clean_data(run)
        users = UserStore.from_records(store.load_users(), load_roles(roles_path))
        digest = rules_hash(rules_path)
        svc = cls(data, load_rules(rules_path), users, data_run_id=run["run_id"], storage=store.dialect.name,
                  rules_digest=digest, etl_rules_digest=run.get("rules_hash"))
        if svc.etl_rules_digest and svc.etl_rules_digest != digest:
            log.warning("feature_rules.yaml отличается от правил ETL-прогона %s: перезапустите ETL", run["run_id"])
        return svc

    def health(self) -> dict:
        return {
            "status": "ok",
            "schema_version": SCHEMA_VERSION,
            "storage": self.storage,
            "data_run_id": self.data_run_id,
            "companies": int(len(self.data.companies)),
            "quarantined_ids": len(self.data.quarantined),
            "users": len(self.users.all()),
            "rules_hash": self.rules_digest,
            "rules_match_etl": None if self.etl_rules_digest is None else self.etl_rules_digest == self.rules_digest,
        }

    # --- базовое -----------------------------------------------------------
    @property
    def _cf(self) -> str:
        return self.data.files["companies"]

    @property
    def _pf(self) -> str:
        return self.data.files["payments"]

    def _okved(self, code: str | None) -> OkvedInfo | None:
        if code is None:
            return None
        if code not in self._okved_cache:
            self._okved_cache[code] = self.engine.okved_dir.parse(code)
        return self._okved_cache[code]

    def require_company(self, company_id: str) -> dict:
        if company_id in self.data.quarantined:
            raise CompanyQuarantined(company_id)
        if company_id not in self.data.companies.index:
            raise CompanyNotFound(company_id)
        return {k: _clean(v) for k, v in self.data.companies.loc[company_id].to_dict().items()}

    def get_user(self, user_id: str) -> UserContext:
        return self.users.get(user_id)

    def authorize(self, user: UserContext, company_id: str) -> None:
        """404/422 для неизвестного/карантинного id проверяется раньше, затем 403."""
        self.require_company(company_id)
        authorize(user, company_id)

    # --- контрагенты --------------------------------------------------------
    def _direction(self, edges) -> DirectionSummary:
        d = DirectionSummary()
        d.total_amt = float(sum(e.pay_amt for e in edges))
        d.total_cnt = int(sum(e.pay_cnt for e in edges))
        d.n_counterparties = len(edges)
        companies = self.data.companies
        for e in edges:
            known = e.counterparty_id in companies.index
            okv = self._okved(companies.at[e.counterparty_id, "MAINOKVED_CODE"]) if known else None
            region = companies.at[e.counterparty_id, "REGION"] if known else None
            if known:
                d.known_amt += e.pay_amt
            d.edges.append(EdgeInfo(e.counterparty_id, e.pay_amt, e.pay_cnt,
                                    e.pay_amt / d.total_amt if d.total_amt else 0.0, known, okv, region,
                                    e.source_line))
        return d

    def _direction_view(self, d: DirectionSummary) -> dict:
        top_n = self.rules["thresholds"]["counterparties_top_n"]
        top = [{
            "company_id": e.counterparty_id,
            "pay_amt": e.pay_amt,
            "pay_cnt": e.pay_cnt,
            "share": round(e.share, 4),
            "known": e.known,
            "okved_code": e.okved.code if e.okved else None,
            "okved_section": e.okved.section if e.okved else None,
            "region": e.region,
            "source_file": self._pf,
            "source_row_id": row_id(e.source_line),
        } for e in d.edges[:top_n]]
        cov = d.known_coverage
        return {
            "total_amt": d.total_amt,
            "total_cnt": d.total_cnt,
            "n_counterparties": d.n_counterparties,
            "known_coverage": None if cov is None else round(cov, 4),
            "top": top,
            "truncated": d.n_counterparties > top_n,
        }

    # --- выручка и сегмент ---------------------------------------------------
    def _group_revenue(self, gid: str | None) -> tuple[float | None, int]:
        """(сумма известной выручки участников группы, число участников с известной выручкой). Кешируется."""
        if not gid:
            return None, 0
        cache = self._group_rev_cache
        if gid not in cache:
            vals = [self.data.companies.at[m, "REVENUE_COMPANY"] for m in self.index.group_members.get(gid, [])]
            vals = [float(x) for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x))]
            cache[gid] = (float(sum(vals)) if vals else None, len(vals))
        return cache[gid]

    def _large_business(self, r: dict) -> tuple[bool | None, str, bool]:
        """(крупный бизнес?, основание, по выручке самого юрлица?). Крупный бизнес — выручка группы компаний (или юрлица)
        >= порога (вебинар, вопрос 16)."""
        thr = self.rules["thresholds"]["large_business_revenue"]
        rev = r.get("REVENUE_COMPANY")
        if rev is not None and rev >= thr:
            return True, f"Выручка юрлица >= {thr:.0f} руб. за {REVENUE_PERIOD} г.", True
        group_sum, _ = self._group_revenue(r.get("GROUP_ID"))
        if group_sum is not None and group_sum >= thr:
            return True, (f"Сумма выручки группы {r.get('GROUP_ID')} >= {thr:.0f} руб. за {REVENUE_PERIOD} г.: сегмент "
                          "определяется по группе; такая группа может относиться и к среднему бизнесу"), False
        if rev is None and group_sum is None:
            return None, "Выручка юрлица и группы неизвестна (нет значения или заглушка 1000)", False
        return False, f"Выручка юрлица и группы < {thr:.0f} руб. за {REVENUE_PERIOD} г.", False

    # --- профиль ------------------------------------------------------------
    def build_profile(self, company_id: str) -> dict:
        if company_id in self._profile_cache:
            return self._profile_cache[company_id]
        r = self.require_company(company_id)
        cf, line = self._cf, int(r["_line"])
        thr = self.rules["thresholds"]
        okv = self._okved(r["MAINOKVED_CODE"])
        issues = self.data.company_issues.get(company_id, [])
        issue_codes = {i.code for i in issues}

        incoming = self._direction(self.index.payments_in(company_id))
        outgoing = self._direction(self.index.payments_out(company_id))
        cinput = CompanyInput(company_id, r, line, cf, self._pf, okv, issue_codes, incoming, outgoing)
        factors = self.engine.compute(cinput)
        industry_rules = self.engine.industry_topics(okv)

        def F(field: str) -> dict:
            return fact(r.get(field), cf, line, field)

        okv_method = "okved_hierarchy_v1: разбор кода ОКВЭД2 по уровням и раздел по feature_rules.yaml"
        industry = {
            "okved_code": F("MAINOKVED_CODE"),
            "okved_name": F("MAINOKVED_NAME"),
            "okved_levels": inference(list(okv.levels) if okv else None, okv_method, source_file=cf, line=line,
                                      source_field="MAINOKVED_CODE", confidence="high"),
            "okved_division": inference(okv.division if okv else None, okv_method, source_file=cf, line=line,
                                        source_field="MAINOKVED_CODE", confidence="high"),
            "okved_section": inference(okv.section if okv else None, okv_method, source_file=cf, line=line,
                                       source_field="MAINOKVED_CODE", confidence="high"),
            "okved_section_name": inference(okv.section_name if okv else None, okv_method, source_file=cf,
                                            line=line, source_field="MAINOKVED_CODE", confidence="high"),
            "industry_rules": industry_rules,
        }

        geography = {
            "city": F("CITY"),
            "region": F("REGION"),
            "city_region_atypical": "city_region_atypical" in issue_codes,
        }

        spark, fns = r.get("AMOUNT_WORKERS_SPARK_GRADATION"), r.get("AMOUNT_WORKERS_FNS_GRADATION")
        large, large_basis, large_by_entity = self._large_business(r)
        size = {
            "revenue": F("REVENUE_COMPANY"),
            "revenue_unit": inference("RUB", REVENUE_CONFIRMED, source_file=cf, source_field="REVENUE_COMPANY",
                                      confidence="high"),
            "revenue_period": inference(REVENUE_PERIOD, REVENUE_CONFIRMED, source_file=cf, source_field="REVENUE_COMPANY",
                                        confidence="high"),
            # Сегмент «крупный бизнес» определяется по выручке группы, а не юрлица (вебинар, вопрос 16); группа с такой
            # выручкой может относиться и к среднему бизнесу — поэтому по группе confidence = medium.
            "is_large_business": inference(large, large_basis, source_file=cf, line=line, source_field="REVENUE_COMPANY",
                                           confidence="high" if large_by_entity else "medium"),
            "workers_fns": F("AMOUNT_WORKERS_FNS_GRADATION"),
            "workers_spark": F("AMOUNT_WORKERS_SPARK_GRADATION"),
            "workers_conflict": inference(
                None if (spark is None or fns is None) else bool(spark != fns),
                "Сравнение градаций ФНС и СПАРК", source_file=cf, line=line,
                source_field="AMOUNT_WORKERS_SPARK_GRADATION", confidence="high"),
            "company_age": F("COMPANY_AGE_YEARS_GRADATION"),
            "eco_stage": F("ECO_MARK_LABEL"),
        }

        own = self.engine.ownership_type(r.get("OKFS_NAME"))
        legal = {
            "org_type": F("ORG_TYPE"),
            "okfs_name": F("OKFS_NAME"),
            "ownership_type": inference(own, "Маппинг OKFS_NAME -> тип собственности (feature_rules.yaml)",
                                        source_file=cf, line=line, source_field="OKFS_NAME", confidence="high"),
        }

        products = {code: F(fld) for fld, code in self.rules["products"].items()}
        bank_relationship = {
            "client_type": F("CL_TYPE"),
            "products": products,
            "products_meaning_confirmed": False,
        }

        countries = [x.strip() for x in (r.get("FTS_COUNTRY_NAME") or "").split(",") if x.strip()]
        fts_flag = r.get("FTS_FLAG")
        foreign_trade = {
            "fts_flag": F("FTS_FLAG"),
            "countries": fact(countries or None, cf, line, "FTS_COUNTRY_NAME"),
            "has_foreign_trade": inference(
                None if (fts_flag is None and not countries) else bool(fts_flag is True or countries),
                "FTS_FLAG = 1 ИЛИ заполнен FTS_COUNTRY_NAME", source_file=cf, line=line, source_field="FTS_FLAG",
                confidence="low" if "fts_inconsistent" in issue_codes else "high"),
            "direction": unknown("Направление ВЭД (импорт/экспорт) в данных отсутствует"),
            "consistent": "fts_inconsistent" not in issue_codes,
        }

        gid = r.get("GROUP_ID")
        members = self.index.group_members.get(gid, []) if gid else []
        limit = thr["group_members_limit"]
        group_sum, n_known = self._group_revenue(gid)
        is_mega = len(members) > thr["mega_group_size"]
        group = {
            "group_id": F("GROUP_ID"),
            "size": len(members),
            "members": [m for m in members if m != company_id][:limit],
            "members_truncated": len(members) - 1 > limit,
            "is_mega_group": is_mega,
            "group_revenue_sum": inference(
                group_sum,
                f"Сумма REVENUE_COMPANY участников группы с известной выручкой ({n_known} из {len(members)}); "
                "внутригрупповые обороты не исключены",
                source_file=cf, source_field="REVENUE_COMPANY", confidence="low"),
        }

        same_group = set(members)
        sp = self.index.shared_person_companies(company_id)
        related_by_people = sorted(({
            "company_id": other,
            "relation_type": "shared_person",
            "shared_persons": n,
            "known": other in self.data.companies.index,
            "same_group": other in same_group,
        } for other, n in sp.items()), key=lambda x: (-x["shared_persons"], x["company_id"]))
        related_by_people = related_by_people[: thr["related_limit"]]

        self_pay = self.index.self_payments(company_id)
        counterparties = {
            "incoming": self._direction_view(incoming),
            "outgoing": self._direction_view(outgoing),
            "self_payments_excluded": self_pay,
            "period": PAYMENTS_PERIOD,
            "note": ("Обороты — только платежи, видимые банку, с 1 января (вебинар, вопрос 20; дата среза неизвестна); "
                     "самоплатежи исключены; повторные строки пар просуммированы."),
        }

        topics = self._aggregate_topics(industry_rules, factors)
        data_gaps = self._data_gaps(r, issue_codes, incoming, outgoing, is_mega, okv)
        reliability_notes = self._reliability_notes(r, issue_codes)

        profile = {
            "company_id": company_id,
            "schema_version": SCHEMA_VERSION,
            "built_at": self._now().isoformat(),
            "data_run_id": self.data_run_id,
            "industry": industry,
            "geography": geography,
            "size": size,
            "legal": legal,
            "bank_relationship": bank_relationship,
            "foreign_trade": foreign_trade,
            "group": group,
            "related_by_people": related_by_people,
            "counterparties": counterparties,
            "sensitivity_factors": factors,
            "topics": topics,
            "data_gaps": data_gaps,
            "reliability_notes": reliability_notes,
            "quality_issues": [i.as_dict() for i in issues if i.field != "NEGATIVEMARK"],
            # NEGATIVEMARK в профиль не входит: признак достоверности сведений о ключевом собственнике (вебинар, вопрос 13)
            # ни в одном выводе не используется (минимизация данных). Сырое значение — только в company_profile.companies (роли etl/api).
        }
        self._profile_cache[company_id] = profile
        return profile

    def _aggregate_topics(self, industry_rules: list[dict], factors: list[dict]) -> list[dict]:
        """Темы профиля с весом и источниками — вход для объяснимого ранжирования (участник 4)."""
        w = self.rules["topic_weights"]
        acc: dict[str, dict] = {}

        def add(topic: str, weight: float, source: str) -> None:
            item = acc.setdefault(topic, {"topic": topic, "weight": 0.0, "sources": []})
            item["weight"] = min(1.0, item["weight"] + weight)
            item["sources"].append({"source": source, "weight": round(weight, 4)})

        for rule in industry_rules:
            for t in rule["topics"]:
                add(t, w["industry"], f"industry:{rule['rule_id']}")
        for f in factors:
            if f["code"] == "supply_chain_industries":
                for t, share in f["details"].get("topic_shares", {}).items():
                    add(t, w["supply_chain"] * share, "factor:supply_chain_industries")
            elif f["level"] in ("high", "medium"):
                for t in f["topics"]:
                    add(t, w["factor_high"] if f["level"] == "high" else w["factor_medium"], f"factor:{f['code']}")
        out = sorted(acc.values(), key=lambda x: (-x["weight"], x["topic"]))
        for x in out:
            x["weight"] = round(x["weight"], 4)
        return out

    def _data_gaps(self, r, issue_codes, incoming, outgoing, is_mega, okv) -> list[dict]:
        gaps = [
            {"code": "no_dates", "message": "Дат операций в данных нет: платежи — суммы с 1 января, дата среза неизвестна; "
                                            "помесячная динамика не строится",
             "fields": []},
            {"code": "trade_direction_unknown", "message": "Направление ВЭД (импорт/экспорт) неизвестно",
             "fields": ["FTS_FLAG", "FTS_COUNTRY_NAME"]},
        ]

        def add(code, message, fields):
            gaps.append({"code": code, "message": message, "fields": fields})

        if r.get("REVENUE_COMPANY") is None:
            add("revenue_missing", "Выручка отсутствует или некорректна", ["REVENUE_COMPANY"])
        if okv is None:
            add("okved_missing", "Код ОКВЭД отсутствует или некорректен", ["MAINOKVED_CODE"])
        if r.get("ECO_MARK_LABEL") is None:
            add("eco_stage_missing", "Стадия развития бизнеса не указана", ["ECO_MARK_LABEL"])
        if r.get("AMOUNT_WORKERS_SPARK_GRADATION") is None:
            add("spark_missing", "Численность по СПАРК не указана", ["AMOUNT_WORKERS_SPARK_GRADATION"])
        if "workers_conflict" in issue_codes:
            add("workers_conflict", "Численность по ФНС и СПАРК расходится",
                ["AMOUNT_WORKERS_FNS_GRADATION", "AMOUNT_WORKERS_SPARK_GRADATION"])
        if "fts_inconsistent" in issue_codes:
            add("fts_inconsistent", "Флаг ФТС противоречит списку стран", ["FTS_FLAG", "FTS_COUNTRY_NAME"])
        if r.get("CL_TYPE") != "CLIENT":
            add("product_meaning_unconfirmed", "Для не-клиентов смысл флагов продуктов не подтверждён",
                list(self.rules["products"].keys()))
        if incoming.n_counterparties == 0 and outgoing.n_counterparties == 0:
            add("no_payments", "Платежей с контрагентами в данных нет", ["PAYER", "BENEFICIARY"])
        else:
            covs = [d.known_coverage for d in (incoming, outgoing) if d.known_coverage is not None]
            if any(c < 1.0 for c in covs):
                add("counterparty_attributes_missing",
                    "Часть контрагентов отсутствует в файле юрлиц: их отрасль и регион неизвестны",
                    ["PAYER", "BENEFICIARY"])
        if is_mega:
            add("mega_group", "Группа необычно велика; состав группы не используется для отраслевых выводов",
                ["GROUP_ID"])
        if "invalid_mark" in issue_codes:
            add("invalid_marks", "Часть флагов имеет некорректные значения", [])
        return gaps

    def _reliability_notes(self, r, issue_codes) -> list[str]:
        notes = [
            "Обороты рассчитаны по платежам, видимым банку, и не равны полному обороту компании.",
            "Связи (группа, общие физлица, платежи) не означают контроль или общего собственника.",
            "Производные признаки — правила-эвристики прототипа (feature_rules.yaml), не оценка банка.",
        ]
        if r.get("CL_TYPE") != "CLIENT":
            notes.append("Компания не является действующим клиентом: флаги продуктов могут иметь иной смысл.")
        if "city_region_atypical" in issue_codes:
            notes.append("Регион нетипичен для указанного города — возможна ошибка в исходных данных.")
        return notes

    # --- связи --------------------------------------------------------------
    def get_related(self, company_id: str, limit: int | None = None, types: list[str] | None = None) -> dict:
        self.require_company(company_id)
        limit = limit or self.rules["thresholds"]["related_limit"]
        rel = self.index.related(company_id)
        companies = self.data.companies
        items = []
        for other, v in rel.items():
            tset = v["types"] if types is None else v["types"] & set(types)
            if not tset:
                continue
            known = other in companies.index
            items.append({
                "company_id": other,
                "relation_types": sorted(tset),
                "known": known,
                "okved_code": companies.at[other, "MAINOKVED_CODE"] if known else None,
                "region": companies.at[other, "REGION"] if known else None,
                "shared_persons": v["shared_persons"],
                "pay_amt_in": v["pay_amt_in"],
                "pay_cnt_in": v["pay_cnt_in"],
                "pay_amt_out": v["pay_amt_out"],
                "pay_cnt_out": v["pay_cnt_out"],
            })
        items.sort(key=lambda x: (-len(x["relation_types"]), -(x["pay_amt_in"] + x["pay_amt_out"]), x["company_id"]))
        return {
            "company_id": company_id,
            "schema_version": SCHEMA_VERSION,
            "total": len(items),
            "truncated": len(items) > limit,
            "relations": items[:limit],
            "note": "Типы связей: same_group, shared_person, payment_in, payment_out. Не означают контроль.",
        }

    # --- пользователь -------------------------------------------------------
    def company_summary(self, company_id: str) -> dict:
        try:
            r = self.require_company(company_id)
        except CompanyQuarantined:
            return {"company_id": company_id, "status": "quarantined"}
        except CompanyNotFound:
            return {"company_id": company_id, "status": "not_found"}
        rev = r.get("REVENUE_COMPANY")
        return {
            "company_id": company_id,
            "status": "ok",
            "okved_code": r.get("MAINOKVED_CODE"),
            "okved_name": r.get("MAINOKVED_NAME"),
            "city": r.get("CITY"),
            "region": r.get("REGION"),
            "revenue": rev,
            "is_large_business": self._large_business(r)[0],
            "client_type": r.get("CL_TYPE"),
        }

    def user_companies(self, user: UserContext) -> dict:
        return {
            "user_id": user.user_id,
            "role": user.role,
            "role_title": user.role_title,
            "priority_topics": user.priority_topics,
            "synthetic": user.synthetic,
            "companies": [self.company_summary(c) for c in user.company_ids],
        }

    # --- демо ---------------------------------------------------------------
    def select_demo_companies(self, n: int = 5) -> list[dict]:
        """Контрастные крупные компании для демо «лента меняется под клиента». Детерминированно."""
        thr = self.rules["thresholds"]["large_business_revenue"]
        df = self.data.companies
        cand = df[(df["REVENUE_COMPANY"] >= thr) & (df["CL_TYPE"] == "CLIENT")].index.tolist()
        scored = []
        for cid in cand:
            p = self.build_profile(cid)
            lv = {f["code"]: f["level"] for f in p["sensitivity_factors"]}
            richness = sum(1 for e in p["counterparties"]["incoming"]["top"] + p["counterparties"]["outgoing"]["top"]
                           if e["known"])
            scored.append((cid, p, lv, richness))
        scored.sort(key=lambda x: (-x[3], -(x[1]["size"]["revenue"]["value"] or 0), x[0]))

        slots = [
            ("credit_and_fx", "Есть кредиты/лизинг и ВЭД — чувствительна к ставке и курсам",
             lambda lv: lv["rate_sensitivity"] == "high" and lv["fx_and_trade_exposure"] == "high"),
            ("no_credit_no_fx", "Нет кредитных продуктов и ВЭД — ставка и курс влияют слабо",
             lambda lv: lv["rate_sensitivity"] == "none" and lv["fx_and_trade_exposure"] == "none"),
            ("consumer_sector", "Потребительский сектор — чувствительна к спросу и инфляции",
             lambda lv: lv["consumer_exposure"] == "high"),
            ("deposits_treasury", "Есть депозиты — интерес казначейства к ставкам размещения",
             lambda lv: lv["deposit_income"] == "medium"),
            ("credit_no_fx", "Кредиты без ВЭД — ставка важна, курс нет",
             lambda lv: lv["rate_sensitivity"] == "high" and lv["fx_and_trade_exposure"] == "none"),
            ("fx_no_credit", "ВЭД без кредитов — курс важен, ставка нет",
             lambda lv: lv["rate_sensitivity"] == "none" and lv["fx_and_trade_exposure"] == "high"),
        ]
        chosen: list[dict] = []
        used_ids: set[str] = set()
        used_sections: set[str | None] = set()
        for slot, reason, pred in slots:
            if len(chosen) >= n:
                break
            options = [s for s in scored if s[0] not in used_ids and pred(s[2])]
            fresh = [s for s in options if s[1]["industry"]["okved_section"]["value"] not in used_sections]
            pick = (fresh or options or [None])[0]
            if pick is None:
                continue
            cid, p, lv, richness = pick
            used_ids.add(cid)
            used_sections.add(p["industry"]["okved_section"]["value"])
            chosen.append({
                "company_id": cid,
                "slot": slot,
                "reason": reason,
                "okved_code": p["industry"]["okved_code"]["value"],
                "okved_name": p["industry"]["okved_name"]["value"],
                "okved_section": p["industry"]["okved_section"]["value"],
                "region": p["geography"]["region"]["value"],
                "revenue": p["size"]["revenue"]["value"],
                "factor_levels": lv,
                "known_top_counterparties": richness,
            })
        return chosen

    def quality_report(self) -> dict:
        return self.data.report.as_dict()


__all__ = ["ProfileService", "CompanyNotFound", "CompanyQuarantined", "AccessDenied", "SCHEMA_VERSION"]
