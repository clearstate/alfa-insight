"""Проверка контракта БЕЗ pydantic: поля Pydantic-модели (по AST) == поля dataclass-модели; Literal-значения == словари; все
реально собранные элементы проходят структурную проверку. Если pydantic установлен — дополнительно model_validate (см. test_contract_pydantic)."""
import ast
import importlib.util
import json
import unittest
from dataclasses import fields
from pathlib import Path

from contracts import news_vocab as V
from services.news_ingest import models as M
from services.news_ingest.pipeline import IngestPipeline
from services.news_ingest.store import NewsStore
from tests.news_ingest.helpers import NOW

ROOT = Path(__file__).resolve().parents[2]
TREE = ast.parse((ROOT / "contracts/news_item.py").read_text(encoding="utf-8"))


def pyd_fields(cls: str) -> set[str]:
    node = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return {s.target.id for s in node.body if isinstance(s, ast.AnnAssign)}


def literal_values(alias: str) -> tuple:
    node = next(n for n in TREE.body if isinstance(n, ast.Assign) and n.targets[0].id == alias)
    return tuple(e.value for e in node.value.slice.elts)


class Static(unittest.TestCase):
    def test_fields_match_dataclasses(self):
        for pyd, dc in (("NewsItem", M.NewsItem), ("KeyFact", M.KeyFact), ("BankView", M.BankView), ("NumericClaim", M.NumericClaim), ("Chunk", M.Chunk)):
            self.assertEqual(pyd_fields(pyd), {f.name for f in fields(dc)}, pyd)

    def test_literals_match_vocabulary(self):
        self.assertEqual(literal_values("ClaimType"), V.CLAIM_TYPES)
        self.assertEqual(literal_values("SourceType"), V.SOURCE_TYPES)
        self.assertEqual(literal_values("DocumentType"), V.DOCUMENT_TYPES)
        self.assertEqual(literal_values("ProcessingStatus"), V.PROCESSING_STATUSES)
        self.assertEqual(literal_values("FactMethod"), V.FACT_METHODS)
        self.assertEqual(literal_values("BankViewKind"), V.BANK_VIEW_KINDS)
        self.assertEqual(literal_values("DatePrecision"), V.DATE_PRECISIONS)

    def test_all_ingested_items_conform(self):
        st = NewsStore("sqlite:///:memory:"); st.init_schema()
        IngestPipeline(st, clock=lambda: NOW).ingest_bank_dir(ROOT / "data/bank_analytics")
        for row in st.query("SELECT id FROM news_items"):
            d = st.get_item(row["id"])
            self.assertEqual(set(d), {f.name for f in fields(M.NewsItem)})
            self.assertEqual(d["schema_version"], V.SCHEMA_VERSION)
            self.assertIn(d["source_type"], V.SOURCE_TYPES); self.assertIn(d["processing_status"], V.PROCESSING_STATUSES)
            self.assertTrue(set(d["topics"]) <= set(V.TOPICS_V1))
            for f in d["key_facts"]:
                self.assertIn(f["claim_type"], V.CLAIM_TYPES); self.assertIn(f["method"], V.FACT_METHODS)
                self.assertTrue(f["provenance"]["item_id"] == d["id"])
            for v in d["bank_views"]:
                self.assertIn(v["kind"], V.BANK_VIEW_KINDS)
            self.assertTrue(0 <= d["source_reliability"]["score"] <= 1)
            self.assertTrue(d["published_at"] is None or d["published_at"].endswith("+00:00"))
            json.dumps(d, ensure_ascii=False)                              # сериализуемо


@unittest.skipUnless(importlib.util.find_spec("pydantic"), "pydantic не установлен")
class WithPydantic(unittest.TestCase):
    def test_model_validate_all_items(self):
        from contracts.news_item import Chunk, IngestRequest, NewsItem
        st = NewsStore("sqlite:///:memory:"); st.init_schema()
        IngestPipeline(st, clock=lambda: NOW).ingest_bank_dir(ROOT / "data/bank_analytics")
        for row in st.query("SELECT id FROM news_items"):
            NewsItem.model_validate(st.get_item(row["id"]))
            for c in st.list_chunks(row["id"]):
                Chunk.model_validate(c)
        with self.assertRaises(ValueError):
            IngestRequest(url="http://a", text="b")
        with self.assertRaises(ValueError):
            IngestRequest()


if __name__ == "__main__":
    unittest.main()
