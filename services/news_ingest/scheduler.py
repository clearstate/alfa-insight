"""Регулярный запуск загрузчика лент и контроль последнего успешного обновления.

  python -m services.news_ingest.cli schedule --loop     постоянный процесс (docker compose: сервис news-ingest-scheduler)
  python -m services.news_ingest.cli schedule            один проход по «созревшим» источникам (для cron / Планировщика Windows)
  python -m services.news_ingest.cli freshness           свежесть источников; код возврата 1, если обновление просрочено

По расписанию обходятся источники из sources.yaml с enabled: true, method: rss и url. Интервал — interval_min; после неудачи
повтор раньше (5, 10, 20... минут, но не реже interval_min). Каждый прогон пишется в source_runs. Источник «просрочен» (stale),
если последний успешный прогон старше max_staleness_min, и «never», если успешных прогонов не было.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from .models import IngestResult
from .pipeline import IngestPipeline
from .store import NewsStore

log = logging.getLogger("news_ingest.scheduler")

DEFAULT_INTERVAL_MIN = 30
DEFAULT_MAX_STALENESS_MIN = 180
RETRY_BASE_MIN = 5
OUTCOMES = ("created", "updated", "duplicate", "skipped", "failed")


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def scheduled_sources(sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {sid: s for sid, s in sources.items() if s.get("enabled") and s.get("method") == "rss" and s.get("url")}


def run_source(pipe: IngestPipeline, source_id: str) -> dict[str, Any]:
    """Один обход ленты с записью результата в source_runs. Исключения не пробрасываются — они фиксируются как неудача."""
    return run_source_detailed(pipe, source_id)[0]


def run_source_detailed(pipe: IngestPipeline, source_id: str) -> tuple[dict[str, Any], list[IngestResult]]:
    started = pipe.clock()
    error = None
    try:
        results = pipe.ingest_feed(source_id)
    except Exception as e:  # noqa: BLE001 — сбой одного источника не останавливает расписание
        pipe.store.add_error("schedule", "unexpected", f"{type(e).__name__}: {e}", source_id)
        results, error = [], f"{type(e).__name__}: {e}"
    counts = {k: sum(1 for r in results if r.outcome == k) for k in OUTCOMES}
    if error is None and not results:
        error = "empty_feed"                       # лента без записей — признак смены формата/адреса, а не успеха
    elif error is None and all(r.outcome == "failed" for r in results):
        error = "; ".join(sorted({r.error or "failed" for r in results}))[:500]
    ok = error is None
    pipe.store.add_source_run(source_id, started, pipe.clock(), ok, counts, error)
    return {"source_id": source_id, "ok": ok, "started_at": started, **counts, "error": error}, results


def is_due(store: NewsStore, source_id: str, cfg: dict[str, Any], now: str) -> bool:
    last = store.source_run_state(source_id)
    run = last["last_run"]
    if run is None:
        return True
    interval = float(cfg.get("interval_min", DEFAULT_INTERVAL_MIN))
    if not run["ok"]:
        interval = min(interval, RETRY_BASE_MIN * 2 ** max(0, last["consecutive_failures"] - 1))
    return _dt(now) - _dt(run["started_at"]) >= timedelta(minutes=interval)


def run_due(pipe: IngestPipeline, now: str | None = None) -> list[dict[str, Any]]:
    now = now or pipe.clock()
    return [run_source(pipe, sid) for sid, cfg in scheduled_sources(pipe.sources).items() if is_due(pipe.store, sid, cfg, now)]


def freshness(store: NewsStore, sources: dict[str, dict[str, Any]], now: str) -> dict[str, Any]:
    out = []
    for sid, cfg in scheduled_sources(sources).items():
        st = store.source_run_state(sid)
        max_age = float(cfg.get("max_staleness_min", DEFAULT_MAX_STALENESS_MIN))
        ok_run, last = st["last_success"], st["last_run"]
        age = round((_dt(now) - _dt(ok_run["finished_at"])).total_seconds() / 60, 1) if ok_run else None
        status = "never" if ok_run is None else ("ok" if age <= max_age else "stale")
        out.append({"source_id": sid, "status": status, "last_success_at": ok_run["finished_at"] if ok_run else None,
                    "age_min": age, "max_staleness_min": max_age, "last_run_at": last["started_at"] if last else None,
                    "last_run_ok": bool(last["ok"]) if last else None, "consecutive_failures": st["consecutive_failures"],
                    "last_error": last["error"] if last and not last["ok"] else None,
                    "last_item_created_at": st["last_item_created_at"]})
    overall = "no_sources" if not out else ("ok" if all(s["status"] == "ok" for s in out) else "stale")
    return {"status": overall, "checked_at": now, "sources": out}


def loop(pipe: IngestPipeline, tick_s: float = 60, should_stop: Callable[[], bool] = lambda: False,
         sleep: Callable[[float], None] = time.sleep, max_consecutive_errors: int = 5) -> None:
    """Постоянный цикл. Если проход падает несколько раз подряд (например, потеряно соединение с БД), процесс завершается
    с ошибкой, чтобы его перезапустил супервизор (docker restart policy) с новым соединением."""
    errors = 0
    while not should_stop():
        try:
            for r in run_due(pipe):
                (log.info if r["ok"] else log.warning)("source run %s", json.dumps(r, ensure_ascii=False))
            errors = 0
        except Exception:  # noqa: BLE001
            errors += 1
            log.exception("проход расписания завершился ошибкой (%d подряд)", errors)
            if errors >= max_consecutive_errors:
                raise
        waited = 0.0
        while waited < tick_s and not should_stop():
            step = min(1.0, tick_s - waited)
            sleep(step)
            waited += step
