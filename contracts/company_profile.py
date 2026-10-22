"""Контракт модуля company_profile (участник 1). schema_version 0.3.0.

Изменения 0.3.0 (только добавления): детализация цепочки поставок по полным кодам ОКВЭД контрагентов —
SupplyChainDetails (details фактора supply_chain_industries); сводка suppliers/customers не изменилась.

Изменения 0.2.0: CompanyProfile.data_run_id (id загрузки данных в PostgreSQL), HealthResponse;
удалён CompanyProfile.restricted (NEGATIVEMARK больше не выдаётся наружу).

Согласование: участники 3 (агент), 4 (ранжирование), 5 (UI), 6 (владелец contracts/).
Все модели extra="forbid": расхождение сервиса с контрактом ловится валидацией в тестах.

claim_type в профиле: fact | inference | unknown. «inference» здесь — детерминированное правило,
не вывод LLM. Сквозная шкала проекта (fact | bank_view | ai_inference | unknown) — см. вопрос к участнику 6
в docs/company_profile_contract.md.
"""

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "0.3.0"

T = TypeVar("T")
ClaimType = Literal["fact", "inference", "unknown"]
Confidence = Literal["high", "medium", "low"]
FactorLevel = Literal["high", "medium", "low", "none", "unknown", "info"]
FactorCode = Literal[
    "rate_sensitivity", "deposit_income", "fx_and_trade_exposure", "payroll_exposure",
    "consumer_exposure", "counterparty_concentration", "supply_chain_industries",
]
RelationType = Literal["same_group", "shared_person", "payment_in", "payment_out"]
Role = Literal["owner", "ceo", "cfo", "chief_accountant", "treasury", "other_c_level", "other"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Attr(_Model, Generic[T]):
    """Значение с происхождением. Пустое поле источника -> value=null, claim_type=unknown."""
    value: T | None
    claim_type: ClaimType
    source_file: str | None = None
    source_row_id: str | None = None  # "line:N" — номер строки в исходном CSV (заголовок = 1)
    source_field: str | None = None
    as_of: str | None = None          # ISO 8601; сейчас всегда null — дат в данных нет
    method: str | None = None
    confidence: Confidence | None = None


class IndustryRuleMatch(_Model):
    rule_id: str
    matched_prefixes: list[str]
    topics: list[str]


class Industry(_Model):
    okved_code: Attr[str]
    okved_name: Attr[str]
    okved_levels: Attr[list[str]]
    okved_division: Attr[str]
    okved_section: Attr[str]
    okved_section_name: Attr[str]
    industry_rules: list[IndustryRuleMatch]


class Geography(_Model):
    city: Attr[str]
    region: Attr[str]
    city_region_atypical: bool


class Size(_Model):
    revenue: Attr[float]
    revenue_unit: Attr[str]
    revenue_period: Attr[str]
    is_large_business: Attr[bool]
    workers_fns: Attr[str]
    workers_spark: Attr[str]
    workers_conflict: Attr[bool]
    company_age: Attr[str]
    eco_stage: Attr[str]


class Legal(_Model):
    org_type: Attr[str]
    okfs_name: Attr[str]
    ownership_type: Attr[str]  # private | foreign | state | mixed_state


class BankRelationship(_Model):
    client_type: Attr[str]  # CLIENT | CLOSE_CLIENT | PROSPECT
    products: dict[str, Attr[bool]]  # rko, guarantees, loans, leasing, deposits, payroll_project, factoring
    products_meaning_confirmed: bool


class ForeignTrade(_Model):
    fts_flag: Attr[bool]
    countries: Attr[list[str]]
    has_foreign_trade: Attr[bool]
    direction: Attr[str]  # всегда unknown в текущих данных
    consistent: bool


class Group(_Model):
    group_id: Attr[str]
    size: int
    members: list[str]
    members_truncated: bool
    is_mega_group: bool
    group_revenue_sum: Attr[float]


class PersonLink(_Model):
    company_id: str
    relation_type: Literal["shared_person"]
    shared_persons: int
    known: bool       # есть ли компания в файле юрлиц
    same_group: bool


class CounterpartyItem(_Model):
    company_id: str
    pay_amt: float
    pay_cnt: int
    share: float      # доля в видимом обороте направления (без самоплатежей)
    known: bool
    okved_code: str | None
    okved_section: str | None
    region: str | None
    source_file: str
    source_row_id: str | None


class CounterpartyDirection(_Model):
    total_amt: float
    total_cnt: int
    n_counterparties: int
    known_coverage: float | None  # доля оборота с контрагентами, известными в файле юрлиц
    top: list[CounterpartyItem]
    truncated: bool


class SelfPayments(_Model):
    pay_amt: float
    pay_cnt: int
    n_rows: int


class Counterparties(_Model):
    incoming: CounterpartyDirection
    outgoing: CounterpartyDirection
    self_payments_excluded: SelfPayments | None
    period: str | None
    note: str


class Evidence(_Model):
    source_file: str
    source_row_id: str | None
    source_field: str
    value: Any


class SupplyChainDivision(_Model):
    """Сводка по классу ОКВЭД (формат 0.2.0, без изменений)."""
    okved_division: str
    okved_section: str | None
    okved_section_name: str | None
    pay_amt: float
    n_counterparties: int
    example_okved_codes: list[str]
    share_of_known: float | None


class SupplyChainCode(_Model):
    """Детализация по полному коду ОКВЭД контрагентов (агрегат по коду, без id контрагентов)."""
    okved_code: str
    okved_levels: list[str]   # для точного совпадения префиксов новости: prefix in okved_levels
    okved_division: str
    okved_section: str | None
    pay_amt: float
    pay_cnt: int
    n_counterparties: int
    share_of_known: float | None  # доля в обороте с известными контрагентами этого направления


class SupplyChainCodesMeta(_Model):
    n_codes: int                  # всего различных кодов в направлении
    truncated: bool               # в *_codes только top_codes кодов по сумме
    omitted_share_of_known: float | None


class SupplyChainDetails(_Model):
    """details фактора supply_chain_industries. Валидируйте этой моделью, если используете детализацию."""
    suppliers: list[SupplyChainDivision]
    customers: list[SupplyChainDivision]
    supplier_codes: list[SupplyChainCode]
    customer_codes: list[SupplyChainCode]
    supplier_codes_meta: SupplyChainCodesMeta
    customer_codes_meta: SupplyChainCodesMeta
    rule_shares: dict[str, float]   # id отраслевого правила -> доля известного оборота (max по направлениям)
    topic_shares: dict[str, float]
    known_coverage_outgoing: float | None
    known_coverage_incoming: float | None


class SensitivityFactor(_Model):
    code: FactorCode
    level: FactorLevel
    claim_type: Literal["inference"]
    rule_id: str
    rationale: str
    based_on: list[Evidence]
    confidence: Confidence
    topics: list[str]
    details: dict[str, Any]


class TopicSource(_Model):
    source: str  # "industry:<rule_id>" | "factor:<code>"
    weight: float


class TopicWeight(_Model):
    topic: str
    weight: float  # 0..1
    sources: list[TopicSource]


class DataGap(_Model):
    code: str
    message: str
    fields: list[str]


class QualityIssue(_Model):
    code: str
    message: str
    source_file: str
    company_id: str | None
    field: str | None
    lines: list[int]


class CompanyProfile(_Model):
    company_id: str
    schema_version: str
    built_at: str  # ISO 8601 UTC
    data_run_id: str | None  # id загрузки (company_profile.etl_runs.run_id); null при работе прямо из CSV
    industry: Industry
    geography: Geography
    size: Size
    legal: Legal
    bank_relationship: BankRelationship
    foreign_trade: ForeignTrade
    group: Group
    related_by_people: list[PersonLink]
    counterparties: Counterparties
    sensitivity_factors: list[SensitivityFactor]
    topics: list[TopicWeight]
    data_gaps: list[DataGap]
    reliability_notes: list[str]
    quality_issues: list[QualityIssue]


class Relation(_Model):
    company_id: str
    relation_types: list[RelationType]
    known: bool
    okved_code: str | None
    region: str | None
    shared_persons: int
    pay_amt_in: float
    pay_cnt_in: int
    pay_amt_out: float
    pay_cnt_out: int


class RelatedResponse(_Model):
    company_id: str
    schema_version: str
    total: int
    truncated: bool
    relations: list[Relation]
    note: str


class CompanySummary(_Model):
    company_id: str
    status: Literal["ok", "not_found", "quarantined"]
    okved_code: str | None = None
    okved_name: str | None = None
    city: str | None = None
    region: str | None = None
    revenue: float | None = None
    is_large_business: bool | None = None
    client_type: str | None = None


class UserCompaniesResponse(_Model):
    user_id: str
    role: Role
    role_title: str | None
    priority_topics: list[str]
    synthetic: bool
    companies: list[CompanySummary]


class DemoCompany(_Model):
    company_id: str
    slot: str
    reason: str
    okved_code: str | None
    okved_name: str | None
    okved_section: str | None
    region: str | None
    revenue: float | None
    factor_levels: dict[str, FactorLevel]
    known_top_counterparties: int


class ErrorBody(_Model):
    code: str
    message: str
    details: dict[str, Any] | None = None
    correlation_id: str | None = None


class ErrorResponse(_Model):
    error: ErrorBody


class HealthResponse(_Model):
    status: Literal["ok"]
    schema_version: str
    storage: Literal["postgres", "sqlite", "csv"]
    data_run_id: str | None
    companies: int
    quarantined_ids: int
    users: int
    rules_hash: str
    rules_match_etl: bool | None  # совпадают ли правила с теми, на которых построена загрузка; null для CSV
