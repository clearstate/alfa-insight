"""Авторизация для АВТОНОМНОГО запуска news_ingest (без общего приложения участника 6).

В модуле company_profile зависимость `current_user` берёт пользователя из `app.state.profile_service.get_user(user_id)`, где
user_id — заголовок X-User-ID. Это допустимо только за шлюзом, который сам аутентифицирует пользователя. Автономно:

  NEWS_STANDALONE_AUTH=token   (по умолчанию в Docker) — `Authorization: Bearer <токен>`. Токены задаются в NEWS_API_TOKENS как
                               «user_id:sha256(токена)» через запятую; в конфигурации хранятся только хеши. Новый токен:
                               `python -m services.news_ingest.cli gen-token USER_ID`. X-User-ID в этом режиме игнорируется.
  NEWS_STANDALONE_AUTH=demo    — любой непустой X-User-ID принимается (роль other, без компаний). Только локальная разработка:
                               в публичную сеть так не выставлять.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from services.company_profile.access import UserContext, UserNotFound

_HEX64 = re.compile(r"[0-9a-f]{64}")
_USER = re.compile(r"[A-Za-z0-9_.@-]{1,64}")


class StandaloneAuth:
    def get_user(self, user_id: str) -> UserContext:
        if not user_id or not user_id.strip():
            raise UserNotFound(user_id)
        return UserContext(user_id=user_id.strip(), role="other", company_ids=[], synthetic=True)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(user_id: str) -> tuple[str, str]:
    """(токен — выдать пользователю один раз, запись для NEWS_API_TOKENS)."""
    if not _USER.fullmatch(user_id or ""):
        raise ValueError("user_id: латиница, цифры, _ . @ -, до 64 символов")
    token = secrets.token_urlsafe(32)
    return token, f"{user_id}:{hash_token(token)}"


class TokenAuth:
    MIN_TOKEN_LEN = 24

    def __init__(self, spec: str | None):
        self._entries: list[tuple[str, str]] = []
        for part in (spec or "").split(","):
            part = part.strip()
            if not part:
                continue
            user, sep, digest = part.rpartition(":")
            digest = digest.strip().lower()
            if not sep or not _USER.fullmatch(user.strip()) or not _HEX64.fullmatch(digest):
                raise ValueError("NEWS_API_TOKENS: ожидается «user_id:sha256hex» через запятую (см. cli gen-token)")
            self._entries.append((user.strip(), digest))
        if not self._entries:
            raise ValueError("NEWS_API_TOKENS пуст: без токенов API в режиме token недоступен (cli gen-token USER_ID)")

    def user_for_token(self, token: str | None) -> UserContext | None:
        if not token or len(token) < self.MIN_TOKEN_LEN:
            return None
        digest = hash_token(token)
        found = None
        for user, d in self._entries:            # сравнение без раннего выхода: время ответа не зависит от совпадения
            if hmac.compare_digest(d, digest):
                found = user
        return UserContext(user_id=found, role="other", company_ids=[], synthetic=False) if found else None

