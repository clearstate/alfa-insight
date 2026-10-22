"""Резервный раннер тестов, когда pytest недоступен (например, в офлайн-песочнице).

Запускает функции test_* без аргументов из tests/company_profile/test_*.py.
Модули, которые не импортируются из-за отсутствующих зависимостей (pytest/pydantic/fastapi), помечаются SKIPPED.
Это НЕ замена pytest: основной прогон — `uv run pytest tests/company_profile`.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    import tests.company_profile as pkg

    passed = failed = 0
    skipped: list[str] = []
    t0 = time.time()
    for mod in sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if m.name.startswith("test_")):
        try:
            module = importlib.import_module(f"tests.company_profile.{mod}")
        except ModuleNotFoundError as exc:
            skipped.append(f"{mod} (missing dependency: {exc.name})")
            continue
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("test_") or fn.__module__ != module.__name__:
                continue
            if inspect.signature(fn).parameters:
                skipped.append(f"{mod}::{name} (needs pytest fixtures)")
                continue
            try:
                fn()
                passed += 1
                print(f"PASSED  {mod}::{name}")
            except Exception:  # noqa: BLE001
                failed += 1
                print(f"FAILED  {mod}::{name}")
                traceback.print_exc()
    for s in skipped:
        print(f"SKIPPED {s}")
    print(f"\n{passed} passed, {failed} failed, {len(skipped)} skipped in {time.time() - t0:.2f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
