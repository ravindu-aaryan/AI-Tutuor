from app.models import TopicMastery
from app.tutor import knowledge as k


def fresh() -> TopicMastery:
    return TopicMastery(p_known=k.P_INIT, ability=0.0, attempts=0, correct=0, misconceptions=[], ease=2.5,
                        interval_days=0.0, repetitions=0, times_taught=0)


def test_bkt_moves_in_the_right_direction():
    assert k.bkt_update(0.5, 1.0, 0.25, 0.0) > 0.5
    assert k.bkt_update(0.5, 0.0, 0.25, 0.0) < 0.5
    # A correct open answer is stronger evidence than a correct 4-option MCQ (less guessable).
    assert k.bkt_update(0.5, 1.0, 0.05, 0.0) > k.bkt_update(0.5, 1.0, 0.25, 0.0)
    # Partial credit lands in between.
    mid = k.bkt_update(0.5, 0.5, 0.05, 0.0)
    assert k.bkt_update(0.5, 0.0, 0.05, 0.0) < mid < k.bkt_update(0.5, 1.0, 0.05, 0.0)


def test_difficulty_tracks_ability():
    assert k.choose_difficulty(-3.0, 0.7) == 1
    assert k.choose_difficulty(3.0, 0.7) == 5
    levels = [k.choose_difficulty(a / 2, 0.7) for a in range(-6, 7)]
    assert levels == sorted(levels)


def test_record_answer_updates_everything():
    m = fresh()
    for _ in range(4):
        k.record_answer(m, score=1.0, level=3, qtype="numeric", n_options=0, learning=True, misconception=None)
    assert m.attempts == 4 and m.correct == 4
    assert m.p_known > k.MASTERED
    assert m.ability > 0
    k.record_answer(m, score=0.0, level=3, qtype="mcq", n_options=4, learning=True, misconception="mixes up terms")
    assert m.misconceptions == ["mixes up terms"]


def test_spaced_repetition_intervals_grow_and_reset():
    m = fresh()
    m.p_known = 0.9
    intervals = []
    for _ in range(4):
        k.schedule_review(m, 5)
        intervals.append(m.interval_days)
    assert intervals[0] == 1 and intervals[1] == 3 and intervals[3] > intervals[2] > 3
    k.schedule_review(m, 1)
    assert m.interval_days == 1 and m.repetitions == 0


def test_weak_topics_come_back_tomorrow():
    m = fresh()
    m.p_known = 0.3
    m.repetitions = 5
    m.interval_days = 20
    k.schedule_review(m, 4)
    assert m.interval_days == 1
