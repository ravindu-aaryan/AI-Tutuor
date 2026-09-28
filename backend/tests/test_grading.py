from app.models import Question
from app.tutor.grading import grade_by_rule, parse_number


def q(**kw) -> Question:
    base = dict(qtype="short", prompt="?", options=[], answer="", acceptable_answers=[], tolerance=None,
                explanation="", hint=None, difficulty=2, hints_used=0)
    base.update(kw)
    return Question(**base)


def test_parse_number_formats():
    assert parse_number("3/4") == 0.75
    assert parse_number("1 1/2") == 1.5
    assert parse_number("-1 1/2") == -1.5
    assert parse_number("1,250 apples") == 1250
    assert parse_number("= 2.5 cm") == 2.5
    assert parse_number("forty") is None


def test_mcq_by_text_letter_and_number():
    opts = [{"text": "2/4", "misconception": None}, {"text": "1/3", "misconception": "bigger denominator"}]
    question = q(qtype="mcq", options=opts, answer="2/4")
    assert grade_by_rule(question, "2/4").verdict == "correct"
    assert grade_by_rule(question, "A").verdict == "correct"
    assert grade_by_rule(question, "1").verdict == "correct"
    wrong = grade_by_rule(question, "b)")
    assert wrong.verdict == "incorrect" and wrong.misconception == "bigger denominator"
    assert not grade_by_rule(question, "I think the first one").decided


def test_numeric_tolerance():
    assert grade_by_rule(q(qtype="numeric", answer="0.75"), "3/4").verdict == "correct"
    assert grade_by_rule(q(qtype="numeric", answer="0.333", tolerance=0.01), "0.33").verdict == "correct"
    assert grade_by_rule(q(qtype="numeric", answer="12"), "13").verdict == "incorrect"
    assert not grade_by_rule(q(qtype="numeric", answer="12"), "twelve").decided


def test_short_answer_normalisation_else_needs_ai():
    question = q(answer="Denominator", acceptable_answers=["the bottom number"])
    assert grade_by_rule(question, "the denominator.").verdict == "correct"
    assert grade_by_rule(question, "Bottom number").verdict == "correct"
    assert not grade_by_rule(question, "the number under the line").decided
    assert grade_by_rule(question, "   ").verdict == "incorrect"
