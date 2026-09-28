import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from tests.fakes import FakeLLM


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("TUTOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TUTOR_PRACTICE_QUESTIONS", "3")
    monkeypatch.setenv("TUTOR_TEST_QUESTIONS", "4")
    monkeypatch.setenv("TUTOR_FRONTEND_DIST", str(tmp_path / "no-dist"))
    from app.config import get_settings

    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture()
def fake_llm():
    from app.llm import set_llm

    llm = FakeLLM()
    set_llm(llm)
    yield llm
    set_llm(None)


@pytest.fixture()
def client(settings, fake_llm):
    from app.db import init_db
    from app.main import create_app

    init_db()
    with TestClient(create_app()) as c:
        yield c


def make_pdf(path, pages: list[str], outline: list[tuple[str, int]] | None = None) -> None:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for i, text in enumerate(pages, start=1):
        pdf.add_page()
        for title, page in outline or []:
            if page == i:
                pdf.start_section(title)
        pdf.multi_cell(0, 8, text)
    pdf.output(str(path))


BODY = (
    "A fraction shows part of a whole. The top number is the numerator and the bottom number is the "
    "denominator. When we add fractions with the same denominator we add the numerators and keep the "
    "denominator the same. Practice: 1/5 + 2/5 = 3/5. "
) * 3


def textbook_pages() -> list[str]:
    return [
        "Maths Made Easy\nGrade 5",
        "Contents\nChapter 1 Fractions ..... 3\nChapter 2 Decimals ..... 5\nChapter 3 Geometry ..... 7",
        "Chapter 1: Fractions\n" + BODY,
        BODY,
        "Chapter 2: Decimals\n" + BODY.replace("fraction", "decimal"),
        BODY,
        "Chapter 3\nShapes and Angles\n" + BODY,
        BODY,
    ]
