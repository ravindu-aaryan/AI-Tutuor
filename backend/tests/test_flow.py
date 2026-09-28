"""End-to-end: upload -> process -> lesson -> tuition (teach/check/re-teach/practice/test) -> report -> progress."""

from .conftest import make_pdf, textbook_pages


def setup_book(client, tmp_path, pages=None):
    student = client.post("/api/students", json={"name": "Asha", "grade": 5}).json()
    path = tmp_path / "maths.pdf"
    make_pdf(path, pages or textbook_pages())
    with path.open("rb") as f:
        r = client.post("/api/textbooks", data={"student_id": student["id"]}, files={"file": ("maths.pdf", f, "application/pdf")})
    assert r.status_code == 202, r.text
    book = client.get(f"/api/textbooks/{r.json()['id']}").json()  # background task already ran
    return student, book


def right(q):
    """The correct answer for a FakeLLM question."""
    if q["qtype"] == "mcq":
        return "2/4"
    if q["qtype"] == "short":
        return "denominator"
    n = int(q["prompt"].split(":")[0].split("Q")[-1])
    return str(n + 1)


def answer(client, sid, s, value):
    r = client.post(f"/api/sessions/{sid}/answer", json={"question_id": s["pending_question"]["id"], "answer": value})
    assert r.status_code == 200, r.text
    return r.json()


def test_textbook_processing_builds_curriculum(client, tmp_path):
    _, book = setup_book(client, tmp_path)
    assert book["status"] == "ready", book["status_detail"]
    assert book["structure_source"] == "headings"
    assert book["title"] == "Maths Made Easy" and book["subject"] == "Mathematics" and book["grade"] == 5
    assert [c["title"] for c in book["chapters"]] == ["Chapter 1: Fractions", "Chapter 2: Decimals", "Chapter 3: Shapes and Angles"]
    topics = book["chapters"][0]["topics"]
    assert len(topics) == 2
    assert topics[1]["end_page"] == 4  # clamped to the chapter


def test_ai_segmentation_fallback(client, tmp_path):
    pages = ["Section one: counting\n" + "numbers " * 50, "numbers " * 60, "Section two: shapes\n" + "shapes " * 60]
    _, book = setup_book(client, tmp_path, pages)
    assert book["status"] == "ready"
    assert book["structure_source"] == "ai"
    assert [(c["start_page"], c["end_page"]) for c in book["chapters"]] == [(1, 2), (3, 3)]


def test_unsupported_and_scanned_uploads(client, tmp_path):
    student = client.post("/api/students", json={"name": "B", "grade": 3}).json()
    r = client.post("/api/textbooks", data={"student_id": student["id"]}, files={"file": ("a.docx", b"xx", "application/octet-stream")})
    assert r.status_code == 415
    blank = tmp_path / "scan.pdf"
    make_pdf(blank, ["", "", ""])
    with blank.open("rb") as f:
        r = client.post("/api/textbooks", data={"student_id": student["id"]}, files={"file": ("scan.pdf", f, "application/pdf")})
    book = client.get(f"/api/textbooks/{r.json()['id']}").json()
    assert book["status"] == "failed" and "OCR" in book["status_detail"]


