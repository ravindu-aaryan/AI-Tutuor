"""The whole app working fully offline (no AI of any kind) on the bundled sample textbook."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.models import Question

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "grade5-sample-textbook.txt"


@pytest.fixture()
def offline_client(settings):
    from app.db import init_db
    from app.llm import set_llm
    from app.main import create_app

    set_llm(None)
    init_db()
    with TestClient(create_app()) as c:
        yield c


def correct_answer(question_id: int) -> str:
    from app.db import new_session

    with new_session() as db:
        return db.get(Question, question_id).answer


def upload_sample(client):
    student = client.post("/api/students", json={"name": "Nimal", "grade": 5}).json()
    r = client.post("/api/textbooks", data={"student_id": student["id"]},
                    files={"file": ("sample.txt", SAMPLE.read_bytes(), "text/plain")})
    assert r.status_code == 202
    return student, client.get(f"/api/textbooks/{r.json()['id']}").json()


def test_offline_curriculum(offline_client):
    _, book = upload_sample(offline_client)
    assert book["status"] == "ready", book["status_detail"]
    assert book["analysis_mode"] == "rules"
    assert book["title"] == "Everyday Maths and Science" and book["grade"] == 5
    assert [c["title"] for c in book["chapters"]] == ["Chapter 1: Fractions", "Chapter 2: Plants"]
    fractions = book["chapters"][0]["topics"]
    assert [t["title"] for t in fractions] == ["1.1 What Is a Fraction", "1.2 Adding Fractions", "1.3 Subtracting Fractions"]
    assert {"numerator", "denominator"} <= set(fractions[0]["key_terms"])
    assert any("1/5 + 2/5" in o for o in fractions[1]["learning_objectives"])
    plants = book["chapters"][1]["topics"]
    assert "photosynthesis" in plants[1]["key_terms"]


def test_offline_tuition_session_end_to_end(offline_client):
    client = offline_client
    student, book = upload_sample(client)
    chapter = book["chapters"][0]
    adding = chapter["topics"][1]
    lesson = client.post("/api/lessons", json={"student_id": student["id"], "chapter_id": chapter["id"],
                                               "topic_ids": [adding["id"]], "notes": "We did adding fractions"}).json()
    s = client.post("/api/sessions", json={"student_id": student["id"], "lesson_id": lesson["id"]}).json()
    sid = s["id"]
    lesson_msg = next(m for m in s["messages"] if m["kind"] == "lesson")["content"]
    assert "add the numerators and keep the denominator" in lesson_msg  # taught from the book
    assert "Worked example" in lesson_msg and "Answer:" in lesson_msg

    # A classic mistake: adding the denominators. The tutor should name it and re-teach.
    q = s["pending_question"]
    if q["qtype"] != "numeric":  # make sure we're looking at a calculation
        s = client.post(f"/api/sessions/{sid}/answer", json={"question_id": q["id"], "answer": correct_answer(q["id"])}).json()
        q = s["pending_question"]
    if q["qtype"] == "numeric" and "+" in q["prompt"]:
        import re
        (a, b), (c, d) = [map(int, f.split("/")) for f in re.findall(r"\d+/\d+", q["prompt"])[:2]]
        s = client.post(f"/api/sessions/{sid}/answer", json={"question_id": q["id"], "answer": f"{a + c}/{b + d}"}).json()
        feedback = next(m for m in reversed(s["messages"]) if m["kind"] == "feedback")["content"]
        assert "denominators too" in feedback
        assert s["messages"][-2]["kind"] == "reteach"

    # Chat works offline, from the book.
    s = client.post(f"/api/sessions/{sid}/chat", json={"text": "what is a denominator?"}).json()
    assert "denominator" in s["messages"][-1]["content"].lower()

    # Answer everything else correctly until the report.
    for _ in range(40):
        if s["phase"] == "complete":
            break
        if s["awaiting"] == "advance":
            s = client.post(f"/api/sessions/{sid}/advance").json()
            continue
        q = s["pending_question"]
        r = client.post(f"/api/sessions/{sid}/answer", json={"question_id": q["id"], "answer": correct_answer(q["id"])})
        assert r.status_code == 200, r.text
        s = r.json()
    assert s["phase"] == "complete"
    report = s["report"]
    assert report["overall"]["test_score"] == 1.0
    assert report["ai"]["message_for_student"].startswith("Fantastic work, Nimal")
    assert report["topics"][0]["next_review_at"]


def test_offline_confused_student_and_text_topic(offline_client):
    client = offline_client
    student, book = upload_sample(client)
    photosynthesis = book["chapters"][1]["topics"][1]
    s = client.post("/api/sessions", json={"student_id": student["id"], "topic_ids": [photosynthesis["id"]]}).json()
    assert "Photosynthesis is the process" in s["messages"][1]["content"]
    s = client.post(f"/api/sessions/{s['id']}/chat", json={"text": "I don't understand"}).json()
    assert [m["kind"] for m in s["messages"][-3:]] == ["chat", "reteach", "question"]
    strategy = s["messages"][-2]["payload"]["strategy"]
    from app.brain.rules.tutor import RuleTutorBrain

    assert strategy in RuleTutorBrain.strategies


def test_settings_endpoint(offline_client, monkeypatch):
    monkeypatch.setattr("app.llm.ollama_client.httpx.get", _no_ollama)
    r = offline_client.get("/api/settings/ai").json()
    assert r["settings"]["provider"] == "rules"
    assert r["providers"]["rules"]["available"] and not r["providers"]["local"]["available"]
    r = offline_client.put("/api/settings/ai", json={"provider": "local", "local_model": "llama3.2:3b",
                                                      "local_url": "http://localhost:11434"}).json()
    assert r["settings"]["provider"] == "local" and r["settings"]["local_model"] == "llama3.2:3b"
    assert offline_client.get("/api/health").json()["provider"] == "local"


def _no_ollama(*args, **kwargs):
    import httpx

    raise httpx.ConnectError("refused")
