"""Заглушка авторизации для АВТОНОМНОГО запуска news_ingest.

В модуле company_profile зависимость `current_user` берёт пользователя из `app.state.profile_service.get_user(user_id)`. В общем
приложении (участник 6) это настоящий ProfileService. В автономном режиме (`uvicorn services.news_ingest.main:create_app --factory`)
его нет — подставляется эта заглушка: любой непустой X-User-ID принимается (роль other, без компаний). Только для демо/разработки;
включается явно: NEWS_STANDALONE_AUTH=demo.
"""
from __future__ import annotations

from services.company_profile.access import UserContext, UserNotFound


class StandaloneAuth:
    def get_user(self, user_id: str) -> UserContext:
        if not user_id or not user_id.strip():
            raise UserNotFound(user_id)
        return UserContext(user_id=user_id.strip(), role="other", company_ids=[], synthetic=True)
