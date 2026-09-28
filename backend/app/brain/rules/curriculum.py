"""Offline curriculum analysis: chapter fallback segmentation, book overview and topic extraction by rules."""

from __future__ import annotations

import re
from pathlib import Path

from ...ingestion.curriculum import BookOverview, ChapterAnalysis, TopicDraft
from ...ingestion.extract import ExtractedDocument
from ...ingestion.structure import HEADING_RE, NON_CONTENT_RE, ChapterSpan, spans_from_starts
from . import maths
from .text import definitions, first_sentences, keywords

SUBJECT_WORDS = {
    "Mathematics": "number numbers add addition subtract subtraction multiply multiplication divide division fraction fractions decimal decimals equation angle angles triangle area perimeter sum product digit digits denominator numerator percent",
    "Science": "energy force plant plants animal animals cell cells water light heat matter experiment living organism organisms electricity magnet habitat food oxygen gas solid liquid",
    "English": "noun nouns verb verbs adjective adjectives sentence sentences poem poems story vocabulary grammar paragraph punctuation spelling reading writing tense",
    "History": "king kings empire war century ancient history kingdom ruler rulers battle independence colonial dynasty civilization",
    "Geography": "river rivers mountain mountains climate map maps continent country rainfall region population soil ocean weather",
}

NUMBERED_SECTION = re.compile(r"^\s*(\d{1,2}\.\d{1,2})\.?\s+([A-Z][^\n]{2,70})$")
EXERCISE = re.compile(r"^\s*(exercises?|practice|questions|try these|activity|review|summary|let'?s practise)\b", re.IGNORECASE)


def _is_heading_like(line: str) -> bool:
    line = line.strip()
    tokens = line.split()
    if not (1 <= len(tokens) <= 8) or len(line) < 4 or len(line) > 70:
        return False
    if line[-1] in ".,;:?!" or not line[0].isupper() or re.search(r"\d{3,}", line):
        return False
    caps = sum(1 for t in tokens if t[0].isupper() or not t[0].isalpha())
    return line.isupper() or caps / len(tokens) >= 0.6


