"""Расписание обхода лент и контроль последнего успешного обновления (scheduler.py)."""
import unittest
from datetime import datetime, timedelta

from services.news_ingest import scheduler
from services.news_ingest.fetcher import SafeFetcher
from services.news_ingest.pipeline import IngestPipeline
from services.news_ingest.store import NewsStore
from tests.news_ingest.helpers import RATE_A, Server, html, rss


class Clock:
    def __init__(self, start: str = "2026-10-21T10:00:00+00:00"):
        self.t = datetime.fromisoformat(start)

    def __call__(self) -> str:
        return self.t.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    def advance(self, minutes: float) -> None:
        self.t += timedelta(minutes=minutes)


def make(base: str, enabled: bool = True):
    st = NewsStore("sqlite:///:memory:"); st.init_schema()
    clock = Clock()
    sources = {"smi": {"id": "smi", "type": "media", "name": "Тестовое СМИ", "method": "rss", "url": base + "/feed",
                       "enabled": enabled, "interval_min": 30, "max_staleness_min": 60, "reliability": {"score": 0.7, "rule": "t"}},
               "manual_file": {"id": "manual_file", "type": "user_submitted", "name": "manual", "method": "manual", "enabled": True,
                               "reliability": {"score": 0.3, "rule": "t"}}}
    f = SafeFetcher(allow_private=True, respect_robots=False, min_interval=0, sleep=lambda s: None, retries=1)
    return st, IngestPipeline(st, fetcher=f, sources=sources, clock=clock), clock


FEED_OK = lambda base: (200, {"Content-Type": "application/rss+xml"},
                        rss([("ЦБ сохранил ставку", base + "/a", "Wed, 21 Oct 2026 12:00:00 +0300", RATE_A[0])]))
PAGE = (200, {"Content-Type": "text/html; charset=utf-8"}, html("ЦБ сохранил ставку", RATE_A))


class Schedule(unittest.TestCase):
    def test_interval_and_freshness(self):
        with Server({}) as s:
            s.routes.update({"/feed": FEED_OK(s.base), "/a": PAGE})
            st, p, clock = make(s.base)
            self.assertEqual(scheduler.freshness(st, p.sources, clock())["status"], "stale")     # ещё не было прогонов
            self.assertEqual(scheduler.freshness(st, p.sources, clock())["sources"][0]["status"], "never")
            runs = scheduler.run_due(p)
            self.assertEqual([(r["source_id"], r["ok"], r["created"]) for r in runs], [("smi", True, 1)])
            clock.advance(10)
            self.assertEqual(scheduler.run_due(p), [])                                            # интервал не прошёл
            fr = scheduler.freshness(st, p.sources, clock())
            self.assertEqual((fr["status"], fr["sources"][0]["age_min"]), ("ok", 10.0))
            clock.advance(25)
            runs = scheduler.run_due(p)
            self.assertEqual([(r["ok"], r["skipped"]) for r in runs], [(True, 1)])               # статья не скачивается заново
            self.assertEqual(s.hits["/a"], 1)

    def test_failures_retry_sooner_and_become_stale(self):
        with Server({}) as s:
            s.routes["/feed"] = (500, {}, b"down")
            st, p, clock = make(s.base)
            r = scheduler.run_due(p)[0]
            self.assertFalse(r["ok"]); self.assertIn("http_500", r["error"])
            clock.advance(4); self.assertEqual(scheduler.run_due(p), [])
            clock.advance(1); self.assertEqual(len(scheduler.run_due(p)), 1)                     # повтор через 5 мин
            clock.advance(5); self.assertEqual(scheduler.run_due(p), [])                          # затем через 10 мин
            clock.advance(5); self.assertEqual(len(scheduler.run_due(p)), 1)
            self.assertEqual(st.source_run_state("smi")["consecutive_failures"], 3)
            s.routes.update({"/feed": FEED_OK(s.base), "/a": PAGE})
            clock.advance(20); self.assertTrue(scheduler.run_due(p)[0]["ok"])
            self.assertEqual(st.source_run_state("smi")["consecutive_failures"], 0)
            s.routes["/feed"] = (500, {}, b"down")
            for _ in range(8):
                clock.advance(30); scheduler.run_due(p)
            fr = scheduler.freshness(st, p.sources, clock())
            self.assertEqual(fr["status"], "stale")
            src = fr["sources"][0]
            self.assertEqual((src["status"], src["last_run_ok"]), ("stale", False)); self.assertGreater(src["age_min"], 60)
            self.assertIn("http_500", src["last_error"])

    def test_empty_feed_is_not_success(self):
        with Server({}) as s:
            s.routes["/feed"] = (200, {"Content-Type": "application/rss+xml"}, rss([]))
            st, p, clock = make(s.base)
            r = scheduler.run_due(p)[0]
        self.assertEqual((r["ok"], r["error"]), (False, "empty_feed"))
        self.assertEqual(scheduler.freshness(st, p.sources, clock())["sources"][0]["status"], "never")

    def test_disabled_source_not_scheduled(self):
        st, p, clock = make("http://127.0.0.1:9", enabled=False)
        self.assertEqual(scheduler.run_due(p), [])
        self.assertEqual(scheduler.freshness(st, p.sources, clock())["status"], "no_sources")

    def test_unexpected_error_is_recorded_not_raised(self):
        st, p, clock = make("http://127.0.0.1:9")
        p.ingest_feed = lambda sid: (_ for _ in ()).throw(RuntimeError("boom"))
        r = scheduler.run_due(p)[0]
        self.assertEqual((r["ok"], r["error"]), (False, "RuntimeError: boom"))
        self.assertEqual(st.errors()[0]["stage"], "schedule")

    def test_loop_stops_and_gives_up_after_repeated_errors(self):
        st, p, clock = make("http://127.0.0.1:9", enabled=False)
        ticks = []
        scheduler.loop(p, tick_s=2, should_stop=lambda: len(ticks) >= 3, sleep=lambda s: ticks.append(s))
        self.assertEqual(ticks, [1.0, 1.0, 1.0])
        calls = []
        def broken(*a, **k):
            calls.append(1); raise ConnectionError("db gone")
        orig = scheduler.run_due
        scheduler.run_due = broken
        try:
            with self.assertRaises(ConnectionError), self.assertLogs("news_ingest.scheduler", level="ERROR") as logs:
                scheduler.loop(p, tick_s=0.0, sleep=lambda s: None, max_consecutive_errors=3)
            self.assertEqual(len(logs.records), 3)
        finally:
            scheduler.run_due = orig
        self.assertEqual(len(calls), 3)


