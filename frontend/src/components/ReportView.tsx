import type { Report } from "../api";
import { Markdown, MasteryBar, StatusPill, STRATEGY_NAMES, formatDate, pct } from "./ui";

export default function ReportView({ report }: { report: Report }) {
  const { overall, topics, test_review, ai } = report;
  return (
    <div className="report">
      <section className="card hero">
        <h2>🎉 Session complete</h2>
        <Markdown>{ai.message_for_student}</Markdown>
        <div className="stats">
          <div><span className="stat">{pct(overall.test_score)}</span><span className="muted small">test score</span></div>
          <div><span className="stat">{overall.correct}/{overall.questions}</span><span className="muted small">answers right</span></div>
          <div><span className="stat">{overall.hints_used}</span><span className="muted small">hints used</span></div>
          <div><span className="stat">{overall.minutes}m</span><span className="muted small">time</span></div>
        </div>
      </section>

      <section className="card">
        <h2>Topics</h2>
        <table className="table">
          <thead>
            <tr><th>Topic</th><th>Mastery (before → after)</th><th>Test</th><th>Next revision</th></tr>
          </thead>
          <tbody>
            {topics.map((t) => (
              <tr key={t.topic_id}>
                <td>
                  <strong>{t.title}</strong> <StatusPill status={t.mastery_label} />
                  {t.misconceptions.length > 0 && (
                    <div className="small muted">Watch out for: {t.misconceptions.join("; ")}</div>
                  )}
                  {t.strategies_used.length > 0 && (
                    <div className="small muted">Re-explained with: {t.strategies_used.map((s) => STRATEGY_NAMES[s] ?? s).join(", ")}</div>
                  )}
                </td>
                <td style={{ minWidth: 160 }}><MasteryBar value={t.mastery_end} from={t.mastery_start} /></td>
                <td>{pct(t.test_score)}</td>
                <td>{formatDate(t.next_review_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {test_review.length > 0 && (
        <section className="card">
          <h2>Test review</h2>
          {test_review.map((r, i) => (
            <details key={i} className={`review review-${r.verdict}`} open={r.verdict !== "correct"}>
              <summary>
                {r.verdict === "correct" ? "✅" : r.verdict === "partial" ? "🟡" : "❌"} Question {i + 1} · <span className="muted">{r.topic}</span>
              </summary>
              <Markdown>{r.question}</Markdown>
              <p><strong>Your answer:</strong> {r.your_answer}</p>
              {r.verdict !== "correct" && <p><strong>Correct answer:</strong> {r.correct_answer}</p>}
              <Markdown>{r.explanation}</Markdown>
            </details>
          ))}
        </section>
      )}

      <section className="card">
        <h2>For parents</h2>
        <Markdown>{ai.summary_for_parent}</Markdown>
        <div className="grid3">
          <div><h3>Strengths</h3><ul>{ai.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul></div>
          <div><h3>To improve</h3><ul>{ai.areas_to_improve.map((s, i) => <li key={i}>{s}</li>)}</ul></div>
          <div><h3>Next steps</h3><ul>{ai.recommended_next_steps.map((s, i) => <li key={i}>{s}</li>)}</ul></div>
        </div>
      </section>
    </div>
  );
}