class RuleCurriculumBrain:
    name = "rules"
    chapter_chars = 10**9  # no model context limit

    def segment(self, doc: ExtractedDocument) -> list[ChapterSpan]:
        starts: list[tuple[str, int]] = []
        for page_no, text in enumerate(doc.pages, start=1):
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:3]
            for ln in lines:
                if (NUMBERED_SECTION.match(ln) is None and re.match(r"^\d{1,2}\.?\s+[A-Z]", ln) and _is_heading_like(re.sub(r"^\d{1,2}\.?\s+", "", ln))) \
                        or (ln.isupper() and _is_heading_like(ln) and not NON_CONTENT_RE.match(ln)):
                    starts.append((ln.title() if ln.isupper() else ln, page_no))
                    break
        if len(starts) >= 2:
            return spans_from_starts(starts, doc.page_count)
        # No visible structure: fixed-size parts named after what they talk about.
        size = 8 if doc.page_count > 16 else max(2, doc.page_count // 2 or 1)
        spans = []
        for i, start in enumerate(range(1, doc.page_count + 1, size), start=1):
            end = min(doc.page_count, start + size - 1)
            words = keywords("\n".join(doc.pages[start - 1 : end]), 3, background="\n".join(doc.pages))
            spans.append((f"Part {i}: {', '.join(words).title()}" if words else f"Part {i}", start))
        return spans_from_starts(spans, doc.page_count)

    def overview(self, doc: ExtractedDocument, chapters: list[ChapterSpan], filename: str) -> BookOverview:
        front = "\n".join(doc.pages[:4])
        title = doc.metadata_title
        if not title:
            first = [ln.strip() for ln in doc.pages[0].splitlines() if ln.strip()] if doc.pages else []
            title = next((ln for ln in first[:3] if 2 <= len(ln.split()) <= 10 and not NON_CONTENT_RE.match(ln)), None)
        title = title or Path(filename).stem.replace("_", " ").replace("-", " ").title()
        text_words = re.findall(r"[a-z]+", "\n".join(doc.pages).lower())
        counts = {subject: sum(1 for w in text_words if w in set(vocab.split())) for subject, vocab in SUBJECT_WORDS.items()}
        if any(maths.find_expressions(p) for p in doc.pages[:40]):
            counts["Mathematics"] += 50
        subject = max(counts, key=counts.get) if max(counts.values()) >= 5 else "General"
        grade_match = re.search(r"\b(?:grade|class|year|standard|std\.?)\s*(\d{1,2})\b", front, re.IGNORECASE)
        grade = int(grade_match.group(1)) if grade_match and 1 <= int(grade_match.group(1)) <= 12 else None
        return BookOverview(title=title, subject=subject, grade=grade)

    def analyze_chapter(self, doc: ExtractedDocument, span: ChapterSpan, *, subject: str | None, grade: int | None) -> ChapterAnalysis:
        sections = self._sections(doc, span)
        chapter_text = "\n".join(doc.pages[span.start_page - 1 : span.end_page])
        topics = [self._topic(title, text, start, end) for title, text, start, end in sections]
        return ChapterAnalysis(
            title=span.title,
            summary=first_sentences(chapter_text, 2) or f"This chapter covers {', '.join(t.title for t in topics[:4])}.",
            topics=topics,
        )

    # ------------------------------------------------------------------ helpers

    def _sections(self, doc: ExtractedDocument, span: ChapterSpan) -> list[tuple[str, str, int, int]]:
        """(title, text, start_page, end_page) for each sub-section of the chapter."""
        marks: list[tuple[str, int, int]] = []  # (title, page, line index)
        numbered = []
        headingish = []
        for page in range(span.start_page, span.end_page + 1):
            lines = doc.pages[page - 1].splitlines()
            for i, raw in enumerate(lines):
                ln = raw.strip()
                if page == span.start_page and i < 3 and (HEADING_RE.match(ln) or ln in span.title):
                    continue  # the chapter title itself
                m = NUMBERED_SECTION.match(ln)
                if m:
                    numbered.append((f"{m.group(1)} {m.group(2).strip()}", page, i))
                elif _is_heading_like(ln) and not EXERCISE.match(ln) and not NON_CONTENT_RE.match(ln) and not HEADING_RE.match(ln):
                    prev = lines[i - 1].strip() if i else ""
                    if not prev or prev.endswith((".", ":", "?", "!")) or i == 0:
                        headingish.append((ln, page, i))
        marks = numbered if len(numbered) >= 2 else headingish if 2 <= len(headingish) <= 12 else []

        pieces: list[tuple[str, str, int, int]] = []
        if marks:
            for n, (title, page, line) in enumerate(marks):
                end_page, end_line = (marks[n + 1][1], marks[n + 1][2]) if n + 1 < len(marks) else (span.end_page, None)
                text = self._slice(doc, page, line + 1, end_page, end_line)
                pieces.append((title, text, page, end_page))
            # Intro text before the first heading belongs to the first topic.
            merged: list[tuple[str, str, int, int]] = []
            for title, text, s, e in pieces:
                if merged and len(text) < 300:  # tiny section: fold into the previous one
                    pt, ptext, ps, _ = merged[-1]
                    merged[-1] = (pt, ptext + "\n" + title + "\n" + text, ps, e)
                else:
                    merged.append((title, text, s, e))
            return merged[:10]

        # No sub-headings: split the chapter into chunks of about three pages.
        n_pages = span.end_page - span.start_page + 1
        n = max(1, min(6, round(n_pages / 3)))
        size = -(-n_pages // n)
        chapter_text = "\n".join(doc.pages[span.start_page - 1 : span.end_page])
        for k, start in enumerate(range(span.start_page, span.end_page + 1, size), start=1):
            end = min(span.end_page, start + size - 1)
            text = "\n".join(doc.pages[start - 1 : end])
            words = keywords(text, 3, background=chapter_text if n > 1 else "\n".join(doc.pages))
            label = span.title if n == 1 else f"{span.title} — {', '.join(words)}" if words else f"{span.title} (part {k})"
            pieces.append((label, text, start, end))
        return pieces

    @staticmethod
    def _slice(doc: ExtractedDocument, start_page: int, start_line: int, end_page: int, end_line: int | None) -> str:
        out = []
        for page in range(start_page, end_page + 1):
            lines = doc.pages[page - 1].splitlines()
            lo = start_line if page == start_page else 0
            hi = end_line if (page == end_page and end_line is not None) else len(lines)
            out.extend(lines[lo:hi])
        return "\n".join(out)

    @staticmethod
    def _topic(title: str, text: str, start: int, end: int) -> TopicDraft:
        defs = definitions(text)
        terms = [d.term for d in defs][:8]  # only words the book actually defines
        calcs = maths.find_expressions(text)
        objectives = [f"Explain what “{d.term}” means" for d in defs[:3]]
        if calcs:
            example = calcs[0][0].text
            objectives.append(f"Work out calculations like {example}")
        objectives.append(f"Answer questions about {re.sub(r'^[0-9.]+ ', '', title).lower()}")
        return TopicDraft(
            title=title,
            summary=first_sentences(text, 2) or f"Pages {start}–{end} of the textbook.",
            learning_objectives=objectives,
            key_terms=terms,
            prerequisites=[],
            start_page=start,
            end_page=end,
        )
