import { useEffect, useState } from "react";
import { api, type AISettings, type AIStatus, type Provider } from "../api";
import { ErrorBanner, Spinner } from "../components/ui";

const OPTIONS: { id: Provider; title: string; cost: string; blurb: string; good: string[]; limits: string[] }[] = [
  {
    id: "rules",
    title: "🔌 Offline tutor (no AI)",
    cost: "Free · works without internet",
    blurb: "Teaches straight from the textbook using rules. Nothing leaves this computer.",
    good: [
      "Lessons built from the book's own sentences, key words and worked examples",
      "Maths: makes new calculations like the book's, solves them step by step, spots classic mistakes",
      "Fill-in-the-blank, multiple-choice, true/false and definition questions",
      "Adaptive difficulty, mastery tracking, tests, reports and revision plans",
    ],
    limits: ["Can't write new explanations or analogies", "Chat only quotes the textbook", "Written answers are checked by key words"],
  },
  {
    id: "local",
    title: "💻 Local AI (Ollama)",
    cost: "Free · runs on this computer",
    blurb: "An open-source model runs on your own PC, so the tutor can explain, re-teach and chat like a person.",
    good: ["Everything the AI tutor does, at no per-use cost", "Private: nothing is sent to the internet"],
    limits: [
      "Needs a reasonably powerful computer (16 GB RAM; a graphics card helps)",
      "Slower, and less accurate than Claude",
    ],
  },
  {
    id: "claude",
    title: "✨ Claude (Anthropic API)",
    cost: "Paid · about $0.40–$1 per session",
    blurb: "The best explanations, questions and marking. Needs an Anthropic API key on the server.",
    good: ["Highest quality teaching and marking", "Best at reading messy textbooks into topics"],
    limits: ["Costs money per use", "Needs internet"],
  },
];

export default function SettingsPage({ onSaved }: { onSaved: (p: Provider) => void }) {
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [form, setForm] = useState<AISettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api.aiSettings()
      .then((s) => {
        setStatus(s);
        setForm(s.settings);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const save = async (next: AISettings) => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const s = await api.saveAiSettings(next);
      setStatus(s);
      setForm(s.settings);
      onSaved(s.settings.provider);
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (error && !status) return <ErrorBanner error={error} />;
  if (!status || !form) return <Spinner label="Loading settings…" />;

  return (
    <>
      <h1>Settings</h1>
      <p className="muted">Choose how the tutor thinks. You can switch at any time; it applies from the next step of a lesson.</p>
      <ErrorBanner error={error} onClose={() => setError(null)} />

      <div className="modes">
        {OPTIONS.map((o) => {
          const st = status.providers[o.id];
          const active = form.provider === o.id;
          return (
            <label key={o.id} className={`card mode-card ${active ? "active" : ""}`}>
              <div className="row between">
                <span className="row">
                  <input type="radio" name="provider" checked={active} onChange={() => setForm({ ...form, provider: o.id })} />
                  <strong>{o.title}</strong>
                </span>
                <span className={`pill ${st.available ? "pill-passed" : "pill-needs_work"}`}>{st.available ? "Ready" : "Not set up"}</span>
              </div>
              <div className="small"><strong>{o.cost}</strong></div>
              <p className="small muted">{o.blurb}</p>
              <ul className="small">
                {o.good.map((g) => <li key={g}>{g}</li>)}
                {o.limits.map((l) => <li key={l} className="muted">⚠︎ {l}</li>)}
              </ul>
              {!st.available && <div className="small error-text">{st.detail}</div>}
            </label>
          );
        })}
      </div>

      {form.provider === "local" && (
        <section className="card">
          <h2>Local AI setup</h2>
          <ol className="small">
            <li>Install Ollama from <a href="https://ollama.com" target="_blank" rel="noreferrer">ollama.com</a> and start it.</li>
            <li>Download a model, e.g. <code>ollama pull qwen2.5:7b</code> (≈5 GB). On a smaller computer try <code>llama3.2:3b</code>.</li>
            <li>Enter the model name below and save.</li>
          </ol>
          <div className="grid2">
            <label>
              Model name
              <input value={form.local_model} onChange={(e) => setForm({ ...form, local_model: e.target.value })} />
            </label>
            <label>
              Ollama address
              <input value={form.local_url} onChange={(e) => setForm({ ...form, local_url: e.target.value })} />
            </label>
          </div>
          <p className="small muted">Status: {status.providers.local.detail}</p>
        </section>
      )}

      <div className="row">
        <button disabled={saving} onClick={() => save(form)}>{saving ? "Saving…" : "Save"}</button>
        <button className="secondary" disabled={saving} onClick={load}>Check again</button>
        {saved && <span className="small muted">Saved ✓</span>}
      </div>
      {form.provider !== status.settings.provider && <p className="small muted">You have unsaved changes.</p>}
      <p className="small muted mt">
        Textbooks are analysed with whichever mode is active when they're uploaded. To re-analyse a book with a different
        mode, use “Re-analyse” on the Textbooks page.
      </p>
    </>
  );
}
