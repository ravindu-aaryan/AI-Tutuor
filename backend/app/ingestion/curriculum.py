"""AI-assisted curriculum analysis: chapter segmentation fallback, book metadata and topic extraction."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import LLMClient
from .extract import ExtractedDocument
from .structure import ChapterSpan, spans_from_starts

ANALYST_SYSTEM = (
    "You are an experienced school curriculum designer. You read school textbooks and describe exactly "
    "what a student is expected to learn from them. Base everything strictly on the textbook text you "
    "are given - never invent content the book does not cover. Page numbers refer to the [[Page N]] "
    "markers in the text."
)


# ---------- schemas ----------


class ChapterStart(BaseModel):
    title: str = Field(description="Chapter title as printed in the book")
    start_page: int = Field(description="Page number (from the [[Page N]] markers) where the chapter begins")


class BookSegmentation(BaseModel):
    chapters: list[ChapterStart]


class BookOverview(BaseModel):
    title: str
    subject: str = Field(description="School subject, e.g. Mathematics, Science, English, History")
    grade: int | None = Field(description="School grade/year the book is written for, if it can be told")


class TopicDraft(BaseModel):
    title: str = Field(description="Short name of one teachable concept/skill")
    summary: str = Field(description="2-3 sentences on what this topic covers in the book")
    learning_objectives: list[str] = Field(description="What the student should be able to do, 'Student can ...'")
    key_terms: list[str]
    prerequisites: list[str] = Field(description="Earlier ideas the student must already know")
    start_page: int
    end_page: int


class ChapterAnalysis(BaseModel):
    title: str = Field(description="Clean chapter title")
    summary: str = Field(description="What the chapter is about, 2-4 sentences")
    topics: list[TopicDraft] = Field(description="Teachable topics in the order the book presents them")


# ---------- helpers ----------


def page_text(doc: ExtractedDocument, start: int, end: int) -> str:
    return "\n\n".join(f"[[Page {p}]]\n{doc.pages[p - 1]}" for p in range(start, end + 1) if doc.pages[p - 1])


def page_windows(doc: ExtractedDocument, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Split a page range into consecutive windows whose text fits in ``max_chars``."""
    windows: list[tuple[int, int]] = []
    w_start, size = start, 0
    for p in range(start, end + 1):
        n = len(doc.pages[p - 1]) + 20
        if size and size + n > max_chars:
            windows.append((w_start, p - 1))
            w_start, size = p, 0
        size += n
    windows.append((w_start, end))
    return windows


# ---------- AI steps ----------


def segment_with_ai(llm: LLMClient, doc: ExtractedDocument, effort: str) -> list[ChapterSpan]:
    """Ask the model to find chapter boundaries from a digest of the start of every page."""
    digest_lines = []
    for i, text in enumerate(doc.pages, start=1):
        head = " ".join(text.split())[:260]
        digest_lines.append(f"[[Page {i}]] {head}")
    digest = "\n".join(digest_lines)
    result = llm.generate(
        system=ANALYST_SYSTEM,
        prompt=(
            "Below is the beginning of every page of a school textbook. Identify where each chapter (or unit/"
            "lesson - whatever the book's main teaching division is) starts. Skip front matter (cover, contents, "
            "preface) and back matter (index, answers, glossary). If the book has no explicit chapters, split it "
            "into coherent sections by subject matter.\n\n" + digest
        ),
        schema=BookSegmentation,
        purpose="segment_book",
        effort=effort,
    )
    starts = [(c.title, c.start_page) for c in result.chapters if 1 <= c.start_page <= doc.page_count]
    return spans_from_starts(starts, doc.page_count)


def book_overview(llm: LLMClient, doc: ExtractedDocument, chapters: list[ChapterSpan], filename: str) -> BookOverview:
    front = page_text(doc, 1, min(doc.page_count, 4))[:8000]
    toc = "\n".join(f"- {c.title}" for c in chapters)
    return llm.generate(
        system=ANALYST_SYSTEM,
        prompt=(
            f"File name: {filename}\n\nChapters:\n{toc}\n\nFirst pages:\n{front}\n\n"
            "Identify the book's title, school subject and the grade it is written for."
        ),
        schema=BookOverview,
        purpose="book_overview",
    )


def analyze_chapter(
    llm: LLMClient,
    doc: ExtractedDocument,
    span: ChapterSpan,
    *,
    subject: str | None,
    grade: int | None,
    max_chars: int,
    effort: str,
) -> ChapterAnalysis:
    """Extract the teachable topics of one chapter. Long chapters are analysed in windows and merged."""
    windows = page_windows(doc, span.start_page, span.end_page, max_chars)
    parts: list[ChapterAnalysis] = []
    for i, (w_start, w_end) in enumerate(windows):
        part_note = (
            f" This is part {i + 1} of {len(windows)} of the chapter (pages {w_start}-{w_end}); list only "
            "topics that are taught in this part."
            if len(windows) > 1
            else ""
        )
        parts.append(
            llm.generate(
                system=ANALYST_SYSTEM,
                prompt=(
                    f"Subject: {subject or 'unknown'}. Grade: {grade or 'unknown'}.\n"
                    f"Chapter: {span.title} (pages {span.start_page}-{span.end_page}).{part_note}\n\n"
                    "Break this chapter into the individual topics a private tutor would teach one at a time. "
                    "Each topic should be a single concept or skill that can be explained and then tested with "
                    "a few questions (typically 2-8 topics per chapter). Give accurate page ranges.\n\n"
                    + page_text(doc, w_start, w_end)
                ),
                schema=ChapterAnalysis,
                purpose="analyze_chapter",
                effort=effort,
            )
        )
    merged = ChapterAnalysis(
        title=parts[0].title or span.title,
        summary=" ".join(p.summary for p in parts),
        topics=[t for p in parts for t in p.topics],
    )
    for t in merged.topics:  # keep page ranges inside the chapter
        t.start_page = min(max(t.start_page, span.start_page), span.end_page)
        t.end_page = min(max(t.end_page, t.start_page), span.end_page)
    return merged
