"""Человекочитаемые подписи для интерфейса: коды признаков, уровней, продуктов, полей данных, проверок и шагов агента.

Коды остаются в API для программ (фильтры, тесты, трассировка), а в текстах для пользователя — только подписи отсюда.
"""
from __future__ import annotations

from services.company_profile.features import country_title

from .textkit import topics_ru

FACTOR_TITLES = {"rate_sensitivity": "Чувствительность к ставке", "deposit_income": "Доход от размещения средств",
                 "fx_and_trade_exposure": "Валюта и внешняя торговля", "payroll_exposure": "Фонд оплаты труда",
                 "consumer_exposure": "Зависимость от потребительского спроса",
                 "counterparty_concentration": "Концентрация контрагентов",
                 "supply_chain_industries": "Отрасли поставщиков и покупателей"}
LEVEL_RU = {"high": "высокая", "medium": "средняя", "low": "низкая", "none": "нет", "info": "справочно", "unknown": "не определена"}
PRODUCT_TITLES = {"rko": "Расчётно-кассовое обслуживание", "loans": "Кредиты", "leasing": "Лизинг", "deposits": "Депозиты",
                  "payroll_project": "Зарплатный проект", "guarantees": "Банковские гарантии", "factoring": "Факторинг"}
# поля CSV кейса, на которые ссылаются признаки компании (основание вывода)
FIELD_TITLES = {"MAINOKVED_CODE": "основной ОКВЭД", "MAINOKVED_NAME": "вид деятельности", "REGION": "регион", "CITY": "город",
                "REVENUE_COMPANY": "выручка", "GROUP_ID": "группа компаний", "CL_TYPE": "статус клиента",
                "AMOUNT_WORKERS_FNS_GRADATION": "численность по ФНС", "AMOUNT_WORKERS_SPARK_GRADATION": "численность по СПАРК",
                "FTS_FLAG": "внешняя торговля (ФТС)", "OKFS_NAME": "форма собственности", "FTS_COUNTRY_NAME": "страны внешней торговли",
                "CL_PRODUCT_RKO_MARK": "расчётно-кассовое обслуживание", "CL_PRODUCT_LOA_MARK": "кредиты",
                "CL_PRODUCT_LEA_MARK": "лизинг", "CL_PRODUCT_DEP_MARK": "депозиты", "CL_PRODUCT_ZPP_MARK": "зарплатный проект",
                "CL_PRODUCT_GAR_MARK": "банковские гарантии", "FACTORING_MARK": "факторинг",
                "PAY_AMT": "суммы платежей", "PAYER/BENEFICIARY": "контрагенты по платежам"}
MULTIPLIER_TITLES = {"reliability": "надёжность источника", "recency": "свежесть", "unconfirmed": "не подтверждено",
                     "stale": "устаревший материал"}
CHECK_TITLES = {"evidence_exist": "Ссылки на источники существуют", "grounded": "Каждый вывод опирается на источник",
                "numbers_grounded": "Числа взяты из источников", "bank_page_refs": "У позиций банка есть страница документа",
                "bank_attribution": "Позиции банка приписаны только по его материалам",
                "coverage": "Вывод связан с данными компании", "rumor_not_fact": "Слухи не поданы как факт",
                "forecast_versions": "Использованы актуальные прогнозы банка", "source_fresh": "Источник актуален",
                "injection_clean": "Нет скрытых инструкций для AI"}
STEP_TITLES = {"plan": "План анализа", "get_company_profile": "Профиль компании", "get_news_item": "Материал события",
               "get_cluster": "Другие публикации о событии", "get_bank_positions": "Позиции банка",
               "get_indicators": "Оценка влияния с прогнозами банка", "match_supply_chain": "Отрасли контрагентов",
               "get_related_companies": "Компании группы", "cross_check_numbers": "Сверка цифр с прогнозами банка",
               "search_bank_corpus": "Поиск по материалам банка", "get_product_catalog": "Продукты банка",
               "extract_facts": "Ключевые факты события", "context": "Единый контекст", "verify": "Самопроверка",
               "revert_to_template": "Возврат к проверенному тексту", "repair_evidence": "Исправление ссылок на источники",
               "broaden_search": "Расширенный поиск", "llm_rewrite": "Редактура текста моделью",
               "injection_guard": "Проверка безопасности"}
STEP_KIND_TITLES = {"plan": "планирование", "tool": "инструмент", "analysis": "анализ", "check": "проверка",
                    "synthesis": "синтез", "adapt": "корректировка"}


def factor_phrase(code: str, level: str | None = None) -> str:
    """«Зависимость от потребительского спроса (высокая)»; уровень «справочно» не показывается — это не степень."""
    title = FACTOR_TITLES.get(code, code)
    return title if level in (None, "info") else f"{title} ({LEVEL_RU.get(level, level)})"


def _value_ru(v, field: str = "") -> str:
    if v is True or v == "True":
        return "да"
    if v is False or v == "False":
        return "нет"
    if v is None or v in ("None", ""):
        return "нет данных"
    s = str(v)
    if field == "FTS_COUNTRY_NAME":
        return ", ".join(country_title(x.strip()) for x in s.split(",") if x.strip())
    return s.lower() if s.isupper() and len(s) > 3 else s       # справочники кейса набраны капслоком


def basis_ru(based_on: list[dict]) -> list[str]:
    """Основание признака компании для пользователя: «кредиты: да (строка 1121, df_Uid_data_hack.csv)»."""
    out = []
    for b in based_on:
        field = FIELD_TITLES.get(b.get("source_field") or "", b.get("source_field") or "поле")
        row = str(b.get("source_row_id") or "")
        where = ", ".join(x for x in ((f"строка {row.split(':')[-1]}" if row and row != "None" else ""), b.get("source_file") or "") if x)
        out.append(f"{field}: {_value_ru(b.get('value'), b.get('source_field') or '')}" + (f" ({where})" if where else ""))
    return out


def profile_source_ru(source: str) -> str:
    """Источник веса темы в профиле: industry:auto -> «отрасль компании», factor:x -> название признака."""
    kind, _, code = source.partition(":")
    if kind == "industry":
        return "отрасль компании"
    if kind == "factor":
        return FACTOR_TITLES.get(code, code).lower()
    if kind == "universal":
        return "касается любой компании"
    return source


__all__ = ["FACTOR_TITLES", "LEVEL_RU", "PRODUCT_TITLES", "FIELD_TITLES", "MULTIPLIER_TITLES", "CHECK_TITLES", "STEP_TITLES",
           "STEP_KIND_TITLES", "factor_phrase", "basis_ru", "profile_source_ru", "topics_ru"]
