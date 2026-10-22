"""СИНТЕТИЧЕСКИЕ данные для тестов company_profile. Не являются данными кейса.

Компании U_T*, внешние (неизвестные) контрагенты U_X*, физлица F_T*.
Сценарий описан в комментариях к строкам; ожидаемые значения проверяются в тестах.
"""

from __future__ import annotations

import csv
import functools
import tempfile
from pathlib import Path

from services.company_profile.access import UserStore, load_roles
from services.company_profile.features import load_rules
from services.company_profile.loader import (
    COMPANIES_FILE, COMPANY_COLUMNS, PAYMENT_COLUMNS, PAYMENTS_FILE, PERSON_COLUMNS, PERSONS_FILE, load_raw,
)
from services.company_profile.service import ProfileService
from services.company_profile.validation import validate


def company(cid, *, okved="46.90", okved_name="Торговля оптовая неспециализированная", revenue="1000000000.0",
            group="group_1_sb", cl_type="CLIENT", rko="1.0", gar="0.0", loa="0.0", lea="0.0", dep="0.0",
            zpp="0.0", fts="0.0", country="", factoring="0.0", fns="16-100", spark="", eco="Оптимизация",
            okfs="ЧАСТНАЯ СОБСТВЕННОСТЬ", age="8-15", neg="0.0", city="г. Москва", region="Москва"):
    return {
        "SYNTHETIC_U": cid, "ORG_TYPE": "КОММ_ОРГ", "OKFS_NAME": okfs, "COMPANY_AGE_YEARS_GRADATION": age,
        "ECO_MARK_LABEL": eco, "MAINOKVED_CODE": okved, "MAINOKVED_NAME": okved_name, "NEGATIVEMARK": neg,
        "AMOUNT_WORKERS_FNS_GRADATION": fns, "AMOUNT_WORKERS_SPARK_GRADATION": spark, "CL_TYPE": cl_type,
        "CL_PRODUCT_RKO_MARK": rko, "CL_PRODUCT_GAR_MARK": gar, "CL_PRODUCT_LOA_MARK": loa,
        "CL_PRODUCT_LEA_MARK": lea, "CL_PRODUCT_DEP_MARK": dep, "CL_PRODUCT_ZPP_MARK": zpp, "FTS_FLAG": fts,
        "FTS_COUNTRY_NAME": country, "FACTORING_MARK": factoring, "REVENUE_COMPANY": revenue, "GROUP_ID": group,
        "CITY": city, "REGION": region,
    }


COMPANIES = [
    # U_T1: полный профиль, розница (47.11), кредиты + депозиты + ЗП, ВЭД, конфликт ФНС/СПАРК. Строка 2.
    company("U_T1", okved="47.11", okved_name="Торговля розничная преимущественно пищевыми продуктами",
            revenue="20000000000.0", group="group_1_sb", loa="1.0", dep="1.0", zpp="1.0", fts="1.0",
            country="КИТАЙ, ТУРЦИЯ", fns="Более 251", spark="101-250"),
    # U_T2: та же группа, нет выручки, PROSPECT.
    company("U_T2", revenue="", group="group_1_sb", cl_type="PROSPECT", rko="0.0", eco=""),
    # U_T3: другая группа, производство, без продуктов кроме РКО.
    company("U_T3", okved="10.11", okved_name="Переработка и консервирование мяса", revenue="500000000.0",
            group="group_2_sb", city="г. Казань", region="Республика Татарстан"),
    # U_T4: без платежей.
    company("U_T4", okved="62.01", okved_name="Разработка компьютерного программного обеспечения",
            group="group_3_sb"),
    # U_T5: полный дубль строки (две одинаковые строки).
    company("U_T5", group="group_4_sb"),
    company("U_T5", group="group_4_sb"),
    # U_T6: коллизия id — две несовместимые строки.
    company("U_T6", okved="41.20", group="group_5_sb"),
    company("U_T6", okved="56.10", group="group_6_sb", city="г. Казань", region="Республика Татарстан"),
    # U_T7: FTS_FLAG=1 без страны; некорректный флаг депозита.
    company("U_T7", fts="1.0", country="", dep="abc", group="group_7_sb"),
]

