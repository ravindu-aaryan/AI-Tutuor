import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type RevisionPlan, type SessionListItem, type Textbook } from "../api";
import { ErrorBanner, MasteryBar, Spinner, StatusPill, formatDate, pct } from "../components/ui";
import { useStudent } from "../student";

export default function HomePage() {
  const student = useStudent();
  const navigate = useNavigate();
  const [plan, setPlan] = useState<RevisionPlan | null>(null);
  const [sessions, setSessions] = useState<SessionListItem[] | null>(null);
  const [books, setBooks] = useState<Textbook[] | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPlan(null);
    setSessions(null);
    Promise.all([api.revisionPlan(student.id), api.sessions(student.id), api.textbooks(student.id)])
      .then(([p, s, b]) => {
        setPlan(p);
        setSessions(s);
        setBooks(b);
      })
      .catch((e) => setError(e.message));
  }, [student.id]);

  const startRevision = async (topicIds: number[]) => {
    setStarting(true);
    setError(null);
    try {
      const s = await api.startSession({ student_id: student.id, topic_ids: topicIds, mode: "revision" });
      navigate(`/session/${s.id}`);
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  };

  const unfinished = sessions?.find((s) => s.phase !== "complete");
  const hasBook = books?.some((b) => b.status === "ready");

  return (
    <>
      <h1>Hi {student.name}! 👋</h1>
      <ErrorBanner error={error} onClose={() => setError(null)} />
      {starting && <Spinner label="Your tutor is getting the revision ready…" />}

      <div className="grid2">
        <section className="card hero">
          <h2>What did you learn at school today?</h2>
          {books === null ? (
            <Spinner />
          ) : hasBook ? (
            <>
              <p className="muted">Pick the chapter and topics from your textbook and I'll go over them with you.</p>
              <Link className="button" to="/lesson">Start today's lesson</Link>
            </>
          ) : (
            <>
              <p className="muted">First, add your school textbook so I know what you're studying.</p>
              <Link className="button" to="/library">Add a textbook</Link>
            </>
          )}
          {unfinished && (
            <p className="mt">
              <Link to={`/session/${unfinished.id}`}>↩ Continue your unfinished session ({unfinished.topic_titles.join(", ")})</Link>
            </p>
          )}
        </section>

        <section className="card">
          <h2>Revision due</h2>
          {plan === null ? (
            <Spinner />
          ) : plan.due.length === 0 ? (
            <p className="muted">Nothing to revise right now. 🎉{plan.upcoming.length > 0 && ` Next review: ${formatDate(plan.upcoming[0].next_review_at)}.`}</p>
          ) : (
            <>
              <ul className="list">
                {plan.due.slice(0, 5).map((t) => (
                  <li key={t.topic_id}>
                    <div className="grow">
                      <strong>{t.title}</strong>
                      <div className="small muted">{t.chapter}</div>
                      <MasteryBar value={t.p_known} />
                    </div>
                    <button className="secondary small" disabled={starting} onClick={() => startRevision([t.topic_id])}>
                      Revise
                    </button>
                  </li>
                ))}
              </ul>
              <button disabled={starting} onClick={() => startRevision(plan.suggested_topic_ids)}>
                Revise the top {plan.suggested_topic_ids.length} together
              </button>
            </>
          )}
        </section>
      </div>

      <section className="card">
        <h2>Recent sessions</h2>
        {sessions === null ? (
          <Spinner />
        ) : sessions.length === 0 ? (
          <p className="muted">No sessions yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Date</th><th>Topics</th><th>Type</th><th>Status</th><th>Test</th><th /></tr>
            </thead>
            <tbody>
              {sessions.slice(0, 10).map((s) => (
                <tr key={s.id}>
                  <td>{formatDate(s.started_at)}</td>
                  <td>{s.topic_titles.join(", ")}</td>
                  <td>{s.mode === "revision" ? "Revision" : "Lesson"}</td>
                  <td>{s.phase === "complete" ? <StatusPill status="passed" /> : <StatusPill status="learning" />}</td>
                  <td>{pct(s.test_score)}</td>
                  <td><Link to={`/session/${s.id}`}>{s.phase === "complete" ? "Report" : "Continue"}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
