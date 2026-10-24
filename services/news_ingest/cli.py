"""CLI модуля news_ingest:  python -m services.news_ingest.cli [--db URL] <команда>

  init-db                          создать схему
  ingest-bank [--dir D]            загрузить 9 документов банка (сайдкары/PDF) — первая вертикаль
  import-file PATH [--title T] [--published-at D] [--source S]   импорт файла (.pdf/.html/.txt) — когда источник недоступен по сети
  ingest-url URL                   загрузить страницу/ленту/PDF по URL (robots, SSRF-защита)
  ingest-feed SOURCE_ID            обойти ленту из sources.yaml (прогон пишется в source_runs)
  schedule [--loop] [--tick S]     обойти «созревшие» включённые ленты (interval_min); --loop — постоянный процесс
  freshness                        свежесть источников (последний успешный прогон); код возврата 1, если просрочено
  export --out DIR                 выгрузка для участников 3/4/6 (items.jsonl, chunks.jsonl, indicators*.json, clusters.json)
  verify-sources                   проверка URL источников (robots.txt, доступность, формат) — запускать на машине с сетью
  gen-token USER_ID                новый токен API (NEWS_STANDALONE_AUTH=token): токен — пользователю, хеш — в NEWS_API_TOKENS
  stats | metrics | errors [--limit N]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

from . import indicators as ind
from . import scheduler
from .auth_shim import new_token
from .fetcher import FetchError, SafeFetcher
from .pipeline import IngestPipeline, build_pipeline, load_sources
from .rss import FeedParseError, parse_feed
from .store import NewsStore
from .textutil import now_iso


def _pipe(args) -> tuple[NewsStore, IngestPipeline]:
    store = NewsStore(args.db)
    store.init_schema()
    return store, build_pipeline(store)


def _dump(path: Path, obj) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def export(store: NewsStore, out: Path) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    items = [store.get_item(r["id"]) for r in store.query("SELECT id FROM news_items ORDER BY published_at DESC, id")]
    with open(out / "items.jsonl", "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    n_chunks = 0
    with open(out / "chunks.jsonl", "w", encoding="utf-8") as fh:
        for it in items:
            for c in store.list_chunks(it["id"]):
                fh.write(json.dumps(c, ensure_ascii=False) + "\n"); n_chunks += 1
    rows = store.indicators()
    _dump(out / "indicators.json", rows)
    _dump(out / "indicator_conflicts.json", ind.compare_forecasts(rows))
    _dump(out / "forecasts_latest.json", ind.latest_forecasts(rows))
    _dump(out / "clusters.json", store.query("SELECT * FROM event_clusters"))
    return {"items": len(items), "chunks": n_chunks, "indicators": len(rows)}


def metrics(store: NewsStore) -> dict:
    """Метрики качества конвейера (для мониторинга и дашборда команды). Все считаются из БД."""
    q = store.query
    total = q("SELECT COUNT(*) n FROM news_items")[0]["n"]
    by_status = {r["processing_status"]: r["n"] for r in q("SELECT processing_status, COUNT(*) n FROM news_items GROUP BY processing_status")}
    errs = {r["code"]: r["n"] for r in q("SELECT code, COUNT(*) n FROM pipeline_errors GROUP BY code")}
    n_err = sum(errs.values())
    llm = q("SELECT COALESCE(SUM(tokens_in+tokens_out),0) tok, COALESCE(SUM(cached),0) cached, COUNT(*) calls FROM llm_usage")[0]
    llm = {k: int(v) for k, v in llm.items()}       # PostgreSQL: SUM(bigint) -> numeric (Decimal), не сериализуется в JSON
    lags = [(datetime.fromisoformat(r["retrieved_at"]) - datetime.fromisoformat(r["published_at"])).total_seconds() / 3600
            for r in q("SELECT published_at, retrieved_at FROM news_items WHERE published_at IS NOT NULL AND source_type<>'bank_analytics'")]
    lag = sum(lags) / len(lags) if lags else None
    return {
        "items_total": total, "items_by_status": by_status,
        "needs_review_share": round(by_status.get("needs_review", 0) / total, 4) if total else None,
        "duplicate_share": round(by_status.get("duplicate", 0) / total, 4) if total else None,
        "pipeline_error_count": n_err, "errors_by_code": errs,
        "failure_rate": round(n_err / (total + n_err), 4) if (total + n_err) else None,
        "avg_publication_lag_hours": round(lag, 2) if lag is not None else None,
        "items_by_source_type": {r["source_type"]: r["n"] for r in q("SELECT source_type, COUNT(*) n FROM news_items GROUP BY source_type")},
        "items_without_topics": q("SELECT COUNT(*) n FROM news_items WHERE id NOT IN (SELECT item_id FROM item_topics)")[0]["n"],
        "clusters_with_conflicts": q("SELECT COUNT(*) n FROM event_clusters WHERE COALESCE(conflicts,'[]')<>'[]'")[0]["n"],
        "llm_tokens_total": llm["tok"], "llm_calls": llm["calls"],
        "llm_cache_hit_rate": round(llm["cached"] / llm["calls"], 4) if llm["calls"] else None,
        "llm_tokens_today": store.llm_tokens_today(now_iso()[:10]),
    }


def verify_sources(sources: dict) -> list[dict]:
    rep = []
    f = SafeFetcher(timeout=15, retries=1, min_interval=1.0)
    for sid, s in sources.items():
        if not s.get("url"):
            continue
        r = {"source_id": sid, "url": s["url"], "robots_allowed": None, "fetch": None, "parsed_entries": None, "error": None}
        try:
            r["robots_allowed"] = f.robots_allowed(s["url"])
            res = f.fetch(s["url"])
            r["fetch"] = {"status": res.status, "content_type": res.content_type, "bytes": len(res.body)}
            if s.get("method") == "rss":
                r["parsed_entries"] = len(parse_feed(res.body))
        except (FetchError, FeedParseError) as e:
            r["error"] = str(e)
        rep.append(r)
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="news_ingest")
    ap.add_argument("--db", default=os.getenv("NEWS_DB_URL", "sqlite:///data/news_ingest.db"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    p = sub.add_parser("ingest-bank"); p.add_argument("--dir")
    p = sub.add_parser("import-file"); p.add_argument("path"); p.add_argument("--title"); p.add_argument("--published-at"); p.add_argument("--source", default="manual_file")
    p = sub.add_parser("ingest-url"); p.add_argument("url")
    p = sub.add_parser("ingest-feed"); p.add_argument("source_id")
    p = sub.add_parser("schedule"); p.add_argument("--loop", action="store_true"); p.add_argument("--tick", type=float, default=60.0)
    sub.add_parser("freshness")
    p = sub.add_parser("export"); p.add_argument("--out", required=True)
    sub.add_parser("verify-sources"); sub.add_parser("stats"); sub.add_parser("metrics")
    p = sub.add_parser("gen-token"); p.add_argument("user_id")
    p = sub.add_parser("errors"); p.add_argument("--limit", type=int, default=20)
    args = ap.parse_args(argv)

    if args.cmd == "gen-token":
        try:
            token, entry = new_token(args.user_id)
        except ValueError as e:
            print(str(e), file=sys.stderr); return 2
        print(json.dumps({"token": token, "news_api_tokens_entry": entry,
                          "note": "токен показывается один раз; в NEWS_API_TOKENS добавить только news_api_tokens_entry"},
                         ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "verify-sources":
        print(json.dumps(verify_sources(load_sources()), ensure_ascii=False, indent=1)); return 0
    store, pipe = _pipe(args)
    if args.cmd == "init-db":
        print("schema ok"); return 0
    if args.cmd == "ingest-bank":
        res = pipe.ingest_bank_dir(args.dir)
    elif args.cmd == "import-file":
        res = [pipe.ingest_file(args.path, args.source, args.title, args.published_at)]
    elif args.cmd == "ingest-url":
        r = pipe.ingest_url(args.url); res = r if isinstance(r, list) else [r]
    elif args.cmd == "ingest-feed":
        if args.source_id not in pipe.sources:
            print(f"неизвестный источник: {args.source_id}", file=sys.stderr); return 2
        _, res = scheduler.run_source_detailed(pipe, args.source_id)
    elif args.cmd == "schedule":
        if not args.loop:
            runs = scheduler.run_due(pipe)
            print(json.dumps(runs, ensure_ascii=False, indent=1))
            return 0 if all(r["ok"] for r in runs) else 1
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        stop = {"flag": False}
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.__setitem__("flag", True))
        scheduler.loop(pipe, tick_s=args.tick, should_stop=lambda: stop["flag"])
        return 0
    elif args.cmd == "freshness":
        rep = scheduler.freshness(store, pipe.sources, pipe.clock())
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep["status"] == "ok" else 1
    elif args.cmd == "export":
        print(json.dumps(export(store, Path(args.out)), ensure_ascii=False)); return 0
    elif args.cmd == "metrics":
        print(json.dumps(metrics(store), ensure_ascii=False, indent=1)); return 0
    elif args.cmd == "stats":
        print(json.dumps(store.stats(), ensure_ascii=False)); return 0
    elif args.cmd == "errors":
        print(json.dumps(store.errors(args.limit), ensure_ascii=False, indent=1)); return 0
    for r in res:
        print(json.dumps(r.to_dict(), ensure_ascii=False))
    print(json.dumps({"summary": {k: sum(1 for r in res if r.outcome == k) for k in ("created", "updated", "duplicate", "skipped", "failed")}}))
    return 1 if any(r.outcome == "failed" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
