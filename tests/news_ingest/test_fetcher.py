import unittest

from services.news_ingest.fetcher import FetchError, SafeFetcher, check_url
from tests.news_ingest.helpers import Server, html


def F(**kw):
    kw.setdefault("allow_private", True)       # сервер на 127.0.0.1
    kw.setdefault("respect_robots", False)
    kw.setdefault("min_interval", 0.0)
    kw.setdefault("sleep", lambda s: None)
    return SafeFetcher(**kw)


class Fetcher(unittest.TestCase):
    def test_ok_and_charset(self):
        body = html("Заголовок", ["Текст абзаца про ключевую ставку и инфляцию достаточно длинный."])
        with Server({"/a": (200, {"Content-Type": "text/html; charset=utf-8"}, body)}) as s:
            r = F().fetch(s.base + "/a")
        self.assertEqual((r.status, r.content_type, r.charset), (200, "text/html", "utf-8"))
        self.assertIn("Заголовок".encode(), r.body)

    def test_404_not_retried(self):
        with Server({}) as s:
            with self.assertRaises(FetchError) as cm:
                F().fetch(s.base + "/missing")
            self.assertEqual(cm.exception.code, "http_404")
            self.assertEqual(s.hits["/missing"], 1)

    def test_500_retried_then_ok(self):
        def flaky(n):
            return (500, {}, b"err") if n < 3 else (200, {"Content-Type": "text/html"}, b"<html>ok</html>")
        sleeps = []
        with Server({"/f": flaky}) as s:
            r = F(retries=3, backoff=1.0, sleep=sleeps.append).fetch(s.base + "/f")
            self.assertEqual(r.status, 200); self.assertEqual(s.hits["/f"], 3)
        self.assertEqual(sleeps, [1.0, 2.0])         # экспоненциальная задержка

    def test_retries_exhausted(self):
        with Server({"/x": (503, {}, b"")}) as s:
            with self.assertRaises(FetchError) as cm:
                F(retries=2).fetch(s.base + "/x")
            self.assertEqual(cm.exception.code, "http_503"); self.assertEqual(s.hits["/x"], 3)

    def test_timeout(self):
        with Server({"/slow": (200, {"Content-Type": "text/html", "X-Delay": "1.5"}, b"x")}) as s:
            with self.assertRaises(FetchError) as cm:
                F(timeout=0.3, retries=0).fetch(s.base + "/slow")
            self.assertEqual(cm.exception.code, "network_error")

    def test_too_large_and_bad_content_type(self):
        with Server({"/big": (200, {"Content-Type": "text/html"}, b"a" * 5000), "/bin": (200, {"Content-Type": "image/png"}, b"x")}) as s:
            with self.assertRaises(FetchError) as cm:
                F(max_bytes=1000).fetch(s.base + "/big")
            self.assertEqual(cm.exception.code, "too_large")
            with self.assertRaises(FetchError) as cm:
                F().fetch(s.base + "/bin")
            self.assertEqual(cm.exception.code, "unsupported_content_type")

    def test_ssrf_blocked_by_default(self):
        for u in ("http://127.0.0.1:9/x", "http://localhost/x", "http://169.254.169.254/latest/meta-data", "http://10.0.0.5/", "http://[::1]/"):
            with self.assertRaises(FetchError) as cm:
                check_url(u)
            self.assertEqual(cm.exception.code, "ssrf_blocked", u)

    def test_bad_scheme_and_credentials_and_domain_allowlist(self):
        for u, code in (("file:///etc/passwd", "bad_scheme"), ("ftp://x/y", "bad_scheme"), ("http://user:pw@example.com/", "bad_url")):
            with self.assertRaises(FetchError) as cm:
                check_url(u, allow_private=True)
            self.assertEqual(cm.exception.code, code)
        with self.assertRaises(FetchError) as cm:
            check_url("http://evil.example.org/", allow_private=True, allowed_domains=["cbr.ru"])
        self.assertEqual(cm.exception.code, "domain_not_allowed")
        check_url("https://www.cbr.ru/x", allow_private=True, allowed_domains=["cbr.ru"])

    def test_redirect_followed_and_loop_limited(self):
        with Server({"/r": (302, {"Location": "/t"}, b""), "/t": (200, {"Content-Type": "text/html"}, b"<html>t</html>"),
                     "/loop": (302, {"Location": "/loop"}, b"")}) as s:
            self.assertEqual(F().fetch(s.base + "/r").status, 200)
            with self.assertRaises(FetchError) as cm:
                F(max_redirects=3).fetch(s.base + "/loop")
            self.assertEqual(cm.exception.code, "too_many_redirects")

    def test_redirect_to_forbidden_scheme_blocked(self):
        with Server({"/r": (302, {"Location": "file:///etc/passwd"}, b"")}) as s:
            with self.assertRaises(FetchError) as cm:
                F().fetch(s.base + "/r")
            self.assertEqual(cm.exception.code, "bad_scheme")

    def test_robots(self):
        routes = {"/robots.txt": (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /private\n"),
                  "/private/a": (200, {"Content-Type": "text/html"}, b"x"), "/pub/a": (200, {"Content-Type": "text/html"}, b"<html>ok</html>")}
        with Server(routes) as s:
            f = F(respect_robots=True)
            self.assertEqual(f.fetch(s.base + "/pub/a").status, 200)
            with self.assertRaises(FetchError) as cm:
                f.fetch(s.base + "/private/a")
            self.assertEqual(cm.exception.code, "robots_disallowed")
        with Server({"/p": (200, {"Content-Type": "text/html"}, b"<html>ok</html>")}) as s:      # нет robots.txt (404) -> разрешено
            self.assertEqual(F(respect_robots=True).fetch(s.base + "/p").status, 200)
        with Server({"/robots.txt": (500, {}, b""), "/p": (200, {"Content-Type": "text/html"}, b"x")}) as s:   # 5xx -> консервативно запрет
            with self.assertRaises(FetchError):
                F(respect_robots=True, retries=0).fetch(s.base + "/p")

    def test_robots_error_is_retried_after_ttl(self):
        """Временная ошибка robots.txt не блокирует источник навсегда (важно для постоянного процесса расписания)."""
        t = [0.0]
        robots = lambda n: (500, {}, b"") if n == 1 else (200, {"Content-Type": "text/plain"}, b"User-agent: *\nAllow: /\n")
        with Server({"/robots.txt": robots, "/p": (200, {"Content-Type": "text/html"}, b"<html>ok</html>")}) as s:
            f = F(respect_robots=True, retries=0, clock=lambda: t[0])
            with self.assertRaises(FetchError):
                f.fetch(s.base + "/p")
            t[0] += 11 * 60
            self.assertEqual(f.fetch(s.base + "/p").status, 200)
            self.assertEqual(s.hits["/robots.txt"], 2)

    def test_rate_limit_sleeps(self):
        sleeps, t = [], [0.0]
        with Server({"/a": (200, {"Content-Type": "text/html"}, b"<html>a</html>")}) as s:
            f = F(min_interval=2.0, sleep=sleeps.append, clock=lambda: t[0])
            f.fetch(s.base + "/a"); t[0] = 0.5; f.fetch(s.base + "/a")
        self.assertEqual(len(sleeps), 1); self.assertAlmostEqual(sleeps[0], 1.5)


if __name__ == "__main__":
    unittest.main()
