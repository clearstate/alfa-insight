"""Стык с участником 1: словарь тем, отрасли (ОКВЭД-префиксы), сопоставление новости с реальным профилем из docs/examples."""
import json
import unittest
from pathlib import Path

import yaml

from contracts.news_vocab import TOPICS_V1
from services.company_profile.industry_terms import match_company, match_supply_chain
from services.news_ingest.pipeline import IngestPipeline
from services.news_ingest.store import NewsStore
from tests.news_ingest.helpers import NOW, html

ROOT = Path(__file__).resolve().parents[2]
PROFILE = json.loads((ROOT / "docs/examples/profile_U_25835.json").read_text(encoding="utf-8"))
CAR_NEWS = [
    "Продажи новых легковых автомобилей в августе снизились на 7% по сравнению с июлем, сообщили аналитики автомобильного рынка.",
    "Спрос на автомобили охлаждается из-за ужесточения макропруденциальных лимитов по автокредитам и роста стоимости заёмного финансирования.",
    "Автодилеры отмечают рост цен на запчасти и автомобильные комплектующие на фоне ослабления рубля и удорожания импорта.",
    "Эксперты ожидают дальнейшего замедления продаж автомобилей, поскольку потребители откладывают крупные покупки.",
]


class Integration(unittest.TestCase):
    def test_topic_vocabulary_matches_company_profile_config(self):
        """TOPICS_V1 обязан совпадать со всеми темами в feature_rules.yaml участника 1 (рассинхрон = ломается пересечение тем)."""
        rules = yaml.safe_load((ROOT / "services/company_profile/config/feature_rules.yaml").read_text(encoding="utf-8"))
        found: set[str] = set()

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "topics" and isinstance(v, list):
                        found.update(x for x in v if isinstance(x, str))
                    else:
                        walk(v)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        walk(rules)
        from contracts.news_vocab import ROLE_ONLY_TOPICS_V1_1
        self.assertEqual(found, set(TOPICS_V1) - set(ROLE_ONLY_TOPICS_V1_1), f"только в feature_rules: {found - set(TOPICS_V1)}; только в news_vocab: {set(TOPICS_V1) - found}")

    def test_news_matches_real_profile_by_okved_and_topics(self):
        st = NewsStore("sqlite:///:memory:"); st.init_schema()
        p = IngestPipeline(st, clock=lambda: NOW)
        r = p.ingest_html("manual_file", "https://smi.example/auto", html("Продажи автомобилей снизились на 7%", CAR_NEWS), "text/html", NOW)
        it = st.get_item(r.item_id)
        levels = PROFILE["industry"]["okved_levels"]["value"]                    # ['45','45.3','45.31','45.31.1']
        self.assertEqual(match_company(it["industries"]["okved_prefixes"], levels), ["45"])
        profile_topics = {t["topic"] for t in PROFILE["topics"]}
        shared = set(it["topics"]) & profile_topics
        self.assertTrue({"auto_market"} <= shared, f"темы новости {it['topics']}, профиль {sorted(profile_topics)}")
        # цепочка поставок: функция участника 1 принимает наши префиксы без ошибок
        self.assertIsInstance(match_supply_chain(it["industries"]["okved_prefixes"], PROFILE), list)
        # SQL-путь участника 4: кандидаты по темам и по префиксам профиля
        self.assertIn(r.item_id, [x["id"] for x in st.search_candidates(topics=sorted(profile_topics))])
        self.assertIn(r.item_id, [x["id"] for x in st.search_candidates(okved_prefixes=levels)])

    def test_prefixes_are_valid_okved_for_company_profile(self):
        from services.company_profile.industry_terms import validate_prefix
        st = NewsStore("sqlite:///:memory:"); st.init_schema()
        p = IngestPipeline(st, clock=lambda: NOW); p.ingest_bank_dir(ROOT / "data/bank_analytics")
        for row in st.query("SELECT DISTINCT okved_prefix FROM item_industries"):
            self.assertTrue(validate_prefix(row["okved_prefix"]), row)


if __name__ == "__main__":
    unittest.main()
