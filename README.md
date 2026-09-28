# AI Personal Tutor

A personal home tutor for a school child. It reads the child's **own school textbook**, is told **what was
taught in class today**, and then teaches, questions, re-teaches, practises, tests and plans revision. It uses
the child's learning history to decide all of this.

```
SCHOOL TEXTBOOK + TODAY'S LESSON + CHILD'S LEARNING HISTORY → PERSONALISED AI TUTOR
```

## Milestone 1 (this slice): working end to end

UPLOAD TEXTBOOK → PROCESS → IDENTIFY CURRICULUM → SELECT TODAY'S LESSON → START TUITION → TEACH → ASK →
EVALUATE → ADAPT → PRACTICE → TEST → SAVE PROGRESS → LEARNING REPORT

| Step | How it works |
|---|---|
| Upload | PDF (with selectable text), `.txt` or `.md`, up to 100 MB. Processing runs in the background and shows progress. |
| Process | Text is extracted page by page and stored. Every explanation and question is grounded in these pages. |
| Curriculum | Chapters are found from the PDF outline first, then heading patterns ("Chapter 3", "Unit IV"), then Claude segmentation as a fallback. Claude breaks each chapter into teachable **topics** with learning objectives, key terms, prerequisites and page ranges. Long chapters are analysed in windows, never silently truncated. |
| Today's lesson | The child or parent picks the chapter and topics covered in class and can add notes ("we did exercise 3B, I got confused when…"). The notes go into every teaching prompt. |
| Teach | A lesson grounded in the textbook pages, with a worked example and key points. If the topic is already mastered, it gives a short recap instead. |
| Ask / evaluate | MCQ, numeric and short-answer questions. MCQ and numeric answers (fractions, mixed numbers, units) and exact short answers are marked by deterministic rules. Open answers are marked by Claude with partial credit and a named misconception. Each wrong MCQ option carries its own misconception. |
| Adapt | A wrong answer leads to a diagnosis, then the topic is **re-taught with a different strategy** (step by step, analogy, visual, worked example, simpler language, Socratic, right-vs-wrong). Strategies are picked by how well each has worked *for this child*. After 3 re-teaches the topic is flagged for follow-up instead of looping. "I don't understand" in chat also triggers a re-teach. |
| Difficulty | Each child/topic pair has an ability rating on a logit scale. The next question's difficulty (1–5) is chosen to hit about 80% success while learning, 70% in practice and 65% in the test. |
| Practice | Adaptive questions on the weakest topic first, with hints available (a hint reduces mastery credit). |
| Test | Short mixed test with no hints and no help in chat. Feedback comes at the end. |
| Save progress | Bayesian Knowledge Tracing per topic, misconceptions, attempts, and SM-2 spaced-repetition review dates. |
| Report | Mastery before and after, test review with worked solutions, strengths, areas to improve, next steps, a note for parents and next revision dates. |
| Revision | The dashboard and Progress page list due and weak topics. One click starts a revision session. |

## Architecture

```
backend/   Python 3.11+, FastAPI, SQLAlchemy (SQLite), Anthropic SDK
  app/ingestion/  extract.py (PDF/text) · structure.py (outline/headings) · curriculum.py (Claude) · pipeline.py
  app/tutor/      engine.py (session state machine) · knowledge.py (BKT, ability, SM-2) · grading.py
                  prompts.py (persona, strategies, schemas) · context.py (grounding) · report.py · progress.py
  app/llm/        base.py (LLMClient interface) · anthropic_client.py (Claude, structured outputs)
  app/api/        REST routes: students, textbooks, lessons, sessions
  tests/          pytest suite; tests/fakes.py is a scripted LLM used ONLY by tests
frontend/  React + TypeScript + Vite
```

* All AI calls go through `LLMClient.generate(system, prompt, schema)`, which returns validated Pydantic objects
  using Claude structured outputs (`claude-opus-5`, adaptive thinking, server-side refusal fallback).
* Each tutoring action runs in one transaction. If the AI fails, the step is rolled back and the child can retry.
  The session is never left half-advanced.

## Running it

Requires Python 3.11+, Node 20+ and an Anthropic API key.

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export ANTHROPIC_API_KEY=sk-ant-...        # or: ant auth login
uvicorn app.main:app --reload --port 8000

# frontend (dev, proxies /api to :8000)
cd frontend
npm install
npm run dev                                 # http://localhost:5173
```

For a single-server setup, run `npm run build` in `frontend/`. FastAPI then serves `frontend/dist` at
http://localhost:8000.

Settings (env vars, see `backend/.env.example`): `TUTOR_LLM_MODEL`, `TUTOR_LLM_EFFORT`,
`TUTOR_PRACTICE_QUESTIONS`, `TUTOR_TEST_QUESTIONS`, `TUTOR_CHECK_QUESTIONS_TO_PASS`,
`TUTOR_MAX_RETEACH_PER_TOPIC`, `TUTOR_DATA_DIR`, …

Without an API key, the app still runs and stores uploads. The UI shows a banner, textbook processing fails with
a clear message (retry once a key is set), and starting a session returns 503.

## Tests

```bash
cd backend && pytest          # learner model, grading, ingestion, Claude adapter (mocked HTTP), full API flow
cd frontend && npm run typecheck && npm run build
```

## Known limitations (documented, not faked)

* **Scanned (image-only) textbooks** are detected and rejected with an explanation. OCR is not implemented yet.
* Diagrams and images in the book are not read. Only text is used.
* No authentication. It is a single-household app, and anyone with access can pick any student profile.
* AI steps are synchronous requests (a few seconds each) and the UI shows a "thinking" indicator. Streaming is a
  future improvement.
* SQLite with `create_all`. There are no migrations yet; add Alembic before the schema changes.
