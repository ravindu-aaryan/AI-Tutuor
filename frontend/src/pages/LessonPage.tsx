import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Textbook, type TextbookDetail } from "../api";
import { ErrorBanner, Spinner } from "../components/ui";
import { useStudent } from "../student";

export default function LessonPage() {
  const student = useStudent();
  const navigate = useNavigate();
  const [books, setBooks] = useState<Textbook[] | null>(null);
  const [book, setBook] = useState<TextbookDetail | null>(null);
  const [chapterId, setChapterId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [notes, setNotes] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.textbooks(student.id)
      .then((all) => {
        const ready = all.filter((b) => b.status === "ready");
        setBooks(ready);
        if (ready.length === 1) pickBook(ready[0].id);
      })
      .catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [student.id]);

  const pickBook = (id: number) => {
    setBook(null);
    setChapterId(null);
    setSelected(new Set());
    api.textbook(id).then(setBook).catch((e) => setError(e.message));
  };

  const chapter = useMemo(() => book?.chapters.find((c) => c.id === chapterId) ?? null, [book, chapterId]);

  const pickChapter = (id: number) => {
    setChapterId(id);
    const ch = book?.chapters.find((c) => c.id === id);
    setSelected(new Set(ch?.topics.map((t) => t.id) ?? []));
  };

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const start = async () => {
    if (!chapter) return;
    setStarting(true);
    setError(null);
    try {
      const topicIds = chapter.topics.filter((t) => selected.has(t.id)).map((t) => t.id);
      const lesson = await api.createLesson({ student_id: student.id, chapter_id: chapter.id, topic_ids: topicIds, notes: notes.trim() || undefined });
      const session = await api.startSession({ student_id: student.id, lesson_id: lesson.id });
      navigate(`/session/${session.id}`);
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  };

  if (books === null) return <Spinner label="Loading your textbooks…" />;
  if (books.length === 0)
    return (
      <div className="card">
        <h2>No textbook ready yet</h2>
        <p className="muted">Add your school textbook first so I know what you're learning.</p>
        <Link className="button" to="/library">Add a textbook</Link>
      </div>
    );

  return (
    <>
      <h1>Today's lesson</h1>
      <p className="muted">Tell me what your teacher covered today and I'll go through it with you.</p>
      <ErrorBanner error={error} onClose={() => setError(null)} />

      <section className="card">
        <h2>1. Which book?</h2>
        <div className="chips">
          {books.map((b) => (
            <button key={b.id} className={book?.id === b.id ? "chip active" : "chip"} onClick={() => pickBook(b.id)}>
              {b.title}
            </button>
          ))}
        </div>
      </section>

      {book && (
        <section className="card">
          <h2>2. Which chapter?</h2>
          <select value={chapterId ?? ""} onChange={(e) => pickChapter(Number(e.target.value))}>
            <option value="" disabled>Choose a chapter…</option>
            {book.chapters.map((c) => (
              <option key={c.id} value={c.id}>{c.title}</option>
            ))}
          </select>
        </section>
      )}

      {chapter && (
        <section className="card">
          <h2>3. Which topics were taught today?</h2>
          <div className="stack">
            {chapter.topics.map((t) => (
              <label key={t.id} className="check">
                <input type="checkbox" checked={selected.has(t.id)} onChange={() => toggle(t.id)} />
                <span>
                  <strong>{t.title}</strong>
                  {t.summary && <span className="small muted"> — {t.summary}</span>}
                </span>
              </label>
            ))}
          </div>
          <label className="mt">
            Anything else about today's class? <span className="muted small">(optional)</span>
            <textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. We did exercise 3B. I got confused when the denominators were different. Homework is page 42."
            />
          </label>
          <button disabled={selected.size === 0 || starting} onClick={start}>
            {starting ? "Preparing your lesson…" : `Start tuition (${selected.size} topic${selected.size === 1 ? "" : "s"})`}
          </button>
          {starting && <Spinner label="Your tutor is reading the chapter and planning the lesson…" />}
        </section>
      )}
    </>
  );
}
