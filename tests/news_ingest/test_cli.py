import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from services.news_ingest import cli
from tests.news_ingest.helpers import RATE_A

ROOT = Path(__file__).resolve().parents[2]


def run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(list(argv))
    return code, buf.getvalue()


class CLI(unittest.TestCase):
    def test_bank_export_roundtrip(self):
        tmp = Path(tempfile.mkdtemp()); db = f"sqlite:///{tmp}/n.db"
        code, out = run("--db", db, "ingest-bank", "--dir", str(ROOT / "data/bank_analytics"))
        self.assertEqual(code, 0); self.assertIn('"created": 9', out)
        code, out = run("--db", db, "ingest-bank", "--dir", str(ROOT / "data/bank_analytics"))
        self.assertIn('"skipped": 9', out)
        code, out = run("--db", db, "export", "--out", str(tmp / "exp"))
        stats = json.loads(out); self.assertEqual(stats["items"], 9)
        items = [json.loads(l) for l in (tmp / "exp/items.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(items), 9)
        fl = json.loads((tmp / "exp/forecasts_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(fl["key_rate_eoy"]["2026"]["value"], 14.0)
        self.assertEqual({s["value"] for s in fl["key_rate_eoy"]["2026"]["superseded"]}, {13.5})
        self.assertEqual(fl["usd_rub_eoy"]["2027"]["value"], 93.0)
        conf = json.loads((tmp / "exp/indicator_conflicts.json").read_text(encoding="utf-8"))
        self.assertTrue(any(c["indicator"] == "key_rate_eoy" for c in conf))

    def test_metrics(self):
        tmp = Path(tempfile.mkdtemp()); db = f"sqlite:///{tmp}/n.db"
        run("--db", db, "ingest-bank", "--dir", str(ROOT / "data/bank_analytics"))
        code, out = run("--db", db, "metrics")
        m = json.loads(out)
        self.assertEqual((m["items_total"], m["items_by_source_type"], m["failure_rate"], m["items_without_topics"]), (9, {"bank_analytics": 9}, 0.0, 0))
        self.assertIsNone(m["avg_publication_lag_hours"])

    def test_import_text_file(self):
        tmp = Path(tempfile.mkdtemp()); f = tmp / "note.txt"; f.write_text(" ".join(RATE_A), encoding="utf-8")
        code, out = run("--db", f"sqlite:///{tmp}/n.db", "import-file", str(f), "--published-at", "2026-09-11")
        self.assertEqual(code, 0); self.assertIn('"created": 1', out)

    def test_import_failure_returns_nonzero(self):
        tmp = Path(tempfile.mkdtemp()); f = tmp / "empty.txt"; f.write_text("коротко", encoding="utf-8")
        code, out = run("--db", f"sqlite:///{tmp}/n.db", "import-file", str(f))
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
