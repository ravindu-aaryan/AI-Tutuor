"""Offline brain building blocks: text analysis, maths, question generation."""

import random
from fractions import Fraction

from app.brain.rules import maths
from app.brain.rules.questions import make_question, material
from app.brain.rules.text import best_matches, definitions, overlap, sentences

TEXT = """[[Page 3]]
A fraction shows part of a whole. The top number is called the numerator. The bottom number is called the
denominator. When two fractions have the same denominator, they are called like fractions.

To add like fractions, we add the numerators and keep the denominator the same. For example,
1/5 + 2/5 = 3/5.
[[Page 4]]
Photosynthesis is the process by which green plants make their own food using sunlight.
"""


def test_sentences_carry_pages():
    s = sentences(TEXT)
    assert s[0].text == "A fraction shows part of a whole." and s[0].page == 3
    assert s[-1].page == 4


def test_definitions_found():
    terms = {d.term for d in definitions(TEXT)}
    assert {"numerator", "denominator", "like fractions", "photosynthesis"} <= terms


def test_overlap_and_search():
    assert overlap("the process by which plants make food using sunlight", "plants use sunlight to make food") > 0.5
    assert overlap("the process by which plants make food using sunlight", "a kind of rock") == 0
    assert "Photosynthesis" in best_matches("how do plants make food?", TEXT, 1)[0].text


def test_expressions_found_and_solved():
    found = maths.find_expressions(TEXT + " In 2023-2024 we read page 12.")
    assert [(e.text, a) for e, a in found] == [("1/5 + 2/5", "3/5")]
    assert found[0][0].value() == Fraction(3, 5)
    e = maths.parse_expression("3 + 4 × 2")
    assert e.value() == 11
    assert maths.parse_expression("2.5 − 0.75").value() == Fraction(7, 4)
    assert maths.parse_expression("1 1/2 + 2/3").value() == Fraction(13, 6)


def test_generated_calculations_keep_their_shape_and_scale():
    template = maths.parse_expression("1/5 + 2/5")
    rng = random.Random(0)
    for difficulty in range(1, 6):
        for _ in range(20):
            e = maths.generate_like(template, difficulty, rng)
            assert e.is_fraction and e.ops == ["+"]
            if difficulty <= 2:
                assert len({o.value.denominator for o in e.operands}) == 1
    subtraction = maths.parse_expression("45 − 17")
    for _ in range(30):
        assert maths.generate_like(subtraction, 3, rng).value() >= 0
    division = maths.parse_expression("84 ÷ 7")
    for _ in range(30):
        assert maths.generate_like(division, 3, rng).value().denominator == 1


def test_mistake_diagnosis():
    assert "denominators too" in maths.diagnose(maths.parse_expression("3/7 + 2/7"), 5 / 14)
    assert "without first making the denominators the same" in maths.diagnose(maths.parse_expression("1/2 + 1/3"), 2 / 3)
    assert "left to right" in maths.diagnose(maths.parse_expression("3 + 4 × 2"), 14)
    assert "added instead of subtracting" in maths.diagnose(maths.parse_expression("12 − 5"), 17)
    assert maths.diagnose(maths.parse_expression("12 − 5"), 3) is None


def test_worked_steps_and_pictures():
    steps = maths.solution_steps(maths.parse_expression("1/2 + 1/3"))
    assert any("common denominator" in s for s in steps) and steps[-1].endswith("5/6.")
    assert "■" in maths.picture(maths.parse_expression("1/5 + 2/5"))


def test_question_generation_covers_every_level_without_repeats():
    m = material("Fractions", "About fractions.", TEXT, [])
    rng = random.Random(1)
    previous: list[str] = []
    kinds = set()
    for level in [1, 2, 3, 4, 5, 1, 2, 3]:
        q = make_question(m, level, previous, rng, ["decimal", "percentage"])
        assert q.prompt[:200] not in previous
        previous.append(q.prompt[:200])
        kinds.add(q.qtype)
        if q.qtype == "mcq":
            assert q.answer in [o.text for o in q.options]
    assert {"numeric", "mcq"} <= kinds


def test_text_only_topic_still_gets_questions():
    m = material("Plants", "", "[[Page 1]]\nPhotosynthesis is the process by which green plants make their own food. "
                 "Chlorophyll is the green pigment in leaves. Roots are the parts that take in water from the soil.", [])
    q = make_question(m, 2, [], random.Random(2), [])
    assert q.qtype in ("mcq", "short") and not m.is_maths
