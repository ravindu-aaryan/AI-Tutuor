"""Tutor persona, output schemas and prompt builders for every AI step of a tuition session."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------


def tutor_system(grade: int) -> str:
    return (
        "You are a warm, patient and highly experienced private home tutor working one-to-one with a "
        f"grade {grade} school student. You teach the student's own school textbook: follow the book's "
        "methods, notation, vocabulary and examples, and never contradict it. Only teach what the textbook "
        "excerpt supports; if something is not in the excerpt, keep to what a grade "
        f"{grade} student is expected to know.\n\n"
        "How you teach:\n"
        "- Speak directly to the student in short, clear sentences suited to their age. Be encouraging but honest.\n"
        "- Build from what they know, one idea at a time; use concrete examples before abstract rules.\n"
        "- When they make a mistake, work out *why* (the misconception), not just that it is wrong.\n"
        "- Never give away the answer to a question the student is currently working on.\n"
        "- Format with Markdown (short paragraphs, bullet lists, **bold** key terms). Write maths with plain "
        "characters and Unicode (×, ÷, ½, x², √, π) - no LaTeX."
    )


# ---------------------------------------------------------------------------
# Teaching strategies (used for re-teaching when the student doesn't understand)
# ---------------------------------------------------------------------------

STRATEGIES: dict[str, str] = {
    "step_by_step": "Break the idea into very small numbered steps and walk through each one slowly.",
    "real_world_analogy": "Explain using an analogy or situation from the student's everyday life.",
    "worked_example": "Teach through a fully worked example, narrating the thinking at every step, then a second similar one.",
    "visual_description": "Describe a picture, diagram, number line, table or physical model the student can imagine or draw.",
    "simpler_language": "Re-explain with much simpler words and shorter sentences, defining every key term.",
    "socratic": "Lead the student to the idea with a short chain of simple guiding questions and their answers.",
    "contrast_mistake": "Show the common wrong way next to the right way and explain exactly where they differ.",
}


# ---------------------------------------------------------------------------
# Output schemas
# ---------------------------------------------------------------------------


class OptionDraft(BaseModel):
    text: str
    misconception: str | None = Field(
        description="For a wrong option: the specific misunderstanding that leads a student to pick it. Null for the correct option."
    )


class QuestionDraft(BaseModel):
    qtype: Literal["mcq", "numeric", "short"] = Field(
        description="mcq = multiple choice (4 options); numeric = answer is a single number; short = a word/phrase/sentence"
    )
    prompt: str = Field(description="The question as shown to the student (Markdown)")
    options: list[OptionDraft] = Field(description="Exactly 4 options for mcq, empty list otherwise")
    answer: str = Field(description="mcq: exact text of the correct option; numeric: the number only; short: model answer")
    acceptable_answers: list[str] = Field(description="Other fully-correct phrasings (short answer); may be empty")
    tolerance: float | None = Field(description="numeric only: allowed absolute error, e.g. 0.01 when rounding; else null")
    explanation: str = Field(description="Step-by-step worked solution shown after the student answers")
    hint: str = Field(description="A nudge that helps without giving the answer away")
    difficulty: int = Field(description="1 (very easy) .. 5 (challenging) for this grade")


class TeachOutput(BaseModel):
    explanation: str = Field(description="The lesson itself (Markdown)")
    worked_example: str = Field(description="One worked example in the book's style (Markdown)")
    key_points: list[str] = Field(description="3-5 things to remember")
    question: QuestionDraft = Field(description="A check-for-understanding question on this topic")


class ReteachOutput(BaseModel):
    what_went_wrong: str = Field(description="Kind, specific explanation of the student's mistake, addressed to them")
    misconception: str | None = Field(description="Short label for the underlying misconception, if any")
    explanation: str = Field(description="The concept taught again using the requested strategy (Markdown)")
    question: QuestionDraft = Field(description="A new check question (different from earlier ones)")


class QuestionOnly(BaseModel):
    question: QuestionDraft


class TestPaper(BaseModel):
    questions: list[QuestionDraft]


class AnswerEvaluation(BaseModel):
    verdict: Literal["correct", "partial", "incorrect"]
    score: float = Field(description="0.0 .. 1.0")
    feedback: str = Field(description="Feedback to the student: what was right, what was missing or wrong")
    misconception: str | None = Field(description="Short label of the misconception revealed, if any")


class ChatReply(BaseModel):
    reply: str = Field(description="Your reply to the student (Markdown)")
    student_is_confused: bool = Field(
        description="True if the student is saying they don't understand the current topic and needs it re-taught"
    )


class SessionSummary(BaseModel):
    message_for_student: str = Field(description="2-4 encouraging sentences to the student about today's work")
    summary_for_parent: str = Field(description="A concise, factual paragraph for the parent")
    strengths: list[str]
    areas_to_improve: list[str]
    recommended_next_steps: list[str]


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

QUESTION_RULES = (
    "Question rules: match the requested difficulty for this grade; it must be answerable from the lesson and "
    "textbook; one unambiguous correct answer; prefer the style of exercises in the textbook. Vary the question "
    "type across a session. For mcq give exactly 4 plausible options where each wrong option reflects a real, "
    "named misconception."
)


def _grounding(topic_desc: str, learner_desc: str, excerpt: str) -> str:
    return (
        f"<topic>\n{topic_desc}\n</topic>\n\n<learner>\n{learner_desc}\n</learner>\n\n"
        f"<textbook_excerpt>\n{excerpt}\n</textbook_excerpt>"
    )


def _avoid(previous_questions: list[str]) -> str:
    if not previous_questions:
        return ""
    return "\n\nQuestions already asked in this session (do not repeat them):\n" + "\n".join(
        f"- {q}" for q in previous_questions[-10:]
    )


def teach_prompt(topic_desc: str, learner_desc: str, excerpt: str, *, recap: bool, difficulty: int, previous: list[str]) -> str:
    if recap:
        task = (
            "The student already knows this topic fairly well. Give a brisk recap of the essentials (a short "
            "explanation and one worked example), then check understanding."
        )
    else:
        task = (
            "Teach this topic now as a private tutor would after school: connect to what they covered in class, "
            "explain the concept clearly, show a worked example, and list the key points. Then ask one "
            "check-for-understanding question."
        )
    return (
        f"{_grounding(topic_desc, learner_desc, excerpt)}\n\n{task}\n"
        f"The question should be difficulty {difficulty}/5.\n{QUESTION_RULES}{_avoid(previous)}"
    )


def reteach_prompt(
    topic_desc: str,
    learner_desc: str,
    excerpt: str,
    *,
    question: str,
    correct_answer: str,
    student_answer: str,
    strategy: str,
    difficulty: int,
    previous: list[str],
    reason: str = "answered a question incorrectly",
) -> str:
    wrong = (
        f"The student {reason}.\nQuestion: {question}\nCorrect answer: {correct_answer}\n"
        f"Student's answer: {student_answer}\n"
        if question
        else f"The student {reason}.\n"
    )
    return (
        f"{_grounding(topic_desc, learner_desc, excerpt)}\n\n{wrong}\n"
        "Diagnose the misunderstanding, then teach the concept again in a DIFFERENT way from before, using this "
        f"strategy: {STRATEGIES[strategy]}\n"
        f"Then ask a new check question at difficulty {difficulty}/5.\n{QUESTION_RULES}{_avoid(previous)}"
    )


def practice_prompt(topic_desc: str, learner_desc: str, excerpt: str, *, difficulty: int, previous: list[str]) -> str:
    return (
        f"{_grounding(topic_desc, learner_desc, excerpt)}\n\n"
        f"Write one practice question on this topic at difficulty {difficulty}/5.\n{QUESTION_RULES}{_avoid(previous)}"
    )


def test_prompt(sections: list[tuple[str, str, list[int]]], learner_desc: str, previous: list[str]) -> str:
    """``sections``: (topic description + excerpt, topic title, difficulties) per topic."""
    parts = []
    total = 0
    for block, title, levels in sections:
        total += len(levels)
        parts.append(
            f"{block}\n\nFor '{title}' write {len(levels)} question(s) with difficulties {', '.join(map(str, levels))}."
        )
    return (
        f"<learner>\n{learner_desc}\n</learner>\n\n"
        + "\n\n---\n\n".join(parts)
        + f"\n\nWrite a short end-of-session test of exactly {total} questions, grouped in the order above. "
        "Test the learning objectives, not trivia; mix question types.\n"
        f"{QUESTION_RULES}{_avoid(previous)}"
    )


def evaluate_prompt(topic_desc: str, *, question: str, model_answer: str, acceptable: list[str], student_answer: str, grade: int) -> str:
    alt = ("\nOther acceptable answers: " + "; ".join(acceptable)) if acceptable else ""
    return (
        f"<topic>\n{topic_desc}\n</topic>\n\nGrade this grade-{grade} student's answer.\n"
        f"Question: {question}\nModel answer: {model_answer}{alt}\nStudent's answer: {student_answer}\n\n"
        "Judge meaning, not wording or spelling. 'correct' = fully right (score 1); 'partial' = right idea but "
        "incomplete or with a small error (score 0.3-0.8); 'incorrect' = wrong or missing the key idea (score 0-0.2). "
        "Write the feedback to the student, and name the misconception if the answer reveals one."
    )


def chat_prompt(topic_desc: str, learner_desc: str, excerpt: str, *, transcript: str, pending_question: str | None, message: str) -> str:
    pending = (
        f"\n\nThe student is currently working on this question - do NOT reveal its answer, "
        f"but you may give a gentle nudge:\n{pending_question}"
        if pending_question
        else ""
    )
    return (
        f"{_grounding(topic_desc, learner_desc, excerpt)}\n\n<recent_conversation>\n{transcript}\n</recent_conversation>"
        f"{pending}\n\nThe student says: \"{message}\"\n\n"
        "Reply as their tutor. If they ask something off-topic, answer briefly and kindly steer back to the lesson."
    )


def summary_prompt(learner_desc: str, facts: str) -> str:
    return (
        f"<learner>\n{learner_desc}\n</learner>\n\n<session_results>\n{facts}\n</session_results>\n\n"
        "Write the end-of-session report. Be specific - refer to the actual topics and mistakes."
    )
