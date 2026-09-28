"""Learner model: knowledge tracing, adaptive difficulty and spaced repetition.

* **Bayesian Knowledge Tracing** (``p_known``) - probability the student has mastered a topic.
* **Ability rating** (``ability``) - a logit-scale (1PL/Elo-style) estimate used to choose the next
  question's difficulty so that the student succeeds roughly ``target`` of the time.
* **SM-2 spaced repetition** - decides when each topic should be revised next.

All functions are pure; :func:`record_answer` / :func:`schedule_review` mutate a ``TopicMastery`` row.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from ..models import TopicMastery, utcnow

# BKT parameters
P_INIT = 0.2
P_SLIP = 0.1
P_TRANSIT_LEARNING = 0.15  # chance of learning from a taught/feedback-rich attempt
P_TRANSIT_TEST = 0.02  # tests give no feedback, little learning happens
P_GUESS_OPEN = 0.05

MASTERED = 0.85
WEAK = 0.6

DIFFICULTY_LEVELS = (1, 2, 3, 4, 5)
MAX_MISCONCEPTIONS = 8


def level_to_logit(level: int) -> float:
    """Map a 1..5 difficulty level onto the ability scale (level 3 = average)."""
    return (level - 3) * 0.9


def p_success(ability: float, level: int) -> float:
    return 1.0 / (1.0 + math.exp(-(ability - level_to_logit(level))))


def choose_difficulty(ability: float, target: float) -> int:
    """Pick the level whose predicted success probability is closest to ``target``."""
    return min(DIFFICULTY_LEVELS, key=lambda lvl: (abs(p_success(ability, lvl) - target), lvl))


def bkt_update(p_known: float, score: float, p_guess: float, p_transit: float) -> float:
    """Posterior after observing an answer. ``score`` in [0, 1] allows partial credit."""
    p_correct_obs = p_known * (1 - P_SLIP) + (1 - p_known) * p_guess
    post_correct = p_known * (1 - P_SLIP) / p_correct_obs
    post_wrong = p_known * P_SLIP / (p_known * P_SLIP + (1 - p_known) * (1 - p_guess))
    posterior = score * post_correct + (1 - score) * post_wrong
    return min(0.999, max(0.001, posterior + (1 - posterior) * p_transit))


def ability_update(ability: float, level: int, score: float, n_attempts: int) -> float:
    k = max(0.3, 1.0 / (1 + n_attempts / 8))  # learn fast at first, then stabilise
    return ability + k * (score - p_success(ability, level))


def guess_probability(qtype: str, n_options: int) -> float:
    if qtype == "mcq" and n_options > 1:
        return 1.0 / n_options
    return P_GUESS_OPEN


def record_answer(
    m: TopicMastery,
    *,
    score: float,
    level: int,
    qtype: str,
    n_options: int,
    learning: bool,
    misconception: str | None,
    now: datetime | None = None,
) -> None:
    m.p_known = bkt_update(
        m.p_known,
        score,
        guess_probability(qtype, n_options),
        P_TRANSIT_LEARNING if learning else P_TRANSIT_TEST,
    )
    m.ability = ability_update(m.ability, level, score, m.attempts)
    m.attempts += 1
    if score >= 0.99:
        m.correct += 1
    if misconception:
        m.misconceptions = (list(m.misconceptions or []) + [misconception])[-MAX_MISCONCEPTIONS:]
    m.last_practiced_at = now or utcnow()


def schedule_review(m: TopicMastery, quality: int, now: datetime | None = None) -> None:
    """SM-2 update. ``quality`` is 0 (blackout) .. 5 (perfect)."""
    now = now or utcnow()
    quality = max(0, min(5, quality))
    if quality < 3:
        m.repetitions = 0
        m.interval_days = 1
    else:
        m.repetitions += 1
        if m.repetitions == 1:
            m.interval_days = 1
        elif m.repetitions == 2:
            m.interval_days = 3
        else:
            m.interval_days = round(m.interval_days * m.ease, 1)
    m.ease = max(1.3, m.ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    # A topic the model still thinks is weak should come back quickly, whatever SM-2 says.
    if m.p_known < WEAK:
        m.interval_days = min(m.interval_days, 1)
    m.next_review_at = now + timedelta(days=m.interval_days)


def mastery_label(p_known: float) -> str:
    if p_known >= MASTERED:
        return "mastered"
    if p_known >= WEAK:
        return "developing"
    return "needs_work"