def test_full_tuition_session(client, tmp_path, fake_llm):
    student, book = setup_book(client, tmp_path)
    chapter = book["chapters"][0]
    topic_ids = [t["id"] for t in chapter["topics"]]
    lesson = client.post(
        "/api/lessons",
        json={"student_id": student["id"], "chapter_id": chapter["id"], "topic_ids": topic_ids,
              "notes": "Teacher did adding fractions with the same denominator"},
    ).json()

    s = client.post("/api/sessions", json={"student_id": student["id"], "lesson_id": lesson["id"]}).json()
    sid = s["id"]
    assert s["phase"] == "check" and s["awaiting"] == "answer"
    kinds = [m["kind"] for m in s["messages"]]
    assert kinds == ["info", "lesson", "question"]
    teach_call = next(c for c in fake_llm.calls if c["purpose"] == "teach")
    assert "Teacher did adding fractions" in teach_call["prompt"]  # today's lesson is used
    assert "A fraction shows part of a whole" in teach_call["prompt"]  # grounded in the textbook

    # Topic 1: wrong -> re-teach with a new strategy, then two right answers pass the topic.
    s = answer(client, sid, s, "999")
    assert [m["kind"] for m in s["messages"][-3:]] == ["feedback", "reteach", "question"]
    assert s["messages"][-2]["payload"]["strategy"]
    s = answer(client, sid, s, right(s["pending_question"]))
    s = answer(client, sid, s, right(s["pending_question"]))
    assert s["topics"][0]["status"] == "passed"
    assert s["messages"][-2]["kind"] == "lesson"  # topic 2 is being taught

    # Topic 2: a hint, then two correct answers.
    r = client.post(f"/api/sessions/{sid}/hint", json={"question_id": s["pending_question"]["id"]}).json()
    assert r["messages"][-1]["kind"] == "hint" and not r["pending_question"]["hints_available"]
    s = answer(client, sid, r, right(r["pending_question"]))
    s = answer(client, sid, s, right(s["pending_question"]))
    assert s["phase"] == "practice"

    # Chatting with the tutor mid-practice.
    s = client.post(f"/api/sessions/{sid}/chat", json={"text": "why do we keep the denominator?"}).json()
    assert s["messages"][-1]["kind"] == "chat" and s["pending_question"] is not None

    # Practice (3 questions in tests), one wrong, one short answer graded by AI.
    fake_llm.question_kinds = ["short"]
    s = answer(client, sid, s, "0")
    assert s["messages"][-2]["payload"]["verdict"] == "incorrect"
    s = answer(client, sid, s, "it is the good bottom part")  # not an exact match -> AI grading
    assert fake_llm.calls[-2]["purpose"] == "evaluate" or any(c["purpose"] == "evaluate" for c in fake_llm.calls)
    s = answer(client, sid, s, right(s["pending_question"]))
    assert s["phase"] == "test_ready" and s["awaiting"] == "advance"

    # Test: 4 questions, no hints, mcq answered by letter.
    s = client.post(f"/api/sessions/{sid}/advance").json()
    assert s["phase"] == "test" and s["test_total"] == 4
    r = client.post(f"/api/sessions/{sid}/hint", json={"question_id": s["pending_question"]["id"]})
    assert r.status_code == 409
    r = client.post(f"/api/sessions/{sid}/chat", json={"text": "what's the answer?"}).json()
    assert "can't help" in r["messages"][-1]["content"]
    s = answer(client, sid, r, right(s["pending_question"]))
    s = answer(client, sid, s, "0")
    s = answer(client, sid, s, right(s["pending_question"]))
    assert s["test_answered"] == 3
    s = answer(client, sid, s, right(s["pending_question"]))

    assert s["phase"] == "complete" and s["pending_question"] is None
    report = s["report"]
    assert report["overall"]["test_questions"] == 4
    assert report["overall"]["test_score"] == 0.75
    assert report["ai"]["message_for_student"] == "Great work today!"
    t1 = report["topics"][0]
    assert t1["reteach_count"] == 1 and t1["strategies_used"] and t1["next_review_at"]
    assert t1["mastery_end"] > t1["mastery_start"]
    assert len(report["test_review"]) == 4

    # Stale question id is rejected.
    r = client.post(f"/api/sessions/{sid}/answer", json={"question_id": 1, "answer": "x"})
    assert r.status_code == 409

    # Progress and revision planning reflect the session.
    prog = client.get(f"/api/students/{student['id']}/progress").json()
    assert prog["sessions_completed"] == 1 and prog["questions_answered"] > 10
    ch = prog["textbooks"][0]["chapters"][0]
    assert all(t["p_known"] is not None for t in ch["topics"])
    assert prog["textbooks"][0]["chapters"][1]["topics"][0]["status"] == "not_started"
    # The strategy that preceded a correct answer is remembered as successful for this student.
    assert any(v["succeeded"] == 1 for v in prog["teaching_strategies"].values())
    plan = client.get(f"/api/students/{student['id']}/revision-plan").json()
    assert {x["topic_id"] for x in plan["due"] + plan["upcoming"]} <= set(topic_ids)

    listing = client.get("/api/sessions", params={"student_id": student["id"]}).json()
    assert listing[0]["test_score"] == 0.75


def test_confused_student_gets_reteach(client, tmp_path):
    student, book = setup_book(client, tmp_path)
    topic = book["chapters"][1]["topics"][0]
    s = client.post("/api/sessions", json={"student_id": student["id"], "topic_ids": [topic["id"]], "mode": "revision"}).json()
    old_q = s["pending_question"]["id"]
    s = client.post(f"/api/sessions/{s['id']}/chat", json={"text": "I don't understand this"}).json()
    assert [m["kind"] for m in s["messages"][-3:]] == ["chat", "reteach", "question"]
    assert s["pending_question"]["id"] != old_q


def test_topic_given_up_after_max_reteach(client, tmp_path, settings):
    student, book = setup_book(client, tmp_path)
    topic = book["chapters"][0]["topics"][0]
    s = client.post("/api/sessions", json={"student_id": student["id"], "topic_ids": [topic["id"]]}).json()
    for _ in range(settings.max_reteach_per_topic + 1):
        s = answer(client, s["id"], s, "-1")
    assert s["topics"][0]["status"] == "needs_followup"
    assert s["phase"] == "practice"


def test_ai_failure_rolls_back(client, tmp_path, fake_llm):
    student, book = setup_book(client, tmp_path)
    topic = book["chapters"][0]["topics"][0]
    s = client.post("/api/sessions", json={"student_id": student["id"], "topic_ids": [topic["id"]]}).json()
    fake_llm.fail_purposes = {"reteach"}
    r = client.post(f"/api/sessions/{s['id']}/answer", json={"question_id": s["pending_question"]["id"], "answer": "-5"})
    assert r.status_code == 502
    after = client.get(f"/api/sessions/{s['id']}").json()
    assert after["pending_question"]["id"] == s["pending_question"]["id"]  # still answerable
    assert len(after["messages"]) == len(s["messages"])
    fake_llm.fail_purposes = set()
    r = client.post(f"/api/sessions/{s['id']}/answer", json={"question_id": s["pending_question"]["id"], "answer": "-5"})
    assert r.status_code == 200


def test_session_requires_llm(client, tmp_path, monkeypatch):
    from app import llm as llm_mod

    student, book = setup_book(client, tmp_path)
    topic = book["chapters"][0]["topics"][0]
    llm_mod.set_llm(None)
    monkeypatch.setattr("app.llm.anthropic_client.credentials_available", lambda: False)
    monkeypatch.setattr(llm_mod, "_default", None)
    r = client.post("/api/sessions", json={"student_id": student["id"], "topic_ids": [topic["id"]]})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_lesson_validation(client, tmp_path):
    student, book = setup_book(client, tmp_path)
    ch1, ch2 = book["chapters"][0], book["chapters"][1]
    r = client.post("/api/lessons", json={"student_id": student["id"], "chapter_id": ch1["id"], "topic_ids": [ch2["topics"][0]["id"]]})
    assert r.status_code == 400
    other = client.post("/api/students", json={"name": "C", "grade": 4}).json()
    r = client.post("/api/sessions", json={"student_id": other["id"], "topic_ids": [ch1["topics"][0]["id"]]})
    assert r.status_code == 400