PERSONS = [
    {"SYNTHETIC_F": "F_T1", "CITY_NAME": "Москва", "RC_NAME": "МОСКОВСКИЙ", "SYNTHETIC_U": "U_T1"},
    {"SYNTHETIC_F": "F_T1", "CITY_NAME": "Москва", "RC_NAME": "МОСКОВСКИЙ", "SYNTHETIC_U": "U_T3"},
    {"SYNTHETIC_F": "F_T2", "CITY_NAME": 'Мск "Юг"', "RC_NAME": "МОСКОВСКИЙ", "SYNTHETIC_U": "U_T1"},
    {"SYNTHETIC_F": "F_T2", "CITY_NAME": 'Мск "Юг"', "RC_NAME": "МОСКОВСКИЙ", "SYNTHETIC_U": "U_T2"},
    {"SYNTHETIC_F": "F_T3", "CITY_NAME": "", "RC_NAME": "", "SYNTHETIC_U": "U_UNKNOWN"},
    {"SYNTHETIC_F": "F_T1", "CITY_NAME": "Москва", "RC_NAME": "МОСКОВСКИЙ", "SYNTHETIC_U": "U_T1"},  # дубль
]


def pay(benef, payer, amt, cnt):
    return {"BENEFICIARY": benef, "PAYER": payer, "PAY_AMT": amt, "PAY_CNT": cnt}


PAYMENTS = [
    pay("U_T1", "U_T3", "6000000.0", "3"),
    pay("U_T1", "U_X1", "2000000.0", "1"),
    pay("U_T1", "U_X2", "1000000.0", "1"),
    pay("U_T1", "U_X3", "500000.0", "1"),
    pay("U_T1", "U_X4", "500000.0", "1"),
    pay("U_T1", "U_T3", "1000000.0", "1"),     # повтор пары -> 7 000 000 / 4
    pay("U_T1", "U_T1", "100000000.0", "10"),  # самоплатёж — исключается
    pay("U_T3", "U_T1", "3000000.0", "2"),     # исходящий у U_T1
    pay("U_T1", "U_X5", "abc", "1"),           # некорректная сумма
    pay("U_T1", "U_X6", "-5", "1"),            # отрицательная сумма
    pay("U_T1", "U_X7", "0", "1"),             # нулевая сумма
    pay("U_T1", "U_X8", "1000.0", "1.5"),      # дробное количество
]

EXPECTED_INCOMING_T1 = {"total_amt": 11_000_000.0, "n_counterparties": 5, "top_id": "U_T3", "top_amt": 7_000_000.0,
                        "top_cnt": 4}

USERS = [
    {"user_id": "u_cfo", "role": "cfo", "company_ids": ["U_T1", "U_T2"], "synthetic": True},
    {"user_id": "u_acc", "role": "chief_accountant", "company_ids": ["U_T3", "U_GONE", "U_T6"], "synthetic": True},
    {"user_id": "u_ceo", "role": "ceo", "company_ids": ["U_T4", "U_T5", "U_T7"], "synthetic": True},
]


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, delimiter=";")
        w.writeheader()
        w.writerows(rows)


def write_dataset(directory: Path, companies=None, persons=None, payments=None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    _write(directory / COMPANIES_FILE, COMPANY_COLUMNS, COMPANIES if companies is None else companies)
    _write(directory / PERSONS_FILE, PERSON_COLUMNS, PERSONS if persons is None else persons)
    _write(directory / PAYMENTS_FILE, PAYMENT_COLUMNS, PAYMENTS if payments is None else payments)
    return directory


@functools.lru_cache(maxsize=1)
def dataset_dir() -> Path:
    return write_dataset(Path(tempfile.mkdtemp(prefix="cp_synth_")))


@functools.lru_cache(maxsize=1)
def service() -> ProfileService:
    data = validate(load_raw(dataset_dir()))
    users = UserStore.from_records(USERS, load_roles())
    return ProfileService(data, load_rules(), users)


def expect_raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}")
