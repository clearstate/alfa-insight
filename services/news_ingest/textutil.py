"""Текстовые утилиты: нормализация, предложения, шинглы/MinHash, хеши, даты (ru/ISO/RFC822). Только stdlib."""
from __future__ import annotations

import hashlib
import random
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

MSK = timezone(timedelta(hours=3))
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\u200c\u200d\ufeff]")


def normalize_text(s: str | None) -> str:
    """NFKC, без управляющих символов, пробелы схлопнуты, абзацы (пустая строка) сохранены."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    s = _CTRL.sub("", s)
    paras = [re.sub(r"[ \t]+", " ", p).strip() for p in re.split(r"\n\s*\n", s)]
    paras = [re.sub(r"\s*\n\s*", " ", p) for p in paras if p.strip()]
    return "\n\n".join(paras)


def clean_text(s: str | None) -> str:
    """Лёгкая очистка с сохранением переводов строк (нужна для таблиц и номеров страниц банковских документов)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    s = _CTRL.sub("", s)
    return "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")).strip()


def fold(s: str) -> str:
    """Нижний регистр, ё -> е (для словарного поиска)."""
    return s.lower().replace("ё", "е")


def content_hash(text: str) -> str:
    """SHA-256 нормализованного текста (регистр и пробелы не влияют)."""
    canon = re.sub(r"\s+", " ", fold(normalize_text(text))).strip()
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


_ABBR_MULTI = ["т.е.", "т. е.", "т.д.", "т. д.", "т.п.", "т. п.", "т.ч.", "т. ч.", "п.п.", "б.п.", "и т.д", "и т.п"]
_ABBR_SINGLE = re.compile(
    r"(?<![а-яa-zё])(г|гг|руб|млрд|млн|тыс|трлн|см|рис|табл|напр|др|пр|им|ул|стр|св|ст|долл|коп|шт|мес|кв|№)\.", re.I)
_PH = "\u0001"


def split_sentences(text: str) -> list[tuple[str, int, int]]:
    """Предложения с позициями (start, end) в исходной строке. Сокращения (г., руб., т.ч., п.п.) не режут."""
    prot = text
    for a in _ABBR_MULTI:
        prot = prot.replace(a, a.replace(".", _PH))
    prot = _ABBR_SINGLE.sub(lambda m: m.group(0).replace(".", _PH), prot)
    out: list[tuple[str, int, int]] = []
    pos = 0
    for m in re.finditer(r"(?<=[.!?…])\s+(?=[«\"(\[A-ZА-ЯЁ0-9\-–—])|\n+", prot):
        seg = prot[pos:m.start()]
        if seg.strip():
            out.append((seg.replace(_PH, ".").strip(), pos, m.start()))
        pos = m.end()
    seg = prot[pos:]
    if seg.strip():
        out.append((seg.replace(_PH, ".").strip(), pos, len(prot)))
    return out


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9]+(?:[.,][0-9]+)?", fold(text))


def shingles(text: str, k: int = 5) -> set[str]:
    t = tokens(text)
    if len(t) < k:
        return {" ".join(t)} if t else set()
    return {" ".join(t[i:i + k]) for i in range(len(t) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


_PRIME = (1 << 61) - 1
_NUM_PERM = 64
_rng = random.Random(20260921)
_PERMS = [(_rng.randrange(1, _PRIME), _rng.randrange(0, _PRIME)) for _ in range(_NUM_PERM)]


def minhash(sh: set[str]) -> list[int]:
    """MinHash-подпись (64 перестановки, детерминированная). Пустое множество -> []."""
    if not sh:
        return []
    hs = [int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big") for s in sh]
    return [min((a * h + b) % _PRIME for h in hs) for a, b in _PERMS]


def minhash_similarity(x: list[int], y: list[int]) -> float:
    if not x or not y or len(x) != len(y):
        return 0.0
    return sum(1 for a, b in zip(x, y) if a == b) / len(x)


_MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
           "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
_RU_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\b", re.I)
_DOT_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def parse_date(value: str | None, default_tz: timezone = MSK) -> tuple[str, str] | None:
    """Строка даты -> (ISO8601 UTC, precision 'day'|'second') или None.

    Форматы: ISO 8601, RFC 822 (RSS), «11 сентября 2026», «11.09.2026». Дата без времени -> 00:00 UTC, precision='day'.
    Дата со временем без пояса считается московской (default_tz).
    """
    if not value or not str(value).strip():
        return None
    v = str(value).strip()
    m = _RU_DATE.search(v)
    if m:
        d, mon, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
        return _safe_day(y, mon, d)
    m = _DOT_DATE.fullmatch(v) or _DOT_DATE.search(v)
    if m and not re.search(r"\d{4}-\d{2}-\d{2}", v):
        return _safe_day(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    try:
        iso = v.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            return _safe_day(dt.year, dt.month, dt.day)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz)
        return _utc_iso(dt), "second"
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return _utc_iso(dt), "second"
    except (TypeError, ValueError, IndexError):
        return None


def _safe_day(y: int, mo: int, d: int) -> tuple[str, str] | None:
    try:
        return _utc_iso(datetime(y, mo, d, tzinfo=timezone.utc)), "day"
    except ValueError:
        return None


def find_dates_ru(text: str) -> list[str]:
    """Все даты «11 сентября 2026» / «11.09.2026» в тексте как ISO-дни (YYYY-MM-DD), по порядку, без повторов."""
    seen: list[str] = []
    found = []
    for m in _RU_DATE.finditer(text):
        found.append((m.start(), _safe_day(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))))
    for m in _DOT_DATE.finditer(text):
        found.append((m.start(), _safe_day(int(m.group(3)), int(m.group(2)), int(m.group(1)))))
    for _, r in sorted(found, key=lambda x: x[0]):
        if r and r[0][:10] not in seen:
            seen.append(r[0][:10])
    return seen


def now_iso() -> str:
    return _utc_iso(datetime.now(timezone.utc))
