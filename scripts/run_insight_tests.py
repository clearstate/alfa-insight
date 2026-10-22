"""Запуск тестов insight без pytest: python scripts/run_insight_tests.py"""
from __future__ import annotations

import importlib
import inspect
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    mod = importlib.import_module("tests.insight.test_insight")
    ok = bad = 0
    t0 = time.time()
    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        if not name.startswith("test_") or fn.__module__ != mod.__name__:
            continue
        try:
            fn()
            ok += 1
            print("PASS", name)
        except Exception:  # noqa: BLE001
            bad += 1
            print("FAIL", name)
            traceback.print_exc()
    print(f"\n{ok} passed, {bad} failed, {time.time() - t0:.1f}s")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
