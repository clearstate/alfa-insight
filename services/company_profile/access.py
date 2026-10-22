"""Профиль пользователя (user_context) и проверка прав.

Сервис создаётся для людей: у одной компании несколько пользователей с разными ролями.
В прототипе пользователи — синтетические (data/synthetic_users.json, флаг synthetic=true).
Реальная аутентификация — зона участника 6; здесь только модель и проверка доступа к company_id.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).parent / "config"
ROLES = ("owner", "ceo", "cfo", "chief_accountant", "treasury", "other_c_level", "other")


class AccessDenied(Exception):
    pass


class UserNotFound(Exception):
    pass


def load_roles(path: str | Path | None = None) -> dict[str, dict]:
    path = Path(path) if path else CONFIG_DIR / "roles.yaml"
    with open(path, encoding="utf-8") as fh:
        roles = yaml.safe_load(fh)["roles"]
    unknown = set(roles) - set(ROLES)
    if unknown:
        raise ValueError(f"roles.yaml: unknown roles {sorted(unknown)}")
    return roles


@dataclass
class UserContext:
    user_id: str
    role: str
    company_ids: list[str]
    display_name: str | None = None
    priority_topics: list[str] = field(default_factory=list)
    role_title: str | None = None
    synthetic: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


class UserStore:
    def __init__(self, users: list[UserContext]):
        self._users = {u.user_id: u for u in users}

    @classmethod
    def from_records(cls, records: list[dict], roles: dict[str, dict] | None = None) -> "UserStore":
        roles = roles if roles is not None else load_roles()
        users = []
        for rec in records:
            role = rec["role"]
            if role not in ROLES:
                raise ValueError(f"user {rec.get('user_id')}: unknown role {role}")
            rcfg = roles.get(role, {})
            users.append(UserContext(
                user_id=str(rec["user_id"]),
                role=role,
                company_ids=[str(c) for c in rec.get("company_ids", [])],
                display_name=rec.get("display_name"),
                priority_topics=list(rec.get("priority_topics") or rcfg.get("priority_topics", [])),
                role_title=rcfg.get("title"),
                synthetic=bool(rec.get("synthetic", True)),
            ))
        return cls(users)

    @classmethod
    def from_json(cls, path: str | Path, roles: dict[str, dict] | None = None) -> "UserStore":
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        return cls.from_records(payload["users"], roles)

    def get(self, user_id: str) -> UserContext:
        user = self._users.get(user_id)
        if user is None:
            raise UserNotFound(user_id)
        return user

    def all(self) -> list[UserContext]:
        return list(self._users.values())


def authorize(user: UserContext, company_id: str) -> None:
    if company_id not in user.company_ids:
        raise AccessDenied(f"user {user.user_id} has no access to {company_id}")
