"""Хранилище news_ingest: SQLite (dev/тесты) и PostgreSQL (прод) с одним набором SQL. Схема PG — `news_ingest`.

Даты хранятся как ISO-8601 UTC TEXT (сортируются лексикографически), JSON — как TEXT. Фильтры по темам/отраслям/регионам —
через связующие таблицы item_topics/item_industries/item_regions (индексируемые в обоих диалектах); tsvector-поиск добавляет участник 4.
PostgreSQL-ветка (psycopg) в этой среде НЕ запускалась (нет драйвера и сервера) — проверять на docker compose.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

from .models import Chunk, Indicator, NewsItem
from .textutil import now_iso

SCHEMA_VERSION = 1

# (имя таблицы, колонки [(имя, тип, ограничения)], ограничения-таблицы, индексы [(имя, колонки)])
TABLES: list[tuple[str, list[tuple[str, str, str]], list[str], list[tuple[str, str]]]] = [
    ("sources", [("id", "text", "PRIMARY KEY"), ("type", "text", "NOT NULL"), ("name", "text", ""), ("method", "text", ""),
                 ("url", "text", ""), ("reliability_score", "real", ""), ("reliability_rule", "text", ""),
                 ("enabled", "int", "DEFAULT 1"), ("verified_at", "text", ""), ("last_success_at", "text", ""),
                 ("last_error_at", "text", "")], [], []),
    ("raw_documents", [("id", "text", "PRIMARY KEY"), ("source_id", "text", "NOT NULL"), ("url", "text", ""),
                       ("content_type", "text", ""), ("sha256", "text", "NOT NULL"), ("byte_size", "int", ""),
                       ("http_status", "int", ""), ("fetched_at", "text", "NOT NULL"), ("body", "blob", "")],
     ["UNIQUE (source_id, url, sha256)"], [("ix_raw_sha", "sha256")]),
    ("news_items", [("id", "text", "PRIMARY KEY"), ("url_key", "text", "NOT NULL UNIQUE"), ("source_id", "text", "NOT NULL"),
                    ("source_type", "text", "NOT NULL"), ("document_type", "text", "NOT NULL"), ("title", "text", ""),
                    ("published_at", "text", ""), ("event_date", "text", ""), ("retrieved_at", "text", "NOT NULL"),
                    ("content_hash", "text", "NOT NULL"), ("version", "int", "NOT NULL DEFAULT 1"),
                    ("processing_status", "text", "NOT NULL"), ("event_cluster_id", "text", ""), ("dup_of", "text", ""),
                    ("language", "text", ""), ("reliability_score", "real", ""), ("item_json", "text", "NOT NULL"),
                    ("minhash", "text", ""), ("created_at", "text", "NOT NULL"), ("updated_at", "text", "NOT NULL"),
                    ("last_seen_at", "text", "NOT NULL")], [],
     [("ix_items_pub", "published_at"), ("ix_items_hash", "content_hash"), ("ix_items_cluster", "event_cluster_id"),
      ("ix_items_src", "source_type, published_at")]),
    ("news_versions", [("item_id", "text", "NOT NULL"), ("version", "int", "NOT NULL"), ("content_hash", "text", "NOT NULL"),
                       ("replaced_at", "text", "NOT NULL"), ("item_json", "text", "NOT NULL")],
     ["PRIMARY KEY (item_id, version)"], []),
    ("event_clusters", [("id", "text", "PRIMARY KEY"), ("label", "text", ""), ("event_date", "text", ""),
                        ("member_count", "int", "NOT NULL DEFAULT 1"), ("conflicts", "text", ""),
                        ("created_at", "text", "NOT NULL"), ("updated_at", "text", "NOT NULL")], [], []),
    ("chunks", [("id", "text", "PRIMARY KEY"), ("news_item_id", "text", "NOT NULL"), ("idx", "int", "NOT NULL"),
                ("page", "int", ""), ("kind", "text", ""), ("claim_type", "text", ""), ("topics", "text", ""),
                ("text", "text", "NOT NULL")], [], [("ix_chunks_item", "news_item_id, idx")]),
    ("item_topics", [("item_id", "text", "NOT NULL"), ("topic", "text", "NOT NULL"), ("score", "real", "")],
     ["PRIMARY KEY (item_id, topic)"], [("ix_topics_topic", "topic")]),
    ("item_industries", [("item_id", "text", "NOT NULL"), ("okved_prefix", "text", "NOT NULL")],
     ["PRIMARY KEY (item_id, okved_prefix)"], [("ix_ind_prefix", "okved_prefix")]),
    ("item_regions", [("item_id", "text", "NOT NULL"), ("region", "text", "NOT NULL")],
     ["PRIMARY KEY (item_id, region)"], [("ix_reg_region", "region")]),
    ("macro_indicators", [("id", "serial", "PRIMARY KEY"), ("item_id", "text", "NOT NULL"), ("indicator", "text", "NOT NULL"),
                          ("label", "text", ""), ("period", "text", "NOT NULL"), ("value", "real", ""), ("unit", "text", ""),
                          ("is_forecast", "int", "NOT NULL"), ("page", "int", ""), ("published_at", "text", ""),
                          ("table_name", "text", "")], [],
     [("ix_macro_ind", "indicator, period"), ("ix_macro_item", "item_id")]),
    ("pipeline_errors", [("id", "serial", "PRIMARY KEY"), ("occurred_at", "text", "NOT NULL"), ("source_id", "text", ""),
                         ("url", "text", ""), ("stage", "text", "NOT NULL"), ("code", "text", "NOT NULL"),
                         ("message", "text", ""), ("correlation_id", "text", ""), ("details", "text", "")], [],
     [("ix_err_time", "occurred_at")]),
    ("ingest_events", [("id", "serial", "PRIMARY KEY"), ("at", "text", "NOT NULL"), ("item_id", "text", "NOT NULL"),
                       ("event_type", "text", "NOT NULL"), ("version", "int", "")], [], []),
    ("llm_cache", [("key", "text", "PRIMARY KEY"), ("model", "text", ""), ("prompt_version", "text", ""),
                   ("response", "text", "NOT NULL"), ("tokens_in", "int", ""), ("tokens_out", "int", ""),
                   ("created_at", "text", "NOT NULL")], [], []),
    ("llm_usage", [("id", "serial", "PRIMARY KEY"), ("at", "text", "NOT NULL"), ("module", "text", "NOT NULL"),
                   ("model", "text", ""), ("tokens_in", "int", ""), ("tokens_out", "int", ""), ("cached", "int", "NOT NULL")],
     [], [("ix_usage_at", "at")]),
]

PG_SCHEMA = "news_ingest"


def render_ddl(dialect: str) -> list[str]:
    pg = dialect == "postgres"
    tmap = {"text": "TEXT", "int": "BIGINT" if pg else "INTEGER", "real": "DOUBLE PRECISION" if pg else "REAL",
            "blob": "BYTEA" if pg else "BLOB"}
    out: list[str] = []
    if pg:
        out.append(f"CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA}")
    q = (lambda n: f"{PG_SCHEMA}.{n}") if pg else (lambda n: n)
    for name, cols, cons, idx in TABLES:
        parts = []
        for cn, ct, cc in cols:
            if ct == "serial":
                parts.append(f"{cn} " + ("BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"))
            else:
                parts.append(f"{cn} {tmap[ct]} {cc}".strip())
        parts += cons
        out.append(f"CREATE TABLE IF NOT EXISTS {q(name)} (\n  " + ",\n  ".join(parts) + "\n)")
        for iname, icols in idx:
            out.append(f"CREATE INDEX IF NOT EXISTS {iname} ON {q(name)} ({icols})")
    return out


class NewsStore:
    def __init__(self, url: str = "sqlite:///:memory:"):
        self.url = url
        self._lock = threading.RLock()
        if url.startswith("sqlite"):
            path = url.split("sqlite:///", 1)[1] or ":memory:"
            self.dialect = "sqlite"
            self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys=ON")
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
        else:  # pragma: no cover - требует psycopg и сервер PostgreSQL
            import psycopg  # type: ignore
            from psycopg.rows import dict_row  # type: ignore
            self.dialect = "postgres"
            self._conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)
        self._in_tx = 0

    # ---- низкоуровневое ----
    def _sql(self, sql: str) -> str:
        if self.dialect == "postgres":  # pragma: no cover
            sql = sql.replace("?", "%s")
            for name, *_ in TABLES:
                sql = _qualify(sql, name)
        return sql

    def execute(self, sql: str, params: Iterable[Any] = ()) -> Any:
        with self._lock:
            return self._conn.execute(self._sql(sql), tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(self._sql(sql), tuple(params))
            return [dict(r) for r in cur.fetchall()]

    @contextmanager
    def tx(self) -> Iterator[None]:
        with self._lock:
            if self._in_tx:
                self._in_tx += 1
                try:
                    yield
                finally:
                    self._in_tx -= 1
                return
            self.execute("BEGIN")
            self._in_tx = 1
            try:
                yield
                self.execute("COMMIT")
            except BaseException:
                self.execute("ROLLBACK")
                raise
            finally:
                self._in_tx = 0

    def init_schema(self) -> None:
        for stmt in render_ddl(self.dialect):
            with self._lock:
                self._conn.execute(stmt)

    # ---- источники / сырьё ----
    def upsert_source(self, s: dict[str, Any]) -> None:
        rel = s.get("reliability", {})
        self.execute("INSERT INTO sources (id,type,name,method,url,reliability_score,reliability_rule,enabled,verified_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET type=excluded.type,name=excluded.name,"
                     "method=excluded.method,url=excluded.url,reliability_score=excluded.reliability_score,"
                     "reliability_rule=excluded.reliability_rule,enabled=excluded.enabled,verified_at=excluded.verified_at",
                     (s["id"], s["type"], s.get("name"), s.get("method"), s.get("url"), rel.get("score"), rel.get("rule"),
                      1 if s.get("enabled", True) else 0, s.get("verified_at")))

    def touch_source(self, source_id: str, ok: bool) -> None:
        col = "last_success_at" if ok else "last_error_at"
        self.execute(f"UPDATE sources SET {col}=? WHERE id=?", (now_iso(), source_id))

    def add_raw(self, raw_id: str, source_id: str, url: str | None, content_type: str | None, sha256: str, body: bytes | None,
                fetched_at: str, http_status: int | None = None) -> bool:
        """Идемпотентно: (source_id, url, sha256) уникален. True если запись новая."""
        cur = self.execute("INSERT INTO raw_documents (id,source_id,url,content_type,sha256,byte_size,http_status,fetched_at,body) "
                           "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                           (raw_id, source_id, url, content_type, sha256, len(body or b""), http_status, fetched_at, body))
        return bool(getattr(cur, "rowcount", 1))

    # ---- элементы ----
    def get_by_url_key(self, url_key: str) -> dict[str, Any] | None:
        r = self.query("SELECT * FROM news_items WHERE url_key=?", (url_key,))
        return r[0] if r else None

    def get_row(self, item_id: str) -> dict[str, Any] | None:
        r = self.query("SELECT * FROM news_items WHERE id=?", (item_id,))
        return r[0] if r else None

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        r = self.get_row(item_id)
        return json.loads(r["item_json"]) if r else None

    def find_by_hash(self, content_hash: str, exclude_id: str | None = None) -> dict[str, Any] | None:
        r = self.query("SELECT * FROM news_items WHERE content_hash=? AND COALESCE(dup_of,'')='' AND id<>? ORDER BY created_at LIMIT 1",
                       (content_hash, exclude_id or ""))
        return r[0] if r else None

    def recent_for_clustering(self, since_iso: str, exclude_id: str) -> list[dict[str, Any]]:
        return self.query("SELECT id,title,published_at,event_date,minhash,event_cluster_id,source_type,item_json FROM news_items "
                          "WHERE COALESCE(published_at, retrieved_at) >= ? AND id<>? AND source_type<>'bank_analytics' "
                          "AND COALESCE(dup_of,'')=''", (since_iso, exclude_id))

    def save_item(self, item: NewsItem, minhash: list[int], chunks: list[Chunk], indicators: list[Indicator],
                  is_new: bool, prev_row: dict[str, Any] | None = None) -> None:
        d = item.to_dict()
        now = now_iso()
        with self.tx():
            if prev_row is not None:
                self.execute("INSERT INTO news_versions (item_id,version,content_hash,replaced_at,item_json) VALUES (?,?,?,?,?) "
                             "ON CONFLICT(item_id,version) DO NOTHING",
                             (item.id, prev_row["version"], prev_row["content_hash"], now, prev_row["item_json"]))
            if is_new:
                self.execute("INSERT INTO news_items (id,url_key,source_id,source_type,document_type,title,published_at,event_date,"
                             "retrieved_at,content_hash,version,processing_status,event_cluster_id,dup_of,language,reliability_score,"
                             "item_json,minhash,created_at,updated_at,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (item.id, d["provenance"]["url_key"], item.source_id, item.source_type, item.document_type, item.title,
                              item.published_at, item.event_date, item.retrieved_at, item.content_hash, item.version,
                              item.processing_status, item.event_cluster_id, item.dup_of, item.language,
                              item.source_reliability.get("score"), json.dumps(d, ensure_ascii=False), json.dumps(minhash),
                              now, now, now))
            else:
                self.execute("UPDATE news_items SET source_id=?,source_type=?,document_type=?,title=?,published_at=?,event_date=?,"
                             "retrieved_at=?,content_hash=?,version=?,processing_status=?,event_cluster_id=?,dup_of=?,language=?,"
                             "reliability_score=?,item_json=?,minhash=?,updated_at=?,last_seen_at=? WHERE id=?",
                             (item.source_id, item.source_type, item.document_type, item.title, item.published_at, item.event_date,
                              item.retrieved_at, item.content_hash, item.version, item.processing_status, item.event_cluster_id,
                              item.dup_of, item.language, item.source_reliability.get("score"),
                              json.dumps(d, ensure_ascii=False), json.dumps(minhash), now, now, item.id))
            for t in ("chunks", "item_topics", "item_industries", "item_regions", "macro_indicators"):
                col = "news_item_id" if t == "chunks" else "item_id"
                self.execute(f"DELETE FROM {t} WHERE {col}=?", (item.id,))
            for c in chunks:
                self.execute("INSERT INTO chunks (id,news_item_id,idx,page,kind,claim_type,topics,text) VALUES (?,?,?,?,?,?,?,?)",
                             (c.id, c.news_item_id, c.idx, c.page, c.kind, c.claim_type, json.dumps(c.topics), c.text))
            for t, sc in item.topic_scores.items():
                self.execute("INSERT INTO item_topics (item_id,topic,score) VALUES (?,?,?)", (item.id, t, sc))
            for p in item.industries.get("okved_prefixes", []):
                self.execute("INSERT INTO item_industries (item_id,okved_prefix) VALUES (?,?)", (item.id, p))
            for r in item.regions:
                self.execute("INSERT INTO item_regions (item_id,region) VALUES (?,?)", (item.id, r))
            for i in indicators:
                self.execute("INSERT INTO macro_indicators (item_id,indicator,label,period,value,unit,is_forecast,page,published_at,"
                             "table_name) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (i.item_id, i.indicator, i.label, i.period, i.value, i.unit, 1 if i.is_forecast else 0, i.page,
                              i.published_at, i.table))

    def touch_seen(self, item_id: str) -> None:
        self.execute("UPDATE news_items SET last_seen_at=? WHERE id=?", (now_iso(), item_id))

    def save_duplicate_marker(self, item_id: str, dup_of: str) -> None:
        self.execute("UPDATE news_items SET dup_of=?, processing_status='duplicate', updated_at=? WHERE id=?", (dup_of, now_iso(), item_id))

    # ---- кластеры ----
    def get_cluster(self, cid: str) -> dict[str, Any] | None:
        r = self.query("SELECT * FROM event_clusters WHERE id=?", (cid,))
        return r[0] if r else None

    def upsert_cluster(self, cid: str, label: str | None, event_date: str | None, member_count: int,
                       conflicts: list[dict[str, Any]]) -> None:
        now = now_iso()
        self.execute("INSERT INTO event_clusters (id,label,event_date,member_count,conflicts,created_at,updated_at) VALUES (?,?,?,?,?,?,?) "
                     "ON CONFLICT(id) DO UPDATE SET label=excluded.label,event_date=excluded.event_date,"
                     "member_count=excluded.member_count,conflicts=excluded.conflicts,updated_at=excluded.updated_at",
                     (cid, label, event_date, member_count, json.dumps(conflicts, ensure_ascii=False), now, now))

    def cluster_members(self, cid: str) -> list[dict[str, Any]]:
        return self.query("SELECT id,title,published_at,item_json,dup_of FROM news_items WHERE event_cluster_id=? ORDER BY published_at", (cid,))

    # ---- журналы ----
    def add_error(self, stage: str, code: str, message: str, source_id: str | None = None, url: str | None = None,
                  correlation_id: str | None = None, details: dict[str, Any] | None = None) -> None:
        self.execute("INSERT INTO pipeline_errors (occurred_at,source_id,url,stage,code,message,correlation_id,details) VALUES (?,?,?,?,?,?,?,?)",
                     (now_iso(), source_id, url, stage, code, (message or "")[:2000], correlation_id,
                      json.dumps(details or {}, ensure_ascii=False)))

    def add_event(self, item_id: str, event_type: str, version: int | None) -> None:
        self.execute("INSERT INTO ingest_events (at,item_id,event_type,version) VALUES (?,?,?,?)", (now_iso(), item_id, event_type, version))

    def changes_since(self, last_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM ingest_events WHERE id>? ORDER BY id LIMIT ?", (last_id, limit))

    def errors(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM pipeline_errors ORDER BY id DESC LIMIT ?", (limit,))

    # ---- LLM кеш/расход ----
    def llm_cache_get(self, key: str) -> dict[str, Any] | None:
        r = self.query("SELECT * FROM llm_cache WHERE key=?", (key,))
        return r[0] if r else None

    def llm_cache_put(self, key: str, model: str, prompt_version: str, response: str, tin: int, tout: int) -> None:
        self.execute("INSERT INTO llm_cache (key,model,prompt_version,response,tokens_in,tokens_out,created_at) VALUES (?,?,?,?,?,?,?) "
                     "ON CONFLICT(key) DO NOTHING", (key, model, prompt_version, response, tin, tout, now_iso()))

    def llm_usage_add(self, module: str, model: str | None, tin: int, tout: int, cached: bool) -> None:
        self.execute("INSERT INTO llm_usage (at,module,model,tokens_in,tokens_out,cached) VALUES (?,?,?,?,?,?)",
                     (now_iso(), module, model, tin, tout, 1 if cached else 0))

    def llm_tokens_today(self, day_prefix: str) -> int:
        r = self.query("SELECT COALESCE(SUM(tokens_in+tokens_out),0) AS n FROM llm_usage WHERE at LIKE ? AND cached=0", (day_prefix + "%",))
        return int(r[0]["n"])

    # ---- чтение для участников 3/4 ----
    def search_candidates(self, topics: list[str] | None = None, okved_prefixes: list[str] | None = None,
                          regions: list[str] | None = None, since: str | None = None, until: str | None = None,
                          source_types: list[str] | None = None, include_duplicates: bool = False,
                          limit: int = 100) -> list[dict[str, Any]]:
        """Кандидаты для ранжирования (участник 4): объединение (OR) по темам/префиксам/регионам, фильтры по дате и типу."""
        conds, params = ["1=1"], []
        if not include_duplicates:
            conds.append("COALESCE(i.dup_of,'')=''")
        rel = []
        for tbl, col, vals in (("item_topics", "topic", topics), ("item_industries", "okved_prefix", okved_prefixes),
                               ("item_regions", "region", regions)):
            if vals:
                rel.append(f"i.id IN (SELECT item_id FROM {tbl} WHERE {col} IN ({','.join('?' * len(vals))}))")
                params += list(vals)
        if rel:
            conds.append("(" + " OR ".join(rel) + ")")
        if since:
            conds.append("COALESCE(i.published_at,i.retrieved_at) >= ?"); params.append(since)
        if until:
            conds.append("COALESCE(i.published_at,i.retrieved_at) <= ?"); params.append(until)
        if source_types:
            conds.append(f"i.source_type IN ({','.join('?' * len(source_types))})"); params += list(source_types)
        rows = self.query("SELECT i.id,i.title,i.published_at,i.event_date,i.source_type,i.document_type,i.processing_status,"
                          "i.event_cluster_id,i.reliability_score,i.version FROM news_items i WHERE " + " AND ".join(conds) +
                          " ORDER BY COALESCE(i.published_at,i.retrieved_at) DESC LIMIT ?", params + [limit])
        return rows

    def list_chunks(self, item_id: str) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM chunks WHERE news_item_id=? ORDER BY idx", (item_id,))
        for r in rows:
            r["topics"] = json.loads(r["topics"] or "[]")
        return rows

    def indicators(self, indicator: str | None = None, period: str | None = None, forecast_only: bool = False) -> list[dict[str, Any]]:
        conds, params = ["1=1"], []
        if indicator:
            conds.append("indicator=?"); params.append(indicator)
        if period:
            conds.append("period=?"); params.append(period)
        if forecast_only:
            conds.append("is_forecast=1")
        return self.query("SELECT * FROM macro_indicators WHERE " + " AND ".join(conds) + " ORDER BY indicator, period, published_at", params)

    def stats(self) -> dict[str, Any]:
        q = lambda s: self.query(s)[0]["n"]
        return {"items": q("SELECT COUNT(*) AS n FROM news_items"), "chunks": q("SELECT COUNT(*) AS n FROM chunks"),
                "clusters": q("SELECT COUNT(*) AS n FROM event_clusters"), "errors": q("SELECT COUNT(*) AS n FROM pipeline_errors"),
                "indicators": q("SELECT COUNT(*) AS n FROM macro_indicators")}


def _qualify(sql: str, table: str) -> str:  # pragma: no cover
    import re
    return re.sub(rf"(?<![\w.]){table}(?![\w])", f"{PG_SCHEMA}.{table}", sql)
