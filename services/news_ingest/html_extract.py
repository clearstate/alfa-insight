"""Извлечение статьи из HTML: заголовок, текст, дата публикации, издатель, язык. bs4 + lxml. Тексты — недоверенные данные."""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .models import Extracted
from .textutil import normalize_text

_DROP = ["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe", "svg", "button"]
_BAD_TITLE_SUFFIX = re.compile(r"\s+[|—–-]\s+[^|—–-]{2,40}$")


def decode_bytes(body: bytes, header_charset: str | None = None) -> tuple[str, str]:
    """Байты -> (текст, использованная кодировка). Учитывает заголовок, BOM, <meta charset>; затем utf-8, затем cp1251."""
    if body.startswith(b"\xef\xbb\xbf"):
        return body[3:].decode("utf-8", "replace"), "utf-8-sig"
    cands = []
    if header_charset:
        cands.append(header_charset)
    m = re.search(rb"<meta[^>]+charset=[\"']?\s*([a-zA-Z0-9_\-]+)", body[:4096], re.I) or \
        re.search(rb"<\?xml[^>]+encoding=[\"']([a-zA-Z0-9_\-]+)", body[:200], re.I)
    if m:
        cands.append(m.group(1).decode("ascii", "ignore"))
    cands += ["utf-8", "cp1251"]
    for enc in cands:
        try:
            return body.decode(enc), enc
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace"), "utf-8-replace"


def _meta(soup: BeautifulSoup, *keys: str) -> str | None:
    for k in keys:
        tag = soup.find("meta", attrs={"property": k}) or soup.find("meta", attrs={"name": k}) or soup.find("meta", attrs={"itemprop": k})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _jsonld(soup: BeautifulSoup) -> dict:
    for s in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(s.string or "")
        except (ValueError, TypeError):
            continue
        for d in (data if isinstance(data, list) else [data]):
            if isinstance(d, dict) and d.get("@type") in ("NewsArticle", "Article", "BlogPosting", "Report"):
                return d
    return {}


def extract_html(html: str, url: str | None = None) -> Extracted:
    soup = BeautifulSoup(html, "lxml")
    ld = _jsonld(soup)
    title = _meta(soup, "og:title", "twitter:title") or ld.get("headline")
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else None)
    if title:
        title = normalize_text(title)
    published = (_meta(soup, "article:published_time", "pubdate", "date", "DC.date.issued", "datePublished")
                 or ld.get("datePublished"))
    if not published:
        t = soup.find("time", attrs={"datetime": True})
        published = t["datetime"] if t else None
    publisher = _meta(soup, "og:site_name", "application-name")
    if not publisher:
        pub = ld.get("publisher")
        publisher = pub.get("name") if isinstance(pub, dict) else None
    lang = (soup.html.get("lang") if soup.html else None) or _meta(soup, "og:locale")
    lang = lang.split("-")[0].split("_")[0].lower() if lang else None

    for t in soup(_DROP):
        t.decompose()
    root = soup.find("article") or soup.find("main")
    if root is None:
        best, best_len = None, 0
        for el in soup.find_all(["div", "section", "td"]):
            ln = sum(len(p.get_text(" ", strip=True)) for p in el.find_all("p", recursive=False))
            if ln > best_len:
                best, best_len = el, ln
        root = best or soup.body or soup
    parts = []
    for el in root.find_all(["p", "h2", "h3", "li", "blockquote"]):
        txt = normalize_text(el.get_text(" ", strip=True))
        if len(txt) >= (25 if el.name == "p" else 12) and txt not in parts:
            parts.append(txt)
    text = "\n\n".join(parts)
    return Extracted(title=title, text=text, published_raw=published, publisher=publisher, language=lang, url=url, method="html",
                     meta={"root_tag": getattr(root, "name", None), "paragraphs": len(parts)})
