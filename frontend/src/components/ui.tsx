import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="spinner-row" role="status">
      <span className="spinner" aria-hidden />
      {label && <span>{label}</span>}
    </div>
  );
}

export function ErrorBanner({ error, onClose }: { error: string | null; onClose?: () => void }) {
  if (!error) return null;
  return (
    <div className="error" role="alert">
      <span>{error}</span>
      {onClose && (
        <button className="link" onClick={onClose} aria-label="Dismiss">
          ✕
        </button>
      )}
    </div>
  );
}

const LABELS: Record<string, string> = {
  mastered: "Mastered",
  developing: "Getting there",
  needs_work: "Needs work",
  not_started: "Not started",
  passed: "Understood",
  learning: "Learning now",
  pending: "Up next",
  needs_followup: "Revisit later",
};

export function StatusPill({ status }: { status: string }) {
  return <span className={`pill pill-${status}`}>{LABELS[status] ?? status}</span>;
}

export function MasteryBar({ value, from }: { value: number | null; from?: number }) {
  if (value === null) return <div className="bar bar-empty" />;
  const pct = Math.round(value * 100);
  const tone = value >= 0.85 ? "good" : value >= 0.6 ? "mid" : "low";
  return (
    <div className="bar" title={`${pct}% mastery`}>
      {from !== undefined && <div className="bar-from" style={{ width: `${Math.round(from * 100)}%` }} />}
      <div className={`bar-fill bar-${tone}`} style={{ width: `${pct}%` }} />
      <span className="bar-label">{pct}%</span>
    </div>
  );
}

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

export const STRATEGY_NAMES: Record<string, string> = {
  step_by_step: "Step by step",
  real_world_analogy: "Real-life examples",
  worked_example: "Worked examples",
  visual_description: "Pictures & diagrams",
  simpler_language: "Simpler words",
  socratic: "Guiding questions",
  contrast_mistake: "Right vs. wrong way",
};
