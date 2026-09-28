"""Small, dependency-free text analysis used by the offline (rule-based) brain."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

STOPWORDS = set(
    """a about above after again against all also am an and any are as at be because been before being below
    between both but by can could did do does doing down during each few for from further had has have having he
    her here hers herself him himself his how i if in into is it its itself just let lets like make makes many me
    more most much must my myself no nor not now of off on once only or other our ours ourselves out over own same
    she should so some such than that the their theirs them themselves then there these they this those through to
    too under until up upon us use used using very was we were what when where which while who whom why will with
    would you your yours yourself yourselves one two three four five six seven eight nine ten first second next
    called known means mean shown show see look example examples page chapter exercise lesson unit may might get
    gets got take takes way ways thing things always often usually every another way new each part parts""".split()
)

PAGE_MARK = re.compile(r"\[\[Page (\d+)\]\]")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


@dataclass
class Sentence:
    text: str
    page: int | None
    index: int


def paragraphs_by_page(excerpt: str) -> list[tuple[int | None, str]]:
    """Split text carrying ``[[Page N]]`` markers into (page, text) pieces."""
    parts = PAGE_MARK.split(excerpt)
    out: list[tuple[int | None, str]] = []
    if parts[0].strip():
        out.append((None, parts[0]))
    for i in range(1, len(parts) - 1, 2):
        out.append((int(parts[i]), parts[i + 1]))
    return out


def _unwrap(text: str) -> str:
    """Join lines broken by the PDF layout, keeping paragraph breaks."""
    text = re.sub(r"[ \t]+", " ", text)
    paras = re.split(r"\n\s*\n", text)
    return "\n\n".join(re.sub(r"\s*\n\s*", " ", p).strip() for p in paras)


_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]?\s+(?=[\"'(\[]?[A-Z0-9])")


def sentences(excerpt: str, min_words: int = 5, max_chars: int = 320) -> list[Sentence]:
    out: list[Sentence] = []
    for page, text in paragraphs_by_page(excerpt):
        for para in _unwrap(text).split("\n\n"):
            for raw in _SPLIT.split(para):
                s = raw.strip()
                if len(s.split()) < min_words or len(s) > max_chars:
                    continue
                if not re.search(r"[a-z]", s):
                    continue
                out.append(Sentence(text=s, page=page, index=len(out)))
    return out


def words(text: str) -> list[str]:
    return [w.lower().strip("'-") for w in _WORD.findall(text)]


def stem(word: str) -> str:
    w = word.lower()
    for suffix in ("ations", "ation", "ingly", "ings", "ing", "ness", "ment", "ies", "ied", "es", "ed", "ly", "s"):
        if len(w) - len(suffix) >= 3 and w.endswith(suffix):
            w = w[: -len(suffix)]
            if suffix in ("ies", "ied"):
                w += "y"
            break
    return w


def content_stems(text: str) -> set[str]:
    return {stem(w) for w in words(text) if w not in STOPWORDS and len(w) > 2}


def overlap(reference: str, candidate: str) -> float:
    """Fraction of the reference's content words that appear in the candidate (0..1)."""
    ref = content_stems(reference)
    if not ref:
        return 0.0
    return len(ref & content_stems(candidate)) / len(ref)


def keywords(text: str, n: int = 8, background: str | None = None) -> list[str]:
    """Most characteristic content words of ``text`` (optionally relative to a larger ``background`` text)."""
    counts = Counter(w for w in words(text) if w not in STOPWORDS and len(w) > 3)
    bg = Counter(w for w in words(background)) if background else None
    total_bg = sum(bg.values()) if bg else 0

    def score(w: str) -> float:
        tf = counts[w]
        if not bg:
            return tf
        return tf * math.log((total_bg + 1) / (bg[w] + 1) + 1)

    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-score(kv[0]), kv[0]))[:n]]


# --------------------------------------------------------------------------- definitions

