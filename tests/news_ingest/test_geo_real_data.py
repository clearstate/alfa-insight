"""География news_ingest должна совпадать с данными кейса символ в символ (profile.foreign_trade.countries, geography.region).
Тесты на реальных CSV (ALFA_DATA_DIR, data/raw или срез data/demo); словари сгенерированы скриптом scripts/build_news_geo.py."""
import json
import unittest
from pathlib import Path

import yaml

from services.news_ingest.enrich import Enricher
from tests.news_ingest.helpers import case_data_dir

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "services/news_ingest/config"
EN = Enricher()
DATA = case_data_dir()
CSV = DATA / "df_Uid_data_hack.csv" if DATA else None
PROFILE = json.loads((ROOT / "docs/examples/profile_U_25835.json").read_text(encoding="utf-8"))


class Geo(unittest.TestCase):
    def test_country_forms_and_no_false_positives(self):
        c = EN.entities_geo("Поставки из Китая, в Китае, с Китаем и китайские товары; Турция, Южная Корея, ОАЭ; Италии и Индии.")[1]
        self.assertEqual(set(c), {"КИТАЙ", "ТУРЦИЯ", "ЮЖНАЯ КОРЕЯ", "ОАЭ", "ИТАЛИЯ", "ИНДИЯ"})
        self.assertEqual(EN.entities_geo("Данные индивидуальные: роман и даниил, перуанский и чилийский не считаем")[1], [])
        self.assertEqual(EN.entities_geo("Американские компании и США")[1], ["США"])

    def test_region_official_names(self):
        r = EN.entities_geo("В Новосибирске, Екатеринбурге и Казани; Московская область, Москва, Санкт-Петербург.")[2]
        self.assertEqual(set(r), {"Новосибирская область", "Свердловская область", "Республика Татарстан", "Московская область", "Москва", "Санкт-Петербург"})
        self.assertEqual(EN.entities_geo("Московская биржа и Московский кредитный банк")[2], [])
        self.assertEqual(EN.entities_geo("Республика Алтай")[2], ["Алтай (Республика)"])
        self.assertEqual(EN.entities_geo("Алтайский край")[2], ["Алтайский край"])

    def test_region_groups_expand_to_official_names(self):
        r = EN.entities_geo("Ситуация на Дальнем Востоке")[2]
        self.assertIn("Приморский край", r); self.assertIn("Хабаровский край", r); self.assertEqual(len(r), 10)

    def test_dictionary_names_match_profile_format(self):
        names_c = {c["name"] for c in yaml.safe_load((CFG / "geo_countries.yaml").read_text(encoding="utf-8"))["countries"]}
        names_r = {c["name"] for c in yaml.safe_load((CFG / "geo_regions.yaml").read_text(encoding="utf-8"))["regions"]}
        self.assertTrue(set(PROFILE["foreign_trade"]["countries"]["value"]) <= names_c)       # ['ОАЭ','КИТАЙ','ИТАЛИЯ']
        self.assertIn(PROFILE["geography"]["region"]["value"], names_r)                       # 'Москва'
        self.assertEqual((len(names_c), len(names_r)), (128, 82))

    @unittest.skipUnless(CSV, "нет CSV кейса (ALFA_DATA_DIR, data/raw, data/demo)")
    def test_dictionaries_cover_every_value_in_real_data(self):
        import pandas as pd
        c = pd.read_csv(CSV, sep=";", dtype=str)
        toks = {t.strip() for v in c["FTS_COUNTRY_NAME"].dropna() for t in v.split(",")}
        names_c = {x["name"] for x in yaml.safe_load((CFG / "geo_countries.yaml").read_text(encoding="utf-8"))["countries"]}
        names_r = {x["name"] for x in yaml.safe_load((CFG / "geo_regions.yaml").read_text(encoding="utf-8"))["regions"]}
        self.assertEqual(toks - names_c, set()); self.assertEqual(set(c["REGION"].dropna()) - names_r, set())

    def test_all_patterns_compile_and_every_name_has_patterns(self):
        for fn, key in (("geo_countries.yaml", "countries"), ("geo_regions.yaml", "regions")):
            for x in yaml.safe_load((CFG / fn).read_text(encoding="utf-8"))[key]:
                self.assertTrue(x["patterns"], x["name"])


if __name__ == "__main__":
    unittest.main()
