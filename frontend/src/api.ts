// Typed client for the tutor backend (/api).

export interface Student { id: number; name: string; grade: number; created_at: string }

export interface Topic {
  id: number; order: number; title: string; summary: string | null;
  learning_objectives: string[]; key_terms: string[]; prerequisites: string[];
  start_page: number | null; end_page: number | null;
}
export interface Chapter {
  id: number; number: number; title: string; summary: string | null;
  start_page: number; end_page: number; topics: Topic[];
}
export interface Textbook {
  id: number; student_id: number; title: string; subject: string | null; grade: number | null;
  filename: string; status: "uploaded" | "processing" | "ready" | "failed"; status_detail: string | null;
  progress: number; page_count: number; structure_source: string | null;
  analysis_mode: Provider | null; created_at: string;
}
export interface TextbookDetail extends Textbook { chapters: Chapter[] }

export interface Lesson {
  id: number; student_id: number; textbook_id: number; chapter_id: number; topic_ids: number[];
  lesson_date: string; notes: string | null; created_at: string;
}

export interface Message {
  id: number; role: "tutor" | "student"; kind: string; content: string;
  payload: Record<string, unknown>; created_at: string;
}
export interface PendingQuestion {
  id: number; topic_id: number; phase: string; qtype: "mcq" | "numeric" | "short";
  prompt: string; options: string[]; difficulty: number; hints_available: boolean;
}
export interface TopicProgress { topic_id: number; title: string; status: string; p_known: number }

export interface ReportTopic {
  topic_id: number; title: string; chapter: string; status: string;
  mastery_start: number; mastery_end: number; mastery_label: string;
  questions: number; correct: number; accuracy: number | null; learning_accuracy: number | null;
  test_score: number | null; reteach_count: number; strategies_used: string[];
  misconceptions: string[]; next_review_at: string | null;
}
export interface Report {
  overall: {
    questions: number; correct: number; accuracy: number | null; test_score: number | null;
    test_questions: number; hints_used: number; minutes: number;
  };
  topics: ReportTopic[];
  test_review: {
    question: string; topic: string; your_answer: string; correct_answer: string;
    verdict: string; feedback: string; explanation: string;
  }[];
  ai: {
    message_for_student: string; summary_for_parent: string; strengths: string[];
    areas_to_improve: string[]; recommended_next_steps: string[];
  };
}

export interface TutorSession {
  id: number; student_id: number; mode: string;
  phase: "teach" | "check" | "practice" | "test_ready" | "test" | "complete";
  awaiting: "answer" | "advance" | "none";
  started_at: string; ended_at: string | null; topics: TopicProgress[];
  practice_done: number; practice_total: number; test_answered: number; test_total: number;
  pending_question: PendingQuestion | null; messages: Message[]; report: Report | null;
}
export interface SessionListItem {
  id: number; mode: string; phase: string; started_at: string; ended_at: string | null;
  topic_titles: string[]; test_score: number | null;
}

export interface ProgressTopic {
  topic_id: number; title: string; status: string; p_known: number | null; attempts: number;
  accuracy: number | null; misconceptions: string[]; next_review_at: string | null;
}
export interface Progress {
  student: { id: number; name: string; grade: number };
  counts: Record<"mastered" | "developing" | "needs_work" | "not_started", number>;
  sessions_completed: number; questions_answered: number;
  recent_test_scores: { session_id: number; date: string | null; score: number }[];
  average_test_score: number | null;
  teaching_strategies: Record<string, { tried: number; succeeded: number; success_rate: number | null }>;
  textbooks: {
    textbook_id: number; title: string; subject: string | null;
    chapters: { chapter_id: number; number: number; title: string; average_mastery: number | null; topics: ProgressTopic[] }[];
  }[];
}
export interface RevisionItem {
  topic_id: number; title: string; chapter: string; textbook: string; p_known: number; status: string;
  next_review_at: string | null; reason: string; misconceptions: string[]; priority: number;
}
export interface RevisionPlan { due: RevisionItem[]; upcoming: RevisionItem[]; suggested_topic_ids: number[] }
export type Provider = "rules" | "local" | "claude";
export interface Health { status: string; provider: Provider }
export interface AISettings { provider: Provider; local_url: string; local_model: string }
export interface AIStatus {
  settings: AISettings;
  providers: Record<Provider, { available: boolean; detail: string }>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "Can't reach the tutor server. Is the backend running?");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* not JSON */ }
    throw new ApiError(res.status, detail || `Request failed (${res.status})`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/health"),
  aiSettings: () => request<AIStatus>("/settings/ai"),
  saveAiSettings: (body: AISettings) => request<AIStatus>("/settings/ai", json("PUT", body)),

  students: () => request<Student[]>("/students"),
  createStudent: (name: string, grade: number) => request<Student>("/students", json("POST", { name, grade })),
  progress: (id: number) => request<Progress>(`/students/${id}/progress`),
  revisionPlan: (id: number) => request<RevisionPlan>(`/students/${id}/revision-plan`),

  textbooks: (studentId: number) => request<Textbook[]>(`/textbooks?student_id=${studentId}`),
  textbook: (id: number) => request<TextbookDetail>(`/textbooks/${id}`),
  uploadTextbook: (studentId: number, file: File, title?: string, subject?: string) => {
    const form = new FormData();
    form.append("student_id", String(studentId));
    form.append("file", file);
    if (title) form.append("title", title);
    if (subject) form.append("subject", subject);
    return request<Textbook>("/textbooks", { method: "POST", body: form });
  },
  reprocessTextbook: (id: number) => request<Textbook>(`/textbooks/${id}/process`, json("POST")),
  deleteTextbook: (id: number) => request<void>(`/textbooks/${id}`, { method: "DELETE" }),

  createLesson: (body: { student_id: number; chapter_id: number; topic_ids: number[]; notes?: string }) =>
    request<Lesson>("/lessons", json("POST", body)),
  lessons: (studentId: number) => request<Lesson[]>(`/lessons?student_id=${studentId}`),

  startSession: (body: { student_id: number; lesson_id?: number; topic_ids?: number[]; mode?: "lesson" | "revision" }) =>
    request<TutorSession>("/sessions", json("POST", body)),
  sessions: (studentId: number) => request<SessionListItem[]>(`/sessions?student_id=${studentId}`),
  session: (id: number) => request<TutorSession>(`/sessions/${id}`),
  answer: (id: number, question_id: number, answer: string) =>
    request<TutorSession>(`/sessions/${id}/answer`, json("POST", { question_id, answer })),
  hint: (id: number, question_id: number) => request<TutorSession>(`/sessions/${id}/hint`, json("POST", { question_id })),
  chat: (id: number, text: string) => request<TutorSession>(`/sessions/${id}/chat`, json("POST", { text })),
  advance: (id: number) => request<TutorSession>(`/sessions/${id}/advance`, json("POST")),
  skipToTest: (id: number) => request<TutorSession>(`/sessions/${id}/skip-to-test`, json("POST")),
};
