"""Turn an uploaded file into per-page plain text (+ PDF outline when available)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}
# Below this many extractable characters per page we assume a scanned (image-only) book.
MIN_CHARS_PER_PAGE = 60
TEXT_PAGE_CHARS = 3000


class ExtractionError(ValueError):
    """The file could not be turned into usable text."""


@dataclass
class OutlineEntry:
    title: str
    page: int  # 1-indexed
    level: int


@dataclass
class ExtractedDocument:
    pages: list[str]
    outline: list[OutlineEntry] = field(default_factory=list)
    metadata_title: str | None = None

    @property
    def page_count(self) -> int:
        return len(self.pages)


def clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract(path: Path) -> ExtractedDocument:
    ext = path.suffix.lower()
    if ext == ".pdf":
        doc = _extract_pdf(path)
    elif ext in (".txt", ".md"):
        doc = _extract_text(path)
    else:
        raise ExtractionError(f"Unsupported file type '{ext}'. Upload a PDF or a .txt/.md file.")

    total_chars = sum(len(p) for p in doc.pages)
    if not doc.pages or total_chars < MIN_CHARS_PER_PAGE * max(1, len(doc.pages)) * 0.5:
        raise ExtractionError(
            "Almost no text could be read from this file. It looks like a scanned book (images of pages). "
            "Scanned books need OCR, which is not supported yet - please upload a PDF with selectable text."
        )
    return doc


def _extract_pdf(path: Path) -> ExtractedDocument:
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise ExtractionError("This PDF is password protected.") from exc
        pages = []
        for i, page in enumerate(reader.pages):
            try:
                pages.append(clean_text(page.extract_text() or ""))
            except Exception:  # noqa: BLE001 - a single bad page should not kill the book
                log.warning("could not extract page %s of %s", i + 1, path.name)
                pages.append("")
    except PdfReadError as exc:
        raise ExtractionError(f"The PDF could not be read: {exc}") from exc

    outline: list[OutlineEntry] = []
    try:
        _walk_outline(reader, reader.outline, 0, outline)
    except Exception:  # noqa: BLE001 - outlines are optional and often malformed
        log.info("ignoring unreadable outline in %s", path.name)
        outline = []

    title = None
    try:
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title).strip() or None
    except Exception:  # noqa: BLE001
        pass
    return ExtractedDocument(pages=pages, outline=outline, metadata_title=title)


def _walk_outline(reader: PdfReader, items, level: int, out: list[OutlineEntry]) -> None:
    for item in items:
        if isinstance(item, list):
            _walk_outline(reader, item, level + 1, out)
            continue
        page = reader.get_destination_page_number(item)
        if page is None or page < 0:
            continue
        out.append(OutlineEntry(title=str(item.title).strip(), page=page + 1, level=level))


def _extract_text(path: Path) -> ExtractedDocument:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if "\f" in text:
        pages = [clean_text(p) for p in text.split("\f")]
    else:
        pages = split_into_pages(text, TEXT_PAGE_CHARS)
    return ExtractedDocument(pages=[p for p in pages if p] or [""])


def split_into_pages(text: str, size: int) -> list[str]:
    """Split plain text into pseudo-pages of roughly ``size`` characters on paragraph boundaries."""
    paragraphs = re.split(r"\n\s*\n", text)
    pages: list[str] = []
    current: list[str] = []
    length = 0
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if current and length + len(para) > size:
            pages.append(clean_text("\n\n".join(current)))
            current, length = [], 0
        current.append(para)
        length += len(para) + 2
    if current:
        pages.append(clean_text("\n\n".join(current)))
    return pages
