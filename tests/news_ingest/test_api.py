"""HTTP-слой news_ingest: автономная авторизация по токенам, права на ингест, health со свежестью лент (нужны fastapi, httpx)."""
import os
import unittest
from unittest import mock

try:
    from fastapi.testclient import TestClient

    from services.news_ingest.auth_shim import TokenAuth, hash_token, new_token
    from services.news_ingest.main import create_app
except ImportError as e:  # pragma: no cover - среда без fastapi/httpx
    raise unittest.SkipTest(f"missing dependency: {e.name}")

from services.news_ingest.store import NewsStore
from tests.news_ingest.helpers import RATE_A

ALICE_TOKEN, ALICE_ENTRY = new_token("alice")
BOB_TOKEN, BOB_ENTRY = new_token("bob")
BASE_ENV = {"NEWS_STANDALONE_AUTH": "token", "NEWS_API_TOKENS": f"{ALICE_ENTRY},{BOB_ENTRY}", "NEWS_INGEST_USERS": "alice",
            "NEWS_INGEST_OPEN": "", "NEWS_BOOTSTRAP_BANK": "", "LLM_BASE_URL": ""}


def client(**env) -> TestClient:
    st = NewsStore("sqlite:///:memory:")
    with mock.patch.dict(os.environ, {**BASE_ENV, **env}):
        app = create_app(store=st)
    return TestClient(app)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TokenMode(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, BASE_ENV)
        self.env.start()
        self.c = client()

    def tearDown(self):
        self.env.stop()

    def test_read_requires_valid_token(self):
        self.assertEqual(self.c.get("/api/news").status_code, 401)
        self.assertEqual(self.c.get("/api/news", headers={"X-User-ID": "alice"}).status_code, 401)   # заголовок не доверяется
        self.assertEqual(self.c.get("/api/news", headers=bearer("x" * 43)).status_code, 401)
        self.assertEqual(self.c.get("/api/news", headers={"Authorization": f"Basic {ALICE_TOKEN}"}).status_code, 401)
        self.assertEqual(self.c.get("/api/news", headers=bearer(ALICE_TOKEN)).status_code, 200)
        self.assertEqual(self.c.get("/api/pipeline/errors", headers=bearer(BOB_TOKEN)).status_code, 200)

    def test_ingest_only_for_allowed_users(self):
        body = {"text": " ".join(RATE_A), "title": "ЦБ сохранил ставку", "published_at": "2026-09-11"}
        self.assertEqual(self.c.post("/api/news/ingest", json=body).status_code, 401)
        self.assertEqual(self.c.post("/api/news/ingest", json=body, headers=bearer(BOB_TOKEN)).status_code, 403)
        r = self.c.post("/api/news/ingest", json=body, headers=bearer(ALICE_TOKEN))
        self.assertEqual(r.status_code, 200, r.text); self.assertEqual(r.json()["outcome"], "created")
        item = self.c.get(f"/api/news/{r.json()['item_id']}", headers=bearer(BOB_TOKEN))
        self.assertEqual(item.status_code, 200); self.assertEqual(item.json()["published_at"], "2026-09-11T00:00:00+00:00")

    def test_health_is_public_and_reports_feed_freshness(self):
        r = self.c.get("/api/news/health")
        self.assertEqual(r.status_code, 200)
        fr = r.json()["freshness"]
        self.assertIn("cbr_press", [s["source_id"] for s in fr["sources"]])     # включённая лента ещё не обходилась
        self.assertEqual(r.json()["status"], "degraded")


class Config(unittest.TestCase):
    def test_refuses_to_start_without_auth(self):
        for env in ({"NEWS_STANDALONE_AUTH": ""}, {"NEWS_API_TOKENS": ""}, {"NEWS_API_TOKENS": "alice:not-a-hash"},
                    {"NEWS_API_TOKENS": "alice"}):
            with self.subTest(env=env), self.assertRaises(RuntimeError):
                client(**env)

    def test_demo_mode_still_available_locally(self):
        with mock.patch.dict(os.environ, {**BASE_ENV, "NEWS_STANDALONE_AUTH": "demo"}):
            c = client(NEWS_STANDALONE_AUTH="demo")
            self.assertEqual(c.get("/api/news", headers={"X-User-ID": "anyone"}).status_code, 200)

    def test_token_hashing(self):
        auth = TokenAuth(f"carol:{hash_token('t' * 30)}")
        self.assertEqual(auth.user_for_token("t" * 30).user_id, "carol")
        self.assertIsNone(auth.user_for_token("t" * 29 + "u")); self.assertIsNone(auth.user_for_token("short"))
        self.assertIsNone(auth.user_for_token(None))
        with self.assertRaises(ValueError):
            new_token("bad user")


if __name__ == "__main__":
    unittest.main()
