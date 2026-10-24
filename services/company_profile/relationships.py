"""Индекс связей между компаниями.

Типы связей: same_group, shared_person, payment_in, payment_out.
Ни один тип сам по себе не означает контроль, аффилированность или общего собственника.
Платежи без дат — суммарные значения с 1 января (вебинар, вопрос 20), без временных агрегатов.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from .validation import CleanData

RELATION_TYPES = ("same_group", "shared_person", "payment_in", "payment_out")


@dataclass
class PaymentEdge:
    counterparty_id: str
    pay_amt: float
    pay_cnt: int
    source_line: int
    n_rows: int


class RelationshipIndex:
    def __init__(self, data: CleanData):
        self._data = data
        companies = data.companies

        self.group_members: dict[str, list[str]] = {
            g: sorted(ids) for g, ids in companies.groupby("GROUP_ID")["SYNTHETIC_U"].apply(list).items()
        }

        self.person_companies: dict[str, list[str]] = defaultdict(list)
        self.company_persons: dict[str, list[str]] = defaultdict(list)
        for f_id, u_id in data.persons[["SYNTHETIC_F", "SYNTHETIC_U"]].itertuples(index=False):
            self.person_companies[f_id].append(u_id)
            self.company_persons[u_id].append(f_id)

        p = data.payments
        self._payer = p["PAYER"].to_numpy()
        self._benef = p["BENEFICIARY"].to_numpy()
        self._amt = p["PAY_AMT"].to_numpy(dtype=float)
        self._cnt = p["PAY_CNT"].to_numpy(dtype=np.int64)
        self._line = p["_line"].to_numpy(dtype=np.int64)
        self._nrows = p["n_rows"].to_numpy(dtype=np.int64)
        self._out_idx = p.groupby("PAYER", sort=False).indices if len(p) else {}
        self._in_idx = p.groupby("BENEFICIARY", sort=False).indices if len(p) else {}

    # --- группа -------------------------------------------------------------
    def group_of(self, company_id: str) -> str | None:
        if company_id not in self._data.companies.index:
            return None
        return self._data.companies.at[company_id, "GROUP_ID"]

    def group_peers(self, company_id: str) -> list[str]:
        gid = self.group_of(company_id)
        if gid is None:
            return []
        return [c for c in self.group_members.get(gid, []) if c != company_id]

    # --- общие физлица ------------------------------------------------------
    def shared_person_companies(self, company_id: str) -> dict[str, int]:
        """Компании, связанные с данной через общих физлиц: id -> число общих физлиц."""
        counts: dict[str, int] = defaultdict(int)
        for f_id in self.company_persons.get(company_id, []):
            for other in set(self.person_companies[f_id]):
                if other != company_id:
                    counts[other] += 1
        return dict(counts)

    # --- платежи ------------------------------------------------------------
    def _edges(self, idx: np.ndarray | None, other: np.ndarray) -> list[PaymentEdge]:
        if idx is None or len(idx) == 0:
            return []
        # Сортировка: сумма по убыванию, при равенстве — id контрагента. Не зависит от порядка строк в хранилище.
        order = idx[np.lexsort((other[idx].astype(str), -self._amt[idx]))]
        return [
            PaymentEdge(str(other[i]), float(self._amt[i]), int(self._cnt[i]), int(self._line[i]), int(self._nrows[i]))
            for i in order
        ]

    def payments_out(self, company_id: str) -> list[PaymentEdge]:
        """Исходящие: компания — плательщик, контрагент — получатель. Отсортировано по сумме."""
        return self._edges(self._out_idx.get(company_id), self._benef)

    def payments_in(self, company_id: str) -> list[PaymentEdge]:
        """Входящие: компания — получатель, контрагент — плательщик. Отсортировано по сумме."""
        return self._edges(self._in_idx.get(company_id), self._payer)

    def self_payments(self, company_id: str) -> dict | None:
        sp = self._data.self_payments
        if company_id not in sp.index:
            return None
        row = sp.loc[company_id]
        return {"pay_amt": float(row["PAY_AMT"]), "pay_cnt": int(row["PAY_CNT"]), "n_rows": int(row["n_rows"])}

    # --- сводно -------------------------------------------------------------
    def related(self, company_id: str) -> dict[str, dict]:
        """Все связанные компании: id -> {types, shared_persons, pay_amt_in, pay_amt_out, ...}."""
        rel: dict[str, dict] = defaultdict(lambda: {
            "types": set(), "shared_persons": 0, "pay_amt_in": 0.0, "pay_cnt_in": 0,
            "pay_amt_out": 0.0, "pay_cnt_out": 0,
        })
        for peer in self.group_peers(company_id):
            rel[peer]["types"].add("same_group")
        for peer, n in self.shared_person_companies(company_id).items():
            rel[peer]["types"].add("shared_person")
            rel[peer]["shared_persons"] = n
        for e in self.payments_in(company_id):
            rel[e.counterparty_id]["types"].add("payment_in")
            rel[e.counterparty_id]["pay_amt_in"] += e.pay_amt
            rel[e.counterparty_id]["pay_cnt_in"] += e.pay_cnt
        for e in self.payments_out(company_id):
            rel[e.counterparty_id]["types"].add("payment_out")
            rel[e.counterparty_id]["pay_amt_out"] += e.pay_amt
            rel[e.counterparty_id]["pay_cnt_out"] += e.pay_cnt
        return dict(rel)
