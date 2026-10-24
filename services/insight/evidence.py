"""Книга доказательств: каждое утверждение ответа ссылается на элементы с первоисточником и происхождением."""
from __future__ import annotations

from typing import Any

from .labels import basis_ru, factor_phrase
from .textkit import ru_date, ru_date_short, ru_num, ru_value, short

# origin — сквозная шкала происхождения вывода (критерии 3 и 12):
#   fact          — факт из новости (подтверждённый)
#   unconfirmed   — слух/предположение из новости (не факт)
#   bank_view     — позиция/прогноз Альфа-Банка (правила по маркерам из аналитических материалов)
#   bank_data     — цифры и факты из аналитических материалов банка (не оценка)
#   company_data  — данные о компании (поля CSV) — «факт»
#   rule          — расчёт/правило системы (детерминированно, не LLM)
#   ai            — вывод AI-компонента (система/LLM), не позиция банка
ORIGINS = ("fact", "unconfirmed", "bank_view", "bank_data", "company_data", "rule", "ai")


class EvidenceBook:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self._key: dict[str, str] = {}

    def _add(self, key: str, **f: Any) -> str:
        if key in self._key:
            return self._key[key]
        eid = f"E{len(self.items) + 1}"
        f["id"] = eid
        self.items.append(f)
        self._key[key] = eid
        return eid

    def get(self, eid: str) -> dict | None:
        return next((e for e in self.items if e["id"] == eid), None)

    # ---- конструкторы
    def news(self, item: dict, text: str, *, key_suffix: str = "", unconfirmed: bool = False) -> str:
        return self._add(f"news:{item['id']}:{key_suffix or text[:40]}", kind="news", origin="unconfirmed" if unconfirmed else "fact",
                         label=("Слух/неподтверждённое сообщение" if unconfirmed else "Новость") + f" · {item.get('display_source') or ''}".rstrip(" ·"),
                         text=short(text, 360), numbers=None,
                         source={"item_id": item["id"], "title": item.get("title"), "publisher": item.get("display_source"),
                                 "published_at": item.get("published_at"), "page": None, "source_file": None, "synthetic": item.get("synthetic", False)})

    def bank_fact(self, item: dict, text: str, page: int | None, claim_type: str = "fact") -> str:
        origin = "bank_view" if claim_type == "bank_view" else "bank_data"
        return self._add(f"bankfact:{item['id']}:{text[:40]}", kind="bank", origin=origin,
                         label=("Позиция Альфа-Банка" if origin == "bank_view" else "Данные из аналитики банка") + f" · {item.get('doc_title')}",
                         text=short(text, 420), numbers=None,
                         source={"item_id": item["id"], "title": item.get("doc_title"), "publisher": "Альфа-Банк", "published_at": item.get("published_at"),
                                 "page": page, "source_file": item.get("source_file")})

    def anchor(self, a: dict) -> str:
        origin = "bank_view" if a.get("claim_type") == "bank_view" else "bank_data"
        return self._add(f"anchor:{a['id']}", kind="bank", origin=origin,
                         label=("Позиция Альфа-Банка" if origin == "bank_view" else "Данные из аналитики банка") + f" · {a['doc_title']}",
                         text=a["quote"], summary=a["summary"], numbers=None,
                         source={"item_id": a["item_id"], "title": a["doc_title"], "publisher": "Альфа-Банк", "published_at": a["published_at"],
                                 "page": a["page"], "source_file": a["source_file"], "chunk_id": a["chunk_id"], "anchor_id": a["id"]})

    def bank_chunk(self, ch: dict, item: dict) -> str:
        origin = "bank_view" if ch.get("claim_type") == "bank_view" else "bank_data"
        return self._add(f"chunk:{ch['id']}", kind="bank", origin=origin,
                         label=("Позиция Альфа-Банка" if origin == "bank_view" else "Данные из аналитики банка") + f" · {item.get('doc_title')}",
                         text=short(ch["text"], 420), numbers=None,
                         source={"item_id": item["id"], "title": item.get("doc_title"), "publisher": "Альфа-Банк", "published_at": item.get("published_at"),
                                 "page": ch.get("page"), "source_file": item.get("source_file"), "chunk_id": ch["id"]})

    def indicator(self, ind: dict) -> str:
        text = f"{ind['label']}, {ind['period']}: {ru_value(ind['value'], ind.get('unit'))} — прогноз банка от {ru_date(ind['published_at'])}, стр. {ind.get('page')}"
        if ind.get("superseded"):
            old = ", ".join(f"{ru_num(s['value'], 2, strip=True)} ({ru_date_short(s['published_at'])})" for s in ind["superseded"][:3])
            text += f". Предыдущие значения: {old} — заменены более поздним документом"
        return self._add(f"ind:{ind['indicator']}:{ind['period']}", kind="indicator", origin="bank_view", label="Прогноз Альфа-Банка · " + (ind.get("doc_title") or ""),
                         text=text, numbers=[ind["value"]] + [s["value"] for s in ind.get("superseded", [])],
                         source={"item_id": ind["item_id"], "title": ind.get("doc_title"), "publisher": "Альфа-Банк", "published_at": ind["published_at"],
                                 "page": ind.get("page"), "source_file": ind.get("source_file"), "indicator": ind["indicator"], "period": ind["period"]})

    def company(self, code: str, factor: dict) -> str:
        based = factor.get("based_on") or []
        origin = "rule"
        return self._add(f"company:{code}", kind="company", origin=origin,
                         label=f"Признак компании · {factor_phrase(code, factor['level'])}", text=short(factor.get("rationale") or "", 380),
                         numbers=None,
                         source={"rule_id": factor.get("rule_id"), "level": factor["level"], "confidence": factor.get("confidence"),
                                 "basis": basis_ru(based[:6]),          # для интерфейса; коды полей — в based_on
                                 "based_on": [f"{b.get('source_file')}:{b.get('source_row_id')}:{b.get('source_field')}={b.get('value')}" for b in based[:6]]})

    def company_fact(self, key: str, text: str, src: dict) -> str:
        return self._add(f"cf:{key}", kind="company", origin="company_data", label="Данные о компании", text=text, numbers=None, source=src)

    def role_fact(self, role: str, text: str) -> str:
        """Настройка роли пользователя (roles.yaml) — правило системы, а не данные о компании."""
        return self._add(f"role:{role}", kind="role", origin="rule", label="Приоритеты роли", text=text, numbers=None,
                         source={"config": "roles.yaml", "role": role})

    def calc(self, key: str, text: str, numbers: list[float]) -> str:
        return self._add(f"calc:{key}", kind="calc", origin="rule", label="Расчёт системы", text=text, numbers=numbers, source={"method": "deterministic_formula"})

    def all_numbers(self) -> set[float]:
        from .textkit import numbers as nums
        out: set[float] = set()
        for e in self.items:
            out.update(nums(e["text"]))
            if e.get("summary"):
                out.update(nums(e["summary"]))
            out.update(e.get("numbers") or [])
        return out
