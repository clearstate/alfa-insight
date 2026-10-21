"""Заливка демо-клиентов и пакетный предрасчёт инсайтов.

Запуск: uv run scripts/seed_demo.py [--clients data/synthetic/clients.csv]
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLIENTS = ROOT / "data" / "synthetic" / "clients.csv"

log = logging.getLogger("seed")


def load_clients(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", type=Path, default=DEFAULT_CLIENTS)
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:8080/api"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.clients.exists():
        log.error("Файл клиентов не найден: %s", args.clients)
        return 1

    clients = load_clients(args.clients)
    log.info("Клиентов к заливке: %d (api=%s)", len(clients), args.api_url)

    # TODO: профиль-сервис (загрузка), затем агент (пакетный предрасчёт инсайтов).
    raise SystemExit("Not implemented yet")


if __name__ == "__main__":
    sys.exit(main())
