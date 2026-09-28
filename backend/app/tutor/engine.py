"""The tuition session state machine.

Flow for each session::

    for each topic of today's lesson:
        TEACH  -> lesson + check question            (recap only if already mastered)
        CHECK  -> correct:  next check question, until ``check_questions_to_pass`` correct -> next topic
                  wrong:    diagnose + RE-TEACH with a different strategy + new question
                            (after ``max_reteach_per_topic`` re-teaches: flag for follow-up, move on)
    PRACTICE   -> ``practice_questions`` adaptive questions, weakest topic first, difficulty targeted at ~70% success
    TEST_READY -> waits for the student to start the test
    TEST       -> ``test_questions`` questions, no hints/feedback until the end, little learning credit
    COMPLETE   -> report, mastery + spaced-repetition schedule updated

Each public method performs one step and leaves everything uncommitted; the caller commits on success or
rolls back on failure (so an AI error never leaves the session half-advanced).
"""

from __future__ import annotations

import copy
import random
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..llm import LLMClient
from ..models import Attempt, DailyLesson, Question, SessionMessage, Student, Topic, TopicMastery, TutorSession, utcnow
from . import knowledge, prompts
from .context import describe_learner, describe_topic, topic_excerpt
from .grading import grade_by_rule, option_letter


class SessionError(ValueError):
    """The request doesn't make sense in the session's current state."""


CHECK_TARGET = 0.8  # while learning, keep questions comfortably achievable
PRACTICE_TARGET = 0.7
TEST_TARGET = 0.65


def get_mastery(db: Session, student_id: int, topic_id: int) -> TopicMastery:
    m = db.scalar(select(TopicMastery).where(TopicMastery.student_id == student_id, TopicMastery.topic_id == topic_id))
    if m is None:
        m = TopicMastery(
            student_id=student_id,
            topic_id=topic_id,
            p_known=knowledge.P_INIT,
            ability=0.0,
            attempts=0,
            correct=0,
            times_taught=0,
            misconceptions=[],
            ease=2.5,
            interval_days=0.0,
            repetitions=0,
        )
        db.add(m)
        db.flush()
    return m


