"""Offline question generation from textbook text.

Question kinds, roughly from easiest to hardest:

* true/false about a textbook sentence (the false version swaps in a different key term or number)
* fill-in-the-blank multiple choice (distractors are other key terms from the book)
* calculation with the same shape as the book's examples (maths)
* fill-in-the-blank typed answer
* "what is X?" in your own words (marked by key-idea overlap)
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from ...tutor.prompts import OptionDraft, QuestionDraft
from . import maths
from .text import Definition, Sentence, definitions, important_sentences, paragraphs_by_page


@dataclass
class TopicMaterial:
    """What the offline brain knows about a topic, pre-digested from its textbook pages."""

    title: str
    summary: str
    definitions: list[Definition]
    key_sentences: list[Sentence]
    calculations: list[tuple[maths.Expression, str | None]]
    terms: list[str]

    @property
    def is_maths(self) -> bool:
        return bool(self.calculations)


def own_pages(excerpt: str, start: int | None, end: int | None, min_chars: int = 200) -> str:
    """Just the topic's own pages from an excerpt that also contains neighbouring pages (if there's enough text)."""
    if not start or not end:
        return excerpt
    pieces = [(p, t) for p, t in paragraphs_by_page(excerpt) if p is not None and start <= p <= end]
    text = "\n".join(f"[[Page {p}]]\n{t}" for p, t in pieces)
    return text if len(text) >= min_chars else excerpt


def material(title: str, summary: str, excerpt: str, key_terms: list[str], start: int | None = None, end: int | None = None) -> TopicMaterial:
    focus = own_pages(excerpt, start, end)
    defs = definitions(focus)
    terms = list(dict.fromkeys([d.term for d in defs] + [t.lower() for t in key_terms if t.strip()]))
    clean_title = re.sub(r"^[0-9.]+\s*", "", title)
    return TopicMaterial(
        title=clean_title,
        summary=summary,
        definitions=defs,
        key_sentences=important_sentences(focus, terms, 8, focus=clean_title),
        calculations=maths.find_expressions(focus),
        terms=terms,
    )


# --------------------------------------------------------------------------- individual generators


def calculation(m: TopicMaterial, difficulty: int, rng: random.Random) -> QuestionDraft | None:
    if not m.calculations:
        return None
    template = rng.choice(m.calculations)[0]
    expr = maths.generate_like(template, difficulty, rng)
    value = expr.value()
    answer, alts = maths.answer_forms(value, expr)
    steps = maths.solution_steps(expr)
    tolerance = None if maths._terminates(value) else 0.005
    hint = steps[0] if len(steps) > 1 else f"Remember how to {maths.OP_WORD[expr.ops[0]]} " + (
        "fractions." if expr.is_fraction else "numbers like these."
    )
    return QuestionDraft(
        qtype="numeric",
        prompt=f"Work out: **{expr.text}**" + (" (give your answer as a fraction in its simplest form)" if expr.is_fraction else ""),
        options=[],
        answer=answer,
        acceptable_answers=alts,
        tolerance=tolerance,
        explanation="\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1)) + f"\n\nSo {expr.text} = **{answer}**.",
        hint=hint,
        difficulty=difficulty,
    )


def _blank(sentence: str, term: str) -> str | None:
    pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
    if not pattern.search(sentence):
        return None
    return pattern.sub("_____", sentence, count=1)


def _distractors(m: TopicMaterial, term: str, pool: list[str], rng: random.Random, n: int = 3) -> list[str]:
    candidates = [t for t in dict.fromkeys(m.terms + pool) if t != term and term not in t and t not in term]
    rng.shuffle(candidates)
    # Prefer distractors of a similar length/shape - they're more plausible.
    candidates.sort(key=lambda t: abs(len(t.split()) - len(term.split())))
    return candidates[:n]


def cloze_choice(m: TopicMaterial, difficulty: int, rng: random.Random, pool: list[str]) -> QuestionDraft | None:
    defs = list(m.definitions)
    rng.shuffle(defs)
    for d in defs:
        blanked = _blank(d.sentence, d.term)
        wrong = _distractors(m, d.term, pool, rng)
        if not blanked or len(wrong) < 2:
            continue
        options = [OptionDraft(text=d.term, misconception=None)] + [
            OptionDraft(text=w, misconception=f"Mixes up '{w}' with '{d.term}'.") for w in wrong
        ]
        return QuestionDraft(
            qtype="mcq",
            prompt=f"Choose the word that fills the gap:\n\n> {blanked}",
            options=options,
            answer=d.term,
            acceptable_answers=[],
            tolerance=None,
            explanation=f"Your textbook says: “{d.sentence}”" + (f" (page {d.page})" if d.page else ""),
            hint=f"It starts with “{d.term[0]}”.",
            difficulty=difficulty,
        )
    return None


def cloze_typed(m: TopicMaterial, difficulty: int, rng: random.Random) -> QuestionDraft | None:
    pairs = [(d.sentence, d.term, d.page) for d in m.definitions]
    for s in m.key_sentences:
        for t in m.terms:
            if re.search(rf"\b{re.escape(t)}\b", s.text, re.IGNORECASE):
                pairs.append((s.text, t, s.page))
    rng.shuffle(pairs)
    for sentence, term, page in pairs:
        blanked = _blank(sentence, term)
        if not blanked:
            continue
        return QuestionDraft(
            qtype="short",
            prompt=f"Fill in the missing word(s):\n\n> {blanked}",
            options=[],
            answer=term,
            acceptable_answers=[term + "s"] if not term.endswith("s") else [term[:-1]],
            tolerance=None,
            explanation=f"Your textbook says: “{sentence}”" + (f" (page {page})" if page else ""),
            hint=f"It starts with “{term[0]}” and has {len(term.replace(' ', ''))} letters.",
            difficulty=difficulty,
        )
    return None


def true_false(m: TopicMaterial, difficulty: int, rng: random.Random, pool: list[str]) -> QuestionDraft | None:
    candidates = list(m.key_sentences)
    rng.shuffle(candidates)
    for s in candidates:
        text = s.text
        make_false = rng.random() < 0.5
        statement, swapped = text, None
        if make_false:
            present = [t for t in m.terms if re.search(rf"\b{re.escape(t)}\b", text, re.IGNORECASE)]
            if present:
                term = rng.choice(present)
                # Swap in another real term of the same number (singular/plural) so the sentence stays grammatical.
                plural = term.endswith("s")
                others = [o for o in _distractors(m, term, pool, rng, 6) if o.endswith("s") == plural]
                if others:
                    statement = _replace_keep_case(text, term, others[0])
                    swapped = (term, others[0])
            if swapped is None:
                nums = re.findall(r"\b\d+\b", text)
                if nums:
                    n = rng.choice(nums)
                    new = str(int(n) + rng.choice([1, 2, 3]))
                    statement = re.sub(rf"\b{n}\b", new, text, count=1)
                    swapped = (n, new)
        is_true = swapped is None
        explanation = f"Your textbook says: “{text}”" + (f" (page {s.page})" if s.page else "")
        if swapped:
            explanation += f"\n\nThe statement said **{swapped[1]}** where it should say **{swapped[0]}**."
        return QuestionDraft(
            qtype="mcq",
            prompt=f"True or false?\n\n> {statement}",
            options=[
                OptionDraft(text="True", misconception=None if is_true else f"Didn't notice '{swapped[1]}' was used instead of '{swapped[0]}'." if swapped else None),
                OptionDraft(text="False", misconception="The statement is exactly what the textbook says." if is_true else None),
            ],
            answer="True" if is_true else "False",
            acceptable_answers=[],
            tolerance=None,
            explanation=explanation,
            hint="Read every word carefully - one small change can make it false.",
            difficulty=difficulty,
        )
    return None


def _replace_keep_case(text: str, old: str, new: str) -> str:
    def sub(match: re.Match[str]) -> str:
        return new[0].upper() + new[1:] if match.group(0)[0].isupper() else new

    return re.sub(rf"\b{re.escape(old)}\b", sub, text, count=1, flags=re.IGNORECASE)


def define(m: TopicMaterial, difficulty: int, rng: random.Random) -> QuestionDraft | None:
    if not m.definitions:
        return None
    d = rng.choice(m.definitions)
    return QuestionDraft(
        qtype="short",
        prompt=f"In your own words, what is meant by **{d.term}**?",
        options=[],
        answer=d.sentence,
        acceptable_answers=[],
        tolerance=None,
        explanation=f"Your textbook says: “{d.sentence}”" + (f" (page {d.page})" if d.page else ""),
        hint="Think about what it is and give an example if you can.",
        difficulty=difficulty,
    )


def about_topic(m: TopicMaterial, difficulty: int, rng: random.Random) -> QuestionDraft:
    reference = m.summary or " ".join(s.text for s in m.key_sentences[:2]) or m.title
    return QuestionDraft(
        qtype="short",
        prompt=f"Explain in one or two sentences what **{m.title}** is about.",
        options=[],
        answer=reference,
        acceptable_answers=[],
        tolerance=None,
        explanation=f"A good answer: {reference}",
        hint="Use the key words from the lesson.",
        difficulty=difficulty,
    )


# --------------------------------------------------------------------------- selection

ORDER = {
    1: ["true_false", "cloze_choice", "calculation", "cloze_typed", "define"],
    2: ["cloze_choice", "calculation", "true_false", "cloze_typed", "define"],
    3: ["calculation", "cloze_typed", "cloze_choice", "define", "true_false"],
    4: ["calculation", "define", "cloze_typed", "cloze_choice", "true_false"],
    5: ["calculation", "define", "cloze_typed", "cloze_choice", "true_false"],
}


def make_question(m: TopicMaterial, difficulty: int, previous: list[str], rng: random.Random, pool: list[str]) -> QuestionDraft:
    difficulty = max(1, min(5, difficulty))
    order = list(ORDER[difficulty])
    if m.is_maths and rng.random() < 0.75:
        order.remove("calculation")
        order.insert(0, "calculation")
    elif not m.is_maths:
        order.remove("calculation")
    else:
        rng.shuffle(order[:3])
    # Variety: whatever kinds were used for the last two questions go to the back of the queue.
    recent = [_kind_of(p) for p in previous[-2:]]
    order.sort(key=lambda k: recent.count(k))
    seen = {p.strip()[:200] for p in previous}
    makers = {
        "calculation": lambda: calculation(m, difficulty, rng),
        "cloze_choice": lambda: cloze_choice(m, difficulty, rng, pool),
        "cloze_typed": lambda: cloze_typed(m, difficulty, rng),
        "true_false": lambda: true_false(m, difficulty, rng, pool),
        "define": lambda: define(m, difficulty, rng),
    }
    for _ in range(6):  # several passes: generators are random, so a repeat can often be avoided
        for kind in order:
            q = makers[kind]()
            if q and q.prompt.strip()[:200] not in seen:
                return q
    return about_topic(m, difficulty, rng)


def _kind_of(prompt: str) -> str:
    text = re.sub(r"^\*\*Question \d+ of \d+\*\*\s*", "", prompt.strip())
    for prefix, kind in (("Work out", "calculation"), ("True or false", "true_false"), ("Choose the word", "cloze_choice"),
                         ("Fill in the missing", "cloze_typed"), ("In your own words", "define")):
        if text.startswith(prefix):
            return kind
    return "other"
