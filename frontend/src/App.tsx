import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, type Health, type Student } from "./api";
import { ErrorBanner, Spinner } from "./components/ui";
import { StudentContext } from "./student";
import HomePage from "./pages/HomePage";
import LibraryPage from "./pages/LibraryPage";
import TextbookPage from "./pages/TextbookPage";
import LessonPage from "./pages/LessonPage";
import SessionPage from "./pages/SessionPage";
import ProgressPage from "./pages/ProgressPage";
import StudentSetup from "./pages/StudentSetup";

const STORAGE_KEY = "tutor.studentId";

function readStoredId(): number | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

export default function App() {
  const [students, setStudents] = useState<Student[] | null>(null);
  const [studentId, setStudentId] = useState<number | null>(readStoredId);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    api.students().then(setStudents).catch((e) => setError(e.message));
    api.health().then(setHealth).catch(() => undefined);
  }, []);

  const choose = (id: number) => {
    setStudentId(id);
    setAdding(false);
    try {
      localStorage.setItem(STORAGE_KEY, String(id));
    } catch {
      /* storage unavailable */
    }
  };

  if (error) return <div className="page"><ErrorBanner error={error} /></div>;
  if (!students) return <div className="page"><Spinner label="Loading…" /></div>;

  const student = students.find((s) => s.id === studentId) ?? null;
  if (!student || adding) {
    return (
      <StudentSetup
        students={students}
        onCancel={student ? () => setAdding(false) : undefined}
        onPick={choose}
        onCreated={(s) => {
          setStudents([...students, s]);
          choose(s.id);
        }}
      />
    );
  }

  return (
    <StudentContext.Provider value={student}>
      <header className="topbar">
        <div className="brand">🦉 My Tutor</div>
        <nav>
          <NavLink to="/" end>Home</NavLink>
          <NavLink to="/lesson">Today's lesson</NavLink>
          <NavLink to="/library">Textbooks</NavLink>
          <NavLink to="/progress">Progress</NavLink>
        </nav>
        <div className="who">
          <select
            value={student.id}
            onChange={(e) => (e.target.value === "new" ? setAdding(true) : choose(Number(e.target.value)))}
            aria-label="Student"
          >
            {students.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} · Grade {s.grade}
              </option>
            ))}
            <option value="new">+ Add student…</option>
          </select>
        </div>
      </header>
      {health && !health.llm.configured && (
        <div className="page">
          <ErrorBanner error="The AI tutor isn't connected: set ANTHROPIC_API_KEY on the server and restart it. Textbooks can't be analysed and lessons can't start until then." />
        </div>
      )}
      <main className="page">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/library/:id" element={<TextbookPage />} />
          <Route path="/lesson" element={<LessonPage />} />
          <Route path="/session/:id" element={<SessionPage />} />
          <Route path="/progress" element={<ProgressPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </StudentContext.Provider>
  );
}
