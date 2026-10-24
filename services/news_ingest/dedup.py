"""Дедупликация и кластеризация событий.

Различаем (требование ТЗ):
  unchanged   — тот же URL, тот же контент: ничего не делаем;
  update      — тот же URL, контент изменился: новая version, старая уходит в news_versions;
  duplicate   — другой URL, тот же текст (SHA-256) или почти тот же (MinHash >= DUP_T): запись помечается dup_of;
  same_event  — независимая публикация о том же событии: тот же кластер, URL сохраняются, противоречия не сливаются, а помечаются;
  new         — новое событие.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .store import NewsStore
from .textutil import minhash_similarity

DUP_T = 0.80
EVENT_SIM_MIN = 0.25
WINDOW_DAYS = 14
# Почти одинаковый текст с датами публикации, разнесёнными больше чем на DUP_MAX_DAYS, — это не перепечатка, а новый выпуск
# шаблонного материала (еженедельный мониторинг ставок, регулярная статистика): цифры другие, скрывать его как дубль нельзя.
DUP_MAX_DAYS = 3


@dataclass
class Decision:
    kind: str
    target_id: str | None = None
    similarity: float = 0.0
    cluster_id: str | None = None
    reasons: list[str] = field(default_factory=list)


def _day(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def decide(store: NewsStore, item_id: str, url_key: str, content_hash: str, sig: list[int], published_at: str | None,
           event_date: str | None, topics: list[str], numeric_values: set[tuple[str, float]], entities: set[str],
           retrieved_at: str, is_bank: bool = False) -> Decision:
    existing = store.get_by_url_key(url_key)
    if existing:
        if existing["content_hash"] == content_hash:
            return Decision("unchanged", existing["id"], 1.0, existing["event_cluster_id"], ["same_url_same_content"])
        return Decision("update", existing["id"], 0.0, existing["event_cluster_id"], ["same_url_content_changed"])
    dup = store.find_by_hash(content_hash, item_id)
    if dup:
        return Decision("duplicate", dup["id"], 1.0, dup["event_cluster_id"], ["same_content_hash_other_url"])
    if is_bank:
        return Decision("new", reasons=["bank_document"])
    ref = _day(event_date) or _day(published_at) or _day(retrieved_at) or datetime.now(timezone.utc)
    pub_ref = _day(published_at) or ref
    since = (ref - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    best: tuple[float, dict[str, Any]] | None = None
    best_event: tuple[float, dict[str, Any], list[str]] | None = None
    for row in store.recent_for_clustering(since, item_id):
        row_day = _day(row["event_date"]) or _day(row["published_at"])
        if row_day is not None and (row_day - ref).days > WINDOW_DAYS:   # окно симметрично: более поздние материалы тоже
            continue
        other = json.loads(row["minhash"] or "[]")
        sim = minhash_similarity(sig, other)
        row_pub = _day(row["published_at"]) or row_day
        close = row_pub is None or abs((row_pub - pub_ref).total_seconds()) <= DUP_MAX_DAYS * 86400
        if sim >= DUP_T and close and (best is None or sim > best[0]):
            best = (sim, row)
            continue
        cand = json.loads(row["item_json"])
        d_other = _day(cand.get("event_date")) or _day(cand.get("published_at"))
        if d_other is None or abs((d_other - ref).days) > 1:
            continue
        t_other = cand.get("topics", [])[:2]
        if not (set(topics[:2]) & set(t_other)):
            continue
        nums_o = {(c["kind"], c["value"]) for c in cand.get("numeric_claims", [])}
        ents_o = {e["name"] for e in cand.get("entities", [])}
        shared_n, shared_e = len(numeric_values & nums_o), len(entities & ents_o)
        shared_kinds = {k for k, _ in numeric_values} & {k for k, _ in nums_o}
        reasons = []
        if sim >= EVENT_SIM_MIN:
            reasons.append(f"text_sim={sim:.2f}")
        if shared_n and shared_e:
            reasons.append("shared_numbers+entities")
        if shared_e >= 3:
            reasons.append("shared_entities>=3")
        if shared_kinds and shared_e >= 2 and topics[:1] == cand.get("topics", [])[:1]:
            reasons.append("same_metric_different_value")   # противоречащие цифры о том же событии: кластер + conflict
        if reasons and (best_event is None or sim > best_event[0]):
            best_event = (sim, row, reasons)
    if best:
        return Decision("duplicate", best[1]["id"], round(best[0], 3), best[1]["event_cluster_id"], [f"near_duplicate_minhash={best[0]:.2f}"])
    if best_event:
        return Decision("same_event", best_event[1]["id"], round(best_event[0], 3), best_event[1]["event_cluster_id"], best_event[2])
    return Decision("new", reasons=["no_match"])


def compute_conflicts(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Противоречащие числовые факты (claim_type=fact) внутри кластера. Не сливаются — возвращаются списком для UI/участника 3."""
    by_kind: dict[str, dict[float, list[str]]] = {}
    for m in members:
        if m.get("dup_of"):
            continue
        it = json.loads(m["item_json"]) if "item_json" in m else m
        for c in it.get("numeric_claims", []):
            if c.get("claim_type") != "fact":
                continue
            by_kind.setdefault(c["kind"], {}).setdefault(c["value"], [])
            if it["id"] not in by_kind[c["kind"]][c["value"]]:
                by_kind[c["kind"]][c["value"]].append(it["id"])
    out = []
    for kind, vals in by_kind.items():
        if len(vals) > 1:
            out.append({"kind": kind, "values": [{"value": v, "item_ids": ids} for v, ids in sorted(vals.items())]})
    return out
