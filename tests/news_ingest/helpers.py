"""Общие помощники тестов: локальный HTTP-сервер (без обращений к реальным сайтам) и сборка HTML/RSS-фикстур."""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

NOW = "2026-10-21T10:00:00+00:00"


class Server:
    """routes: path -> (status, headers, body) или callable(count)->(status, headers, body)."""

    def __init__(self, routes: dict[str, object]):
        self.routes, self.hits = routes, {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # тихо
                pass

            def do_GET(self):
                path = self.path.split("?")[0]
                outer.hits[path] = outer.hits.get(path, 0) + 1
                r = outer.routes.get(path)
                if r is None:
                    r = (404, {}, b"not found")
                if callable(r):
                    r = r(outer.hits[path])
                status, headers, body = r
                if headers.get("X-Delay"):
                    time.sleep(float(headers["X-Delay"]))
                self.send_response(status)
                for k, v in headers.items():
                    if k != "X-Delay":
                        self.send_header(k, v)
                if "Content-Length" not in headers:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self._t = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


def html(title: str, paragraphs: list[str], date: str | None = "2026-09-11T15:30:00+03:00", site: str = "Тестовое СМИ",
         lang: str = "ru", extra_head: str = "") -> bytes:
    d = f'<meta property="article:published_time" content="{date}">' if date else ""
    ps = "".join(f"<p>{p}</p>" for p in paragraphs)
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{title} — {site}</title>'
            f'<meta property="og:title" content="{title}"><meta property="og:site_name" content="{site}">{d}{extra_head}</head>'
            f'<body><nav>Главная Новости Экономика</nav><article>{ps}</article><footer>© {site}</footer></body></html>').encode("utf-8")


def rss(items: list[tuple[str, str, str, str]]) -> bytes:
    body = "".join(f"<item><title>{t}</title><link>{l}</link><pubDate>{d}</pubDate><description>{s}</description></item>" for t, l, d, s in items)
    return f'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'.encode("utf-8")


RATE_A = [
    "Банк России на заседании совета директоров 11 сентября сохранил ключевую ставку на уровне 14,0% годовых, как и ожидало большинство аналитиков.",
    "Председатель Банка России Эльвира Набиуллина пояснила, что вариант снижения ставки на заседании не рассматривался, а риски ускорения инфляции выросли.",
    "Инфляционные ожидания населения в августе составили 13,7%, что выше среднего значения за прошлый год, отметил регулятор в пресс-релизе.",
    "Регулятор будет принимать дальнейшие решения по ключевой ставке в зависимости от динамики инфляции и инфляционных ожиданий.",
    "Следующее заседание совета директоров по ключевой ставке запланировано на 23 октября 2026 года, а затем на 18 декабря.",
    "Доходности облигаций федерального займа после заседания выросли, длинные выпуски подешевели на фоне разочарования инвесторов.",
    "Корпоративное кредитование продолжает расти быстрее прогнозов регулятора, что остаётся одним из главных индикаторов спроса.",
    "Эксперты отмечают, что для компаний с заёмным финансированием пауза означает сохранение высокой стоимости обслуживания долга.",
]
RATE_B = [
    "Банк России оставил ключевую ставку без изменений — 14,0% годовых, сообщил регулятор по итогам заседания в пятницу.",
    "Глава Банка России Набиуллина заявила журналистам, что снижение ставки совет директоров даже не обсуждал, поскольку проинфляционные риски усилились.",
    "Ожидания по инфляции у населения остаются повышенными, а рынок облигаций отреагировал ростом доходностей на дальнем конце кривой.",
    "Аналитики ожидают сохранения ставки на уровне 14,0% до конца года, следующее решение будет принято в октябре.",
    "Для заёмщиков это означает, что дешёвых кредитов в ближайшие месяцы ждать не стоит, а стоимость рефинансирования останется высокой.",
]
RATE_C = [
    "Банк России на заседании 11 сентября оставил ключевую ставку на уровне 14,25% годовых, сообщили в пресс-службе регулятора.",
    "Набиуллина сказала, что вариант снижения не рассматривался, а инфляционные риски выросли по сравнению с предыдущим заседанием.",
    "Рынок ОФЗ отреагировал ростом доходностей, а корпоративное кредитование идёт быстрее ожиданий Банка России.",
    "Следующее заседание по ключевой ставке состоится 23 октября, отметили аналитики рынка облигаций.",
    "Решение по ставке означает паузу в цикле смягчения денежно-кредитной политики для банков и заёмщиков.",
]


def make_pdf(text_lines: list[str]) -> bytes:
    """Минимальный валидный PDF с текстовым слоем (латиница, Helvetica) — для тестов пути pdf_text без внешних файлов."""
    stream = "BT /F1 12 Tf 50 700 Td 14 TL " + " ".join(f"({l}) Tj T*" for l in text_lines) + " ET"
    objs = ["<</Type/Catalog/Pages 2 0 R>>", "<</Type/Pages/Kids[3 0 R]/Count 1>>",
            "<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            f"<</Length {len(stream)}>>\nstream\n{stream}\nendstream", "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{x}\n%%EOF".encode()
