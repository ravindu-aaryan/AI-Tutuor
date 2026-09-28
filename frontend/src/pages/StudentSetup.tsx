import { useState } from "react";
import { api, type Student } from "../api";
import { ErrorBanner } from "../components/ui";

interface Props {
  students: Student[];
  onPick: (id: number) => void;
  onCreated: (s: Student) => void;
  onCancel?: () => void;
}

export default function StudentSetup({ students, onPick, onCreated, onCancel }: Props) {
  const [name, setName] = useState("");
  const [grade, setGrade] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onCreated(await api.createStudent(name.trim(), grade));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page narrow">
      <h1>🦉 Welcome to My Tutor</h1>
      <p className="muted">
        A personal tutor that learns your school textbook, goes over what you did in class each day, and helps you
        practise until you've really got it.
      </p>
      {students.length > 0 && (
        <section className="card">
          <h2>Who's learning today?</h2>
          <div className="stack">
            {students.map((s) => (
              <button key={s.id} className="secondary" onClick={() => onPick(s.id)}>
                {s.name} · Grade {s.grade}
              </button>
            ))}
          </div>
        </section>
      )}
      <form className="card" onSubmit={submit}>
        <h2>Add a student</h2>
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
        </label>
        <label>
          School grade
          <select value={grade} onChange={(e) => setGrade(Number(e.target.value))}>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((g) => (
              <option key={g} value={g}>
                Grade {g}
              </option>
            ))}
          </select>
        </label>
        <ErrorBanner error={error} />
        <div className="row">
          <button type="submit" disabled={busy || !name.trim()}>
            {busy ? "Saving…" : "Start learning"}
          </button>
          {onCancel && (
            <button type="button" className="secondary" onClick={onCancel}>
              Cancel
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
