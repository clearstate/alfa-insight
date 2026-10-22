"""Чтение исходных CSV кейса.

Все поля читаются как строки (keep_default_na=False), типы приводит validation.py.
К каждой строке добавляется `_line` — номер строки в файле (заголовок = 1), он идёт в provenance.source_row_id.
Ограничение: номер строки корректен, пока в полях нет переводов строк (в текущих файлах их нет, см. аудит).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

COMPANIES_FILE = "df_Uid_data_hack.csv"
PERSONS_FILE = "df_Fid_Uid_link_hack.csv"
PAYMENTS_FILE = "df_Uid_payment_hack.csv"

COMPANY_COLUMNS = [
    "SYNTHETIC_U", "ORG_TYPE", "OKFS_NAME", "COMPANY_AGE_YEARS_GRADATION", "ECO_MARK_LABEL",
    "MAINOKVED_CODE", "MAINOKVED_NAME", "NEGATIVEMARK", "AMOUNT_WORKERS_FNS_GRADATION",
    "AMOUNT_WORKERS_SPARK_GRADATION", "CL_TYPE", "CL_PRODUCT_RKO_MARK", "CL_PRODUCT_GAR_MARK",
    "CL_PRODUCT_LOA_MARK", "CL_PRODUCT_LEA_MARK", "CL_PRODUCT_DEP_MARK", "CL_PRODUCT_ZPP_MARK",
    "FTS_FLAG", "FTS_COUNTRY_NAME", "FACTORING_MARK", "REVENUE_COMPANY", "GROUP_ID", "CITY", "REGION",
]
PERSON_COLUMNS = ["SYNTHETIC_F", "CITY_NAME", "RC_NAME", "SYNTHETIC_U"]
PAYMENT_COLUMNS = ["BENEFICIARY", "PAYER", "PAY_AMT", "PAY_CNT"]


class DataFormatError(ValueError):
    """Файл отсутствует или не соответствует ожидаемой структуре."""


@dataclass
class RawData:
    companies: pd.DataFrame
    persons: pd.DataFrame
    payments: pd.DataFrame
    files: dict[str, str]


def read_csv_as_str(path: Path, expected_columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise DataFormatError(f"file not found: {path.name}")
    df = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    missing = [c for c in expected_columns if c not in df.columns]
    if missing:
        raise DataFormatError(f"{path.name}: missing columns {missing}")
    df = df[expected_columns].copy()
    df["_line"] = np.arange(len(df), dtype=np.int64) + 2
    return df


def load_raw(data_dir: str | Path) -> RawData:
    data_dir = Path(data_dir)
    return RawData(
        companies=read_csv_as_str(data_dir / COMPANIES_FILE, COMPANY_COLUMNS),
        persons=read_csv_as_str(data_dir / PERSONS_FILE, PERSON_COLUMNS),
        payments=read_csv_as_str(data_dir / PAYMENTS_FILE, PAYMENT_COLUMNS),
        files={"companies": COMPANIES_FILE, "persons": PERSONS_FILE, "payments": PAYMENTS_FILE},
    )
