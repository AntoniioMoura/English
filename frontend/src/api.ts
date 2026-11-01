// Cliente da API. O frontend só exibe o estado; regras de etapa vêm do backend.

export interface Frame {
  id: string;
  text: string;
  explanation_pt: string;
  level: string;
  grammar_tags: string[];
  examples: string[];
  enabled: boolean;
}

export interface SentenceVersion {
  version_index: number;
  text: string;
  hints_opened: boolean;
  created_at: string;
}

export interface Adjustment {
  type: "error" | "improvement";
  message_pt: string;
  excerpt?: string | null;
  correction?: string | null;
  suggestion_en?: string | null;
}

export interface Feedback {
  highlight: string;
  grammar_corrections: Adjustment[];
  idea_suggestions: Adjustment[];
  final_is_correct: boolean;
  corrected_final_sentence: string | null;
  self_corrections: string[];
  frame_note: string | null;
  next_tip: string;
  next_tip_example?: string | null;
}

export interface GrammarObservation {
  id: number;
  topic_id: string;
  version_index: number;
  evidence_type: "error" | "correct" | "self_correction" | "not_assessed";
  original_excerpt: string;
  suggested_correction: string | null;
  explanation_pt: string;
  review_status: string;
}

export interface Evaluation {
  id: number;
  status: "ok" | "failed";
  model: string;
  created_at: string;
  error_message: string | null;
  feedback: Feedback | null;
  score: number | null;
  grammar_observations: GrammarObservation[];
}

export type ExerciseStatus = "in_progress" | "awaiting_evaluation" | "evaluated";

export interface ExerciseState {
  id: number;
  status: ExerciseStatus;
  selection_mode: "manual" | "random";
  started_at: string;
  completed_at: string | null;
  frame: Frame;
  versions: SentenceVersion[];
  next_version_index: number | null;
  stage_label: string;
  total_versions: number;
  can_request_hints: boolean;
  can_evaluate: boolean;
  hints: Record<string, string[]>;
  evaluation: Evaluation | null;
}

export interface ExerciseSummary {
  id: number;
  frame_text: string;
  status: ExerciseStatus;
  latest_text: string | null;
  version_count: number;
  started_at: string;
  selection_mode: "manual" | "random";
}


export interface OllamaStatus {
  reachable: boolean;
  model_available: boolean;
  models: string[];
  message: string | null;
}

export type TopicState = "precisa_de_atencao" | "revisar" | "em_evolucao" | "consistente" | "dados_insuficientes";
export type ReportPeriod = "7d" | "30d" | "90d" | "all";

export interface ReportTopic {
  topic_id: string;
  name_pt: string;
  errors: number;
  correct: number;
  opportunities: number;
  error_rate: number | null;
  self_corrections: number;
  state: TopicState;
  examples: { excerpt: string; correction: string; explanation_pt: string; date: string }[];
}

export interface RecallReport {
  attempts: number;
  study_days: number;
  new: Partial<Record<"correct" | "incorrect" | "needs_review", number>>;
  review: Partial<Record<"correct" | "incorrect" | "needs_review", number>>;
  new_accuracy: number | null;
  review_accuracy: number | null;
  avg_score: number | null;
  words: { practiced: number; used: number; not_used_examples: string[] };
  topics: { topic_id: string; name_pt: string; errors: number; correct: number }[];
  recurring_errors: { excerpt: string; correction: string; rule_pt: string; sentence_pt: string; count: number }[];
  reviews: { pending_now: number; learning: number; stable: number };
  limitations: string[];
}

export interface ReportData {
  period: { key: ReportPeriod; label: string; start_local: string; end_local: string };
  totals: {
    exercises: number;
    study_days: number;
    expansions: number;
    hint_rate: number | null;
    relevant_expansion_rate: number | null;
    distinct_connectors: string[];
    grammar_errors: number;
    grammar_opportunities: number;
    self_corrections: number;
    dismissed_by_you: number;
  };
  topics: ReportTopic[];
  elaboration_examples: { comment_pt: string; original: string; suggestion_en: string; date: string }[];
  self_corrections: { before: string; after: string; topic: string; date: string }[];
  weekly: { week_start: string; exercises: number; error_rate: number | null; opportunities: number; hint_rate: number | null }[];
  limitations: string[];
  has_builder?: boolean;
  recall?: RecallReport | null;
  narrative: {
    summary_pt: string;
    strengths_pt: string[];
    errors_comment_pt: string;
    elaboration_comment_pt: string;
    evolution_comment_pt: string;
    recall_comment_pt?: string;
    next_topics: { topic_id: string; name_pt: string; reason_pt: string }[];
  } | null;
}

