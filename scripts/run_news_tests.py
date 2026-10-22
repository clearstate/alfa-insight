"""Запуск тестов news_ingest без pytest:  python scripts/run_news_tests.py  (код возврата 0 = всё прошло)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests" / "news_ingest"), top_level_dir=str(ROOT))
res = unittest.TextTestRunner(verbosity=1).run(suite)
print(f"\nrun={res.testsRun} failures={len(res.failures)} errors={len(res.errors)} skipped={len(res.skipped)}")
for t, why in res.skipped:
    print("SKIPPED:", t.id().split('.')[-1], "—", why)
sys.exit(0 if res.wasSuccessful() else 1)
