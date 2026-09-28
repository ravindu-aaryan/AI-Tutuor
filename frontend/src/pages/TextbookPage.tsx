import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type TextbookDetail } from "../api";
import { ErrorBanner, Spinner } from "../components/ui";

export default function TextbookPage() {
  const { id } = useParams();
  const [book, setBook] = useState<TextbookDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    api.textbook(Number(id)).then(setBook).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <ErrorBanner error={error} />;
  if (!book) return <Spinner label="Loading…" />;

  return (
    <>
      <p><Link to="/library">← Textbooks</Link></p>
      <h1>{book.title}</h1>
      <p className="muted">
        {[book.subject, book.grade && `Grade ${book.grade}`, `${book.page_count} pages`, `${book.chapters.length} chapters`]
          .filter(Boolean)
          .join(" · ")}
      </p>
      {book.chapters.map((c) => (
        <section key={c.id} className="card">
          <button className="chapter-head" onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id}>
            <span>{c.title}</span>
            <span className="muted small">pp. {c.start_page}–{c.end_page} · {c.topics.length} topics {open === c.id ? "▲" : "▼"}</span>
          </button>
          {open === c.id && (
            <>
              {c.summary && <p className="muted">{c.summary}</p>}
              {c.topics.map((t) => (
                <div key={t.id} className="topic">
                  <h3>{t.order}. {t.title} <span className="muted small">pp. {t.start_page}–{t.end_page}</span></h3>
                  {t.summary && <p>{t.summary}</p>}
                  {t.learning_objectives.length > 0 && (
                    <ul>{t.learning_objectives.map((o, i) => <li key={i}>{o}</li>)}</ul>
                  )}
                  {t.key_terms.length > 0 && <p className="small"><strong>Key terms:</strong> {t.key_terms.join(", ")}</p>}
                </div>
              ))}
            </>
          )}
        </section>
      ))}
    </>
  );
}
