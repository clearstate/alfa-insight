"""Сквозная проверка на РЕАЛЬНЫХ данных кейса: профили всех крупных компаний (выручка > 15 млрд) участника 1 + 9 документов
банка участника 2. Данные: ALFA_DATA_DIR, полные data/raw или срез data/demo из репозитория (все 115 крупных компаний)."""
import unittest
from pathlib import Path

from contracts.news_vocab import TOPICS_V1
from services.news_ingest.pipeline import IngestPipeline
from services.news_ingest.store import NewsStore
from tests.news_ingest.helpers import NOW, case_data_dir

ROOT = Path(__file__).resolve().parents[2]
RAW = case_data_dir()


@unittest.skipUnless(RAW, "нет CSV кейса (ALFA_DATA_DIR, data/raw, data/demo)")
class RealDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from services.company_profile.service import ProfileService
        svc = ProfileService.from_data_dir(RAW)
        c = svc.data.companies
        cls.ids = c.loc[c["REVENUE_COMPANY"].astype(float) > 15e9, "SYNTHETIC_U"].tolist()
        cls.profiles = {i: svc.build_profile(i) for i in cls.ids}
        cls.st = NewsStore("sqlite:///:memory:"); cls.st.init_schema()
        IngestPipeline(cls.st, clock=lambda: NOW).ingest_bank_dir(ROOT / "data/bank_analytics")

    def test_large_business_size_and_profiles_valid(self):
        self.assertEqual(len(self.ids), 115)                       # крупный бизнес кейса: выручка > 15 млрд ₽
        for p in self.profiles.values():
            self.assertTrue({t["topic"] for t in p["topics"]} <= set(TOPICS_V1))
            self.assertTrue(p["industry"]["okved_levels"]["value"])

    def test_every_company_gets_candidates_via_sql_join(self):
        """Путь участника 4: темы профиля + уровни ОКВЭД + регион + страны -> кандидаты из хранилища."""
        empty = []
        for cid, p in self.profiles.items():
            topics = [t["topic"] for t in p["topics"]]
            levels = p["industry"]["okved_levels"]["value"]
            region = p["geography"]["region"]["value"]
            rows = self.st.search_candidates(topics=topics, okved_prefixes=levels, regions=[region] if region else None, limit=50)
            if not rows:
                empty.append(cid)
        self.assertEqual(empty, [], f"компании без единого кандидата: {empty[:5]}")

    def test_geography_values_are_joinable(self):
        """Регионы/страны, которые встречаются в профилях, существуют в словарях news_ingest (иначе соединение по ним невозможно)."""
        import yaml
        cfg = ROOT / "services/news_ingest/config"
        regions = {x["name"] for x in yaml.safe_load((cfg / "geo_regions.yaml").read_text(encoding="utf-8"))["regions"]}
        countries = {x["name"] for x in yaml.safe_load((cfg / "geo_countries.yaml").read_text(encoding="utf-8"))["countries"]}
        for p in self.profiles.values():
            r = p["geography"]["region"]["value"]
            self.assertTrue(r is None or r in regions, r)
            self.assertTrue(set(p["foreign_trade"]["countries"]["value"] or []) <= countries)

    def test_okved_join_finds_real_companies_for_sector_news(self):
        from services.company_profile.industry_terms import match_company
        from tests.news_ingest.test_integration_company_profile import CAR_NEWS
        from tests.news_ingest.helpers import html
        p = IngestPipeline(self.st, clock=lambda: NOW)
        r = p.ingest_html("manual_file", "https://smi.example/auto2", html("Продажи автомобилей снизились на 7%", CAR_NEWS), "text/html", NOW)
        pref = self.st.get_item(r.item_id)["industries"]["okved_prefixes"]
        hits = [i for i, pr in self.profiles.items() if match_company(pref, pr["industry"]["okved_levels"]["value"])]
        self.assertGreater(len(hits), 0)                             # в крупном бизнесе есть компании автосектора


if __name__ == "__main__":
    unittest.main()
