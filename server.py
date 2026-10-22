"""HTTP-сервер (стандартная библиотека, без внешних зависимостей): REST API + раздача собранного интерфейса.

Аутентификация демонстрационная: POST /api/auth/login (login/пароль из synthetic_users.json, пароль «demo») → подписанный токен (HMAC).
Права: пользователь видит только свои компании (403 иначе). Журнал обращений — data/runtime/audit.jsonl (без текстов и профилей).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from services.company_profile.access import AccessDenied, UserNotFound
from services.company_profile.service import CompanyNotFound, CompanyQuarantined

from .service import InsightService
from .settings import load_settings

log = logging.getLogger("insight.server")
MAX_BODY = 64 * 1024
# Явные MIME-типы: на Windows mimetypes берёт их из реестра, где .js/.css бывают text/plain —
# при заголовке nosniff браузер тогда не выполнит скрипт и страница окажется пустой.
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8", ".png": "image/png", ".ico": "image/x-icon",
        ".pdf": "application/pdf", ".woff2": "font/woff2", ".map": "application/json"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class App:
    def __init__(self, svc: InsightService):
        self.svc = svc
        self.secret = (svc.s.secret or secrets.token_hex(16)).encode()
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    # ---- токены
    def issue(self, user_id: str) -> str:
        payload = base64.urlsafe_b64encode(json.dumps({"u": user_id, "exp": int(time.time()) + 12 * 3600}).encode()).decode()
        sig = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{payload}.{sig}"

    def verify(self, token: str):
        try:
            payload, sig = token.rsplit(".", 1)
            if not hmac.compare_digest(sig, hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()[:32]):
                raise ValueError
            data = json.loads(base64.urlsafe_b64decode(payload))
            if data["exp"] < time.time():
                raise ValueError
            return self.svc.dir.user(data["u"])
        except Exception as exc:  # noqa: BLE001
            raise ApiError(401, "unauthenticated", "Требуется вход") from exc

    def rate_limit(self, key: str, limit: int = 240, window: int = 60) -> None:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and q[0] < now - window:
                q.popleft()
            if len(q) >= limit:
                raise ApiError(429, "rate_limited", "Слишком много запросов")
            q.append(now)

    # ---- маршрутизация
    def handle(self, method: str, path: str, query: dict, body: dict, headers) -> tuple[int, object]:
        s = self.svc
        if path == "/api/health":
            return 200, s.health()
        if path == "/api/auth/accounts":
            return 200, {"accounts": s.dir.demo_accounts(), "password_hint": "Пароль всех демо-учётных записей — demo"}
        if path == "/api/auth/login" and method == "POST":
            u = s.dir.authenticate(str(body.get("login", "")).strip(), str(body.get("password", "")))
            if not u:
                s.journal.audit(None, "login_failed")
                raise ApiError(401, "bad_credentials", "Неверный логин или пароль")
            s.journal.audit(u.user_id, "login")
            return 200, {"token": self.issue(u.user_id), "user": self._user(u)}
        if path == "/api/openapi.json":
            return 200, OPENAPI
        auth = headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise ApiError(401, "unauthenticated", "Требуется вход")
        user = self.verify(auth[7:])
        self.rate_limit(user.user_id)
        q = lambda k, d=None: (query.get(k) or [d])[0]  # noqa: E731
        role = q("role")
        if path == "/api/me":
            return 200, self._user(user)
        if path == "/api/feed":
            return 200, s.feed(user, q("company", ""), role, q("tab", "all"), int(q("limit", 14)))
        if path == "/api/context":
            return 200, s.context(user, q("company", ""), role)
        m = re.fullmatch(r"/api/insights/([\w:.-]+)", path)
        if m:
            return 200, s.insight(user, q("company", ""), role, m.group(1))
        if path == "/api/ask" and method == "POST":
            return 200, s.ask(user, str(body.get("company", "")), body.get("role"), str(body.get("question", "")), body.get("item_id"))
        if path == "/api/feedback" and method == "POST":
            s.check(user, str(body.get("company", "")), body.get("role"))
            rating = body.get("rating")
            if rating not in ("up", "down"):
                raise ApiError(422, "bad_request", "rating: up|down")
            rec = s.journal.write("feedback", {"user": user.user_id, "company": body.get("company"), "item": body.get("item_id"), "rating": rating,
                                               "reason": str(body.get("reason", ""))[:40], "comment": str(body.get("comment", ""))[:500]})
            return 200, {"ok": True, "recorded": rec["ts"]}
        if path == "/api/actions" and method == "POST":
            s.check(user, str(body.get("company", "")), body.get("role"))
            typ = body.get("type")
            if typ not in ("manager", "request", "callback"):
                raise ApiError(422, "bad_request", "type: manager|request|callback")
            rec = s.journal.write("actions", {"user": user.user_id, "company": body.get("company"), "item": body.get("item_id"), "type": typ, "note": str(body.get("note", ""))[:500]})
            return 200, {"ok": True, "ticket": "DEMO-" + hashlib.sha1(rec["ts"].encode()).hexdigest()[:6].upper(), "message": {
                "manager": "Менеджер свяжется с вами (демо: заявка записана в журнал).", "request": "Заявка зарегистрирована (демо).", "callback": "Обратный звонок заказан (демо)."}[typ]}
        if path == "/api/analytics/macro":
            return 200, s.macro()
        if path == "/api/calendar":
            return 200, {"events": s.kb.calendar()}
        m = re.fullmatch(r"/api/sources/([\w:.-]+)", path)
        if m:
            d = s.source(m.group(1), int(q("page")) if q("page") else None)
            if not d:
                raise ApiError(404, "not_found", "Источник не найден")
            return 200, d
        if path == "/api/news/ingest" and method == "POST":
            try:
                return 200, s.ingest(user, str(body.get("text", "")), body.get("title"))
            except ValueError as exc:
                raise ApiError(422, "bad_request", str(exc)) from exc
        if path == "/api/metrics":
            return 200, s.journal.metrics(s.agent, s.kb, s.llm)
        raise ApiError(404, "not_found", "Не найдено")

    def _user(self, u) -> dict:
        return {"user_id": u.user_id, "name": u.display_name, "role": u.role, "role_title": u.role_title, "companies": self.svc.dir.user_cards(u), "roles": self.svc.dir.roles_list()}


def make_handler(app: App):
    static = app.svc.s.frontend_dir
    pdfs = app.svc.s.bank_pdf_dir

    class H(BaseHTTPRequestHandler):
        server_version = "AlfaInsight/1.0"

        def log_message(self, fmt, *args):  # noqa: A003
            log.info("%s %s", self.address_string(), fmt % args)

        def _send(self, status: int, payload, ctype: str = "application/json; charset=utf-8", extra: dict | None = None):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if app.svc.s.cors_origin:
                self.send_header("Access-Control-Allow-Origin", app.svc.s.cors_origin)
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):  # noqa: N802
            self._send(204, b"")

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def do_POST(self):  # noqa: N802
            self._route("POST")

        def _route(self, method: str):
            u = urlparse(self.path)
            path = unquote(u.path)
            cid = self.headers.get("X-Correlation-ID") or secrets.token_hex(6)
            try:
                if path.startswith("/api/"):
                    body = {}
                    if method == "POST":
                        n = int(self.headers.get("Content-Length") or 0)
                        if n > MAX_BODY:
                            raise ApiError(413, "too_large", "Слишком большой запрос")
                        try:
                            body = json.loads(self.rfile.read(n) or b"{}")
                        except json.JSONDecodeError as exc:
                            raise ApiError(400, "bad_json", "Некорректный JSON") from exc
                    status, payload = app.handle(method, path, parse_qs(u.query), body, self.headers)
                    return self._send(status, payload, extra={"X-Correlation-ID": cid})
                if path.startswith("/files/"):
                    return self._file(pdfs, path[len("/files/"):])
                return self._static(path)
            except ApiError as e:
                self._send(e.status, {"error": {"code": e.code, "message": e.message, "correlation_id": cid}}, extra={"X-Correlation-ID": cid})
            except AccessDenied:
                self._send(403, {"error": {"code": "forbidden", "message": "Нет доступа к этой компании", "correlation_id": cid}})
            except (CompanyNotFound, CompanyQuarantined, KeyError, UserNotFound):
                self._send(404, {"error": {"code": "not_found", "message": "Не найдено", "correlation_id": cid}})
            except Exception:  # noqa: BLE001
                log.exception("ошибка обработки %s %s [%s]", method, path, cid)
                self._send(500, {"error": {"code": "internal", "message": "Внутренняя ошибка", "correlation_id": cid}})

        def _file(self, root: Path, rel: str):
            """Отдаёт PDF материалов банка потоково (файлы до десятков МБ не читаются в память целиком)."""
            p = (root / rel).resolve()
            if not str(p).startswith(str(root.resolve()) + os.sep) or not p.is_file():
                return self._send(404, {"error": {"code": "not_found", "message": "Файл не найден"}})
            self.send_response(200)
            self.send_header("Content-Type", MIME.get(p.suffix.lower()) or mimetypes.guess_type(str(p))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(p.stat().st_size))
            self.send_header("Content-Disposition", "inline")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                with p.open("rb") as fh:
                    shutil.copyfileobj(fh, self.wfile, 256 * 1024)
            except (BrokenPipeError, ConnectionResetError):
                pass           # клиент закрыл вкладку — нормальная ситуация для просмотрщика PDF

        def _static(self, path: str):
            if not static.exists():
                return self._send(200, "<h1>Alfa Insight API</h1><p>Интерфейс не собран: см. README (frontend).</p>".encode(), "text/html; charset=utf-8")
            rel = path.lstrip("/") or "index.html"
            p = (static / rel).resolve()
            if not str(p).startswith(str(static.resolve())) or not p.is_file():
                p = static / "index.html"        # SPA
            ctype = MIME.get(p.suffix.lower()) or mimetypes.guess_type(str(p))[0] or "application/octet-stream"
            self._send(200, p.read_bytes(), ctype, {"Cache-Control": "no-cache"})

    return H


OPENAPI = {
    "openapi": "3.0.3", "info": {"title": "Alfa Insight API", "version": "1.0.0", "description": "Персонализированная новостная аналитика для крупного бизнеса. Демо-вход: POST /api/auth/login (пароль demo)."},
    "paths": {
        "/api/auth/login": {"post": {"summary": "Вход (демо)", "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"login": {"type": "string"}, "password": {"type": "string"}}}}}}}},
        "/api/me": {"get": {"summary": "Пользователь, его компании и роли"}},
        "/api/feed": {"get": {"summary": "Персональная лента", "parameters": [{"name": "company", "in": "query", "required": True}, {"name": "role", "in": "query"}, {"name": "tab", "in": "query"}]}},
        "/api/context": {"get": {"summary": "Контекст компании: признаки чувствительности, показатели банка, календарь"}},
        "/api/insights/{item_id}": {"get": {"summary": "Полный инсайт: что произошло, почему важно, последствия, позиция банка, действия, источники, проверки, трассировка"}},
        "/api/ask": {"post": {"summary": "Уточняющий вопрос по инсайту или компании"}},
        "/api/feedback": {"post": {"summary": "Обратная связь (up|down)"}},
        "/api/actions": {"post": {"summary": "Действие: manager | request | callback"}},
        "/api/analytics/macro": {"get": {"summary": "Прогнозы банка с версиями и заменёнными значениями"}},
        "/api/calendar": {"get": {"summary": "Ближайшие события из материалов банка"}},
        "/api/sources/{item_id}": {"get": {"summary": "Первоисточник: текст страницы/материала"}},
        "/api/news/ingest": {"post": {"summary": "Добавить новость текстом — проходит весь конвейер и ранжирование"}},
        "/api/metrics": {"get": {"summary": "Метрики качества контента, персонализации и AI-компонента"}},
        "/api/health": {"get": {"summary": "Состояние сервиса"}},
    },
}


def serve() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = load_settings()
    svc = InsightService(s)
    app = App(svc)
    try:
        httpd = ThreadingHTTPServer((s.host, s.port), make_handler(app))
    except OSError as exc:
        log.error("Порт %s занят или недоступен (%s). Задайте другой: переменная PORT, например PORT=8090.", s.port, exc)
        raise SystemExit(1) from exc
    print(f"\n  Alfa Insight запущен: http://localhost:{s.port}/   (логин demo, пароль demo)\n", flush=True)
    log.info("Alfa Insight: http://%s:%s (режим: %s, данные: %s)", s.host, s.port, "llm" if svc.llm.available else "правила", s.data_dir)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve()
