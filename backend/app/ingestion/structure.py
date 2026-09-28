"""Detect the chapter layout of a textbook.

Strategy (first that yields at least two chapters wins):

1. The PDF outline (bookmarks) - most publisher PDFs have one.
2. Heading patterns in the text ("Chapter 3", "Unit IV: ...", "Lesson 2 - ...").
3. The AI, given a compact digest of every page (see :mod:`app.ingestion.curriculum`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .extract import ExtractedDocument

HEADING_RE = re.compile(
    r"^\s*(chapter|unit|lesson|module|topic)\s+([0-9]{1,3}|[ivxlc]{1,6})\b\s*[.:\-–—]?\s*(.*)$",
    re.IGNORECASE,
)
# "Chapter 3 Fractions ........ 42" - a table-of-contents entry, not a heading.
TOC_LINE_RE = re.compile(r"(\.{3,}|\u2026|\s{3,})\s*\d{1,4}\s*$")
NON_CONTENT_RE = re.compile(
    r"^(contents|table of contents|preface|foreword|acknowledg|index|glossary|answers?|"
    r"bibliography|references|about (the|this) book|cover|title page|copyright|appendix)",
    re.IGNORECASE,
)


@dataclass
class ChapterSpan:
    title: str
    start_page: int  # 1-indexed, inclusive
    end_page: int  # inclusive


def spans_from_starts(starts: list[tuple[str, int]], page_count: int) -> list[ChapterSpan]:
    """Turn (title, start_page) pairs into contiguous spans that cover the rest of the book."""
    starts = sorted({p: t for t, p in starts}.items())  # dedupe on page, sort by page
    spans: list[ChapterSpan] = []
    for i, (page, title) in enumerate(starts):
        page = max(1, min(page, page_count))
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else page_count
        end = max(page, min(end, page_count))
        spans.append(ChapterSpan(title=title.strip() or f"Chapter {i + 1}", start_page=page, end_page=end))
    return spans


def from_outline(doc: ExtractedDocument) -> list[ChapterSpan]:
    if not doc.outline:
        return []
    levels = sorted({e.level for e in doc.outline})
    for level in levels:
        entries = [e for e in doc.outline if e.level == level and not NON_CONTENT_RE.match(e.title)]
        if len(entries) >= 2:
            return spans_from_starts([(e.title, e.page) for e in entries], doc.page_count)
    return []


def from_headings(doc: ExtractedDocument) -> list[ChapterSpan]:
    found: dict[str, tuple[str, int]] = {}
    for page_no, text in enumerate(doc.pages, start=1):
        lines = [ln.strip() for ln in text.splitlines()]
        first = next((ln for ln in lines if ln), "")
        if NON_CONTENT_RE.match(first):
            continue  # contents / index pages list chapters but don't start them
        matches = [(i, HEADING_RE.match(ln)) for i, ln in enumerate(lines) if not TOC_LINE_RE.search(ln)]
        matches = [(i, m) for i, m in matches if m]
        if len(matches) >= 3:
            continue  # a page listing many chapters is a table of contents, not a chapter start
        for i, m in matches:
            # Real chapter headings sit near the top of a page.
            if i > 6:
                continue
            kind, number, rest = m.group(1), m.group(2).lower(), m.group(3).strip()
            key = f"{kind.lower()} {number}"
            if key in found:
                continue
            if not rest:
                rest = next((ln for ln in lines[i + 1 : i + 4] if ln), "")
            title = f"{kind.title()} {m.group(2)}: {rest}".rstrip(": ") if rest else f"{kind.title()} {m.group(2)}"
            found[key] = (title[:200], page_no)
    if len(found) < 2:
        return []
    return spans_from_starts(list(found.values()), doc.page_count)


def detect_chapters(doc: ExtractedDocument) -> tuple[list[ChapterSpan], str | None]:
    """Return detected chapter spans and which method found them (``None`` if nothing was found)."""
    spans = from_outline(doc)
    if spans:
        return spans, "outline"
    spans = from_headings(doc)
    if spans:
        return spans, "headings"
    return [], None
