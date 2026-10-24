"""Разбор RSS 2.0 и Atom. XML парсится lxml без раскрытия сущностей и сетевых обращений (защита от XXE/billion laughs)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment
from lxml import etree

from .html_extract import decode_bytes
from .textutil import normalize_text


class FeedParseError(ValueError):
    pass


@dataclass
class FeedEntry:
    title: str | None
    link: str | None
    published_raw: str | None
    summary: str | None
    guid: str | None
    content: str | None = None      # полный текст статьи, если лента его отдаёт (content:encoded, Atom content, rbc full-text)


# Описание в лентах часто — HTML (экранированный или в CDATA): <p>, &nbsp;, комментарии, сноски <sup>1</sup>.
_HTMLISH = re.compile(r"<\s*/?\s*[a-zA-Z!][^>]*>|&(?:[a-zA-Z]{2,8}|#\d{1,6}|#x[0-9a-fA-F]{1,6});")
_BLOCK = ["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "tr", "table", "section", "article"]
_FOOTNOTE = re.compile(r"\s*[\d*†]{1,3}\s*")
# Приоритет полей даты: дата публикации важнее даты обновления.
_DATE_PRIORITY = {"pubDate": 0, "published": 0, "issued": 1, "date": 1, "created": 2, "updated": 3, "modified": 3}
# Приоритет полей текста: краткое описание, затем полный текст.
_SUMMARY_PRIORITY = {"description": 0, "summary": 0, "anons": 1, "encoded": 2, "content": 2, "full-text": 2}
# Поля с полным текстом статьи (content:encoded, Atom <content>, РБК <rbc_news:full-text>).
_CONTENT_TAGS = ("encoded", "content", "full-text")


def _local(tag) -> str:
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def _raw(el) -> str:
    return "".join(el.itertext()) if el is not None else ""


def _text(el) -> str | None:
    return normalize_text(_raw(el)) if el is not None else None


def html_to_text(s: str | None) -> str:
    """HTML-фрагмент описания -> обычный текст с абзацами. Теги, комментарии, скрипты и сноски удаляются, сущности раскрываются."""
    if not s:
        return ""
    if not _HTMLISH.search(s):
        return normalize_text(s)
    soup = BeautifulSoup(s, "lxml")
    for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
        c.extract()
    for t in soup(["script", "style", "noscript", "iframe", "object", "embed", "svg", "form"]):
        t.decompose()
    for t in soup.find_all("sup"):            # маркеры сносок («...Федерации<sup>1</sup>») не должны склеиваться с числами
        if _FOOTNOTE.fullmatch(t.get_text()):
            t.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for t in soup.find_all(_BLOCK):
        t.insert_before("\n\n")
        t.insert_after("\n\n")
    return normalize_text(soup.get_text())


def _pick_link(links: list[tuple[str | None, str | None]]) -> str | None:
    """Atom: rel="alternate" (или без rel) — страница статьи; self/enclosure/related — не статья. RSS: текст <link>."""
    good = [href for rel, href in links if href and (rel in (None, "", "alternate"))]
    return good[0] if good else next((href for _, href in links if href), None)


def parse_feed(body: bytes) -> list[FeedEntry]:
    text, _ = decode_bytes(body)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=False, dtd_validation=False, load_dtd=False)
    try:
        root = etree.fromstring(text.encode("utf-8") if not text.lstrip().startswith("<?xml") else
                                text.split("?>", 1)[1].encode("utf-8"), parser)
    except etree.XMLSyntaxError as e:
        raise FeedParseError(f"некорректный XML: {e}")
    kind = _local(root.tag)
    if kind not in ("rss", "feed", "RDF"):
        raise FeedParseError(f"неизвестный корневой элемент ленты: {kind!r}")
    out: list[FeedEntry] = []
    for it in root.iter():
        n = _local(it.tag)
        if n not in ("item", "entry"):
            continue
        d: dict[str, str | None] = {}
        links: list[tuple[str | None, str | None]] = []
        date_rank, summary_rank = 99, 99
        content = ""
        for ch in it:
            k = _local(ch.tag)
            if k == "link":
                links.append((ch.get("rel"), (ch.get("href") or _text(ch) or "").strip() or None))
            elif k in ("title", "guid", "id"):
                d.setdefault("guid" if k in ("guid", "id") else k, html_to_text(_raw(ch)) if k == "title" else _text(ch))
            elif k in _DATE_PRIORITY:
                val = _text(ch)
                if val and _DATE_PRIORITY[k] < date_rank:
                    d["published"], date_rank = val, _DATE_PRIORITY[k]
            elif k in _SUMMARY_PRIORITY:
                val = html_to_text(_raw(ch))
                if val and _SUMMARY_PRIORITY[k] < summary_rank:
                    d["summary"], summary_rank = val, _SUMMARY_PRIORITY[k]
                if k in _CONTENT_TAGS and len(val) > len(content):
                    content = val
        link = _pick_link(links)
        guid = d.get("guid")
        if not link and guid and re.match(r"https?://", guid):   # RSS: guid isPermaLink — адрес статьи
            link = guid
        out.append(FeedEntry(title=d.get("title") or None, link=link, published_raw=d.get("published"),
                             summary=d.get("summary") or "", guid=guid, content=content or None))
    return out