export interface ReportSummary {
  id: number;
  period_label: string;
  status: "complete" | "numbers_only";
  created_at: string;
  exercises: number;
  translations?: number | null;
}

export interface Report extends ReportSummary {
  model: string;
  narrative_error: string | null;
  content_md: string;
  data: ReportData;
}

export type StudyActivity = "builder" | "anki_practice" | "anki_review" | "listening";

export interface StudyToday {
  day: string;
  total_seconds: number;
  seconds_until_reset: number;
}

export interface StudyDay {
  date: string;
  total_seconds: number;
  activities: Partial<Record<StudyActivity, number>>;
}

export interface StudyMonth {
  month: string;
  today: string;
  total_seconds: number;
  days: StudyDay[];
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("Não foi possível falar com o servidor local. Ele está rodando?", 0);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      throw new ApiError(detail.message, response.status, detail.code);
    }
    if (Array.isArray(detail)) {
      throw new ApiError(detail.map((d: { msg: string }) => d.msg).join("; "), response.status);
    }
    throw new ApiError(`Erro ${response.status}`, response.status);
  }
  return body as T;
}

const post = <T>(path: string, data?: unknown) =>
  request<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data) });

export const api = {
  frames: () => request<Frame[]>("/api/frames"),
  createExercise: (selection_mode: "manual" | "random", frame_id?: string) =>
    post<ExerciseState>("/api/exercises", { selection_mode, frame_id }),
  exercise: (id: number) => request<ExerciseState>(`/api/exercises/${id}`),
  exercises: (status?: ExerciseStatus) =>
    request<ExerciseSummary[]>(`/api/exercises${status ? `?status=${status}` : ""}`),
  finishedExercises: () => request<ExerciseSummary[]>("/api/exercises?finished_only=true"),
  deleteExercise: async (id: number) => {
    const response = await fetch(`/api/exercises/${id}`, { method: "DELETE" });
    if (!response.ok) throw new ApiError("Não foi possível excluir o estudo.", response.status);
  },
  saveVersion: (id: number, version_index: number, text: string) =>
    post<ExerciseState>(`/api/exercises/${id}/versions`, { version_index, text }),
  hints: (id: number, refresh = false) =>
    post<{ stage: number; hints: string[] }>(`/api/exercises/${id}/hints`, { refresh }),
  evaluate: (id: number) => post<ExerciseState>(`/api/exercises/${id}/evaluate`),
  reviewObservation: (id: number, review_status: "pending" | "confirmed" | "dismissed") =>
    request<GrammarObservation>(`/api/observations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ review_status }),
    }),
  reports: () => request<ReportSummary[]>("/api/reports"),
  report: (id: number) => request<Report>(`/api/reports/${id}`),
  createReport: (period: ReportPeriod) => post<Report>("/api/reports", { period }),
  deleteReport: async (id: number) => {
    const response = await fetch(`/api/reports/${id}`, { method: "DELETE" });
    if (!response.ok) throw new ApiError("Não foi possível excluir o relatório.", response.status);
  },
  reportMarkdownUrl: (id: number) => `/api/reports/${id}/markdown`,
  ollamaStatus: () => request<OllamaStatus>("/api/settings/ollama/status"),
  studyToday: () => request<StudyToday>("/api/study-time/today"),
  addStudyTime: (day: string, seconds: Partial<Record<StudyActivity, number>>, keepalive = false) =>
    request<StudyToday>("/api/study-time", { method: "POST", body: JSON.stringify({ day, seconds }), keepalive }),
  studyMonth: (month?: string) => request<StudyMonth>(`/api/study-time/month${month ? `?month=${month}` : ""}`),
};
