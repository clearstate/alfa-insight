"""CLI модуля company_profile.

python scripts/company_profile_cli.py --data-dir DATA demo [-n 5]
python scripts/company_profile_cli.py --data-dir DATA users --out data/synthetic_users.json
python scripts/company_profile_cli.py --data-dir DATA profile U_25835 [--prompt-view]
python scripts/company_profile_cli.py --data-dir DATA related U_25835 [--limit 20]
python scripts/company_profile_cli.py --data-dir DATA quality --out docs/data_quality_report.json
python scripts/company_profile_cli.py ddl > services/company_profile/db_sql/schema.postgres.sql
Вместо --data-dir можно передать --database-url (PostgreSQL/SQLite после ETL).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.company_profile.demo_users import build_demo_users  # noqa: E402
from services.company_profile.prompt_view import build_prompt_view  # noqa: E402
from services.company_profile.service import ProfileService  # noqa: E402

def _dump(obj, out: str | None) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"written {out}")
    else:
        print(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--database-url")
    ap.add_argument("--rules")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo"); d.add_argument("-n", type=int, default=5); d.add_argument("--out")
    u = sub.add_parser("users"); u.add_argument("--out", default="data/synthetic_users.json")
    p = sub.add_parser("profile"); p.add_argument("company_id"); p.add_argument("--prompt-view", action="store_true")
    p.add_argument("--out")
    r = sub.add_parser("related"); r.add_argument("company_id"); r.add_argument("--limit", type=int, default=20)
    r.add_argument("--out")
    q = sub.add_parser("quality"); q.add_argument("--out")
    sub.add_parser("ddl")
    args = ap.parse_args()

    if args.cmd == "ddl":
        from services.company_profile.db import MIGRATION_VERSION, PostgresDialect, render_ddl

        print(f"-- company_profile: схема PostgreSQL (миграция {MIGRATION_VERSION}).\n"
              "-- СГЕНЕРИРОВАНО из services/company_profile/db.py (render_ddl). Не править вручную: менять TABLES и\n"
              "-- перегенерировать: python scripts/company_profile_cli.py ddl > "
              "services/company_profile/db_sql/schema.postgres.sql\n"
              "-- Применяется автоматически ETL (SqlStore.migrate).\n")
        print(";\n\n".join(render_ddl(PostgresDialect())) + ";")
        return 0
    if args.database_url:
        from services.company_profile.db import SqlStore

        store = SqlStore.connect(args.database_url)
        svc = ProfileService.from_store(store, rules_path=args.rules)
        store.close()
    elif args.data_dir:
        svc = ProfileService.from_data_dir(args.data_dir, rules_path=args.rules)
    else:
        ap.error("нужен --data-dir или --database-url")
    if args.cmd == "demo":
        _dump(svc.select_demo_companies(args.n), args.out)
    elif args.cmd == "users":
        demo = svc.select_demo_companies(6)
        _dump({"synthetic": True,
               "note": "Синтетические учётные записи для демо и e2e; company_ids из обезличенных данных кейса",
               "demo_slots": {x["slot"]: x["company_id"] for x in demo}, "users": build_demo_users(demo)}, args.out)
    elif args.cmd == "profile":
        prof = svc.build_profile(args.company_id)
        _dump(build_prompt_view(prof) if args.prompt_view else prof, args.out)
    elif args.cmd == "related":
        _dump(svc.get_related(args.company_id, limit=args.limit), args.out)
    elif args.cmd == "quality":
        _dump(svc.quality_report(), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
