"""База знаний: новости и материалы банка (через конвейер участника 2), прогнозы, якорные позиции банка, поиск BM25, календарь."""
from __future__ import annotations

import json
import logging
import math
import re
import threading
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from services.news_ingest.indicators import latest_forecasts
from services.news_ingest.pipeline import IngestPipeline
from services.news_ingest.store import NewsStore

from .settings import Settings
from .textkit import (INJECTION_RE, MONTHS, content_tokens, days_between, is_unconfirmed, jaccard, numbers, short,
                      significant_numbers)

log = logging.getLogger("insight.kb")
CONFIG = Path(__file__).parent / "config"


class KnowledgeBase:
    def __init__(self, settings: Settings):
        self.s = settings
        settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.store = NewsStore(f"sqlite:///{settings.runtime_dir / 'news.db'}")
        self.store.init_schema()
        self.pipeline = IngestPipeline(self.store)
        self.lock = threading.RLock()
        self.items: dict[str, dict[str, Any]] = {}
        self.chunks: dict[str, dict[str, Any]] = {}
        self.forecasts: dict[str, dict[str, dict[str, Any]]] = {}
        self.anchors: list[dict[str, Any]] = []
        self.anchors_rejected: list[dict[str, Any]] = []
        self.clusters: dict[str, dict[str, Any]] = {}
        self._bm: dict[str, Any] = {}
        self.version = 0

    # ------------------------------------------------------------------ загрузка
    def bootstrap(self) -> dict[str, Any]:
        """Идемпотентно: материалы банка (сайдкары), синтетические внешние новости, демонстрационный RSS."""
        stats = {"bank": 0, "news": 0, "rss": 0, "failed": 0}
        res = self.pipeline.ingest_bank_dir(self.s.root / "data" / "bank_analytics")
        stats["bank"] = len(res)
        p = self.s.news_demo_dir / "external_news.json"
        if p.exists():
            for n in json.loads(p.read_text(encoding="utf-8")):
                r = self.pipeline.ingest_text(n["text"], n["title"], source_id="manual_file", published_at=n["published_at"],
                                              publisher=n.get("publisher"))
                stats["news" if r.outcome != "failed" else "failed"] += 1
        f = self.s.news_demo_dir / "demo_feed.xml"
        if f.exists():
            for r in self.pipeline.ingest_feed_bytes("demo_rss", f.read_bytes(), "https://example.invalid/", fetch_articles=False):
                stats["rss" if r.outcome != "failed" else "failed"] += 1
        self.reload()
        return stats

    def reload(self) -> None:
        with self.lock:
            rows = self.store.query("SELECT id FROM news_items")
            items: dict[str, dict] = {}
            for r in rows:
                it = self.store.get_item(r["id"])
                if it:
                    items[it["id"]] = self._derive(it)
            chunks: dict[str, dict] = {}
            for iid, it in items.items():
                for ch in self.store.list_chunks(iid):
                    ch = dict(ch)
                    ch["item_id"] = iid
                    chunks[ch["id"]] = ch
            self.items, self.chunks = items, chunks
            self._build_clusters()
            self._load_forecasts()
            self._load_anchors()
            self._build_bm25()
            self.version += 1

    def _derive(self, it: dict) -> dict:
        bank = it.get("bank") or {}
        it["kind"] = "bank" if it.get("source_type") == "bank_analytics" else "news"
        pub = (it.get("publisher") or "")
        it["synthetic"] = "синтет" in pub.lower() or "демо" in pub.lower()
        text = (it.get("title") or "") + " " + (it.get("text") or "")
        it["unconfirmed"] = is_unconfirmed(text)
        it["injection"] = bool(INJECTION_RE.search(text)) or "prompt_injection_suspected" in (it.get("security_flags") or [])
        pa = it.get("published_at")
        it["age_days"] = days_between(pa, self.s.as_of) if pa else 9999.0
        it["stale"] = bool(bank.get("stale")) or it["age_days"] > 365
        it["display_source"] = bank.get("author_unit") or it.get("publisher") or it.get("source_id")
        it["source_file"] = bank.get("source_file")
        it["doc_title"] = bank.get("case_list_title") or it.get("title")
        return it

    def _build_clusters(self) -> None:
        """Кластеры событий: участник 2 (event_cluster_id) + доп. склейка близких по смыслу и дате публикаций разных изданий."""
        news = [i for i in self.items.values() if i["kind"] == "news" and not i.get("dup_of")]
        parent: dict[str, str] = {i["id"]: i["id"] for i in news}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        toks = {i["id"]: set(content_tokens(i["title"] + " " + (i.get("summary") or ""))) for i in news}
        for a in news:
            for b in news:
                if a["id"] >= b["id"]:
                    continue
                if abs((a["age_days"] or 0) - (b["age_days"] or 0)) > 5:
                    continue
                shared_topics = set(a["topics"][:2]) & set(b["topics"][:2])
                shared_okved = set(a["industries"]["okved_prefixes"]) & set(b["industries"]["okved_prefixes"])
                sim = jaccard(toks[a["id"]], toks[b["id"]])
                if (sim >= 0.30 and (shared_topics or shared_okved)) or (a.get("event_cluster_id") and a.get("event_cluster_id") == b.get("event_cluster_id")):
                    parent[find(a["id"])] = find(b["id"])
        groups: dict[str, list[dict]] = defaultdict(list)
        for i in news:
            groups[find(i["id"])].append(i)
        clusters: dict[str, dict] = {}
        for root, members in groups.items():
            members.sort(key=lambda m: (-(m.get("source_reliability") or {}).get("score", 0), m["age_days"]))
            primary = members[0]
            cid = "evt_" + primary["id"][5:15]
            conflict = self._cluster_conflict(members) if len(members) > 1 else None
            clusters[cid] = {"id": cid, "primary": primary["id"], "members": [m["id"] for m in members], "conflict": conflict}
            for m in members:
                m["cluster_id"] = cid
        for i in self.items.values():
            if i["kind"] == "bank":
                i["cluster_id"] = "evt_" + i["id"][5:15]
                clusters[i["cluster_id"]] = {"id": i["cluster_id"], "primary": i["id"], "members": [i["id"]], "conflict": None}
            elif i.get("dup_of") and i.get("dup_of") in self.items:
                i["cluster_id"] = self.items[i["dup_of"]].get("cluster_id")
        self.clusters = clusters

    @staticmethod
    def _cluster_conflict(members: list[dict]) -> dict | None:
        rng = []
        for m in members:
            for a, b in re.findall(r"(\d+)\s*[–-]\s*(\d+)\s*%", m.get("text") or ""):
                rng.append((m["id"], f"{a}–{b}%"))
        vals = {v for _, v in rng}
        if len(vals) > 1:
            return {"kind": "estimate_range", "values": sorted(vals), "items": sorted({i for i, _ in rng}),
                    "note": "Публикации оценивают эффект по-разному: " + " и ".join(sorted(vals)) + ". Цифры не усредняются."}
        return None

    def _load_forecasts(self) -> None:
        rows = self.store.indicators(forecast_only=True)
        self.forecasts = latest_forecasts(rows)
        try:
            from services.news_ingest.indicators import compare_forecasts
            self.forecast_conflicts = [c for c in compare_forecasts(rows) if c.get("spread")]
        except Exception:  # noqa: BLE001
            self.forecast_conflicts = []

    def indicator(self, code: str, period: str) -> dict | None:
        v = (self.forecasts.get(code) or {}).get(str(period))
        if not v:
            return None
        it = self.items.get(v["item_id"]) or {}
        out = dict(v)
        out.update({"indicator": code, "period": str(period), "doc_title": it.get("doc_title"), "source_file": it.get("source_file"),
                    "label": self._indicator_label(code)})
        return out

    @staticmethod
    def _indicator_label(code: str) -> str:
        return {
            "key_rate_eoy": "Ключевая ставка, конец года", "key_rate_avg": "Ключевая ставка, среднегодовая",
            "usd_rub_eoy": "Курс USD/RUB, конец года", "cny_rub_eoy": "Курс CNY/RUB, конец года",
            "inflation_dec_yoy": "Инфляция, декабрь к декабрю", "inflation_avg_yoy": "Инфляция, среднегодовая",
            "gdp_growth": "Рост ВВП", "wages_nominal": "Рост номинальных зарплат", "wages_real": "Рост реальных зарплат",
            "unemployment": "Безработица", "retail_turnover": "Оборот розничной торговли", "import_usd": "Импорт товаров",
            "export_usd": "Экспорт товаров", "corp_credit_growth": "Рост корпоративного кредитования",
            "retail_credit_growth": "Рост розничного кредитования", "corp_deposits_growth": "Рост корпоративных депозитов",
            "oil_urals": "Нефть Urals", "budget_balance": "Баланс бюджета", "investment_growth": "Инвестиции",
            "industrial_production": "Промпроизводство", "mortgage_growth": "Рост ипотеки",
        }.get(code, code)

    # ------------------------------------------------------------------ якорные позиции банка
    def _load_anchors(self) -> None:
        cfg = yaml.safe_load((CONFIG / "bank_anchors.yaml").read_text(encoding="utf-8"))
        ok, bad = [], []
        by_file: dict[str, list[dict]] = defaultdict(list)
        for ch in self.chunks.values():
            by_file[ch["item_id"]].append(ch)
        norm = lambda s: re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip()  # noqa: E731
        for a in cfg["anchors"]:
            found = None
            for iid, it in self.items.items():
                sf = it.get("source_file") or ""
                if it["kind"] != "bank" or a["file"] not in sf:
                    continue
                for ch in by_file.get(iid, []):
                    if ch.get("page") == a["page"] and norm(a["match"]) in norm(ch["text"]):
                        found = (it, ch)
                        break
                if found:
                    break
            if not found:
                bad.append({"id": a["id"], "reason": "чанк не найден по file/page/match"})
                continue
            it, ch = found
            chunk_nums = set(numbers(norm(ch["text"])))
            missing = [n for n in significant_numbers(a["summary"]) if n not in chunk_nums]
            if missing:
                bad.append({"id": a["id"], "reason": f"числа из summary не найдены в тексте страницы: {missing}"})
                continue
            ok.append({**a, "item_id": it["id"], "chunk_id": ch["id"], "claim_type": ch.get("claim_type"),
                       "quote": short(norm(ch["text"]), 420), "published_at": it.get("published_at"),
                       "doc_title": it.get("doc_title"), "source_file": it.get("source_file"), "stale": it.get("stale", False)})
        self.anchors, self.anchors_rejected = ok, bad
        if bad:
            log.warning("якорные позиции отклонены: %s", bad)

    def anchors_for(self, topics: list[str] | set[str], limit: int = 4) -> list[dict]:
        tset = set(topics)
        scored = []
        for a in self.anchors:
            if a["stale"]:
                continue
            ov = len(tset & set(a["topics"][:3]))
            if ov:
                # первая тема в списке якоря — «основная»; свежесть документа как тай-брейк
                prim = 1 if a["topics"][0] in tset else 0
                scored.append((ov + 0.5 * prim, a["published_at"] or "", a))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [a for _, _, a in scored[:limit]]

    # ------------------------------------------------------------------ календарь
    def calendar(self) -> list[dict]:
        out = []
        for a in self.anchors:
            if a["id"] != "cbr_dates":
                continue
            m = re.search(r"\((\d{1,2})\s+(\w+)\s+и\s+(\d{1,2})\s+(\w+)\)", a["quote"])
            if not m:
                continue
            for d, mon in ((m.group(1), m.group(2)), (m.group(3), m.group(4))):
                if mon in MONTHS:
                    day = date(2026, MONTHS[mon], int(d))
                    if day >= datetime.fromisoformat(self.s.as_of).date():
                        out.append({"date": day.isoformat(), "title": "Заседание Банка России по ключевой ставке",
                                    "detail": "Банк ожидает паузы: ставка 14,0%" if day.month == 10 else "Второе заседание года по ставке",
                                    "source": {"item_id": a["item_id"], "page": a["page"], "doc_title": a["doc_title"], "source_file": a["source_file"]}})
        return sorted(out, key=lambda e: e["date"])

    # ------------------------------------------------------------------ поиск (BM25)
    def _build_bm25(self) -> None:
        docs = []
        for ch in self.chunks.values():
            it = self.items.get(ch["item_id"]) or {}
            if it.get("injection") or ch.get("kind") == "boilerplate":
                continue
            docs.append({"id": ch["id"], "item_id": ch["item_id"], "page": ch.get("page"), "text": ch["text"], "claim_type": ch.get("claim_type"),
                         "kind": it.get("kind"), "topics": ch.get("topics") or [], "published_at": it.get("published_at"),
                         "stale": it.get("stale", False)})
        for it in self.items.values():
            if it["kind"] == "news" and not it["injection"] and not it.get("dup_of"):
                docs.append({"id": "item:" + it["id"], "item_id": it["id"], "page": None, "text": it["title"] + ". " + it["text"], "claim_type": "unknown" if it["unconfirmed"] else "fact",
                             "kind": "news", "topics": it["topics"], "published_at": it.get("published_at"), "stale": it.get("stale", False)})
        tf, df, lens = [], Counter(), []
        for d in docs:
            toks = content_tokens(d["text"])
            c = Counter(toks)
            tf.append(c)
            lens.append(len(toks))
            for t in c:
                df[t] += 1
        n = max(1, len(docs))
        self._bm = {"docs": docs, "tf": tf, "df": df, "avg": (sum(lens) / n) if lens else 1.0, "lens": lens, "n": n}

    def search(self, query: str, k: int = 5, kinds: set[str] | None = None, topics: set[str] | None = None, allow_stale: bool = False) -> list[dict]:
        bm = self._bm
        q = content_tokens(query)
        if not q or not bm:
            return []
        res = []
        k1, b = 1.4, 0.75
        for idx, d in enumerate(bm["docs"]):
            if kinds and d["kind"] not in kinds:
                continue
            if d["stale"] and not allow_stale:
                continue
            score = 0.0
            tf = bm["tf"][idx]
            for t in q:
                if t not in tf:
                    continue
                idf = math.log(1 + (bm["n"] - bm["df"][t] + 0.5) / (bm["df"][t] + 0.5))
                f = tf[t]
                score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * bm["lens"][idx] / bm["avg"]))
            if topics and set(d["topics"]) & topics:
                score *= 1.25
            if score > 0:
                res.append((score, d))
        res.sort(key=lambda x: -x[0])
        return [dict(d, score=round(s, 3)) for s, d in res[:k]]

    # ------------------------------------------------------------------ доступ
    def get(self, item_id: str) -> dict | None:
        return self.items.get(item_id)

    def page_text(self, item_id: str, page: int | None) -> dict | None:
        it = self.items.get(item_id)
        if not it:
            return None
        chs = [c for c in self.chunks.values() if c["item_id"] == item_id and (page is None or c.get("page") == page)]
        chs.sort(key=lambda c: c.get("idx", 0))
        return {"item_id": item_id, "page": page, "title": it.get("doc_title"), "source_file": it.get("source_file"),
                "publisher": it.get("display_source"), "published_at": it.get("published_at"), "synthetic": it.get("synthetic"),
                "kind": it.get("kind"), "url": it.get("url"),
                "text": "\n\n".join(c["text"] for c in chs) if chs else (it.get("text") or ""), "pages": (it.get("extraction") or {}).get("page_count")}

    def ingest_user_text(self, text: str, title: str | None, published_at: str | None = None) -> dict:
        r = self.pipeline.ingest_text(text, title or None, source_id="manual_file", published_at=published_at or self.s.as_of,
                                      publisher="Добавлено пользователем (демо)")
        self.reload()
        return {"outcome": r.outcome, "item_id": r.item_id, "status": r.status, "dup_of": r.dup_of, "reasons": r.reasons, "error": r.error}

    def stats(self) -> dict:
        kinds = Counter(i["kind"] for i in self.items.values())
        return {"items": len(self.items), "bank_docs": kinds.get("bank", 0), "news": kinds.get("news", 0), "chunks": len(self.chunks),
                "clusters": len(self.clusters), "anchors_ok": len(self.anchors), "anchors_rejected": self.anchors_rejected,
                "indicators": len(self.forecasts), "forecast_conflicts": len(getattr(self, "forecast_conflicts", [])), "version": self.version}
