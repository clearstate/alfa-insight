"""ETL company_profile: CSV кейса -> валидация -> PostgreSQL.

python -m services.company_profile.etl --data-dir /data/raw [--database-url URL] [--profiles large|all|none]

Шаги:
1. миграция схемы (идемпотентно);
2. запись прогона в etl_runs со статусом running (отдельный коммит — сбой будет виден);
3. чтение и валидация CSV;
4. в ОДНОЙ транзакции: нормализованные таблицы, демо-компании, синтетические пользователи,
   материализованные профили, статус success;
5. при ошибке — откат данных и статус failed с текстом ошибки.

--profiles: large — компании с выручкой >= порога из feature_rules.yaml (по умолчанию); all — все (~85 тыс.,
долго и объёмно); none — не материализовать. API строит любой профиль на лету независимо от этого флага.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import uuid
from pathlib import Path

from .access import UserStore, load_roles
from .db import SqlStore
from .demo_users import build_demo_users
from .features import load_rules
from .loader import COMPANIES_FILE, PAYMENTS_FILE, PERSONS_FILE, load_raw
from .service import SCHEMA_VERSION, ProfileService, rules_hash
from .validation import validate

log = logging.getLogger("company_profile.etl")


def profile_scope(svc: ProfileService, scope: str, extra_ids: list[str]) -> list[str]:
    df = svc.data.companies
    if scope == "none":
        ids: list[str] = []
    elif scope == "all":
        ids = df.index.tolist()
    elif scope == "large":
        thr = svc.rules["thresholds"]["large_business_revenue"]
        ids = df.index[df["REVENUE_COMPANY"] >= thr].tolist()
    else:
        raise ValueError(f"unknown profiles scope: {scope}")
    known = [c for c in extra_ids if c in df.index]
    return sorted(dict.fromkeys(ids + known))


def run_etl(data_dir: str | Path, database_url: str, profiles: str = "large",
            rules_path: str | Path | None = None, roles_path: str | Path | None = None) -> dict:
    store = SqlStore.connect(database_url)
    run_id = f"run_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{uuid.uuid4().hex[:8]}"
    t0 = time.time()
    try:
        store.migrate()
        digest = rules_hash(rules_path)
        files = {"companies": COMPANIES_FILE, "persons": PERSONS_FILE, "payments": PAYMENTS_FILE}
        store.start_run(run_id, files, digest, SCHEMA_VERSION)
        try:
            clean = validate(load_raw(data_dir))
            rules = load_rules(rules_path)
            roles = load_roles(roles_path)
            svc = ProfileService(clean, rules, data_run_id=run_id, storage=store.dialect.name, rules_digest=digest)
            demo = svc.select_demo_companies(6)
            users = build_demo_users(demo)
            UserStore.from_records(users, roles)  # проверка ролей до записи
            ids = profile_scope(svc, profiles, [d["company_id"] for d in demo] +
                                [c for u in users for c in u["company_ids"]])

            cur = store.conn.cursor()
            counts = store.save_clean_data(cur, clean)
            counts["demo_companies"] = store.save_demo(cur, demo, run_id)
            counts["users"] = store.save_users(cur, users)
            counts["company_profiles"] = store.save_profiles(cur, (svc.build_profile(c) for c in ids), run_id)
            clean.report.stats["etl_seconds"] = round(time.time() - t0, 1)
            clean.report.stats["profiles_scope"] = profiles
            store.finish_run(cur, run_id, clean.report)
            store.conn.commit()
        except Exception as exc:
            store.conn.rollback()
            store.fail_run(run_id, f"{type(exc).__name__}: {exc}")
            raise
        result = {"run_id": run_id, "status": "success", "counts": counts, "seconds": round(time.time() - t0, 1),
                  "demo": [{"slot": d["slot"], "company_id": d["company_id"]} for d in demo]}
        log.info("ETL finished: %s", result)
        return result
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="company_profile ETL: CSV -> PostgreSQL")
    ap.add_argument("--data-dir", default=os.getenv("COMPANY_PROFILE_DATA_DIR"))
    ap.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--profiles", choices=["large", "all", "none"], default=os.getenv("COMPANY_PROFILE_PROFILES",
                                                                                     "large"))
    ap.add_argument("--rules", default=os.getenv("COMPANY_PROFILE_RULES"))
    args = ap.parse_args(argv)
    if not args.data_dir or not args.database_url:
        ap.error("нужны --data-dir (или COMPANY_PROFILE_DATA_DIR) и --database-url (или DATABASE_URL)")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    result = run_etl(args.data_dir, args.database_url, args.profiles, args.rules)
    print(f"ETL success: run_id={result['run_id']} seconds={result['seconds']} counts={result['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
