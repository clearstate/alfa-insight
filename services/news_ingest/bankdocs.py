"""Материалы банка (PDF): сайдкар-экстракт (транскрипция) -> текстовый слой -> OCR. Разбиение на чанки с номерами страниц.

Порядок источников текста (первый успешный):
  1. сайдкар `<имя>.extract.json` рядом с PDF или в data/bank_analytics, ТОЛЬКО если source_sha256 совпал с хэшем PDF;
  2. текстовый слой PDF (pdfplumber), если в среднем >= 80 символов на страницу;
  3. OCR (tesseract, rus+eng; в Docker нужен пакет tesseract-ocr-rus и poppler-utils). Нет языка rus -> OcrUnavailable.
Графики/сканы с подписями можно дополнительно прогонять через Qwen3-VL (llm.py, tier "vision"), по умолчанию выключено (бюджет).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .models import Chunk, Extracted, PageText
from .textutil import fold, sha256_bytes

SIDECAR_SUFFIX = ".extract.json"
_BOILER = re.compile(r"все права защищены|не является индивидуальной инвестиционной|дисклеймер|контакты и дисклеймер|"
                     r"несанкционированное копирование", re.I)


class OcrUnavailable(RuntimeError):
    pass


def load_sidecar(pdf_path: Path, pdf_sha: str, search_dirs: list[Path] | None = None) -> dict[str, Any] | None:
    dirs = [pdf_path.parent] + list(search_dirs or [])
    for d in dirs:
        cand = d / (pdf_path.stem + SIDECAR_SUFFIX)
        if cand.exists():
            doc = json.loads(cand.read_text(encoding="utf-8"))
            if doc.get("source_sha256") == pdf_sha:
                return doc
    return None


def _page_kind(text: str, idx: int) -> str:
    if _BOILER.search(text) and len(text) < 3500 and len(re.findall(r"\d", text)) < 80:
        return "boilerplate"
    return "text"


def _ocr_pages(pdf_path: Path, lang: str, dpi: int = 200) -> list[str]:  # pragma: no cover - требует tesseract-rus
    import pytesseract
    if "rus" not in pytesseract.get_languages(config=""):
        raise OcrUnavailable("tesseract без языка rus: установите пакет tesseract-ocr-rus (см. Dockerfile)")
    if not shutil.which("pdftoppm"):
        raise OcrUnavailable("нет pdftoppm (poppler-utils)")
    from PIL import Image
    out = []
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf_path), f"{td}/p"], check=True, capture_output=True)
        for png in sorted(Path(td).glob("p-*.png")):
            out.append(pytesseract.image_to_string(Image.open(png), lang=lang))
    return out


def read_pdf(pdf_path: str | Path, *, sidecar_dirs: list[Path] | None = None, allow_ocr: bool = True,
             ocr_lang: str = "rus+eng") -> Extracted:
    p = Path(pdf_path)
    raw = p.read_bytes()
    sha = sha256_bytes(raw)
    sc = load_sidecar(p, sha, sidecar_dirs)
    if sc:
        doc = sc["document"]
        pages = [PageText(page=x["page"], kind=x["kind"], text=x["text"]) for x in sc["pages"]]
        ex = _assemble(pages, title=doc["title"], published_raw=doc.get("published_at"), method="pdf_vision_sidecar")
        ex.language = doc.get("language")
        ex.meta.update({"pdf_sha256": sha, "source_file": p.name, "bank": {k: v for k, v in doc.items() if k not in ("title",)},
                        "extraction_note": sc.get("extraction_note"), "sidecar": p.stem + SIDECAR_SUFFIX})
        return ex
    import pdfplumber
    with pdfplumber.open(p) as pdf:
        texts = [(pg.extract_text() or "") for pg in pdf.pages]
        info = pdf.metadata or {}
    method = "pdf_text"
    if sum(len(t) for t in texts) / max(1, len(texts)) < 80:
        if not allow_ocr:
            raise OcrUnavailable("PDF без текстового слоя, OCR отключён")
        texts = _ocr_pages(p, ocr_lang)
        method = "pdf_ocr"
    pages = [PageText(page=i + 1, kind=_page_kind(t, i), text=t.strip()) for i, t in enumerate(texts)]
    first = next((x.text.splitlines()[0] for x in pages if x.text.strip()), None)
    ex = _assemble(pages, title=(info.get("Title") or first or p.stem), published_raw=None, method=method)
    ex.meta.update({"pdf_sha256": sha, "source_file": p.name, "bank": {}, "pdf_metadata": {k: str(v) for k, v in info.items()}})
    return ex


def _assemble(pages: list[PageText], title: str, published_raw: str | None, method: str) -> Extracted:
    parts, offsets, pos = [], {}, 0
    for pg in pages:
        if pg.kind in ("boilerplate", "cover", "divider") or not pg.text.strip():
            continue
        offsets[pg.page] = pos
        parts.append(pg.text.strip())
        pos += len(pg.text.strip()) + 2
    text = "\n\n".join(parts)
    return Extracted(title=title, text=text, published_raw=published_raw, language=None, method=method, pages=pages,
                     meta={"page_offsets": offsets, "skipped_pages": [p.page for p in pages if p.page not in offsets],
                           "page_count": len(pages)})


def chunk_pages(item_id: str, pages: list[PageText], topic_fn, bank_marker_fn=None, max_chars: int = 900) -> list[Chunk]:
    """Чанки по абзацам внутри страницы (не пересекают границу страницы), чтобы каждая цитата имела номер страницы."""
    chunks: list[Chunk] = []
    for pg in pages:
        if pg.kind in ("boilerplate", "cover", "divider") or not pg.text.strip():
            continue
        paras = [p.strip() for p in re.split(r"\n+", pg.text) if p.strip()]
        buf = ""
        pieces: list[str] = []
        for para in paras:
            if buf and len(buf) + len(para) + 1 > max_chars:
                pieces.append(buf)
                buf = para
            else:
                buf = (buf + "\n" + para).strip()
            while len(buf) > max_chars * 2:      # очень длинный абзац режем по предложениям-границам
                cut = buf.rfind(". ", 0, max_chars * 2)
                cut = cut + 1 if cut > 200 else max_chars * 2
                pieces.append(buf[:cut].strip())
                buf = buf[cut:].strip()
        if buf:
            pieces.append(buf)
        for piece in pieces:
            idx = len(chunks)
            ct = "bank_view" if (bank_marker_fn and bank_marker_fn(piece)) else "fact"
            chunks.append(Chunk(id=f"{item_id}:c{idx:03d}", news_item_id=item_id, idx=idx, text=piece, page=pg.page,
                                kind=pg.kind, topics=topic_fn(piece), claim_type=ct))
    return chunks
