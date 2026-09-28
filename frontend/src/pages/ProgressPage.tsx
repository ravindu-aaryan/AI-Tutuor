import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Progress, type RevisionPlan } from "../api";
import { ErrorBanner, MasteryBar, Spinner, StatusPill, STRATEGY_NAMES, formatDate, pct } from "../components/ui";
import { useStudent } from "../student";

export default function ProgressPage() {
  const student = useStudent();
  const navigate = useNavigate();
  const [progress, setProgress] = useState<Progress | null>(null);
  const [plan, setPlan] = useState<RevisionPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    Promise.all([api.progress(student.id), api.revisionPlan(student.id)])
      .then(([p, r]) => {
        setProgress(p);
        setPlan(r);
      })
      .catch((e) => setError(e.message));
  }, [student.id]);

  const revise = async (topicIds: number[]) => {
    setStarting(true);
    try {
      const s = await api.startSession({ student_id: student.id, topic_ids: topicIds, mode: "revision" });
      navigate(`/session/${s.id}`);
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  };

  if (error) return <ErrorBanner error={error} />;
  if (!progress || !plan) return <Spinner label="Loading progress…" />;

  const { counts } = progress;
  const strategies = Object.entries(progress.teaching_strategies).sort((a, b) => (b[1].success_rate ?? 0) - (a[1].success_rate ?? 0));

  return (
    <>
      <h1>{student.name}'s progress</h1>
      {starting && <Spinner label="Preparing revision…" />}
      <section className="card">
        <div className="stats">
          <div><span className="stat">{counts.mastered}</span><span className="muted small">topics mastered</span></div>
          <div><span className="stat">{counts.developing}</span><span className="muted small">getting there</span></div>
          <div><span className="stat">{counts.needs_work}</span><span className="muted small">need work</span></div>
          <div><span className="stat">{progress.sessions_completed}</span><span className="muted small">sessions</span></div>
          <div><span className="stat">{pct(progress.average_test_score)}</span><span className="muted small">avg test</span></div>
        </div>
      </section>

      <div className="grid2">
        <section className="card">
          <h2>Revision plan</h2>
          {plan.due.length === 0 && plan.upcoming.length === 0 && <p className="muted">Nothing scheduled yet — finish a session first.</p>}
          {plan.due.length > 0 && (
            <>
              <h3>Due now</h3>
              <ul className="list">
                {plan.due.map((t) => (
                  <li key={t.topic_id}>
                    <div className="grow">
                      <strong>{t.title}</strong> <StatusPill status={t.status} />
                      <div className="small muted">{t.chapter}{t.misconceptions.length > 0 && ` · watch: ${t.misconceptions.join("; ")}`}</div>
                    </div>
                    <button className="secondary small" disabled={starting} onClick={() => revise([t.topic_id])}>Revise</button>
                  </li>
                ))}
              </ul>
            </>
          )}
          {plan.upcoming.length > 0 && (
            <>
              <h3>Coming up this week</h3>
              <ul className="list">
                {plan.upcoming.map((t) => (
                  <li key={t.topic_id}><span className="grow">{t.title}</span><span className="small muted">{formatDate(t.next_review_at)}</span></li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="card">
          <h2>How {student.name} learns best</h2>
          {strategies.length === 0 ? (
            <p className="muted">I'll learn which explanations work best as we go.</p>
          ) : (
            <ul className="list">
              {strategies.map(([k, v]) => (
                <li key={k}>
                  <span className="grow">{STRATEGY_NAMES[k] ?? k}</span>
                  <span className="small muted">worked {v.succeeded}/{v.tried} times</span>
                </li>
              ))}
            </ul>
          )}
          {progress.recent_test_scores.length > 0 && (
            <>
              <h3>Recent tests</h3>
              <div className="sparkbars">
                {[...progress.recent_test_scores].reverse().map((r) => (
                  <div key={r.session_id} title={`${formatDate(r.date)}: ${pct(r.score)}`} style={{ height: `${Math.max(4, r.score * 100)}%` }} />
                ))}
              </div>
            </>
          )}
        </section>
      </div>

      {progress.textbooks.map((b) => (
        <section key={b.textbook_id} className="card">
          <h2>{b.title}</h2>
          {b.chapters.map((c) => (
            <details key={c.chapter_id} open={c.average_mastery !== null}>
              <summary className="row between">
                <span>{c.title}</span>
                <span className="small muted">{c.average_mastery === null ? "not started" : `avg ${pct(c.average_mastery)}`}</span>
              </summary>
              <table className="table">
                <tbody>
                  {c.topics.map((t) => (
                    <tr key={t.topic_id}>
                      <td>{t.title}</td>
                      <td><StatusPill status={t.status} /></td>
                      <td style={{ minWidth: 140 }}><MasteryBar value={t.p_known} /></td>
                      <td className="small muted">{t.attempts ? `${pct(t.accuracy)} of ${t.attempts}` : ""}</td>
                      <td className="small muted">{t.next_review_at ? `review ${formatDate(t.next_review_at)}` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ))}
        </section>
      ))}
    </>
  );
}