class TutorEngine:
    def __init__(self, db: Session, session: TutorSession, llm: LLMClient, settings: Settings) -> None:
        self.db = db
        self.s = session
        self.llm = llm
        self.cfg = settings
        self.student: Student = db.get(Student, session.student_id)  # type: ignore[assignment]
        self.lesson: DailyLesson | None = db.get(DailyLesson, session.daily_lesson_id) if session.daily_lesson_id else None
        self._topics = {t.id: t for t in db.scalars(select(Topic).where(Topic.id.in_(session.topic_ids)))}
        self._state: dict[str, Any] = copy.deepcopy(session.state or {})

    # ------------------------------------------------------------------ creation

    @classmethod
    def create(
        cls,
        db: Session,
        llm: LLMClient,
        settings: Settings,
        *,
        student: Student,
        topic_ids: list[int],
        lesson: DailyLesson | None = None,
        mode: str = "lesson",
    ) -> TutorEngine:
        if not topic_ids:
            raise SessionError("Choose at least one topic to study.")
        session = TutorSession(
            student_id=student.id,
            daily_lesson_id=lesson.id if lesson else None,
            mode=mode,
            topic_ids=list(dict.fromkeys(topic_ids)),
            phase="teach",
            awaiting="none",
            state={},
        )
        db.add(session)
        db.flush()
        engine = cls(db, session, llm, settings)
        if len(engine._topics) != len(session.topic_ids):
            raise SessionError("Some of the chosen topics don't exist.")
        engine._state = {
            "topic_index": 0,
            "current_question_id": None,
            "practice_done": 0,
            "test_question_ids": [],
            "topics": {
                str(tid): {
                    "status": "pending",
                    "check_correct": 0,
                    "check_attempts": 0,
                    "reteach_count": 0,
                    "strategies_used": [],
                    "last_strategy": None,
                    "mastery_start": get_mastery(db, student.id, tid).p_known,
                }
                for tid in session.topic_ids
            },
        }
        topic_names = ", ".join(f"**{engine._topics[t].title}**" for t in session.topic_ids)
        intro = (
            f"Hi {student.name}! Let's go over what you learned today: {topic_names}. "
            if mode == "lesson"
            else f"Hi {student.name}! Time for some revision: {topic_names}. "
        )
        engine._say("info", intro + "I'll explain each idea, ask you some questions, and we'll finish with a short test. "
                    "You can ask me anything at any time.")
        engine._teach_current()
        engine._save()
        return engine

    # ------------------------------------------------------------------ public actions

    def answer(self, question_id: int, answer: str) -> None:
        q = self._pending_question()
        if q is None or q.id != question_id:
            raise SessionError("That question isn't the one waiting for an answer.")
        answer = answer.strip()
        if not answer:
            raise SessionError("Please write an answer first.")
        self._student_says("answer", answer, {"question_id": q.id})

        verdict, score, feedback, misconception, graded_by = self._grade(q, answer)
        self.db.add(
            Attempt(
                question_id=q.id,
                student_id=self.student.id,
                topic_id=q.topic_id,
                answer=answer,
                verdict=verdict,
                score=score,
                feedback=feedback,
                misconception=misconception,
                graded_by=graded_by,
            )
        )
        mastery = get_mastery(self.db, self.student.id, q.topic_id)
        credit = min(score, 0.7) if q.hints_used and score > 0.7 else score
        knowledge.record_answer(
            mastery,
            score=credit,
            level=q.difficulty,
            qtype=q.qtype,
            n_options=len(q.options),
            learning=q.phase != "test",
            misconception=misconception,
        )
        self._state["current_question_id"] = None

        if q.phase == "check":
            self._after_check(q, answer, verdict, feedback, graded_by)
        elif q.phase == "practice":
            self._feedback(q, verdict, feedback, graded_by)
            self._state["practice_done"] += 1
            self._next_practice_or_test_ready()
        elif q.phase == "test":
            self._say("info", "Answer saved. ✏️", {"question_id": q.id})
            self._next_test_question()
        self._save()

    def hint(self, question_id: int) -> str:
        q = self._pending_question()
        if q is None or q.id != question_id:
            raise SessionError("That question isn't the one waiting for an answer.")
        if q.phase == "test":
            raise SessionError("Hints aren't available during the test - give it your best try!")
        q.hints_used += 1
        text = q.hint or "Look back at the worked example above and try the same steps."
        self._say("hint", f"💡 **Hint:** {text}", {"question_id": q.id})
        self._save()
        return text

    def chat(self, message: str) -> None:
        message = message.strip()
        if not message:
            raise SessionError("Type a message first.")
        if self.s.phase == "complete":
            raise SessionError("This session has finished. Start a new one to keep learning!")
        self._student_says("chat", message)
        if self.s.phase == "test":
            self._say("chat", "During the test I can't help with the questions - give it your best try! "
                      "We'll go through everything together afterwards.")
            self._save()
            return

        pending = self._pending_question()
        topic = self._topics[pending.topic_id] if pending else self._current_topic()
        mastery = get_mastery(self.db, self.student.id, topic.id)
        transcript = "\n".join(
            f"{m.role.upper()}: {m.content[:600]}" for m in self.s.messages[-8:] if m.kind != "info"
        )
        reply = self.llm.generate(
            system=prompts.tutor_system(self.student.grade),
            prompt=prompts.chat_prompt(
                describe_topic(topic),
                describe_learner(self.student, mastery, self.lesson),
                self._excerpt(topic),
                transcript=transcript,
                pending_question=pending.prompt if pending else None,
                message=message,
            ),
            schema=prompts.ChatReply,
            purpose="chat",
        )
        self._say("chat", reply.reply)
        if reply.student_is_confused and self.s.phase == "check" and pending is not None:
            # Replace the pending question with a fresh explanation in a new style.
            self._state["current_question_id"] = None
            self._reteach(topic, pending, None, reason="said they don't understand the explanation")
        self._save()

    def advance(self) -> None:
        """Continue when the session is waiting for the student (start the test) or recover a stalled step."""
        if self.s.phase == "test_ready":
            self._start_test()
        elif self._pending_question() is None and self.s.phase != "complete":
            if self.s.phase in ("teach", "check"):
                self._teach_current()
            elif self.s.phase == "practice":
                self._next_practice_or_test_ready()
            elif self.s.phase == "test":
                self._next_test_question()
        else:
            raise SessionError("There's nothing to continue right now.")
        self._save()

    def skip_to_test(self) -> None:
        if self.s.phase not in ("practice", "test_ready"):
            raise SessionError("You can skip to the test once practice has started.")
        self._state["current_question_id"] = None
        self._start_test()
        self._save()

    # ------------------------------------------------------------------ phase logic

    def _after_check(self, q: Question, answer: str, verdict: str, feedback: str, graded_by: str) -> None:
        topic = self._topics[q.topic_id]
        ts = self._topic_state(topic.id)
        ts["check_attempts"] += 1
        last_strategy = ts.get("last_strategy")
        if verdict == "correct":
            self._feedback(q, verdict, feedback, graded_by)
            if last_strategy:
                self._record_strategy(last_strategy, succeeded=True)
                ts["last_strategy"] = None
            ts["check_correct"] += 1
            if ts["check_correct"] >= self.cfg.check_questions_to_pass:
                ts["status"] = "passed"
                self._next_topic()
            elif ts["check_attempts"] >= self._max_check_attempts():
                ts["status"] = "needs_followup"
                self._next_topic()
            else:
                self._ask(topic, "check", self._difficulty(topic.id, CHECK_TARGET), prompt_kind="practice")
            return

        if last_strategy:
            ts["last_strategy"] = None  # that strategy didn't land; it stays counted as tried
        out_of_budget = (
            ts["reteach_count"] >= self.cfg.max_reteach_per_topic or ts["check_attempts"] >= self._max_check_attempts()
        )
        if verdict == "partial" and not out_of_budget:
            self._feedback(q, verdict, feedback, graded_by)
            self._ask(topic, "check", max(1, q.difficulty - 1), prompt_kind="practice")
            return
        if out_of_budget:
            self._feedback(q, verdict, feedback, graded_by)
            ts["status"] = "needs_followup"
            self._say(
                "info",
                f"This one is tricky, and that's okay! We'll come back to **{topic.title}** in your next revision "
                "session. Let's keep going.",
            )
            self._next_topic()
            return
        self._reteach(topic, q, answer)

    def _next_topic(self) -> None:
        self._state["topic_index"] += 1
        if self._state["topic_index"] < len(self.s.topic_ids):
            self._teach_current()
        else:
            self.s.phase = "practice"
            self._say("info", "You've worked through every topic - brilliant! Now some practice questions to make it stick. 💪")
            self._next_practice_or_test_ready()

    def _teach_current(self) -> None:
        topic = self._current_topic()
        ts = self._topic_state(topic.id)
        ts["status"] = "learning"
        mastery = get_mastery(self.db, self.student.id, topic.id)
        difficulty = self._difficulty(topic.id, CHECK_TARGET)
        out = self.llm.generate(
            system=prompts.tutor_system(self.student.grade),
            prompt=prompts.teach_prompt(
                describe_topic(topic),
                describe_learner(self.student, mastery, self.lesson),
                self._excerpt(topic),
                recap=mastery.p_known >= knowledge.MASTERED,
                difficulty=difficulty,
                previous=self._previous_prompts(),
            ),
            schema=prompts.TeachOutput,
            purpose="teach",
        )
        mastery.times_taught += 1
        body = f"## {topic.title}\n\n{out.explanation}\n\n### Worked example\n\n{out.worked_example}"
        if out.key_points:
            body += "\n\n### Remember\n" + "\n".join(f"- {p}" for p in out.key_points)
        self._say("lesson", body, {"topic_id": topic.id})
        self.s.phase = "check"
        self._create_question(topic, "check", out.question, difficulty)

    def _reteach(self, topic: Topic, q: Question, answer: str | None, reason: str = "answered a question incorrectly") -> None:
        ts = self._topic_state(topic.id)
        strategy = self._choose_strategy(ts["strategies_used"])
        ts["strategies_used"] = ts["strategies_used"] + [strategy]
        ts["reteach_count"] += 1
        ts["last_strategy"] = strategy
        self._record_strategy(strategy, succeeded=False)
        mastery = get_mastery(self.db, self.student.id, topic.id)
        mastery.times_taught += 1
        difficulty = max(1, min(q.difficulty - 1, self._difficulty(topic.id, CHECK_TARGET)))
        out = self.llm.generate(
            system=prompts.tutor_system(self.student.grade),
            prompt=prompts.reteach_prompt(
                describe_topic(topic),
                describe_learner(self.student, mastery, self.lesson),
                self._excerpt(topic),
                question=q.prompt if answer is not None else "",
                correct_answer=q.answer,
                student_answer=answer or "",
                strategy=strategy,
                difficulty=difficulty,
                previous=self._previous_prompts(),
                reason=reason,
            ),
            schema=prompts.ReteachOutput,
            purpose="reteach",
        )
        if answer is not None:
            if out.misconception:
                ms = list(mastery.misconceptions or [])
                if not ms or ms[-1] != out.misconception:
                    mastery.misconceptions = (ms + [out.misconception])[-knowledge.MAX_MISCONCEPTIONS:]
            self._say(
                "feedback",
                f"❌ Not quite - the answer is **{self._display_answer(q)}**.\n\n{out.what_went_wrong}",
                {"question_id": q.id, "verdict": "incorrect", "misconception": out.misconception},
            )
        self._say(
            "reteach",
            f"### Let's look at it another way\n\n{out.explanation}",
            {"topic_id": topic.id, "strategy": strategy},
        )
        self._create_question(topic, "check", out.question, difficulty)

    def _next_practice_or_test_ready(self) -> None:
        if self._state["practice_done"] >= self.cfg.practice_questions:
            self.s.phase = "test_ready"
            self.s.awaiting = "advance"
            self._say("info", f"Practice done! 🎉 Ready for a short test of {self.cfg.test_questions} questions? "
                      "No hints this time - just show what you know.")
            return
        topic = self._pick_practice_topic()
        self._ask(topic, "practice", self._difficulty(topic.id, PRACTICE_TARGET), prompt_kind="practice")

    def _start_test(self) -> None:
        self.s.phase = "test"
        n = self.cfg.test_questions
        tids = list(self.s.topic_ids)
        # Spread questions over topics, weakest topics first when they don't divide evenly.
        tids.sort(key=lambda t: get_mastery(self.db, self.student.id, t).p_known)
        per_topic: dict[int, int] = defaultdict(int)
        for i in range(n):
            per_topic[tids[i % len(tids)]] += 1
        sections = []
        plan: list[tuple[int, int]] = []  # (topic_id, difficulty) in paper order
        for number, tid in enumerate(t for t in self.s.topic_ids if per_topic[t]):
            topic = self._topics[tid]
            base = self._difficulty(tid, TEST_TARGET)
            levels = [max(1, min(5, base + d)) for d in ([0, -1, 1, 0, 1, -1] * 3)[: per_topic[tid]]]
            levels.sort()
            plan += [(tid, lvl) for lvl in levels]
            block = f"<topic_{number + 1}>\n{describe_topic(topic)}\n\n<textbook_excerpt>\n{self._excerpt(topic, 0.5)}\n</textbook_excerpt>\n</topic_{number + 1}>"
            sections.append((block, topic.title, levels))
        paper = self.llm.generate(
            system=prompts.tutor_system(self.student.grade),
            prompt=prompts.test_prompt(sections, describe_learner(self.student, None, self.lesson), self._previous_prompts()),
            schema=prompts.TestPaper,
            purpose="test",
        )
        if not paper.questions:
            raise SessionError("The test could not be prepared - please try again.")
        ids = []
        for i, draft in enumerate(paper.questions[:n]):
            tid, lvl = plan[min(i, len(plan) - 1)]
            ids.append(self._create_question(self._topics[tid], "test", draft, lvl, present=False).id)
        self._state["test_question_ids"] = ids
        self._say("info", f"📝 **Test time!** {len(ids)} questions. Take your time.")
        self._next_test_question()

    def _next_test_question(self) -> None:
        answered = {
            a.question_id for a in self.db.scalars(
                select(Attempt).where(Attempt.question_id.in_(self._state["test_question_ids"]))
            )
        }
        remaining = [qid for qid in self._state["test_question_ids"] if qid not in answered]
        if not remaining:
            self._complete()
            return
        q = self.db.get(Question, remaining[0])
        assert q is not None
        number = len(self._state["test_question_ids"]) - len(remaining) + 1
        self._present(q, f"**Question {number} of {len(self._state['test_question_ids'])}**\n\n")

    def _complete(self) -> None:
        from .report import build_report  # local import: report depends on engine helpers

        self.s.phase = "complete"
        self.s.awaiting = "none"
        self.s.ended_at = utcnow()
        report = build_report(self.db, self.s, self.student, self._state, self.llm, self.lesson)
        self.s.report = report
        self._say("summary", report["ai"]["message_for_student"] or "Well done today!", {"report": True})

    # ------------------------------------------------------------------ questions

    def _ask(self, topic: Topic, phase: str, difficulty: int, prompt_kind: str) -> None:
        mastery = get_mastery(self.db, self.student.id, topic.id)
        out = self.llm.generate(
            system=prompts.tutor_system(self.student.grade),
            prompt=prompts.practice_prompt(
                describe_topic(topic),
                describe_learner(self.student, mastery, self.lesson),
                self._excerpt(topic),
                difficulty=difficulty,
                previous=self._previous_prompts(),
            ),
            schema=prompts.QuestionOnly,
            purpose=f"question_{phase}",
        )
        self._create_question(topic, phase, out.question, difficulty)

    def _create_question(self, topic: Topic, phase: str, draft: prompts.QuestionDraft, difficulty: int, present: bool = True) -> Question:
        qtype = draft.qtype
        options = [{"text": o.text.strip(), "misconception": o.misconception} for o in draft.options if o.text.strip()]
        answer = draft.answer.strip()
        if qtype == "mcq":
            texts = [o["text"] for o in options]
            if len(options) < 2 or answer not in texts:
                # The correct answer must be one of the options; otherwise treat it as open-ended.
                match = next((t for t in texts if t.lower() == answer.lower()), None)
                if match and len(options) >= 2:
                    answer = match
                else:
                    qtype, options = "short", []
            if qtype == "mcq":
                random.shuffle(options)
        else:
            options = []
        q = Question(
            session_id=self.s.id,
            topic_id=topic.id,
            phase=phase,
            qtype=qtype,
            prompt=draft.prompt.strip(),
            options=options,
            answer=answer,
            acceptable_answers=[a for a in draft.acceptable_answers if a.strip()],
            tolerance=draft.tolerance if qtype == "numeric" else None,
            explanation=draft.explanation,
            hint=draft.hint,
            difficulty=max(1, min(5, difficulty)),
            hints_used=0,
        )
        self.s.questions.append(q)
        self.db.flush()
        if present:
            self._present(q)
        return q

    def _present(self, q: Question, prefix: str = "") -> None:
        self._state["current_question_id"] = q.id
        self.s.awaiting = "answer"
        self._say("question", prefix + q.prompt, {"question_id": q.id, "topic_id": q.topic_id, "phase": q.phase})

    def _grade(self, q: Question, answer: str) -> tuple[str, float, str, str | None, str]:
        rule = grade_by_rule(q, answer)
        if rule.decided:
            if rule.verdict == "correct":
                feedback = q.explanation
            else:
                why = f"{rule.misconception}\n\n" if rule.misconception else ""
                feedback = f"{why}{q.explanation}"
            return rule.verdict, rule.score, feedback, rule.misconception, "rule"
        topic = self._topics[q.topic_id]
        ev = self.llm.generate(
            system=prompts.tutor_system(self.student.grade),
            prompt=prompts.evaluate_prompt(
                describe_topic(topic),
                question=q.prompt + ("\nOptions: " + "; ".join(o["text"] for o in q.options) if q.options else ""),
                model_answer=q.answer,
                acceptable=q.acceptable_answers,
                student_answer=answer,
                grade=self.student.grade,
            ),
            schema=prompts.AnswerEvaluation,
            purpose="evaluate",
        )
        score = max(0.0, min(1.0, ev.score))
        verdict = ev.verdict
        if verdict == "correct":
            score = max(score, 0.99)
        return verdict, score, ev.feedback, ev.misconception, "ai"

    def _feedback(self, q: Question, verdict: str, feedback: str, graded_by: str) -> None:
        head = {
            "correct": "✅ **Correct!**",
            "partial": f"🟡 **Partly right.** A complete answer: **{self._display_answer(q)}**.",
            "incorrect": f"❌ **Not quite.** The answer is **{self._display_answer(q)}**.",
        }[verdict]
        body = feedback
        if graded_by == "ai" and verdict != "correct" and q.explanation:
            body = f"{feedback}\n\n**Solution:** {q.explanation}"
        self._say("feedback", f"{head}\n\n{body}".strip(), {"question_id": q.id, "verdict": verdict})

    @staticmethod
    def _display_answer(q: Question) -> str:
        if q.qtype == "mcq":
            for i, o in enumerate(q.options):
                if o["text"] == q.answer:
                    return f"{option_letter(i)}) {q.answer}"
        return q.answer

    # ------------------------------------------------------------------ helpers

    def _difficulty(self, topic_id: int, target: float) -> int:
        return knowledge.choose_difficulty(get_mastery(self.db, self.student.id, topic_id).ability, target)

    def _max_check_attempts(self) -> int:
        return self.cfg.check_questions_to_pass + 2 * self.cfg.max_reteach_per_topic + 2

    def _pick_practice_topic(self) -> Topic:
        counts: dict[int, int] = defaultdict(int)
        for q in self.s.questions:
            if q.phase == "practice":
                counts[q.topic_id] += 1
        last = next((q.topic_id for q in reversed(self.s.questions) if q.phase == "practice"), None)
        candidates = list(self.s.topic_ids)
        if len(candidates) > 1 and last in candidates:
            candidates.remove(last)
        return self._topics[
            min(candidates, key=lambda t: (get_mastery(self.db, self.student.id, t).p_known + 0.1 * counts[t], t))
        ]

    def _choose_strategy(self, used: list[str]) -> str:
        stats = (self.student.learning_profile or {}).get("strategy_stats", {})
        remaining = [s for s in prompts.STRATEGIES if s not in used] or list(prompts.STRATEGIES)

        def success_rate(s: str) -> float:  # Laplace-smoothed, so untried strategies get a fair chance
            v = stats.get(s, {})
            return (v.get("succeeded", 0) + 1) / (v.get("tried", 0) + 2)

        return max(remaining, key=lambda s: (success_rate(s), -list(prompts.STRATEGIES).index(s)))

    def _record_strategy(self, strategy: str, succeeded: bool) -> None:
        profile = dict(self.student.learning_profile or {})
        stats = {k: dict(v) for k, v in profile.get("strategy_stats", {}).items()}
        entry = stats.setdefault(strategy, {"tried": 0, "succeeded": 0})
        if succeeded:
            entry["succeeded"] += 1
        else:
            entry["tried"] += 1
        profile["strategy_stats"] = stats
        self.student.learning_profile = profile

    def _excerpt(self, topic: Topic, scale: float = 1.0) -> str:
        return topic_excerpt(self.db, topic, int(self.cfg.context_chars_per_topic * scale))

    def _previous_prompts(self) -> list[str]:
        return [q.prompt[:200] for q in self.s.questions]

    def _current_topic(self) -> Topic:
        idx = min(self._state.get("topic_index", 0), len(self.s.topic_ids) - 1)
        return self._topics[self.s.topic_ids[idx]]

    def _topic_state(self, topic_id: int) -> dict[str, Any]:
        return self._state["topics"][str(topic_id)]

    def _pending_question(self) -> Question | None:
        qid = self._state.get("current_question_id")
        return self.db.get(Question, qid) if qid else None

    def _say(self, kind: str, content: str, payload: dict[str, Any] | None = None) -> None:
        msg = SessionMessage(session_id=self.s.id, role="tutor", kind=kind, content=content, payload=payload or {})
        self.s.messages.append(msg)

    def _student_says(self, kind: str, content: str, payload: dict[str, Any] | None = None) -> None:
        msg = SessionMessage(session_id=self.s.id, role="student", kind=kind, content=content, payload=payload or {})
        self.s.messages.append(msg)

    def _save(self) -> None:
        if self._state.get("current_question_id") is None and self.s.awaiting == "answer":
            self.s.awaiting = "none"
        # JSON columns are only persisted on reassignment, so always hand SQLAlchemy a fresh copy.
        self.s.state = {**self._state, "topics": {k: dict(v) for k, v in self._state.get("topics", {}).items()}}
        self.db.flush()
