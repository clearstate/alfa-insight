"""Безопасная загрузка по HTTP(S): защита от SSRF, лимит размера, тайм-аут, ретраи с экспоненциальной задержкой, rate limit по хосту,
robots.txt. Только stdlib. Не обходит авторизацию, CAPTCHA и пейвол — такие ответы (401/403/429/captcha) считаются отказом источника.

Ограничение: DNS-имя резолвится для проверки, затем urllib резолвит повторно (окно DNS-rebinding). Для продакшена — egress-прокси
с запретом приватных диапазонов (см. README, раздел безопасности).
"""
from __future__ import annotations

import ipaddress
import socket
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from .textutil import now_iso

ALLOWED_CT = ("text/html", "application/xhtml", "application/rss+xml", "application/atom+xml", "application/xml", "text/xml",
              "text/plain", "application/pdf", "application/json")
# robots.txt перечитывается: правила сайта меняются, а временная ошибка (5xx/сеть) не должна блокировать источник навсегда
ROBOTS_TTL_S = 6 * 3600
ROBOTS_ERROR_TTL_S = 10 * 60


class FetchError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, status: int | None = None):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.retryable, self.status = code, message, retryable, status


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    charset: str | None
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    fetched_at: str = ""


def check_url(url: str, allow_private: bool = False, allowed_domains: list[str] | None = None) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise FetchError("bad_scheme", f"разрешены только http/https: {p.scheme!r}")
    host = p.hostname
    if not host:
        raise FetchError("bad_url", "в URL нет хоста")
    if p.username or p.password:
        raise FetchError("bad_url", "учётные данные в URL запрещены")
    if allowed_domains and not any(host == d or host.endswith("." + d) for d in allowed_domains):
        raise FetchError("domain_not_allowed", f"домен {host} не в списке разрешённых")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise FetchError("dns_error", f"{host}: {e}", retryable=True)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise FetchError("ssrf_blocked", f"{host} -> {ip}: приватный/служебный адрес")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None        # редиректы обрабатывает SafeFetcher: каждый новый адрес проходит check_url


class SafeFetcher:
    def __init__(self, *, timeout: float = 10.0, max_bytes: int = 5_000_000, retries: int = 2, backoff: float = 1.0,
                 min_interval: float = 2.0, user_agent: str = "AlfaInsightBot/0.1", allow_private: bool = False,
                 allowed_domains: list[str] | None = None, respect_robots: bool = True, max_redirects: int = 3,
                 sleep=time.sleep, clock=time.monotonic):
        self.timeout, self.max_bytes, self.retries, self.backoff = timeout, max_bytes, retries, backoff
        self.min_interval, self.user_agent = min_interval, user_agent
        self.allow_private, self.allowed_domains = allow_private, allowed_domains
        self.respect_robots, self.max_redirects = respect_robots, max_redirects
        self._sleep, self._clock = sleep, clock
        self._last: dict[str, float] = {}
        self._robots: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}   # origin -> (истекает, правила)
        self._opener = urllib.request.build_opener(_NoRedirect)

    # ---- robots.txt ----
    def robots_allowed(self, url: str) -> bool:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        cached = self._robots.get(origin)
        if cached is None or self._clock() >= cached[0]:
            rp: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            ttl = ROBOTS_TTL_S
            try:
                r = self._get_with_redirects(origin + "/robots.txt", max_bytes=500_000, check_ct=False)
                rp.parse(r.body.decode("utf-8", "replace").splitlines())
            except FetchError as e:
                if e.status is None or e.status >= 500:
                    rp, ttl = None, ROBOTS_ERROR_TTL_S      # недоступен/5xx -> консервативно запрещено, повтор через 10 минут
                else:
                    rp.parse([])                            # 4xx (нет robots.txt) -> разрешено
            cached = self._robots[origin] = (self._clock() + ttl, rp)
        rp = cached[1]
        return bool(rp and rp.can_fetch(self.user_agent, url))

    # ---- основной вызов ----
    def fetch(self, url: str) -> FetchResult:
        check_url(url, self.allow_private, self.allowed_domains)
        if self.respect_robots and not self.robots_allowed(url):
            raise FetchError("robots_disallowed", f"robots.txt запрещает/недоступен для {url}")
        attempt = 0
        while True:
            try:
                return self._get_with_redirects(url)
            except FetchError as e:
                if not e.retryable or attempt >= self.retries:
                    raise
                self._sleep(self.backoff * (2 ** attempt))
                attempt += 1

    def _get_with_redirects(self, url: str, **kw) -> FetchResult:
        cur = url
        for _ in range(self.max_redirects + 1):
            r = self._get_once(cur, **kw)
            if r.status in (301, 302, 303, 307, 308):
                loc = r.headers.get("location")
                if not loc:
                    raise FetchError("bad_redirect", "редирект без Location", status=r.status)
                cur = urljoin(cur, loc)
                check_url(cur, self.allow_private, self.allowed_domains)
                continue
            return r
        raise FetchError("too_many_redirects", f">{self.max_redirects} редиректов")

    def _throttle(self, host: str) -> None:
        last = self._last.get(host)
        now = self._clock()
        if last is not None and now - last < self.min_interval:
            self._sleep(self.min_interval - (now - last))
        self._last[host] = self._clock()

    def _get_once(self, url: str, max_bytes: int | None = None, check_ct: bool = True) -> FetchResult:
        self._throttle(urlparse(url).netloc)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "identity",
                                                   "Accept": "text/html,application/xml,application/rss+xml,application/pdf;q=0.9,*/*;q=0.5"})
        limit = max_bytes or self.max_bytes
        try:
            resp = self._opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                return FetchResult(url, url, e.code, "", None, b"", {k.lower(): v for k, v in e.headers.items()})
            retry = e.code >= 500 or e.code == 429
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                if ra and ra.isdigit():
                    self._sleep(min(int(ra), 30))
            raise FetchError(f"http_{e.code}", url, retryable=retry, status=e.code) from e
        except OSError as e:          # URLError, таймаут, обрыв соединения
            raise FetchError("network_error", f"{url}: {e}", retryable=True) from e
        with resp:
            ct_full = resp.headers.get("Content-Type", "") or ""
            ct = ct_full.split(";")[0].strip().lower()
            if check_ct and ct and not any(ct.startswith(a) for a in ALLOWED_CT):
                raise FetchError("unsupported_content_type", ct)
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise FetchError("too_large", f"Content-Length {declared} > {limit}")
            chunks, total = [], 0
            while True:
                b = resp.read(65536)
                if not b:
                    break
                total += len(b)
                if total > limit:
                    raise FetchError("too_large", f">{limit} байт")
                chunks.append(b)
            charset = None
            if "charset=" in ct_full.lower():
                charset = ct_full.lower().split("charset=")[1].split(";")[0].strip().strip('"')
            return FetchResult(url, url, resp.status, ct, charset, b"".join(chunks),
                               {k.lower(): v for k, v in resp.headers.items()}, now_iso())
