"""Словари контракта news_item (чистый Python, без зависимостей).

Единый источник констант для: contracts/news_item.py (Pydantic), services/news_ingest, участников 3, 4, 6.
Темы (TOPICS_V1) — словарь участника 1 (services/company_profile/config/feature_rules.yaml); рассинхрон ловит
tests/news_ingest/test_integration_company_profile.py.
"""

SCHEMA_VERSION = "news_item/1.0"

CLAIM_TYPES = ("fact", "bank_view", "ai_inference", "unknown")
SOURCE_TYPES = ("regulator", "statistics", "media", "bank_analytics", "user_submitted")
DOCUMENT_TYPES = ("news", "press_release", "statistics_release", "bank_analytics")
PROCESSING_STATUSES = ("ok", "needs_review", "failed", "duplicate")
EXTRACTION_METHODS = ("html", "rss", "pdf_text", "pdf_ocr", "pdf_vision_sidecar", "manual_text")
FACT_METHODS = ("rule", "llm", "manual")
BANK_VIEW_KINDS = ("forecast", "assessment", "recommendation")
DATE_PRECISIONS = ("day", "second")

TOPICS_V1 = (
    "agro", "auto_market", "bond_market", "business_activity", "chemicals", "commodities", "construction",
    "consumer_credit", "consumer_demand", "counterparty_risk", "credit_conditions", "deposit_rates", "export",
    "financial_regulation", "food_prices", "foreign_trade", "fuel_prices", "fx_rates", "gdp", "gold",
    "import_substitution", "inflation", "it", "key_rate", "labor_market", "liquidity", "logistics", "metals",
    "mortgage", "oil_gas", "real_estate", "retail", "sanctions", "tourism", "wage_inflation", "wholesale_trade",
    # v1.1 (insight-слой): темы, которые раньше были только в приоритетах ролей, теперь классифицируются и в новостях
    "taxes", "regulation",
)
ROLE_ONLY_TOPICS_V1_1 = ("taxes", "regulation")

# Соответствие «старого» списка тем из ТЗ участника 2 словарю участника 1 (для документации и миграции).
LEGACY_TOPIC_MAP = {
    "key_rate": "key_rate", "inflation": "inflation", "fx": "fx_rates", "commodities": "commodities",
    "regulation": "financial_regulation", "taxes": None, "labor": "labor_market", "consumption": "consumer_demand",
    "gdp": "gdp", "bonds": "bond_market", "gold": "gold", "sanctions": "sanctions", "logistics": "logistics",
    "industry_specific": None,
}
