"""Журналы выполнения: обратная связь, действия пользователя, аудит обращений; метрики качества."""
from __future__ import annotations

import json
import threading
import time
from collections import Counter
from pathlib import Path


class Journal:
    def __init__(self, runtime_dir: Path):
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self.dir = runtime_dir
        self.lock = threading.Lock()

    def write(self, name: str, rec: dict) -> dict:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}
        with self.lock, (self.dir / f"{name}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def read(self, name: str, limit: int = 5000) -> list[dict]:
        p = self.dir / f"{name}.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def audit(self, user: str | None, action: str, **kw) -> None:
        self.write("audit", {"user": user, "action": action, **kw})   # данные профиля и тексты в журнал не пишутся

    def metrics(self, agent, kb, llm) -> dict:
        fb = self.read("feedback")
        votes = Counter(f.get("rating") for f in fb)
        total = votes.get("up", 0) + votes.get("down", 0)
        runs, built = list(agent.audit), list(agent.cache.copy().values())      # снимки: сервер многопоточный
        checks_failed = sum(1 for k in built if not (k.get("checks") or {}).get("passed", True))
        n = max(1, len(built))
        lat = sorted(r["ms"] for r in runs) or [0]
        return {
            "content": {"items": len(kb.items), "bank_docs": sum(1 for i in kb.items.values() if i["kind"] == "bank"),
                        "needs_review": sum(1 for i in kb.items.values() if i.get("processing_status") != "ok"),
                        "blocked_injection": sum(1 for i in kb.items.values() if i.get("injection")),
                        "unconfirmed": sum(1 for i in kb.items.values() if i.get("unconfirmed")), "stale": sum(1 for i in kb.items.values() if i.get("stale"))},
            "quality": {"insights_built": len(built), "self_check_failed_share": round(checks_failed / n, 3),
                        "useful_share": round(votes.get("up", 0) / total, 3) if total else None, "feedback_total": total,
                        "irrelevant_reports": sum(1 for f in fb if f.get("reason") == "irrelevant"),
                        "hidden_by_users": sum(1 for h in self.read("hidden") if h.get("hidden")),
                        "p50_ms": lat[len(lat) // 2], "p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))]},
            "usage": {"actions": Counter(a.get("type") for a in self.read("actions")), "questions": len(self.read("questions"))},
            "llm": llm.status(), "kb": kb.stats(),
        }
