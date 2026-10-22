"""Валидация и нормализация исходных данных.

Принципы:
- неизвестное = None (не пустая строка и не 0);
- некорректное значение не исправляем «по смыслу», а превращаем в None и пишем issue;
- id с несовместимыми строками (коллизия, например U_428697) отправляем в карантин: профиль не строим;
- самоплатежи (PAYER == BENEFICIARY) отделяем: они не участвуют в долях контрагентов.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from dataclasses import field as dc_field

import numpy as np
import pandas as pd

from .loader import COMPANY_COLUMNS, RawData
from .okved import okved_levels

MARK_FIELDS = [
    "NEGATIVEMARK", "CL_PRODUCT_RKO_MARK", "CL_PRODUCT_GAR_MARK", "CL_PRODUCT_LOA_MARK",
    "CL_PRODUCT_LEA_MARK", "CL_PRODUCT_DEP_MARK", "CL_PRODUCT_ZPP_MARK", "FTS_FLAG", "FACTORING_MARK",
]
_TRUE = {"1", "1.0"}
_FALSE = {"0", "0.0"}
SAMPLE_LIMIT = 20


@dataclass
class Issue:
    code: str
    message: str
    source_file: str
    company_id: str | None = None
    field: str | None = None
    lines: list[int] = dc_field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "code": self.code, "message": self.message, "source_file": self.source_file,
            "company_id": self.company_id, "field": self.field, "lines": self.lines,
        }


@dataclass
class ValidationReport:
    counters: Counter = dc_field(default_factory=Counter)
    samples: dict[str, list[Issue]] = dc_field(default_factory=lambda: defaultdict(list))
    stats: dict[str, int | float] = dc_field(default_factory=dict)

    def add(self, issue: Issue, count: int = 1) -> None:
        self.counters[issue.code] += count
        if len(self.samples[issue.code]) < SAMPLE_LIMIT:
            self.samples[issue.code].append(issue)

    def as_dict(self) -> dict:
        return {
            "stats": dict(self.stats),
            "counters": dict(self.counters),
            "samples": {k: [i.as_dict() for i in v] for k, v in self.samples.items()},
        }


@dataclass
class CleanData:
    companies: pd.DataFrame          # index = company_id, одна строка на компанию
    quarantined: dict[str, list[int]]  # company_id -> строки исходного файла
    company_issues: dict[str, list[Issue]]
    persons: pd.DataFrame            # SYNTHETIC_F, SYNTHETIC_U, _line
    payments: pd.DataFrame           # PAYER, BENEFICIARY, PAY_AMT, PAY_CNT, _line, n_rows (без самоплатежей)
    self_payments: pd.DataFrame      # index = company_id: PAY_AMT, PAY_CNT, n_rows
    report: ValidationReport
    files: dict[str, str]

    def is_known(self, company_id: str) -> bool:
        return company_id in self.companies.index


def _strip(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        df[c] = df[c].astype(str).str.strip()
    return df


def _none_if_empty(series: pd.Series) -> pd.Series:
    s = series.astype(object)
    return s.where(s != "", None)


def _parse_marks(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    s = series.astype(str)
    out = pd.Series([None] * len(s), index=s.index, dtype=object)
    out[s.isin(_TRUE)] = True
    out[s.isin(_FALSE)] = False
    invalid = ~(s.isin(_TRUE) | s.isin(_FALSE) | (s == ""))
    return out, invalid


def _parse_float(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    s = series.astype(str)
    num = pd.to_numeric(s.where(s != "", np.nan), errors="coerce").astype(float)
    bad = (s != "") & (num.isna() | ~np.isfinite(num.fillna(0)) | (num < 0))
    num = num.where(~bad, np.nan)
    return num, bad


def _validate_companies(raw: RawData, report: ValidationReport):
    fname = raw.files["companies"]
    df = _strip(raw.companies.copy(), COMPANY_COLUMNS)
    report.stats["companies_rows"] = int(len(df))
    issues: dict[str, list[Issue]] = defaultdict(list)

    missing_id = df["SYNTHETIC_U"] == ""
    for line in df.loc[missing_id, "_line"].tolist():
        report.add(Issue("missing_company_id", "Строка без SYNTHETIC_U пропущена", fname, lines=[int(line)]))
    df = df[~missing_id]

    exact_dup = df.duplicated(COMPANY_COLUMNS, keep="first")
    for cid, line in df.loc[exact_dup, ["SYNTHETIC_U", "_line"]].itertuples(index=False):
        iss = Issue("duplicate_row", "Полный дубль строки удалён", fname, company_id=cid, lines=[int(line)])
        report.add(iss)
        issues[cid].append(iss)
    df = df[~exact_dup]

    collided = df["SYNTHETIC_U"].duplicated(keep=False)
    quarantined: dict[str, list[int]] = {}
    for cid, grp in df[collided].groupby("SYNTHETIC_U"):
        lines = [int(x) for x in grp["_line"].tolist()]
        quarantined[cid] = lines
        report.add(Issue(
            "id_collision",
            f"Один id соответствует {len(lines)} несовместимым строкам; профиль не строится",
            fname, company_id=cid, lines=lines[:SAMPLE_LIMIT],
        ))
    df = df[~collided].set_index("SYNTHETIC_U", drop=False)
    df.index.name = "company_id"

    for col in MARK_FIELDS:
        parsed, invalid = _parse_marks(df[col])
        for cid, line in df.loc[invalid, ["SYNTHETIC_U", "_line"]].itertuples(index=False):
            iss = Issue("invalid_mark", f"Некорректное значение флага {col}", fname, cid, col, [int(line)])
            report.add(iss)
            issues[cid].append(iss)
        df[col] = parsed

    revenue, bad = _parse_float(df["REVENUE_COMPANY"])
    for cid, line in df.loc[bad, ["SYNTHETIC_U", "_line"]].itertuples(index=False):
        iss = Issue("invalid_revenue", "Некорректная выручка заменена на null", fname, cid, "REVENUE_COMPANY", [int(line)])
        report.add(iss)
        issues[cid].append(iss)
    df["REVENUE_COMPANY"] = revenue

    text_cols = [c for c in COMPANY_COLUMNS if c not in MARK_FIELDS and c != "REVENUE_COMPANY"]
    for col in text_cols:
        df[col] = _none_if_empty(df[col])

    for cid, code, line in df[["SYNTHETIC_U", "MAINOKVED_CODE", "_line"]].itertuples(index=False):
        if code is not None and okved_levels(code) is None:
            iss = Issue("invalid_okved", f"Некорректный код ОКВЭД: {code}", fname, cid, "MAINOKVED_CODE", [int(line)])
            report.add(iss)
            issues[cid].append(iss)

    flag = df["FTS_FLAG"]
    has_country = df["FTS_COUNTRY_NAME"].notna()
    fts_bad = ((flag == True) & ~has_country) | ((flag == False) & has_country)  # noqa: E712
    for cid, line in df.loc[fts_bad, ["SYNTHETIC_U", "_line"]].itertuples(index=False):
        iss = Issue("fts_inconsistent", "FTS_FLAG не согласован с FTS_COUNTRY_NAME", fname, cid, "FTS_FLAG", [int(line)])
        report.add(iss)
        issues[cid].append(iss)

    fns, spark = df["AMOUNT_WORKERS_FNS_GRADATION"], df["AMOUNT_WORKERS_SPARK_GRADATION"]
    conflict = fns.notna() & spark.notna() & (fns != spark)
    for cid, line in df.loc[conflict, ["SYNTHETIC_U", "_line"]].itertuples(index=False):
        iss = Issue("workers_conflict", "Градации численности ФНС и СПАРК расходятся", fname, cid,
                    "AMOUNT_WORKERS_SPARK_GRADATION", [int(line)])
        report.add(iss)
        issues[cid].append(iss)

    known_geo = df[df["CITY"].notna() & df["REGION"].notna()]
    if len(known_geo):
        modal = known_geo.groupby("CITY")["REGION"].agg(lambda s: s.value_counts().index[0])
        atypical = known_geo["REGION"] != known_geo["CITY"].map(modal)
        for cid, line in known_geo.loc[atypical, ["SYNTHETIC_U", "_line"]].itertuples(index=False):
            iss = Issue("city_region_atypical", "Регион нетипичен для города (возможна ошибка данных)", fname,
                        cid, "REGION", [int(line)])
            report.add(iss)
            issues[cid].append(iss)

    report.stats["companies_valid"] = int(len(df))
    report.stats["companies_quarantined_ids"] = len(quarantined)
    return df, quarantined, issues


def _validate_persons(raw: RawData, companies: pd.DataFrame, report: ValidationReport) -> pd.DataFrame:
    fname = raw.files["persons"]
    df = _strip(raw.persons.copy(), ["SYNTHETIC_F", "SYNTHETIC_U"])
    report.stats["person_links_rows"] = int(len(df))
    incomplete = (df["SYNTHETIC_F"] == "") | (df["SYNTHETIC_U"] == "")
    if incomplete.any():
        report.add(Issue("person_link_incomplete", "Связь без SYNTHETIC_F или SYNTHETIC_U пропущена", fname,
                         lines=[int(x) for x in df.loc[incomplete, "_line"].head(SAMPLE_LIMIT)]),
                   count=int(incomplete.sum()))
    df = df[~incomplete]
    dup = df.duplicated(["SYNTHETIC_F", "SYNTHETIC_U"])
    if dup.any():
        report.add(Issue("duplicate_person_link", "Повтор связи физлицо-компания удалён", fname,
                         lines=[int(x) for x in df.loc[dup, "_line"].head(SAMPLE_LIMIT)]), count=int(dup.sum()))
    df = df[~dup]
    unknown = ~df["SYNTHETIC_U"].isin(companies.index)
    report.stats["person_links_unknown_company"] = int(unknown.sum())
    # Геоданные физлиц в профиль компании не переносим (минимизация данных).
    return df[["SYNTHETIC_F", "SYNTHETIC_U", "_line"]].reset_index(drop=True)


def _validate_payments(raw: RawData, report: ValidationReport) -> tuple[pd.DataFrame, pd.DataFrame]:
    fname = raw.files["payments"]
    df = _strip(raw.payments.copy(), ["BENEFICIARY", "PAYER"])
    report.stats["payments_rows"] = int(len(df))

    amt = pd.to_numeric(df["PAY_AMT"].str.strip(), errors="coerce").astype(float)
    cnt = pd.to_numeric(df["PAY_CNT"].str.strip(), errors="coerce").astype(float)
    bad_amt = amt.isna() | ~np.isfinite(amt.fillna(0)) | (amt <= 0)
    bad_cnt = cnt.isna() | ~np.isfinite(cnt.fillna(0)) | (cnt < 1) | (cnt % 1 != 0)
    bad_id = (df["BENEFICIARY"] == "") | (df["PAYER"] == "")
    for code, mask, msg in (
        ("invalid_pay_amt", bad_amt, "PAY_AMT нечисловой или <= 0; строка исключена"),
        ("invalid_pay_cnt", bad_cnt & ~bad_amt, "PAY_CNT нечисловой, < 1 или дробный; строка исключена"),
        ("payment_missing_id", bad_id & ~bad_amt & ~bad_cnt, "Платёж без PAYER/BENEFICIARY исключён"),
    ):
        if mask.any():
            report.add(Issue(code, msg, fname, lines=[int(x) for x in df.loc[mask, "_line"].head(SAMPLE_LIMIT)]),
                       count=int(mask.sum()))
    ok = ~(bad_amt | bad_cnt | bad_id)
    df = df[ok].copy()
    df["PAY_AMT"] = amt[ok]
    df["PAY_CNT"] = cnt[ok].astype(np.int64)

    is_self = df["PAYER"] == df["BENEFICIARY"]
    self_df = (
        df[is_self].groupby("PAYER").agg(PAY_AMT=("PAY_AMT", "sum"), PAY_CNT=("PAY_CNT", "sum"),
                                         n_rows=("_line", "size"))
    )
    self_df.index.name = "company_id"
    report.stats["payments_self_rows"] = int(is_self.sum())
    df = df[~is_self]

    agg = (
        df.groupby(["PAYER", "BENEFICIARY"], sort=False)
        .agg(PAY_AMT=("PAY_AMT", "sum"), PAY_CNT=("PAY_CNT", "sum"), _line=("_line", "min"), n_rows=("_line", "size"))
        .reset_index()
    )
    dup_rows = int(len(df) - len(agg))
    if dup_rows:
        report.add(Issue("duplicate_payment_pair", "Повторные строки пары PAYER-BENEFICIARY просуммированы",
                         fname, lines=[int(x) for x in agg.loc[agg["n_rows"] > 1, "_line"].head(SAMPLE_LIMIT)]),
                   count=dup_rows)
    report.stats["payments_pairs"] = int(len(agg))
    return agg, self_df


def validate(raw: RawData) -> CleanData:
    report = ValidationReport()
    companies, quarantined, issues = _validate_companies(raw, report)
    persons = _validate_persons(raw, companies, report)
    payments, self_payments = _validate_payments(raw, report)
    return CleanData(
        companies=companies, quarantined=quarantined, company_issues=dict(issues), persons=persons,
        payments=payments, self_payments=self_payments, report=report, files=raw.files,
    )
