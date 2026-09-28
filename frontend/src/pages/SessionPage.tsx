import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Message, type PendingQuestion, type TutorSession } from "../api";
import ReportView from "../components/ReportView";
import { ErrorBanner, Markdown, MasteryBar, Spinner, StatusPill } from "../components/ui";

const PHASES: { key: string; label: string; match: string[] }[] = [
  { key: "learn", label: "Learn", match: ["teach", "check"] },
  { key: "practice", label: "Practice", match: ["practice"] },
  { key: "test", label: "Test", match: ["test_ready", "test"] },
  { key: "report", label: "Report", match: ["complete"] },
];

function Bubble({ m }: { m: Message }) {
  const verdict = typeof m.payload.verdict === "string" ? m.payload.verdict : "";
  if (m.role === "student") {
    return (
      <div className="bubble student">
        {m.kind === "answer" && <div className="small muted">Your answer</div>}
        {m.content}
      </div>
    );
  }
  return (
    <div className={`bubble tutor kind-${m.kind} ${verdict ? `verdict-${verdict}` : ""}`}>
      {m.kind === "question" && <div className="tag">Question</div>}
      <Markdown>{m.content}</Markdown>
    </div>
  );
}

function QuestionInput({ q, busy, onSubmit }: { q: PendingQuestion; busy: boolean; onSubmit: (a: string) => void }) {
  const [value, setValue] = useState("");
  useEffect(() => setValue(""), [q.id]);

  if (q.qtype === "mcq") {
    return (
      <div className="options">
        {q.options.map((o, i) => (
          <button key={i} className={value === o ? "option active" : "option"} disabled={busy} onClick={() => setValue(o)}>
            <span className="letter">{String.fromCharCode(65 + i)}</span>
            <span className="grow">{o}</span>
          </button>
        ))}
        <button disabled={busy || !value} onClick={() => onSubmit(value)}>Check my answer</button>
      </div>
    );
  }
  return (
    <form
      className="answer-row"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) onSubmit(value.trim());
      }}
    >
      {q.qtype === "short" ? (
        <textarea rows={2} value={value} onChange={(e) => setValue(e.target.value)} placeholder="Type your answer…" disabled={busy} autoFocus />
      ) : (
        <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Your answer (e.g. 12, 3/4, 2.5)" disabled={busy} autoFocus inputMode="text" />
      )}
      <button type="submit" disabled={busy || !value.trim()}>Check</button>
    </form>
  );
}

export default function SessionPage() {
  const { id } = useParams();
  const sessionId = Number(id);
  const [s, setS] = useState<TutorSession | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chat, setChat] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.session(sessionId).then(setS).catch((e) => setError(e.message));
  }, [sessionId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [s?.messages.length, busy]);

  const run = async (label: string, fn: () => Promise<TutorSession>) => {
    setBusy(label);
    setError(null);
    try {
      setS(await fn());
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(null);
    }
  };

  if (error && !s) return <ErrorBanner error={error} />;
  if (!s) return <Spinner label="Loading session…" />;

  const q = s.pending_question;
  const phaseIndex = PHASES.findIndex((p) => p.match.includes(s.phase));
  const isTest = s.phase === "test";

  return (
    <div className="session">
      <aside className="side">
        <ol className="steps">
          {PHASES.map((p, i) => (
            <li key={p.key} className={i < phaseIndex ? "done" : i === phaseIndex ? "current" : ""}>{p.label}</li>
          ))}
        </ol>
        <h3>Topics</h3>
        {s.topics.map((t) => (
          <div key={t.topic_id} className="side-topic">
            <div className="row between"><span>{t.title}</span><StatusPill status={t.status} /></div>
            <MasteryBar value={t.p_known} />
          </div>
        ))}
        {(s.phase === "practice" || s.phase === "test_ready") && (
          <p className="small muted">Practice: {s.practice_done}/{s.practice_total}</p>
        )}
        {(isTest || s.phase === "complete") && <p className="small muted">Test: {s.test_answered}/{s.test_total}</p>}
        <p className="small"><Link to="/">← Back home</Link></p>
      </aside>

      <section className="main">
        <div className="transcript">
          {s.messages.map((m) => <Bubble key={m.id} m={m} />)}
          {busy && <div className="bubble tutor typing"><Spinner label={busy} /></div>}
          <div ref={endRef} />
        </div>

        <ErrorBanner error={error} onClose={() => setError(null)} />

        {s.phase === "complete" && s.report && <ReportView report={s.report} />}

        {s.phase !== "complete" && (
          <div className="composer card">
            {q && s.awaiting === "answer" && (
              <>
                <QuestionInput q={q} busy={!!busy} onSubmit={(a) => run(isTest ? "Saving…" : "Checking your answer…", () => api.answer(s.id, q.id, a))} />
                <div className="row between mt">
                  <div className="row">
                    {q.hints_available && (
                      <button className="secondary small" disabled={!!busy} onClick={() => run("Getting a hint…", () => api.hint(s.id, q.id))}>
                        💡 Hint
                      </button>
                    )}
                    <span className="small muted">Difficulty {"★".repeat(q.difficulty)}{"☆".repeat(5 - q.difficulty)}</span>
                  </div>
                  {s.phase === "practice" && (
                    <button className="link small" disabled={!!busy} onClick={() => run("Preparing your test…", () => api.skipToTest(s.id))}>
                      Skip to the test →
                    </button>
                  )}
                </div>
              </>
            )}
            {s.awaiting === "advance" && (
              <button className="big" disabled={!!busy} onClick={() => run("Preparing your test…", () => api.advance(s.id))}>
                Start the test 📝
              </button>
            )}
            {s.awaiting === "none" && !q && (
              <button disabled={!!busy} onClick={() => run("Continuing…", () => api.advance(s.id))}>Continue</button>
            )}

            {!isTest && (
              <form
                className="chat-row"
                onSubmit={async (e) => {
                  e.preventDefault();
                  const text = chat.trim();
                  if (text && (await run("Thinking…", () => api.chat(s.id, text)))) setChat("");
                }}
              >
                <input
                  value={chat}
                  onChange={(e) => setChat(e.target.value)}
                  placeholder="Ask your tutor anything… (e.g. “I don't understand”, “why do we do that?”)"
                  disabled={!!busy}
                  maxLength={2000}
                />
                <button type="submit" className="secondary" disabled={!!busy || !chat.trim()}>Ask</button>
              </form>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
