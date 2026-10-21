"""Расчёт оффлайн-метрик качества по размеченному набору data/eval/.

Запуск: uv run scripts/run_eval.py [--labels data/eval/labels.jsonl]
Метрики описаны в docs/quality-metrics.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LABELS = ROOT / "data" / "eval" / "labels.jsonl"


def load_labels(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "eval" / "report.json")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    labels = load_labels(args.labels)
    if not labels:
        logging.error("Разметка не найдена или пуста: %s", args.labels)
        return 1

    # TODO: precision@k / recall@k, точность claim_type, доля утверждений с provenance,
    # прохождение критиком, калибровка confidence. Результат писать в args.out.
    report: dict[str, object] = {"examples": len(labels), "metrics": {}}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("Отчёт: %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
