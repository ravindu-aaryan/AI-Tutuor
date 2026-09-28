"""Deterministic answer checking. Anything a rule can't decide is graded by the AI (see engine)."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from fractions import Fraction

from ..models import Question


@dataclass
class RuleGrade:
    decided: bool
    verdict: str = "incorrect"  # correct | partial | incorrect
    score: float = 0.0
    misconception: str | None = None


_ARTICLES = re.compile(r"\b(a|an|the)\b")
_NUMBER = re.compile(r"-?\d+\s+\d+/\d+|-?\d+/\d+|-?\d*\.?\d+(?:e-?\d+)?", re.IGNORECASE)


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = text.translate(str.maketrans("", "", string.punctuation.replace("-", "").replace(".", "")))
    text = text.replace("-", " ")
    text = _ARTICLES.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text


def parse_number(text: str) -> float | None:
    """Pull the first number out of an answer: '3/4', '1 1/2', '1,250', '-2.5 cm', '40%'."""
    cleaned = text.replace(",", "").replace("−", "-").strip()
    m = _NUMBER.search(cleaned)
    if not m:
        return None
    token = m.group(0).strip()
    try:
        if " " in token:  # mixed number
            whole, frac = token.split()
            value = abs(int(whole)) + Fraction(frac)
            return float(-value if whole.startswith("-") else value)
        if "/" in token:
            return float(Fraction(token))
        return float(token)
    except (ValueError, ZeroDivisionError):
        return None


def option_letter(i: int) -> str:
    return string.ascii_uppercase[i]


def resolve_mcq_choice(q: Question, answer: str) -> int | None:
    """Index of the option the student picked: accepts the option text, 'B', 'b)' or '2'."""
    texts = [o["text"] for o in q.options]
    norm = normalize(answer)
    for i, t in enumerate(texts):
        if normalize(t) == norm:
            return i
    token = answer.strip().rstrip(").:").strip().upper()
    if len(token) == 1 and token in string.ascii_uppercase[: len(texts)]:
        return string.ascii_uppercase.index(token)
    if token.isdigit() and 1 <= int(token) <= len(texts):
        return int(token) - 1
    return None


def grade_by_rule(q: Question, answer: str) -> RuleGrade:
    if not answer.strip():
        return RuleGrade(decided=True, verdict="incorrect", score=0.0, misconception=None)

    if q.qtype == "mcq":
        idx = resolve_mcq_choice(q, answer)
        if idx is None:
            return RuleGrade(decided=False)
        correct_idx = next((i for i, o in enumerate(q.options) if normalize(o["text"]) == normalize(q.answer)), None)
        if idx == correct_idx:
            return RuleGrade(decided=True, verdict="correct", score=1.0)
        return RuleGrade(decided=True, verdict="incorrect", score=0.0, misconception=q.options[idx].get("misconception"))

    if q.qtype == "numeric":
        expected = parse_number(q.answer)
        got = parse_number(answer)
        if expected is None:
            return RuleGrade(decided=False)
        if got is None:
            return RuleGrade(decided=False)  # e.g. answered in words - let the AI judge
        tol = q.tolerance if q.tolerance is not None else max(1e-9, abs(expected) * 1e-6)
        if abs(got - expected) <= tol:
            return RuleGrade(decided=True, verdict="correct", score=1.0)
        return RuleGrade(decided=True, verdict="incorrect", score=0.0)

    # short answer: accept exact (normalised) matches; everything else needs judgement
    candidates = {normalize(a) for a in [q.answer, *q.acceptable_answers] if a}
    if normalize(answer) in candidates:
        return RuleGrade(decided=True, verdict="correct", score=1.0)
    return RuleGrade(decided=False)