_TERM = r"([A-Za-z][A-Za-z-]*(?: [A-Za-z][A-Za-z-]*){0,3}?)"
DEFINITION_PATTERNS = [
    # "... is called the denominator." / "... are known as mammals."
    re.compile(r"\b(?:is|are) (?:called|known as|termed|named) (?:an? |the )?[\"'‘“]?" + _TERM + r"[\"'’”]?\s*(?:[.,;:]|$)"),
    # "The bottom number is the denominator." (short predicate noun at the end of a clause)
    re.compile(r"\b(?:is|are) the ([a-z][a-z-]{3,20})(?:[.;]|,| and\b|$)"),
    # "A fraction is a part of a whole."  "Photosynthesis is the process ..."  "Nouns are naming words."
    re.compile(r"^(?:An? |The )?" + _TERM + r" (?:is|are|means|refers to) (?:an? |the |any |how |when |what )"),
    # "We call this a triangle."
    re.compile(r"\b(?:we|you) call (?:this|these|it|them) (?:an? |the )?" + _TERM + r"\s*[.,;]"),
]

_BAD_FIRST = {"this", "these", "that", "those", "it", "its", "they", "which", "what", "there", "and", "or", "but", "so", "when", "if"}
_BAD_TERMS = {"this", "these", "that", "it", "there", "they", "which", "what", "answer", "result", "number", "same", "following", "above", "below"}


@dataclass
class Definition:
    term: str
    sentence: str
    page: int | None


def _clean_term(term: str) -> str | None:
    term = term.strip(" .,:;\"'").lower()
    term = re.sub(r"^(?:an?|the) ", "", term)
    tokens = term.split()
    if not tokens or len(tokens) > 4 or len(term) < 3:
        return None
    if tokens[-1] in STOPWORDS or term in _BAD_TERMS or tokens[0] in _BAD_FIRST or (len(tokens) == 1 and tokens[0] in STOPWORDS):
        return None
    return term


def definitions(excerpt: str) -> list[Definition]:
    """Terms the textbook defines, with the defining sentence, in book order (first definition wins)."""
    found: dict[str, Definition] = {}
    for s in sentences(excerpt, min_words=4):
        for pattern in DEFINITION_PATTERNS:
            for m in pattern.finditer(s.text):
                term = _clean_term(m.group(1))
                if term and term not in found and term in s.text.lower():
                    found[term] = Definition(term=term, sentence=s.text, page=s.page)
    return list(found.values())


def important_sentences(excerpt: str, terms: list[str], n: int, focus: str = "") -> list[Sentence]:
    """The ``n`` most informative sentences, returned in book order. ``focus`` (e.g. the topic title) boosts
    sentences about it."""
    sents = sentences(excerpt)
    focus_stems = content_stems(focus)
    if not sents:
        return []
    kw = set(keywords(excerpt, 12))
    lowered_terms = [t.lower() for t in terms]
    defined = {d.sentence for d in definitions(excerpt)}

    def score(s: Sentence) -> float:
        low = s.text.lower()
        value = 3.0 * sum(1 for t in lowered_terms if t in low)
        value += 4.0 if s.text in defined else 0.0
        value += 0.5 * len(kw & set(words(low)))
        value += 1.0 if re.search(r"\d", low) else 0.0
        value += 2.0 * len(focus_stems & content_stems(low))
        value -= 0.02 * s.index  # earlier sentences usually introduce the idea
        n_words = len(s.text.split())
        if n_words > 40:
            value -= 2
        return value

    best = sorted(sents, key=score, reverse=True)[:n]
    return sorted(best, key=lambda s: s.index)


def best_matches(query: str, excerpt: str, n: int = 2) -> list[Sentence]:
    """Sentences that best answer a free-text question (content-word overlap, IDF-weighted)."""
    sents = sentences(excerpt)
    if not sents:
        return []
    q = content_stems(query)
    if not q:
        return []
    df = Counter(st for s in sents for st in content_stems(s.text))
    scored = []
    for s in sents:
        stems = content_stems(s.text)
        common = q & stems
        if common:
            scored.append((sum(math.log(1 + len(sents) / df[c]) for c in common), s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:n]]


def first_sentences(text: str, n: int = 2) -> str:
    return " ".join(s.text for s in sentences(text)[:n])
