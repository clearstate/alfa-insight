"""Профили компаний и пользователей: тонкий слой над company_profile (участник 1)."""
from __future__ import annotations

import logging
from typing import Any

from services.company_profile.access import UserContext, UserNotFound, authorize, load_roles
from services.company_profile.industry_terms import match_supply_chain
from services.company_profile.prompt_view import build_prompt_view
from services.company_profile.service import CompanyNotFound, CompanyQuarantined, ProfileService

from .settings import Settings

log = logging.getLogger("insight.people")
DEMO_PASSWORD = "demo"


class Directory:
    def __init__(self, settings: Settings):
        self.s = settings
        users_path = settings.root / "data" / "synthetic_users.json"
        self.svc = ProfileService.from_data_dir(settings.data_dir, users_path=users_path)
        self.roles = load_roles()
        log.info("профили: %s компаний из %s", len(self.svc.data.companies), settings.data_dir)

    # ---- пользователи
    def authenticate(self, login: str, password: str) -> UserContext | None:
        try:
            u = self.svc.users.get(login)
        except UserNotFound:
            return None
        return u if password == DEMO_PASSWORD else None

    def user(self, user_id: str) -> UserContext:
        return self.svc.users.get(user_id)

    def demo_accounts(self) -> list[dict]:
        return [{"login": u.user_id, "name": u.display_name, "role": u.role, "role_title": u.role_title, "companies": len(u.company_ids)}
                for u in self.svc.users.all() if u.company_ids]

    def authorize(self, user: UserContext, company_id: str) -> None:
        authorize(user, company_id)

    def role_info(self, role: str) -> dict:
        r = self.roles.get(role) or self.roles["other"]
        return {"code": role, "title": r.get("title"), "focus": r.get("focus"), "priority_topics": list(r.get("priority_topics") or [])}

    def roles_list(self) -> list[dict]:
        return [self.role_info(c) for c in self.roles]

    # ---- компании
    def profile(self, company_id: str) -> dict:
        return self.svc.build_profile(company_id)

    def prompt_view(self, profile: dict) -> dict:
        return build_prompt_view(profile)

    def related(self, company_id: str, limit: int = 40) -> dict:
        return self.svc.get_related(company_id, limit=limit)

    def supply_matches(self, prefixes: list[str], profile: dict) -> list[dict]:
        if not prefixes:
            return []
        try:
            return match_supply_chain(prefixes, profile)
        except Exception:  # noqa: BLE001 — неизвестный префикс не должен ронять ранжирование
            return []

    def card(self, company_id: str) -> dict[str, Any]:
        """Карточка для переключателя компаний и шапки (без чувствительных деталей)."""
        s = self.svc.company_summary(company_id)
        if s.get("status") != "ok":
            return {"company_id": company_id, "status": s.get("status"), "name": f"Компания {company_id}"}
        p = self.profile(company_id)
        name_okved = s.get("okved_name") or ""
        short_name = name_okved.split(",")[0]
        short_name = short_name[:1].upper() + short_name[1:]
        number = company_id.split("_")[-1]
        return {
            "company_id": company_id, "status": "ok", "name": f"Компания №{number}", "letter": (short_name[:1] or "К").upper(),
            "okved_code": s.get("okved_code"), "okved_name": name_okved, "city": s.get("city"), "region": s.get("region"),
            "revenue": s.get("revenue"), "is_large_business": s.get("is_large_business"), "client_type": s.get("client_type"),
            "headline": short_name[:70] + ("…" if len(short_name) > 70 else ""),
            "factor_levels": {f["code"]: f["level"] for f in p["sensitivity_factors"]},
        }

    def user_cards(self, user: UserContext) -> list[dict]:
        out = []
        for cid in user.company_ids:
            try:
                out.append(self.card(cid))
            except (CompanyNotFound, CompanyQuarantined):
                out.append({"company_id": cid, "status": "not_found", "name": f"Компания {cid}"})
        return out

    def health(self) -> dict:
        return self.svc.health()
