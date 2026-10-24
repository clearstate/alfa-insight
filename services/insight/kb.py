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

from services.news_ingest import scheduler
from services.news_ingest.indicators import compare_forecasts, latest_forecasts
from services.news_ingest.llm import LLMClient as NewsLLMClient, OpenAICompatTransport
from services.news_ingest.pipeline import IngestPipeline, default_fetcher
from services.news_ingest.store import NewsStore

from .settings import Settings, today_msk
from .textkit import (INJECTION_RE, MONTHS, business_flags, content_tokens, days_between, is_unconfirmed, jaccard, numbers, short,
                      significant_numbers)

log = logging.getLogger("insight.kb")
CONFIG = Path(__file__).parent / "config"
# синтетическая демо-лента (data/news_demo/demo_feed.xml); не опрашивается по расписанию (нет url)
USER_PUBLISHER = "Добавлено пользователем (демо)"         # новость, вставленная в окне «Проверить свою новость»
DEMO_SOURCE = {"id": "demo_rss", "type": "media", "name": "Демо-лента (синтетические новости)", "method": "rss", "enabled": False,
               "reliability": {"score": 0.5, "rule": "синтетические данные для демонстрации"}}


class KnowledgeBase:
    def __init__(self, settings: Settings):
        self.s = settings
        settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.store = NewsStore(f"sqlite:///{settings.runtime_dir / 'news.db'}")
        self.store.init_schema()
        # обогащение новостей моделью (темы и ключевые факты), когда правилам не хватило данных: живые ленты и своя новость
        llm = (NewsLLMClient(self.store, OpenAICompatTransport(settings.llm_base_url, settings.llm_api_key), model_simple=settings.llm_model_simple)
               if settings.llm_configured else None)
        self.pipeline = IngestPipeline(self.store, llm=llm)
        self.pipeline.sources.setdefault(DEMO_SOURCE["id"], DEMO_SOURCE)
        self.store.upsert_source(DEMO_SOURCE)
        self.lock = threading.RLock()
        self.ingest_lock = threading.Lock()      # одна запись в конвейер за раз: пользовательский ввод и обход лент
        self._feeds_thread: threading.Thread | None = None
        self._feeds_stop = threading.Event()
        self.items: dict[str, dict[str, Any]] = {}
        self.chunks: dict[str, dict[str, Any]] = {}
        self.forecasts: dict[str, dict[str, dict[str, Any]]] = {}
        self.forecast_conflicts: list[dict[str, Any]] = []
        self.anchors: list[dict[str, Any]] = []
        self.anchors_rejected: list[dict[str, Any]] = []
        self.clusters: dict[str, dict[str, Any]] = {}
        self._bm: dict[str, Any] = {}
        self.version = 0
        self._classified: dict[tuple, tuple] = {}     # (id, version) -> темы/отрасли по текущим правилам (см. _reclassify)

    # ------------------------------------------------------------------ загрузка
    def bootstrap(self) -> dict[str, Any]:
        """Идемпотентно: материалы банка (сайдкары), синтетические внешние новости, демонстрационный RSS."""
        stats = {"bank": 0, "news": 0, "rss": 0, "failed": 0}
        res = self.pipeline.ingest_bank_dir(self.s.root / "data" / "bank_analytics")
        stats["bank"] = len(res)
        if not self.s.demo_news:
            self.reload()
            return stats
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
        """Перечитывает базу. Запросы пользователей идут параллельно (живые ленты перезагружают базу из фонового
        потока), поэтому новое состояние собирается целиком на локальных структурах и публикуется одним
        присваиванием: читатель видит либо прежнюю базу, либо новую — без материалов без кластера или поиска
        по прежнему набору. Прежние объекты не изменяются."""
        with self.lock:
            rows = self.store.query("SELECT id FROM news_items")
            items: dict[str, dict] = {}
            for r in rows:
                it = self.store.get_item(r["id"])
                if it and (self.s.demo_news or not self._is_demo_news(it)):
                    items[it["id"]] = self._derive(it)
            chunks: dict[str, dict] = {}
            for iid in items:
                for ch in self.store.list_chunks(iid):
                    ch = dict(ch)
                    ch["item_id"] = iid
                    chunks[ch["id"]] = ch
            clusters = self._build_clusters(items)
            forecasts, conflicts = self._load_forecasts()
            anchors, rejected = self._load_anchors(items, chunks)
            bm = self._build_bm25(items, chunks)
            (self.items, self.chunks, self.clusters, self.forecasts, self.forecast_conflicts, self.anchors,
             self.anchors_rejected, self._bm, self.version) = (items, chunks, clusters, forecasts, conflicts, anchors,
                                                               rejected, bm, self.version + 1)
            if rejected:
                log.warning("якорные позиции отклонены: %s", rejected)

    @staticmethod
    def _is_demo_news(it: dict) -> bool:
        """Синтетическая демо-новость (data/news_demo), в т.ч. сохранённая в базе прошлым запуском. Новости,
        добавленные пользователем, сюда не относятся."""
        return it.get("source_id") == "demo_rss" or (it.get("publisher") or "").startswith("Демо")

    def _reclassify(self, it: dict) -> None:
        """Темы и отрасли — по текущим правилам news_ingest, а не по тем, что действовали при сохранении материала:
        иначе исправление ложного срабатывания в topic_rules/industry_overrides не доходит до уже загруженных новостей.
        Темы, добавленные LLM при загрузке, сохраняются. Результат кешируется по (id, version)."""
        key = (it["id"], it.get("version"))
        if key not in self._classified:
            en = self.pipeline.enricher
            title, text = it.get("title") or "", it.get("text") or ""
            topics, scores, _ = en.topics(title, text)
            econ, _off = business_flags(title, text)
            # темы от модели (дообогащение при загрузке) — не больше двух и только у новости с экономической сутью: на живой
            # ленте модель ставила «деловую активность» протестам во Франции и «туризм» — сообщениям о ковиде
            if econ and ("llm_enriched" in (it.get("status_reasons") or []) or any(f.get("method") == "llm" for f in it.get("key_facts") or [])):
                for t in [t for t in it.get("topics") or [] if t not in topics][:2]:
                    topics.append(t)
                    scores[t] = min(0.3, (it.get("topic_scores") or {}).get(t, 0.3))
            _ents, countries, regions = en.entities_geo(title + "\n" + text)      # регионы — без шапки агентства (см. entities_geo)
            self._classified[key] = (topics, scores, en.industries(title, text), countries, regions)
        c = self._classified[key]
        it["topics"], it["topic_scores"], it["industries"], it["countries"], it["regions"] = list(c[0]), dict(c[1]), c[2], list(c[3]), list(c[4])

    def _derive(self, it: dict) -> dict:
        self._reclassify(it)
        bank = it.get("bank") or {}
        it["kind"] = "bank" if it.get("source_type") == "bank_analytics" else "news"
        # синтетика — только демо-лента data/news_demo; новость, добавленная пользователем, к ней не относится
        it["synthetic"] = self._is_demo_news(it)
        it["user_submitted"] = it.get("publisher") == USER_PUBLISHER
        text = (it.get("title") or "") + " " + (it.get("text") or "")
        # официальные первоисточники (регулятор, материалы банка) слухами не помечаются
        it["unconfirmed"] = is_unconfirmed(text) and it.get("source_type") not in ("regulator", "bank_analytics")
        it["injection"] = bool(INJECTION_RE.search(text)) or "prompt_injection_suspected" in (it.get("security_flags") or [])
        it["econ"], it["offtopic"] = business_flags(it.get("title") or "", it.get("text") or "")
        pa = it.get("published_at")
        it["age_days"] = days_between(pa, self.s.as_of) if pa else 9999.0
        it["stale"] = bool(bank.get("stale")) or it["age_days"] > 365
        it["display_source"] = (bank.get("author_unit") or it.get("publisher")
                                or (self.pipeline.sources.get(it.get("source_id")) or {}).get("name") or it.get("source_id"))
        it["source_file"] = bank.get("source_file")
        it["doc_title"] = bank.get("case_list_title") or it.get("title")
        return it

    def _build_clusters(self, items: dict[str, dict]) -> dict[str, dict]:
        """Кластеры событий: участник 2 (event_cluster_id) + доп. склейка близких по смыслу и дате публикаций разных изданий.
        Проставляет cluster_id в материалах items (новый набор, ещё не опубликованный)."""
        news = [i for i in items.values() if i["kind"] == "news" and not i.get("dup_of")]
        parent: dict[str, str] = {i["id"]: i["id"] for i in news}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        toks = {i["id"]: set(content_tokens(i["title"] + " " + (i.get("summary") or ""))) for i in news}
        by_age = sorted(news, key=lambda i: i["age_days"])
        for ia, a in enumerate(by_age):
            # сравниваем только публикации в окне 5 дней: при живых лентах новостей тысячи, полный перебор пар — O(n²)
            for b in by_age[ia + 1:]:
                if b["age_days"] - a["age_days"] > 5:
                    break
                shared_topics = set(a["topics"][:2]) & set(b["topics"][:2])
                shared_okved = set(a["industries"]["okved_prefixes"]) & set(b["industries"]["okved_prefixes"])
                sim = jaccard(toks[a["id"]], toks[b["id"]])
                if (sim >= 0.30 and (shared_topics or shared_okved)) or (a.get("event_cluster_id") and a.get("event_cluster_id") == b.get("event_cluster_id")):
                    parent[find(a["id"])] = find(b["id"])
        groups: dict[str, list[dict]] = defaultdict(list)
        for i in news:
            groups[find(i["id"])].append(i)
        clusters: dict[str, dict] = {}
        for members in groups.values():
            members.sort(key=lambda m: (-(m.get("source_reliability") or {}).get("score", 0), m["age_days"]))
            primary = members[0]
            cid = "evt_" + primary["id"][5:15]
            conflict = self._cluster_conflict(members) if len(members) > 1 else None
            clusters[cid] = {"id": cid, "primary": primary["id"], "members": [m["id"] for m in members], "conflict": conflict}
            for m in members:
                m["cluster_id"] = cid
        for i in items.values():
            if i["kind"] == "bank":
                i["cluster_id"] = "evt_" + i["id"][5:15]
                clusters[i["cluster_id"]] = {"id": i["cluster_id"], "primary": i["id"], "members": [i["id"]], "conflict": None}
            elif i.get("dup_of"):
                # дубль показывается в кластере оригинала; если оригинала в базе нет — отдельным событием
                i["cluster_id"] = (items.get(i["dup_of"]) or {}).get("cluster_id") or "evt_" + i["id"][5:15]
        return clusters

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

    def _load_forecasts(self) -> tuple[dict, list[dict]]:
        rows = self.store.indicators(forecast_only=True)
        return latest_forecasts(rows), [c for c in compare_forecasts(rows) if c.get("spread")]

    def indicator(self, code: str, period: str) -> dict | None:
        v = (self.forecasts.get(code) or {}).get(str(period))
        if not v:
            return None
        it = self.items.get(v["item_id"]) or {}
        out = dict(v)
        label = self._indicator_label(code)
        # части единицы, которые уже есть в названии («конец года», «среднегодовая»), не повторяем: «14,0 %», а не «14,0 конец года, %»
        unit = ", ".join(x.strip() for x in (v.get("unit") or "").split(",") if x.strip() and x.strip().lower() not in label.lower())
        out.update({"indicator": code, "period": str(period), "doc_title": it.get("doc_title"), "source_file": it.get("source_file"),
                    "label": label, "unit": unit})
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
            "budget_revenue": "Доходы бюджета", "budget_expenditure": "Расходы бюджета", "current_account": "Счёт текущих операций",
            "gdp_nominal": "Номинальный ВВП", "key_rate_path": "Ключевая ставка, траектория", "retail_deposits_growth": "Рост розничных депозитов",
        }.get(code, code)

    # ------------------------------------------------------------------ якорные позиции банка
    def _load_anchors(self, items: dict[str, dict], chunks: dict[str, dict]) -> tuple[list[dict], list[dict]]:
        """Якорные позиции банка из bank_anchors.yaml, сверенные с текстом страницы: (принятые, отклонённые)."""
        cfg = yaml.safe_load((CONFIG / "bank_anchors.yaml").read_text(encoding="utf-8"))
        ok, bad = [], []
        by_file: dict[str, list[dict]] = defaultdict(list)
        for ch in chunks.values():
            by_file[ch["item_id"]].append(ch)
        norm = lambda s: re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip()  # noqa: E731
        for a in cfg["anchors"]:
            found = None
            for iid, it in items.items():
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
        return ok, bad

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
        """Предстоящие заседания ЦБ по ставке — из якоря cbr_dates (даты в тексте материала банка). Год — год публикации
        материала; пояснение — из другой позиции банка, где упомянута та же дата, иначе нейтральное."""
        out = []
        today = datetime.fromisoformat(self.s.as_of).date()
        for a in self.anchors:
            if a["id"] != "cbr_dates":
                continue
            m = re.search(r"\((\d{1,2})\s+(\w+)\s+и\s+(\d{1,2})\s+(\w+)\)", a["quote"])
            if not m:
                continue
            pub = (a.get("published_at") or self.s.as_of)[:10]
            year, pub_month = int(pub[:4]), int(pub[5:7])
            for d, mon in ((m.group(1), m.group(2)), (m.group(3), m.group(4))):
                if mon not in MONTHS:
                    continue
                # дата раньше месяца публикации — заседание следующего года (декабрьский обзор называет февраль)
                day = date(year + (MONTHS[mon] < pub_month), MONTHS[mon], int(d))
                if day < today:
                    continue
                view = next((x for x in self.anchors if x["id"] != a["id"] and f"{int(d)} {mon}" in x["match"]), None)
                src = view or a
                # «Банк ожидает паузы на заседании 23 октября» -> «Банк ожидает паузы»: дата уже есть в событии календаря
                detail = re.sub(r"\s+на\s+заседании.*$", "", view["summary"].split(":")[0]) if view else "Дата — по материалам банка"
                out.append({"date": day.isoformat(), "title": "Заседание Банка России по ключевой ставке", "detail": detail,
                            "source": {"item_id": src["item_id"], "page": src["page"], "doc_title": src["doc_title"],
                                       "source_file": src["source_file"]}})
        return sorted(out, key=lambda e: e["date"])

    # ------------------------------------------------------------------ поиск (BM25)
    def _build_bm25(self, items: dict[str, dict], chunks: dict[str, dict]) -> dict[str, Any]:
        docs = []
        for ch in chunks.values():
            it = items.get(ch["item_id"]) or {}
            if it.get("injection") or ch.get("kind") == "boilerplate":
                continue
            docs.append({"id": ch["id"], "item_id": ch["item_id"], "page": ch.get("page"), "text": ch["text"], "claim_type": ch.get("claim_type"),
                         "kind": it.get("kind"), "topics": ch.get("topics") or [], "published_at": it.get("published_at"),
                         "stale": it.get("stale", False)})
        for it in items.values():
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
        return {"docs": docs, "tf": tf, "df": df, "avg": (sum(lens) / n) if lens else 1.0, "lens": lens, "n": n}

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
        if page is not None and not chs:
            page, chs = None, [c for c in self.chunks.values() if c["item_id"] == item_id]     # такой страницы нет — документ целиком
        chs.sort(key=lambda c: (c.get("page") or 0, c.get("idx", 0)))
        return {"item_id": item_id, "page": page, "title": it.get("doc_title"), "source_file": it.get("source_file"),
                "publisher": it.get("display_source"), "published_at": it.get("published_at"), "synthetic": it.get("synthetic"),
                "kind": it.get("kind"), "url": it.get("url"),
                "text": "\n\n".join(c["text"] for c in chs) if chs else (it.get("text") or ""), "pages": (it.get("extraction") or {}).get("page_count")}

    def ingest_user_text(self, text: str, title: str | None, published_at: str | None = None) -> dict:
        with self.ingest_lock:
            r = self.pipeline.ingest_text(text, title or None, source_id="manual_file", published_at=published_at or self.s.as_of,
                                          publisher=USER_PUBLISHER)
        self.reload()
        return {"outcome": r.outcome, "item_id": r.item_id, "status": r.status, "dup_of": r.dup_of, "reasons": r.reasons, "error": r.error}

    # ------------------------------------------------------------------ живые ленты
    def poll_feeds(self) -> list[dict]:
        """Один проход расписания news_ingest (созревшие источники) в эту базу знаний. reload — после каждого источника с
        новыми/обновлёнными материалами (а не в конце прохода: с обогащением моделью полный проход занимает минуты, и новости
        первой ленты ждали бы остальные) и при смене суток (возраст материалов и календарь считаются от опорной даты)."""
        new_day = self.s.as_of_auto and self.s.as_of != today_msk()
        if new_day:
            self.s.as_of = today_msk()
            self.reload()
        runs = []
        now = self.pipeline.clock()
        for sid, cfg in scheduler.scheduled_sources(self.pipeline.sources).items():
            if not scheduler.is_due(self.store, sid, cfg, now):
                continue
            with self.ingest_lock:
                r = scheduler.run_source(self.pipeline, sid)
            runs.append(r)
            (log.info if r["ok"] else log.warning)("лента %s: %s", r["source_id"], json.dumps(r, ensure_ascii=False))
            if r["created"] or r["updated"]:
                self.reload()
        return runs

    def start_live_feeds(self) -> None:
        """Фоновый обход лент (ALFA_LIVE_FEEDS=1). Сбой сети или источника фиксируется в source_runs и журнале и не
        влияет на работу сервиса; свежесть видна в /api/health (kb.feeds)."""
        if self._feeds_thread is not None:
            return
        self.pipeline.fetcher = default_fetcher(self.pipeline.sources)

        def run() -> None:
            while not self._feeds_stop.is_set():
                try:
                    self.poll_feeds()
                except Exception:  # noqa: BLE001 — фоновый поток не должен падать
                    log.exception("обход лент завершился ошибкой")
                self._feeds_stop.wait(self.s.live_feeds_tick)

        self._feeds_thread = threading.Thread(target=run, name="live-feeds", daemon=True)
        self._feeds_thread.start()

    def feeds_status(self) -> dict:
        return {"enabled": self._feeds_thread is not None,
                **scheduler.freshness(self.store, self.pipeline.sources, self.pipeline.clock())}

    def stats(self) -> dict:
        kinds = Counter(i["kind"] for i in self.items.values())
        return {"items": len(self.items), "bank_docs": kinds.get("bank", 0), "news": kinds.get("news", 0), "chunks": len(self.chunks),
                "clusters": len(self.clusters), "anchors_ok": len(self.anchors), "anchors_rejected": self.anchors_rejected,
                "indicators": len(self.forecasts), "forecast_conflicts": len(self.forecast_conflicts), "version": self.version,
                "feeds": self.feeds_status() if self._feeds_thread is not None else {"enabled": False}}
