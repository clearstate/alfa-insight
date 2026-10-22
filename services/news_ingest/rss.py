"""Разбор RSS 2.0 и Atom. XML парсится lxml без раскрытия сущностей и сетевых обращений (защита от XXE/billion laughs)."""
from __future__ import annotations

from dataclasses import dataclass

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


def _local(tag) -> str:
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def _text(el) -> str | None:
    return normalize_text("".join(el.itertext())) if el is not None else None


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
        d: dict[str, object] = {}
        for ch in it:
            k = _local(ch.tag)
            if k == "link":
                d["link"] = ch.get("href") or _text(ch)
            elif k in ("title", "guid", "id"):
                d["guid" if k in ("guid", "id") else k] = _text(ch)
            elif k in ("pubDate", "published", "updated", "date"):
                d.setdefault("published", _text(ch))
            elif k in ("description", "summary", "content", "encoded"):
                d.setdefault("summary", _text(ch))
        out.append(FeedEntry(title=d.get("title"), link=d.get("link"), published_raw=d.get("published"),
                             summary=d.get("summary"), guid=d.get("guid")))  # type: ignore[arg-type]
    return out
