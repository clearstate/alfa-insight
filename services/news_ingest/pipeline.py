"""Конвейер: получение -> сырой снимок -> извлечение -> нормализация -> валидация -> content_hash -> дедупликация/версии ->
кластеризация -> обогащение (правила, затем LLM по необходимости) -> сохранение -> событие для поиска (ingest_events).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import yaml

from . import dedup, indicators as ind
from .bankdocs import OcrUnavailable, PdfBackendUnavailable, _assemble, chunk_pages, read_pdf
from .enrich import Enricher, _BANK_MARK
from .fetcher import FetchError, SafeFetcher
from .html_extract import decode_bytes, extract_html
from .llm import LLMClient, OpenAICompatTransport
from .models import Chunk, Extracted, IngestResult, KeyFact, NewsItem, PageText
from .rss import FeedEntry, FeedParseError, parse_feed
from .store import NewsStore
from .textutil import (clean_text, content_hash, fold, find_dates_ru, minhash, normalize_text, now_iso, parse_date, sha256_bytes,
                       shingles, split_sentences)

CONFIG = Path(__file__).resolve().parent / "config"
REPO = Path(__file__).resolve().parents[2]
PARA = "\n\n"
RSS_MIN_CHARS = 30          # минимум для сохранения записи ленты по заголовку/аннотации (резерв при недоступной статье)
FEED_FULLTEXT_MIN = 500     # полный текст в самой ленте (content:encoded, rbc full-text) не короче — страницу не скачиваем
_TRACKING = re.compile(r"^(utm_|fbclid|gclid|yclid|_openstat|ref$|from$)", re.I)


def canonical_url(url: str) -> str:
    p = urlparse(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)]
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", "", urlencode(q), ""))


def detect_language(text: str) -> str | None:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text[:3000])
    if len(letters) < 20:
        return None
    cyr = sum(1 for c in letters if "А" <= c <= "я" or c in "Ёё")
    return "ru" if cyr / len(letters) > 0.5 else "en"


def load_sources(path: Path | None = None) -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load((path or CONFIG / "sources.yaml").read_text(encoding="utf-8"))
    d = doc.get("defaults", {})
    return {s["id"]: {**d, **s} for s in doc["sources"]}


def build_pipeline(store: NewsStore, sources: dict[str, dict[str, Any]] | None = None) -> IngestPipeline:
    """Конвейер с настройками из ENV — один для API (main.py) и для процесса расписания (cli schedule).
    Сетевые параметры — из defaults в sources.yaml; NEWS_ALLOWED_DOMAINS (через запятую) сужает список доменов;
    LLM подключается, только если задан LLM_BASE_URL."""
    sources = sources if sources is not None else load_sources()
    llm = LLMClient(store, OpenAICompatTransport()) if os.getenv("LLM_BASE_URL") else None
    return IngestPipeline(store, llm=llm, fetcher=default_fetcher(sources), sources=sources)


def default_fetcher(sources: dict[str, dict[str, Any]]) -> SafeFetcher:
    d = next(iter(sources.values()), {})          # load_sources подмешивает defaults в каждый источник
    doms = [x.strip() for x in os.getenv("NEWS_ALLOWED_DOMAINS", "").split(",") if x.strip()] or None
    return SafeFetcher(timeout=d.get("timeout_s", 10), max_bytes=d.get("max_bytes", 5_000_000), retries=d.get("retries", 2),
                       backoff=d.get("backoff_s", 1.0), min_interval=d.get("min_interval_s", 2.0),
                       user_agent=d.get("user_agent", "AlfaInsightBot/0.1"), allowed_domains=doms)


def _saved_from_feed(row: dict[str, Any]) -> bool:
    """Элемент сохранён по данным ленты (аннотация/заголовок), а не по странице статьи."""
    try:
        return (json.loads(row["item_json"]).get("extraction") or {}).get("method") == "rss"   # rss_full — полный текст
    except (TypeError, ValueError):
        return False


def _redirected_to_homepage(link: str, final_url: str | None) -> bool:
    """Ссылка на статью привела на главную страницу сайта (статья удалена или закрыта)."""
    if not final_url:
        return False
    a, b = urlparse(link), urlparse(final_url)
    return (a.path or "/").rstrip("/") != "" and (b.path or "/").rstrip("/") == "" and not b.query


class IngestPipeline:
    def __init__(self, store: NewsStore, *, enricher: Enricher | None = None, llm: LLMClient | None = None,
                 fetcher: SafeFetcher | None = None, sources: dict[str, dict[str, Any]] | None = None,
                 clock=now_iso, stale_days: int = 365, store_pdf_bodies: bool = False):
        self.store, self.enricher, self.llm, self.fetcher = store, enricher or Enricher(), llm, fetcher
        self.sources = sources if sources is not None else load_sources()
        self.clock, self.stale_days, self.store_pdf_bodies = clock, stale_days, store_pdf_bodies
        for s in self.sources.values():
            store.upsert_source(s)

    # ------------------------------------------------------------------ точки входа
    def ingest_bank_dir(self, directory: str | Path | None = None, source_id: str = "alfa_bank_analytics") -> list[IngestResult]:
        d = Path(directory) if directory else REPO / self.sources[source_id].get("path", "data/bank_analytics")
        return [self.ingest_bank_pdf(p, source_id) for p in sorted(d.glob("*.pdf"))] or self._bank_from_sidecars(d, source_id)

    def _bank_from_sidecars(self, d: Path, source_id: str) -> list[IngestResult]:
        """Если PDF-файлов рядом нет (в репозитории хранятся только экстракты) — читаем сайдкары напрямую."""
        out = []
        for sc in sorted(d.glob("*.extract.json")):
            doc = json.loads(sc.read_text(encoding="utf-8"))
            pages = [PageText(page=x["page"], kind=x["kind"], text=x["text"]) for x in doc["pages"]]
            ex = _assemble(pages, doc["document"]["title"], doc["document"].get("published_at"), "pdf_vision_sidecar")
            ex.language = doc["document"].get("language")
            ex.meta.update({"pdf_sha256": doc["source_sha256"], "source_file": doc["source_file"],
                            "bank": {k: v for k, v in doc["document"].items() if k != "title"},
                            "extraction_note": doc.get("extraction_note"), "sidecar": sc.name})
            out.append(self._safe(lambda ex=ex, doc=doc: self._process(
                self.sources[source_id], ex, url=None, url_key="bank:" + Path(doc["source_file"]).stem,
                raw_sha=doc["source_sha256"], raw_body=None, fetched_at=self.clock(), correlation_id=None),
                source_id, doc["source_file"]))
        return out

    def ingest_bank_pdf(self, path: str | Path, source_id: str = "alfa_bank_analytics",
                        sidecar_dirs: list[Path] | None = None, allow_ocr: bool = True) -> IngestResult:
        p = Path(path)

        def run() -> IngestResult:
            try:
                ex = read_pdf(p, sidecar_dirs=(sidecar_dirs or [REPO / "data" / "bank_analytics"]), allow_ocr=allow_ocr)
            except PdfBackendUnavailable as e:
                self.store.add_error("extract", "pdf_backend_unavailable", str(e), source_id, str(p))
                return IngestResult("failed", error=f"pdf_backend_unavailable: {e}")
            except OcrUnavailable as e:
                self.store.add_error("extract", "ocr_unavailable", str(e), source_id, str(p))
                return IngestResult("failed", error=f"ocr_unavailable: {e}")
            body = p.read_bytes() if self.store_pdf_bodies else None
            return self._process(self.sources[source_id], ex, url=None, url_key="bank:" + p.stem, raw_sha=ex.meta["pdf_sha256"],
                                 raw_body=body, fetched_at=self.clock(), correlation_id=None)
        return self._safe(run, source_id, str(p))

    def ingest_html(self, source_id: str, url: str, body: bytes, content_type: str | None = None, fetched_at: str | None = None,
                    http_status: int | None = None, charset: str | None = None, correlation_id: str | None = None,
                    feed: FeedEntry | None = None) -> IngestResult:
        def run() -> IngestResult:
            html, enc = decode_bytes(body, charset)
            ex = extract_html(html, url)
            ex.meta["encoding"] = enc
            # запись ленты: ключ — ссылка из ленты (не адрес после редиректа), чтобы статья и резервная запись по аннотации
            # были одним элементом: появление статьи обновляет запись (version+1), а не создаёт дубль
            key = canonical_url(feed.link) if feed is not None and feed.link else canonical_url(url)
            if feed is not None:                  # запись ленты: заголовок/дата/издатель ленты — резерв для страницы
                pub = self.sources.get(source_id, {}).get("name")
                ex.meta["feed_title"] = feed.title
                if not ex.title and feed.title:
                    ex.meta["feed_title_used"] = True
                if not ex.publisher and pub and self.sources.get(source_id, {}).get("type") != "adhoc":
                    ex.publisher = pub
                    ex.meta["feed_publisher_used"] = True
                if feed.published_raw:            # резерв и для пустой, и для нераспознаваемой даты страницы
                    ex.meta["feed_published_raw"] = feed.published_raw
            return self._process(self.sources.get(source_id) or self._adhoc_source(source_id), ex, url=url,
                                 url_key=key, raw_sha=sha256_bytes(body), raw_body=body,
                                 fetched_at=fetched_at or self.clock(), correlation_id=correlation_id,
                                 content_type=content_type, http_status=http_status)
        return self._safe(run, source_id, url, correlation_id)

    def ingest_text(self, text: str, title: str | None = None, *, source_id: str = "manual_file", url: str | None = None,
                    published_at: str | None = None, publisher: str | None = None, correlation_id: str | None = None) -> IngestResult:
        def run() -> IngestResult:
            ex = Extracted(title=title, text=text, published_raw=published_at, publisher=publisher, url=url, method="manual_text")
            key = canonical_url(url) if url else "text:" + content_hash(text)[:32]
            return self._process(self.sources.get(source_id) or self._adhoc_source(source_id), ex, url=url, url_key=key,
                                 raw_sha=sha256_bytes(text.encode("utf-8")), raw_body=text.encode("utf-8"), fetched_at=self.clock(),
                                 correlation_id=correlation_id, content_type="text/plain")
        return self._safe(run, source_id, url, correlation_id)

    def ingest_url(self, url: str, source_id: str = "manual_file", correlation_id: str | None = None) -> IngestResult | list[IngestResult]:
        if self.fetcher is None:
            raise RuntimeError("fetcher не сконфигурирован")
        try:
            r = self.fetcher.fetch(url)
        except FetchError as e:
            self.store.add_error("fetch", e.code, e.message, source_id, url, correlation_id)
            if source_id in self.sources:
                self.store.touch_source(source_id, False)
            return IngestResult("failed", error=f"{e.code}: {e.message}")
        if r.content_type == "application/pdf" or r.body[:5] == b"%PDF-":
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                tf.write(r.body)
            try:
                if source_id == "alfa_bank_analytics":
                    return self.ingest_bank_pdf(tf.name, source_id)
                return self._ingest_pdf_generic(tf.name, url, source_id, r)
            finally:
                Path(tf.name).unlink(missing_ok=True)
        if r.content_type in ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml") or r.body.lstrip()[:5] == b"<?xml":
            return self.ingest_feed_bytes(source_id, r.body, url)
        return self.ingest_html(source_id, r.final_url, r.body, r.content_type, r.fetched_at, r.status, r.charset, correlation_id)

    def _ingest_pdf_generic(self, path: str, url: str, source_id: str, r) -> IngestResult:
        def run() -> IngestResult:
            ex = read_pdf(path)
            return self._process(self.sources.get(source_id) or self._adhoc_source(source_id), ex, url=url, url_key=canonical_url(url),
                                 raw_sha=sha256_bytes(r.body), raw_body=None, fetched_at=r.fetched_at, correlation_id=None,
                                 content_type="application/pdf")
        return self._safe(run, source_id, url)

    def ingest_file(self, path: str | Path, source_id: str = "manual_file", title: str | None = None,
                    published_at: str | None = None) -> IngestResult:
        """Импорт файла (запасной путь, если источник недоступен по сети): .pdf / .html / .txt / .md."""
        p = Path(path)
        suf = p.suffix.lower()
        if suf == ".pdf":
            if source_id == "alfa_bank_analytics":
                return self.ingest_bank_pdf(p, source_id)

            def run() -> IngestResult:
                ex = read_pdf(p, sidecar_dirs=[REPO / "data" / "bank_analytics"])
                if title:
                    ex.title = title
                return self._process(self.sources.get(source_id) or self._adhoc_source(source_id), ex, url=None, url_key="file:" + p.name,
                                     raw_sha=ex.meta["pdf_sha256"], raw_body=None, fetched_at=self.clock(), correlation_id=None,
                                     content_type="application/pdf")
            return self._safe(run, source_id, str(p))
        raw = p.read_bytes()
        if suf in (".html", ".htm"):
            return self.ingest_html(source_id, "file:" + p.name, raw, "text/html", self.clock())
        text, _ = decode_bytes(raw)
        return self.ingest_text(text, title or p.stem, source_id=source_id, url=None, published_at=published_at)

    def ingest_feed(self, source_id: str, fetch_articles: bool = True) -> list[IngestResult]:
        src = self.sources[source_id]
        if self.fetcher is None:
            raise RuntimeError("fetcher не сконфигурирован")
        try:
            r = self.fetcher.fetch(src["url"])
        except FetchError as e:
            self.store.add_error("fetch_feed", e.code, e.message, source_id, src["url"])
            self.store.touch_source(source_id, False)
            return [IngestResult("failed", error=f"{e.code}: {e.message}")]
        # fetch_articles: false в sources.yaml — сайт не отдаёт страницы ботам (403) или лента уже содержит текст
        return self.ingest_feed_bytes(source_id, r.body, src["url"], fetch_articles and src.get("fetch_articles", True))

    def ingest_feed_bytes(self, source_id: str, body: bytes, base_url: str, fetch_articles: bool = True) -> list[IngestResult]:
        try:
            entries = parse_feed(body)
        except FeedParseError as e:
            self.store.add_error("parse_feed", "feed_parse_error", str(e), source_id, base_url)
            return [IngestResult("failed", error=f"feed_parse_error: {e}")]
        results = []
        for e in entries:
            try:
                res = self._feed_entry(source_id, e, fetch_articles)
                results.append(res)
            except Exception as ex:   # noqa: BLE001 — лента продолжает работу
                self.store.add_error("feed_entry", "unexpected", repr(ex), source_id, e.link)
                results.append(IngestResult("failed", error=repr(ex)))
        self.store.touch_source(source_id, any(r.outcome != "failed" for r in results) if results else True)
        return results

    def _feed_entry(self, source_id: str, e: FeedEntry, fetch_articles: bool) -> IngestResult:
        """Одна запись ленты. Порядок: статья целиком -> резервные данные RSS.

        Резерв: если страница статьи недоступна (4xx/5xx, robots, сеть) или из неё не извлекается полноценный текст
        (видео-заглушка, редирект на главную, слишком короткий текст), материал сохраняется по описанию из RSS
        (summary_only) с датой, заголовком и издателем из ленты. Дата из RSS также дополняет страницу, опубликованную без даты.
        Причины фиксируются в status_reasons: rss_fallback, feed_date_used, feed_title_used, feed_publisher_used.
        """
        cfg = self.sources.get(source_id) or {"id": source_id, "type": "adhoc", "name": source_id}
        pub = cfg.get("name") if cfg.get("type") != "adhoc" else None
        prev = self.store.get_by_url_key(canonical_url(e.link)) if e.link else None
        if prev and not _saved_from_feed(prev):
            # статья уже сохранена целиком: ленту опрашивают по расписанию, повторно страницу не скачиваем и не
            # заменяем полный текст аннотацией, если статья временно недоступна
            self.store.touch_seen(prev["id"])
            return IngestResult("skipped", prev["id"], prev["version"], prev["processing_status"], prev["dup_of"],
                                prev["event_cluster_id"], reasons=["already_ingested"])
        full = normalize_text(e.content or "")
        if len(full) >= FEED_FULLTEXT_MIN:
            # лента отдаёт полный текст статьи: это полноценный материал, страницу не скачиваем
            ex = Extracted(title=e.title or None, text=full, published_raw=e.published_raw, url=e.link, method="rss_full",
                           publisher=pub, meta={"feed_title": e.title, "feed_published_raw": e.published_raw})
            return self._process_feed_item(source_id, cfg, ex, e)
        art_ex = None
        failed: str | None = None
        if e.link and fetch_articles and self.fetcher is not None:
            try:
                r = self.fetcher.fetch(e.link)
            except FetchError as fe:
                self.store.add_error("fetch", fe.code, fe.message, source_id, e.link)
                failed = f"fetch:{fe.code}"
            else:
                if _redirected_to_homepage(e.link, r.final_url):
                    # главная страница вместо статьи (статья удалена/закрыта): её текст — не текст новости
                    self.store.add_error("feed_entry", "redirect_to_homepage", f"{e.link} -> {r.final_url}", source_id, e.link)
                    failed = "article:redirect_to_homepage"
                elif r.content_type == "application/pdf" or r.body[:5] == b"%PDF-":
                    try:
                        art_ex = self._pdf_from_bytes(r.body)
                    except (OcrUnavailable, PdfBackendUnavailable) as ex:  # PDF без текста/OCR: действует резерв RSS
                        self.store.add_error("extract", "ocr_unavailable" if isinstance(ex, OcrUnavailable) else "pdf_backend_unavailable",
                                             str(ex), source_id, e.link)
                        failed = "extract:pdf_failed"
                    except Exception as ex:  # noqa: BLE001 — битый PDF: действует резерв RSS
                        self.store.add_error("extract", "pdf_failed", f"{type(ex).__name__}: {ex}", source_id, e.link)
                        failed = "extract:pdf_failed"
                    else:
                        # PDF-документ по ссылке из ленты — полноценный материал. Заголовок ленты точнее метаданных PDF
                        # (там часто «Microsoft Word - …»); дата и издатель ленты — резерв
                        art_ex.url, art_ex.title = e.link, e.title or art_ex.title
                        art_ex.publisher = art_ex.publisher or pub
                        art_ex.meta.update({"feed_title": e.title, "feed_published_raw": e.published_raw})
                        res = self._process_feed_item(source_id, cfg, art_ex, e, "application/pdf")
                        if res.outcome != "failed":
                            return res
                        failed = f"article:{res.error or 'failed'}"
                else:
                    # заголовок/издатель/дата ленты — резерв для страницы без этих полей (ingest_html)
                    res = self.ingest_html(source_id, r.final_url, r.body, r.content_type, r.fetched_at, r.status, r.charset, feed=e)
                    if res.outcome != "failed":
                        return res
                    art_ex = extract_html(decode_bytes(r.body, r.charset)[0], r.final_url)
                    self.store.add_error("feed_entry", "article_rejected", res.error or "failed", source_id, e.link)
                    failed = f"article:{res.error or 'failed'}"

        summary = normalize_text(e.summary or "")
        title = normalize_text(e.title or "")
        text = summary
        if failed is not None and art_ex is not None and art_ex.text and len(text) < 60:
            # аннотации нет или она короткая: добавляем абзацы отклонённой (слишком короткой) страницы
            extra = [p for p in normalize_text(art_ex.text).split(PARA) if len(p) >= 60 and fold(p) not in fold(summary)]
            text = normalize_text(PARA.join(([text] if text else []) + extra))
        if len(text) < 60 and title and fold(text) not in fold(title):
            text = normalize_text(title + PARA + text) if text else title   # короткая аннотация дополняется заголовком
        elif not text:
            text = title
        title_only = bool(text) and text == title
        if len(text) < RSS_MIN_CHARS or (title_only and not e.link):
            # резервных данных нет (ни аннотации, ни осмысленного заголовка со ссылкой)
            if failed is None:   # причина отказа страницы уже в журнале; иначе фиксируем здесь
                self.store.add_error("feed_entry", "no_rss_fallback", "в записи ленты нет текста для сохранения", source_id, e.link)
            return IngestResult("failed", error=failed or "empty_entry", reasons=["no_rss_fallback"])
        ex = Extracted(title=e.title or None, text=text, published_raw=e.published_raw, url=e.link, method="rss", publisher=pub,
                       language=getattr(art_ex, "language", None) if art_ex else None,
                       meta={"summary_only": True, "rss_fallback": failed or "no_article", "feed_title": e.title,
                             "feed_published_raw": e.published_raw, "title_only": title_only})
        return self._process_feed_item(source_id, cfg, ex, e)

    def _process_feed_item(self, source_id: str, cfg: dict[str, Any], ex: Extracted, e: FeedEntry,
                           content_type: str = "application/rss+xml") -> IngestResult:
        url_key = canonical_url(e.link) if e.link else "rss:" + (e.guid or content_hash(e.title or "")[:24])
        return self._safe(lambda: self._process(cfg, ex, url=e.link, url_key=url_key,
                                                raw_sha=sha256_bytes((ex.text or e.title or "").encode()), raw_body=None,
                                                fetched_at=self.clock(), correlation_id=None, content_type=content_type),
                          source_id, e.link)

    @staticmethod
    def _pdf_from_bytes(body: bytes) -> Extracted:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(body)
        try:
            return read_pdf(tf.name, sidecar_dirs=[])
        finally:
            Path(tf.name).unlink(missing_ok=True)

    # ------------------------------------------------------------------ служебное
    def _adhoc_source(self, source_id: str) -> dict[str, Any]:
        cfg = {"id": source_id, "type": "media", "name": source_id, "method": "adhoc", "reliability": {"score": 0.5, "rule": "источник не описан в sources.yaml"}}
        self.store.upsert_source(cfg)
        self.sources[source_id] = cfg
        return cfg

    def _safe(self, fn, source_id: str, url: str | None, correlation_id: str | None = None) -> IngestResult:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            self.store.add_error("process", "unexpected", f"{type(e).__name__}: {e}", source_id, url, correlation_id)
            return IngestResult("failed", error=f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------------ ядро
    def _process(self, source: dict[str, Any], ex: Extracted, *, url: str | None, url_key: str, raw_sha: str, raw_body: bytes | None,
                 fetched_at: str, correlation_id: str | None, content_type: str | None = None,
                 http_status: int | None = None) -> IngestResult:
        sid, stype = source["id"], source["type"]
        is_bank = stype == "bank_analytics"
        reasons: list[str] = []
        status = "ok"

        # 1. сырой снимок (идемпотентно)
        raw_id = "raw_" + hashlib.sha256(f"{sid}|{url_key}|{raw_sha}".encode()).hexdigest()[:20]
        self.store.add_raw(raw_id, sid, url or url_key, content_type or ("application/pdf" if is_bank else None), raw_sha, raw_body,
                           fetched_at, http_status)

        # 2. нормализация
        if is_bank and ex.pages:
            pages = [PageText(p.page, p.kind, clean_text(p.text)) for p in ex.pages]
            text = ex.text
        else:
            pages, text = None, normalize_text(ex.text)
        title = normalize_text(ex.title or "")
        # 3. валидация
        # запись ленты (rss) может состоять из заголовка и короткой аннотации — она уходит в needs_review, а не теряется
        min_chars = RSS_MIN_CHARS if ex.method == "rss" else 60 if (ex.meta.get("summary_only") or ex.method == "manual_text") else 200
        if not text.strip():
            self.store.add_error("validate", "empty_content", "нет извлечённого текста", sid, url, correlation_id)
            return IngestResult("failed", error="empty_content", reasons=["empty_content"])
        if not is_bank and len(text) < min_chars:
            self.store.add_error("validate", "text_too_short", f"{len(text)} < {min_chars} символов", sid, url, correlation_id)
            return IngestResult("failed", error="text_too_short", reasons=["text_too_short"])
        if ex.meta.get("summary_only"):
            reasons.append("summary_only")
        feed_title = normalize_text(ex.meta.get("feed_title") or "")
        if not title or (ex.meta.get("feed_title_used") and feed_title):
            title = feed_title or title
        if not title:
            sents = split_sentences(text)
            title = (sents[0][0] if sents else text)[:120].rstrip(" .,;:")
            reasons.append("title_derived")
            status = "needs_review"
        elif ex.meta.get("feed_title_used"):
            reasons.append("feed_title_used")
        now = self.clock()
        horizon = (datetime.fromisoformat(now.replace("Z", "+00:00")) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        # дата страницы; для записи, сохранённой по данным ленты (method=rss), страницы нет — дата всегда из RSS
        from_feed = ex.method in ("rss", "rss_full")
        page_date = None if from_feed else parse_date(ex.published_raw)
        feed_date = None if is_bank else parse_date(ex.meta.get("feed_published_raw")
                                                    or (ex.published_raw if from_feed else None))
        dated = page_date or feed_date
        feed_date_used = page_date is None and feed_date is not None
        if dated and dated[0] > horizon:
            reasons.append("date_in_future"); status = "needs_review"
            published_at, precision = dated
        elif dated:
            published_at, precision = dated
        else:
            published_at, precision = None, None
            reasons.append("date_missing"); status = "needs_review"
        if feed_date_used:
            # дата страницы пустая/битая, дата взята из RSS (для сохранения по аннотации это всегда так)
            reasons.append("feed_date_used")
        if ex.meta.get("feed_publisher_used"):
            reasons.append("feed_publisher_used")
        if ex.meta.get("rss_fallback"):
            reasons.append("rss_fallback")
        if ex.meta.get("summary_only") and status == "ok":
            status = "needs_review"     # сохранён по аннотации RSS: материал неполный, виден в очереди проверки
        # дата события
        event_date = None
        bank_meta = dict(ex.meta.get("bank") or {})
        if bank_meta.get("event_date"):
            ed = parse_date(bank_meta["event_date"]); event_date = ed[0] if ed else None
        elif published_at:
            for d in find_dates_ru(text[:700]):
                if abs((datetime.fromisoformat(d + "T00:00:00+00:00") - datetime.fromisoformat(published_at)).days) <= 30:
                    event_date = d + "T00:00:00+00:00"; break
        event_date = event_date or published_at

        chash = content_hash(text)
        item_id = "news_" + hashlib.sha256(url_key.encode()).hexdigest()[:20]
        sh = shingles(text)
        sig = minhash(sh)

        # 4. обогащение правилами
        en = self.enricher
        topics, tscores, _ev = en.topics(title, text)
        industries = en.industries(title, text)
        ents, countries, regions = en.entities_geo(title + "\n" + text)
        if pages:
            offs = ex.meta.get("page_offsets", {})
            sent_pages = [(p.page, p.text, offs[p.page]) for p in pages if p.page in offs and p.kind in ("text", "mixed")]
        else:
            sent_pages = [(None, text, 0)]
        facts, views = en.analyse_sentences(sent_pages, is_bank, 14 if is_bank else 8, topics)
        nclaims = en.numeric_claims(sent_pages, is_bank)
        flags = en.injection_flags(title + "\n" + text)
        if flags:
            reasons.append("prompt_injection_suspected")

        # 5. LLM поверх правил (только если правила не справились)
        usage: dict[str, int] = {}
        # Модель — только когда правила не справились: нет тем или мало фактов в полном тексте. Для записи ленты по аннотации
        # (2–3 предложения) факты модель всё равно может взять только из них — зовём её лишь при отсутствии тем.
        # Текст с инструкциями для AI (prompt injection) модели не отдаётся.
        need_llm = not topics or (len(facts) < 2 and not ex.meta.get("summary_only"))
        if self.llm and not is_bank and not flags and need_llm:
            res, why = self.llm.enrich(title, text)
            if res is None:
                reasons.append(f"llm_skipped:{why}")
            else:
                usage = dict(self.llm.last_usage)
                if res["topics"] or res["key_facts"]:
                    reasons.append("llm_enriched")       # темы/факты от модели: база знаний сохраняет их при пересчёте тем правилами
                for t in res["topics"]:
                    if t not in topics:
                        topics.append(t); tscores[t] = 0.3
                for f in res["key_facts"]:
                    pos = text.find(f)
                    if pos >= 0 and not any(f in x.text or x.text in f for x in facts):
                        facts.append(KeyFact(text=f, claim_type="fact", method="llm", span={"field": "text", "start": pos, "end": pos + len(f), "page": None}))

        # 6. надёжность и актуальность
        rel = dict(source.get("reliability") or {"score": 0.5, "rule": "по умолчанию"})
        stale = bool(bank_meta.get("stale"))
        if is_bank and published_at and not stale:
            age = (datetime.fromisoformat(now.replace("Z", "+00:00")) - datetime.fromisoformat(published_at)).days
            stale = age > self.stale_days
        if stale:
            reasons.append("stale_document")
            rel = {"score": 0.2, "rule": "устаревший материал: " + (bank_meta.get("stale_reason") or f"старше {self.stale_days} дн.")}

        provenance = {"source_id": sid, "url": url, "url_key": url_key, "raw_document_id": raw_id, "raw_sha256": raw_sha,
                      "extraction_method": ex.method, "retrieved_at": fetched_at,
                      "locator": (f"pdf:{ex.meta.get('source_file')}" if is_bank else (url or "text"))}
        item = NewsItem(
            id=item_id, title=title, text=text, url=url, canonical_url=canonical_url(url) if url else None,
            publisher=ex.publisher or ("Альфа-Банк" if is_bank else None), source_id=sid, source_type=stype,
            document_type="bank_analytics" if is_bank else ("press_release" if stype == "regulator" else "news"),
            published_at=published_at, date_precision=precision, event_date=event_date, retrieved_at=fetched_at,
            content_hash=chash, summary=en.summary(text), language=ex.language or detect_language(text), topics=topics,
            topic_scores=tscores, industries=industries, regions=regions, countries=countries, entities=ents, key_facts=facts,
            bank_views=views, numeric_claims=nclaims, source_reliability=rel, provenance=provenance, processing_status=status,
            status_reasons=reasons, security_flags=flags,
            extraction={"method": ex.method, **{k: v for k, v in ex.meta.items() if k in (
                "page_count", "skipped_pages", "sidecar", "extraction_note", "encoding", "pdf_sha256", "source_file", "summary_only",
                "title_only", "rss_fallback")}},
            bank=({"author_unit": bank_meta.get("author_unit"), "doc_family": bank_meta.get("doc_family"), "stale": stale,
                   "stale_reason": bank_meta.get("stale_reason"), "superseded_note": bank_meta.get("superseded_note"),
                   "published_at_note": bank_meta.get("published_at_note"), "case_list_title": bank_meta.get("case_list_title"),
                   "source_file": ex.meta.get("source_file")} if is_bank else None))
        pv = {"item_id": item_id, "source_id": sid, "url": url, "published_at": published_at, "raw_sha256": raw_sha}
        for f in item.key_facts:
            f.provenance = {**pv, "page": f.span.get("page")}
        for v in item.bank_views:
            v.provenance = {**pv, "page": v.page}
        for c in item.numeric_claims:
            c.provenance = {**pv, "page": c.page}

        # 7. дедупликация / версии / кластер
        nums = {(c.kind, c.value) for c in nclaims}
        dec = dedup.decide(self.store, item_id, url_key, chash, sig, published_at, event_date, topics, nums,
                           {e["name"] for e in ents}, fetched_at, is_bank)
        prev = self.store.get_row(item_id) if dec.kind in ("update", "unchanged") else None
        if dec.kind == "unchanged":
            self.store.touch_seen(item_id)
            return IngestResult("skipped", item_id, prev["version"], prev["processing_status"], None, prev["event_cluster_id"], reasons=dec.reasons)
        is_new = dec.kind != "update"
        if dec.kind == "update":
            item.version = prev["version"] + 1
            item.event_cluster_id = prev["event_cluster_id"]
        elif dec.kind == "duplicate":
            item.dup_of = dec.target_id
            item.processing_status = "duplicate"
            item.event_cluster_id = dec.cluster_id
            item.status_reasons += dec.reasons
        elif dec.kind == "same_event":
            item.event_cluster_id = dec.cluster_id
            item.status_reasons += ["same_event_as:" + str(dec.target_id)] + dec.reasons
        else:
            item.event_cluster_id = "evc_" + item_id[5:]

        # 8. чанки и показатели
        chunks: list[Chunk] = []
        inds: list = []
        if item.dup_of is None:
            topic_fn = lambda t: en.topics("", t)[0][:3]
            if pages:
                chunks = chunk_pages(item_id, pages, topic_fn, lambda t: bool(_BANK_MARK.search(fold(t))))
                for p in pages:
                    if p.kind in ("text", "mixed", "table", "chart"):
                        inds += ind.parse_tables(p.text, item_id, p.page, published_at)
            else:
                chunks = chunk_pages(item_id, [PageText(1, "text", text)], topic_fn)
                for c in chunks:
                    c.page = None
        item.chunk_count = len(chunks)

        with self.store.tx():
            self.store.save_item(item, sig, chunks, inds, is_new=is_new, prev_row=prev)
            cid = item.event_cluster_id
            members = self.store.cluster_members(cid)
            conflicts = dedup.compute_conflicts(members) if len(members) > 1 else []
            self.store.upsert_cluster(cid, title[:200], event_date, len(members), conflicts)
            if conflicts and dec.kind == "same_event":
                item.status_reasons.append("cluster_conflict")
                self.store.save_item(item, sig, chunks, inds, is_new=False, prev_row=None)
            self.store.add_event(item_id, {"new": "created", "update": "updated", "duplicate": "duplicate", "same_event": "created"}[dec.kind], item.version)
        if source["id"] in self.sources:
            self.store.touch_source(sid, True)
        outcome = {"new": "created", "same_event": "created", "update": "updated", "duplicate": "duplicate"}[dec.kind]
        return IngestResult(outcome, item_id, item.version, item.processing_status, item.dup_of, item.event_cluster_id,
                            reasons=list(item.status_reasons), token_usage=usage)
