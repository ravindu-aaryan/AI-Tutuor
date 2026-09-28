import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Textbook } from "../api";
import { ErrorBanner, Spinner } from "../components/ui";
import { useStudent } from "../student";

export function TextbookStatus({ book }: { book: Textbook }) {
  if (book.status === "ready") return <span className="pill pill-passed">Ready</span>;
  if (book.status === "failed") return <span className="pill pill-needs_work">Failed</span>;
  return (
    <div className="grow">
      <div className="bar"><div className="bar-fill bar-mid" style={{ width: `${Math.round(book.progress * 100)}%` }} /></div>
      <div className="small muted">{book.status_detail}</div>
    </div>
  );
}

export default function LibraryPage() {
  const student = useStudent();
  const [books, setBooks] = useState<Textbook[] | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api.textbooks(student.id).then(setBooks).catch((e) => setError(e.message)), [student.id]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while anything is being processed.
  const busy = books?.some((b) => b.status === "uploaded" || b.status === "processing");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [busy, load]);

  const upload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadTextbook(student.id, file, title.trim() || undefined, subject.trim() || undefined);
      setFile(null);
      setTitle("");
      setSubject("");
      if (fileInput.current) fileInput.current.value = "";
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <h1>Textbooks</h1>
      <ErrorBanner error={error} onClose={() => setError(null)} />
      <form className="card" onSubmit={upload}>
        <h2>Add a school textbook</h2>
        <p className="muted small">
          Upload the PDF of the textbook (with selectable text) or a .txt/.md file. I'll read it and work out the chapters,
          topics and learning goals. Big books take a few minutes.
        </p>
        <label>
          File
          <input ref={fileInput} type="file" accept=".pdf,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
        </label>
        <div className="grid2">
          <label>
            Title <span className="muted small">(optional)</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Worked out from the book" />
          </label>
          <label>
            Subject <span className="muted small">(optional)</span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. Mathematics" />
          </label>
        </div>
        <button type="submit" disabled={!file || uploading}>{uploading ? "Uploading…" : "Upload & analyse"}</button>
      </form>

      <section className="card">
        <h2>{student.name}'s books</h2>
        {books === null ? (
          <Spinner />
        ) : books.length === 0 ? (
          <p className="muted">No textbooks yet.</p>
        ) : (
          <ul className="list">
            {books.map((b) => (
              <li key={b.id}>
                <div className="grow">
                  {b.status === "ready" ? <Link to={`/library/${b.id}`}><strong>{b.title}</strong></Link> : <strong>{b.title}</strong>}
                  <div className="small muted">
                    {[b.subject, b.grade && `Grade ${b.grade}`, b.page_count && `${b.page_count} pages`].filter(Boolean).join(" · ") || b.filename}
                  </div>
                  {b.status === "failed" && <div className="small error-text">{b.status_detail}</div>}
                </div>
                <TextbookStatus book={b} />
                {b.status === "failed" && (
                  <button className="secondary small" onClick={() => act(() => api.reprocessTextbook(b.id))}>Retry</button>
                )}
                {b.status !== "processing" && (
                  <button
                    className="link danger small"
                    onClick={() => confirm(`Delete "${b.title}"? Progress on its topics will be lost.`) && act(() => api.deleteTextbook(b.id))}
                  >
                    Delete
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
