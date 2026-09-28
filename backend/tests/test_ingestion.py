from app.ingestion.extract import ExtractedDocument, extract, split_into_pages
from app.ingestion.structure import detect_chapters

from .conftest import make_pdf, textbook_pages


def test_headings_detected_and_contents_page_ignored(tmp_path):
    path = tmp_path / "book.pdf"
    make_pdf(path, textbook_pages())
    doc = extract(path)
    assert doc.page_count == 8
    spans, source = detect_chapters(doc)
    assert source == "headings"
    assert [(s.start_page, s.end_page) for s in spans] == [(3, 4), (5, 6), (7, 8)]
    assert spans[0].title == "Chapter 1: Fractions"
    assert spans[2].title == "Chapter 3: Shapes and Angles"


def test_outline_preferred_and_front_matter_skipped(tmp_path):
    path = tmp_path / "book.pdf"
    make_pdf(path, textbook_pages(), outline=[("Contents", 2), ("Fractions", 3), ("Decimals", 5), ("Geometry", 7)])
    spans, source = detect_chapters(extract(path))
    assert source == "outline"
    assert [s.title for s in spans] == ["Fractions", "Decimals", "Geometry"]


def test_no_structure_found():
    doc = ExtractedDocument(pages=["just some text " * 20, "more text " * 20])
    assert detect_chapters(doc) == ([], None)


def test_text_pagination():
    pages = split_into_pages("\n\n".join(["para " * 100] * 10), 1200)
    assert len(pages) > 3 and all(len(p) <= 1300 for p in pages)