class TemplatedReports(unittest.TestCase):
    """Шаблонные регулярные материалы (еженедельный мониторинг ставок ЦБ) — не дубли друг друга; перепечатка того же дня — дубль."""
    TPL = ("Результаты мониторинга в октябре 2026 года максимальных процентных ставок по вкладам в российских рублях десяти "
           "кредитных организаций, привлекающих наибольший объем депозитов. Средняя максимальная ставка составила {v} процента "
           "годовых. Мониторинг проводится Банком России еженедельно по данным официальных сайтов кредитных организаций, "
           "в выборку входят крупнейшие банки по объему привлеченных средств населения. Значения рассчитываются как "
           "среднее арифметическое максимальных ставок по вкладам сроком до одного года, без учета специальных условий, "
           "надбавок и предложений для отдельных категорий вкладчиков. Перечень кредитных организаций, участвующих в "
           "мониторинге, пересматривается ежеквартально по данным отчетности, представляемой в Банк России.")

    def test_weekly_reports_are_separate_items(self):
        st = NewsStore("sqlite:///:memory:"); st.init_schema()
        p = IngestPipeline(st, clock=lambda: "2026-10-22T10:00:00+00:00")
        a = p.ingest_text(self.TPL.format(v="16,12"), "Мониторинг ставок", url="https://cbr.example/1", published_at="2026-10-21")
        b = p.ingest_text(self.TPL.format(v="16,35"), "Мониторинг ставок", url="https://cbr.example/2", published_at="2026-10-13")
        c = p.ingest_text(self.TPL.format(v="16,50"), "Мониторинг ставок", url="https://cbr.example/3", published_at="2026-10-01")
        self.assertEqual([r.outcome for r in (a, b, c)], ["created"] * 3)
        self.assertTrue(all(st.get_item(r.item_id)["dup_of"] is None for r in (a, b, c)))
        d = p.ingest_text(self.TPL.format(v="16,12") + " Об этом сообщила пресс-служба.", "Перепечатка", url="https://smi.example/reprint", published_at="2026-10-21")
        self.assertEqual((d.outcome, d.dup_of), ("duplicate", a.item_id))


if __name__ == "__main__":
    unittest.main()
