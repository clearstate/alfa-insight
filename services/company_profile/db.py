"""Хранилище company_profile: PostgreSQL (основное) и SQLite (локальная разработка и тесты без Docker).

Схема описана один раз (TABLES); DDL генерируется под диалект. Для PostgreSQL всё лежит в схеме `company_profile`,
JSON-поля — JSONB с GIN-индексами для поиска по ОКВЭД и темам. Справочная копия DDL: db/schema.postgres.sql.

Стратегия загрузки — полная перезагрузка в одной транзакции: читатели не видят частичного состояния.
Каждая загрузка записывается в etl_runs (run_id, статус, статистика качества, хэш правил).

URL подключения:
  postgresql://user:password@host:5432/dbname   (драйвер psycopg 3)
  sqlite:///path/to/file.db  |  sqlite:///:memory:
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .loader import COMPANY_COLUMNS
from .validation import MARK_FIELDS, CleanData, Issue, ValidationReport

SCHEMA = "company_profile"
MIGRATION_VERSION = "0001_init"


# --- описание схемы -----------------------------------------------------------
@dataclass(frozen=True)
class Column:
    name: str
    kind: str  # text | int | bigint | float | bool | json | timestamptz
    nullable: bool = True


@dataclass(frozen=True)
class Index:
    name: str
    columns: tuple[str, ...]
    gin: bool = False  # только PostgreSQL; в SQLite не создаётся


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    indexes: tuple[Index, ...] = ()

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


def _company_columns() -> tuple[Column, ...]:
    cols = [Column("synthetic_u", "text", nullable=False)]
    for c in COMPANY_COLUMNS[1:]:
        kind = "bool" if c in MARK_FIELDS else "float" if c == "REVENUE_COMPANY" else "text"
        cols.append(Column(c.lower(), kind))
    cols.append(Column("source_line", "int", nullable=False))
    return tuple(cols)


T = {t.name: t for t in (
    Table("schema_migrations", (Column("version", "text", False), Column("applied_at", "timestamptz", False)),
          ("version",)),
    Table("etl_runs", (
        Column("run_id", "text", False), Column("status", "text", False),
        Column("started_at", "timestamptz", False), Column("finished_at", "timestamptz"),
        Column("source_files", "json"), Column("stats", "json"), Column("counters", "json"),
        Column("samples", "json"), Column("rules_hash", "text"), Column("schema_version", "text"),
        Column("error", "text"),
    ), ("run_id",), (Index("etl_runs_status_idx", ("status", "finished_at")),)),
    Table("companies", _company_columns(), ("synthetic_u",), (
        Index("companies_group_idx", ("group_id",)),
        Index("companies_okved_idx", ("mainokved_code",)),
        Index("companies_region_idx", ("region",)),
    )),
    Table("quarantined_companies", (Column("company_id", "text", False), Column("source_lines", "json", False)),
          ("company_id",)),
    Table("company_issues", (
        Column("company_id", "text", False), Column("issue_no", "int", False), Column("code", "text", False),
        Column("field", "text"), Column("message", "text", False), Column("source_file", "text", False),
        Column("lines", "json", False),
    ), ("company_id", "issue_no"), (Index("company_issues_code_idx", ("code",)),)),
    Table("person_links", (
        Column("synthetic_f", "text", False), Column("synthetic_u", "text", False),
        Column("source_line", "int", False),
    ), ("synthetic_f", "synthetic_u"), (Index("person_links_company_idx", ("synthetic_u",)),)),
    Table("payments", (
        Column("payer", "text", False), Column("beneficiary", "text", False), Column("pay_amt", "float", False),
        Column("pay_cnt", "bigint", False), Column("source_line", "int", False), Column("n_rows", "int", False),
    ), ("payer", "beneficiary"), (Index("payments_beneficiary_idx", ("beneficiary",)),)),
    Table("self_payments", (
        Column("company_id", "text", False), Column("pay_amt", "float", False), Column("pay_cnt", "bigint", False),
        Column("n_rows", "int", False),
    ), ("company_id",)),
    Table("users", (
        Column("user_id", "text", False), Column("role", "text", False), Column("display_name", "text"),
        Column("synthetic", "bool", False), Column("priority_topics", "json"),
    ), ("user_id",)),
    Table("user_companies", (Column("user_id", "text", False), Column("company_id", "text", False)),
          ("user_id", "company_id"), (Index("user_companies_company_idx", ("company_id",)),)),
    Table("company_profiles", (
        Column("company_id", "text", False), Column("run_id", "text", False),
        Column("schema_version", "text", False), Column("built_at", "timestamptz", False),
        Column("is_large_business", "bool"), Column("okved_code", "text"), Column("okved_section", "text"),
        Column("region", "text"), Column("okved_levels", "json", False), Column("topic_names", "json", False),
        Column("profile", "json", False),
    ), ("company_id",), (
        Index("company_profiles_okved_levels_gin", ("okved_levels",), gin=True),
        Index("company_profiles_topics_gin", ("topic_names",), gin=True),
        Index("company_profiles_large_idx", ("is_large_business",)),
    )),
    Table("demo_companies", (
        Column("slot", "text", False), Column("company_id", "text", False), Column("run_id", "text", False),
        Column("payload", "json", False),
    ), ("slot",)),
)}

DATA_TABLES = ("companies", "quarantined_companies", "company_issues", "person_links", "payments", "self_payments")


# --- диалекты -----------------------------------------------------------------
class Dialect:
    name = "base"
    param = "?"
    types: dict[str, str] = {}

    def table(self, name: str) -> str:
        raise NotImplementedError

    def placeholder(self, kind: str) -> str:
        return self.param

    def preamble(self) -> list[str]:
        return []

    def create_index(self, table: Table, idx: Index) -> str | None:
        cols = ", ".join(idx.columns)
        return f"CREATE INDEX IF NOT EXISTS {idx.name} ON {self.table(table.name)} ({cols})"

    def encode(self, kind: str, value: Any) -> Any:
        value = to_python(value)
        if value is None:
            return None
        if kind == "json":
            return json.dumps(value, ensure_ascii=False, default=str)
        if kind == "bool":
            return bool(value)
        if kind == "timestamptz":
            return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return value

    def decode(self, kind: str, value: Any) -> Any:
        if value is None:
            return None
        if kind == "json":
            return json.loads(value) if isinstance(value, (str, bytes)) else value
        if kind == "bool":
            return bool(value)
        if kind == "timestamptz":
            return value.isoformat() if isinstance(value, datetime) else str(value)
        if kind == "float":
            return float(value)
        if kind in ("int", "bigint"):
            return int(value)
        return value

    def clear(self, cur, table: str) -> None:
        cur.execute(f"DELETE FROM {self.table(table)}")

    def bulk_insert(self, cur, table: Table, rows: Iterable[tuple]) -> int:
        cols = table.column_names
        ph = ", ".join(self.placeholder(c.kind) for c in table.columns)
        sql = f"INSERT INTO {self.table(table.name)} ({', '.join(cols)}) VALUES ({ph})"
        n = 0
        batch: list[tuple] = []
        for row in rows:
            batch.append(row)
            if len(batch) >= 10_000:
                cur.executemany(sql, batch)
                n += len(batch)
                batch = []
        if batch:
            cur.executemany(sql, batch)
            n += len(batch)
        return n


class PostgresDialect(Dialect):
    name = "postgres"
    param = "%s"
    types = {"text": "TEXT", "int": "INTEGER", "bigint": "BIGINT", "float": "DOUBLE PRECISION",
             "bool": "BOOLEAN", "json": "JSONB", "timestamptz": "TIMESTAMPTZ"}

    def table(self, name: str) -> str:
        return f"{SCHEMA}.{name}"

    def placeholder(self, kind: str) -> str:
        return "%s::jsonb" if kind == "json" else "%s"

    def preamble(self) -> list[str]:
        return [f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"]

    def create_index(self, table: Table, idx: Index) -> str | None:
        using = " USING GIN" if idx.gin else ""
        return f"CREATE INDEX IF NOT EXISTS {idx.name} ON {self.table(table.name)}{using} ({', '.join(idx.columns)})"

    def clear(self, cur, table: str) -> None:
        cur.execute(f"TRUNCATE {self.table(table)}")

    def bulk_insert(self, cur, table: Table, rows: Iterable[tuple]) -> int:
        """COPY FROM STDIN (psycopg 3). JSON уже сериализован в строку — в текстовом COPY это валидный jsonb."""
        cols = ", ".join(table.column_names)
        n = 0
        with cur.copy(f"COPY {self.table(table.name)} ({cols}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
                n += 1
        return n


class SQLiteDialect(Dialect):
    name = "sqlite"
    param = "?"
    types = {"text": "TEXT", "int": "INTEGER", "bigint": "INTEGER", "float": "REAL", "bool": "INTEGER",
             "json": "TEXT", "timestamptz": "TEXT"}

    def table(self, name: str) -> str:
        return f"{SCHEMA}_{name}"

    def create_index(self, table: Table, idx: Index) -> str | None:
        if idx.gin:
            return None
        return f"CREATE INDEX IF NOT EXISTS {idx.name} ON {self.table(table.name)} ({', '.join(idx.columns)})"

    def encode(self, kind: str, value: Any) -> Any:
        value = super().encode(kind, value)
        if value is None:
            return None
        if kind == "bool":
            return int(value)
        if kind == "timestamptz":
            return value.isoformat()
        return value


def render_ddl(dialect: Dialect) -> list[str]:
    stmts = list(dialect.preamble())
    for t in T.values():
        cols = [f"{c.name} {dialect.types[c.kind]}{'' if c.nullable else ' NOT NULL'}" for c in t.columns]
        cols.append(f"PRIMARY KEY ({', '.join(t.primary_key)})")
        stmts.append(f"CREATE TABLE IF NOT EXISTS {dialect.table(t.name)} (\n    " + ",\n    ".join(cols) + "\n)")
        for idx in t.indexes:
            sql = dialect.create_index(t, idx)
            if sql:
                stmts.append(sql)
    return stmts


def to_python(v: Any) -> Any:
    """numpy/pandas -> встроенные типы Python; NaN -> None."""
    if v is None or v is pd.NA:
        return None
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        v = float(v)
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


# --- хранилище ------------------------------------------------------------------
class SqlStore:
    def __init__(self, conn, dialect: Dialect):
        self.conn = conn
        self.dialect = dialect

    @classmethod
    def connect(cls, url: str) -> "SqlStore":
        if url.startswith(("postgresql://", "postgres://")):
            import psycopg  # psycopg 3

            return cls(psycopg.connect(url), PostgresDialect())
        if url.startswith("sqlite:///"):
            import sqlite3

            return cls(sqlite3.connect(url[len("sqlite:///"):]), SQLiteDialect())
        raise ValueError("Поддерживаются postgresql://... и sqlite:///...")

    def close(self) -> None:
        self.conn.close()

    def _t(self, name: str) -> str:
        return self.dialect.table(name)

    def _rows(self, table: str, where: str = "", params: tuple = (), order: str = "") -> list[dict]:
        t = T[table]
        sql = f"SELECT {', '.join(t.column_names)} FROM {self._t(table)} {where} {order}"
        cur = self.conn.cursor()
        cur.execute(sql, params)
        out = []
        for row in cur.fetchall():
            out.append({c.name: self.dialect.decode(c.kind, v) for c, v in zip(t.columns, row)})
        return out

    def _insert(self, cur, table: str, records: Iterable[dict]) -> int:
        t = T[table]
        rows = (tuple(self.dialect.encode(c.kind, r.get(c.name)) for c in t.columns) for r in records)
        return self.dialect.bulk_insert(cur, t, rows)

    # --- миграции -------------------------------------------------------------
    def migrate(self) -> None:
        cur = self.conn.cursor()
        for stmt in render_ddl(self.dialect):
            cur.execute(stmt)
        p = self.dialect.param
        cur.execute(
            f"INSERT INTO {self._t('schema_migrations')} (version, applied_at) VALUES ({p}, {p}) "
            "ON CONFLICT (version) DO NOTHING",
            (MIGRATION_VERSION, self.dialect.encode("timestamptz", datetime.now(timezone.utc))),
        )
        self.conn.commit()

    # --- прогоны ETL ----------------------------------------------------------
    def start_run(self, run_id: str, source_files: dict, rules_hash: str, schema_version: str) -> None:
        cur = self.conn.cursor()
        self._insert(cur, "etl_runs", [{
            "run_id": run_id, "status": "running", "started_at": datetime.now(timezone.utc),
            "source_files": source_files, "rules_hash": rules_hash, "schema_version": schema_version,
        }])
        self.conn.commit()

    def _update_run(self, cur, run_id: str, **fields: Any) -> None:
        kinds = {c.name: c.kind for c in T["etl_runs"].columns}
        sets = ", ".join(f"{k} = {self.dialect.placeholder(kinds[k])}" for k in fields)
        params = tuple(self.dialect.encode(kinds[k], v) for k, v in fields.items()) + (run_id,)
        cur.execute(f"UPDATE {self._t('etl_runs')} SET {sets} WHERE run_id = {self.dialect.param}", params)

    def finish_run(self, cur, run_id: str, report: ValidationReport) -> None:
        rep = report.as_dict()
        self._update_run(cur, run_id, status="success", finished_at=datetime.now(timezone.utc),
                         stats=rep["stats"], counters=rep["counters"], samples=rep["samples"])

    def fail_run(self, run_id: str, error: str) -> None:
        cur = self.conn.cursor()
        self._update_run(cur, run_id, status="failed", finished_at=datetime.now(timezone.utc), error=error[:4000])
        self.conn.commit()

    def latest_run(self) -> dict | None:
        p = self.dialect.param
        rows = self._rows("etl_runs", f"WHERE status = {p}", ("success",), "ORDER BY finished_at DESC")
        return rows[0] if rows else None

    # --- данные ---------------------------------------------------------------
    def save_clean_data(self, cur, clean: CleanData) -> dict[str, int]:
        for name in DATA_TABLES:
            self.dialect.clear(cur, name)
        counts: dict[str, int] = {}
        comp = clean.companies
        src_cols = COMPANY_COLUMNS + ["_line"]
        dst_cols = [c.lower() for c in COMPANY_COLUMNS] + ["source_line"]
        counts["companies"] = self._insert(cur, "companies", (
            dict(zip(dst_cols, row)) for row in comp[src_cols].itertuples(index=False, name=None)))
        counts["quarantined_companies"] = self._insert(cur, "quarantined_companies", (
            {"company_id": k, "source_lines": v} for k, v in clean.quarantined.items()))
        counts["company_issues"] = self._insert(cur, "company_issues", (
            {"company_id": cid, "issue_no": i, "code": iss.code, "field": iss.field, "message": iss.message,
             "source_file": iss.source_file, "lines": iss.lines}
            for cid, issues in clean.company_issues.items() for i, iss in enumerate(issues)))
        counts["person_links"] = self._insert(cur, "person_links", (
            {"synthetic_f": f, "synthetic_u": u, "source_line": ln}
            for f, u, ln in clean.persons[["SYNTHETIC_F", "SYNTHETIC_U", "_line"]].itertuples(index=False, name=None)))
        p = clean.payments[["PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT", "_line", "n_rows"]]
        counts["payments"] = self._insert(cur, "payments", (
            {"payer": a, "beneficiary": b, "pay_amt": amt, "pay_cnt": cnt, "source_line": ln, "n_rows": n}
            for a, b, amt, cnt, ln, n in p.itertuples(index=False, name=None)))
        sp = clean.self_payments.reset_index()
        counts["self_payments"] = self._insert(cur, "self_payments", (
            {"company_id": cid, "pay_amt": amt, "pay_cnt": cnt, "n_rows": n}
            for cid, amt, cnt, n in sp[["company_id", "PAY_AMT", "PAY_CNT", "n_rows"]].itertuples(index=False,
                                                                                                    name=None)))
        return counts

    def load_clean_data(self, run: dict) -> CleanData:
        comp_rows = self._rows("companies", order="ORDER BY source_line")
        comp = pd.DataFrame.from_records(comp_rows, columns=T["companies"].column_names)
        comp = comp.rename(columns={c.lower(): c for c in COMPANY_COLUMNS} | {"source_line": "_line"})
        for c in COMPANY_COLUMNS:
            if c == "REVENUE_COMPANY":
                comp[c] = pd.to_numeric(comp[c], errors="coerce").astype(float)
            else:
                comp[c] = comp[c].astype(object).where(comp[c].notna(), None)
        comp["_line"] = comp["_line"].astype(np.int64)
        comp = comp.set_index("SYNTHETIC_U", drop=False)
        comp.index.name = "company_id"

        quarantined = {r["company_id"]: list(r["source_lines"]) for r in self._rows("quarantined_companies")}
        issues: dict[str, list[Issue]] = {}
        for r in self._rows("company_issues", order="ORDER BY company_id, issue_no"):
            issues.setdefault(r["company_id"], []).append(
                Issue(r["code"], r["message"], r["source_file"], r["company_id"], r["field"], list(r["lines"])))

        pl = self._rows("person_links", order="ORDER BY source_line")
        persons = pd.DataFrame({
            "SYNTHETIC_F": [r["synthetic_f"] for r in pl], "SYNTHETIC_U": [r["synthetic_u"] for r in pl],
            "_line": np.array([r["source_line"] for r in pl], dtype=np.int64),
        })

        cur = self.conn.cursor()
        cur.execute(f"SELECT payer, beneficiary, pay_amt, pay_cnt, source_line, n_rows FROM {self._t('payments')} "
                    "ORDER BY source_line")
        prow = cur.fetchall()
        payments = pd.DataFrame.from_records(prow, columns=["PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT", "_line",
                                                            "n_rows"])
        payments = payments.astype({"PAY_AMT": float, "PAY_CNT": np.int64, "_line": np.int64, "n_rows": np.int64})

        sp = self._rows("self_payments", order="ORDER BY company_id")
        self_payments = pd.DataFrame({
            "PAY_AMT": [r["pay_amt"] for r in sp], "PAY_CNT": np.array([r["pay_cnt"] for r in sp], dtype=np.int64),
            "n_rows": np.array([r["n_rows"] for r in sp], dtype=np.int64),
        }, index=pd.Index([r["company_id"] for r in sp], name="company_id"))

        report = ValidationReport()
        report.stats.update(run.get("stats") or {})
        report.counters.update(run.get("counters") or {})
        for code, items in (run.get("samples") or {}).items():
            report.samples[code] = [Issue(i["code"], i["message"], i["source_file"], i.get("company_id"),
                                          i.get("field"), list(i.get("lines") or [])) for i in items]
        files = run.get("source_files") or {}
        return CleanData(companies=comp, quarantined=quarantined, company_issues=issues, persons=persons,
                         payments=payments, self_payments=self_payments, report=report, files=files)

    # --- пользователи ---------------------------------------------------------
    def save_users(self, cur, users: list[dict]) -> int:
        self.dialect.clear(cur, "user_companies")
        self.dialect.clear(cur, "users")
        n = self._insert(cur, "users", ({
            "user_id": u["user_id"], "role": u["role"], "display_name": u.get("display_name"),
            "synthetic": bool(u.get("synthetic", True)), "priority_topics": u.get("priority_topics"),
        } for u in users))
        self._insert(cur, "user_companies", (
            {"user_id": u["user_id"], "company_id": c} for u in users for c in dict.fromkeys(u["company_ids"])))
        return n

    def load_users(self) -> list[dict]:
        links: dict[str, list[str]] = {}
        for r in self._rows("user_companies", order="ORDER BY user_id, company_id"):
            links.setdefault(r["user_id"], []).append(r["company_id"])
        return [{**u, "company_ids": links.get(u["user_id"], [])}
                for u in self._rows("users", order="ORDER BY user_id")]

    # --- материализованные профили и демо -------------------------------------
    def save_profiles(self, cur, profiles: Iterable[dict], run_id: str) -> int:
        self.dialect.clear(cur, "company_profiles")

        def rows():
            for p in profiles:
                yield {
                    "company_id": p["company_id"], "run_id": run_id, "schema_version": p["schema_version"],
                    "built_at": p["built_at"], "is_large_business": p["size"]["is_large_business"]["value"],
                    "okved_code": p["industry"]["okved_code"]["value"],
                    "okved_section": p["industry"]["okved_section"]["value"],
                    "region": p["geography"]["region"]["value"],
                    "okved_levels": p["industry"]["okved_levels"]["value"] or [],
                    "topic_names": [t["topic"] for t in p["topics"]], "profile": p,
                }

        return self._insert(cur, "company_profiles", rows())

    def get_profile(self, company_id: str) -> dict | None:
        rows = self._rows("company_profiles", f"WHERE company_id = {self.dialect.param}", (company_id,))
        return rows[0]["profile"] if rows else None

    def save_demo(self, cur, demo: list[dict], run_id: str) -> int:
        self.dialect.clear(cur, "demo_companies")
        return self._insert(cur, "demo_companies", (
            {"slot": d["slot"], "company_id": d["company_id"], "run_id": run_id, "payload": d} for d in demo))

    def count(self, table: str) -> int:
        cur = self.conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {self._t(table)}")
        return int(cur.fetchone()[0])
