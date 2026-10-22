"""Синтетические учётные записи для демо и e2e (synthetic = true).

Пользователи привязаны к демо-компаниям по слотам из ProfileService.select_demo_companies.
Реальных пользователей и аутентификацию предоставляет интеграция (участник 6).
"""

from __future__ import annotations

# user_id, роль, отображаемое имя, демо-слоты компаний
USER_PLAN = [
    ("u_cfo_demo", "cfo", "Ирина Волкова", ["credit_and_fx", "credit_no_fx"]),
    ("u_treasury_demo", "treasury", "Дмитрий Орлов", ["deposits_treasury", "credit_and_fx"]),
    ("u_accountant_demo", "chief_accountant", "Елена Смирнова", ["consumer_sector"]),
    ("u_owner_demo", "owner", "Сергей Морозов", ["no_credit_no_fx", "consumer_sector"]),
    ("u_ceo_demo", "ceo", "Андрей Лебедев", ["credit_no_fx", "no_credit_no_fx"]),
    ("u_other_demo", "other", "Ольга Кузнецова", []),
]


def build_demo_users(demo: list[dict]) -> list[dict]:
    by_slot = {x["slot"]: x["company_id"] for x in demo}
    users = []
    for uid, role, name, slots in USER_PLAN:
        ids = list(dict.fromkeys(by_slot[s] for s in slots if s in by_slot))
        users.append({"user_id": uid, "role": role, "display_name": name, "company_ids": ids,
                      "priority_topics": None, "synthetic": True})
    return users
