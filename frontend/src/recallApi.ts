// Cliente da API do Anki Premium (Sentence Recall). Cota, revisões e julgamentos vêm sempre do backend.
import { ApiError } from "./api";

export interface VocabEntry {
  id: number;
  english_text: string;
  translation_pt: string | null;
  part_of_speech: string | null;
  notes: string | null;
  enabled: boolean;
  times_used: number;
  times_demonstrated: number;
}

export type Verdict = "correct" | "incorrect" | "needs_review";

export interface RecallResult {
  verdict: Verdict;
  meaning_match: boolean;
  errors: {
    category: string;
    topic_id: string;
    excerpt: string;
    correction: string;
    explanation_pt: string;
    rule_pt?: string;
  }[];
  corrected_answer: string | null;
  alternative_en: string | null;
  natural_en?: string | null;
  target_usage: {
    vocabulary_id: number;
    english_text: string;
    demonstrated: boolean;
    meaning_pt?: string | null;
  }[];
  suggestion: { comment_pt: string; example_en: string } | null;
  message_pt: string | null;
}

export interface Quota {
  errors_today: number;
  limit: number;
  blocked: boolean;
}

export interface RecallExercise {
  id: number;
  mode: "new" | "review";
  sentence_pt: string;
  status: "pending_answer" | "awaiting_evaluation" | "evaluated" | "skipped";
  review: { item_id: number; target_type: ReviewItem["target_type"]; label_pt: string | null } | null;
  reference_en: string | null;
  targets: { vocabulary_id: number; english_text: string; intended_meaning: string | null }[];
  answer: string | null;
  verdict: Verdict | null;
  score: number | null;
  result: RecallResult | null;
  evaluation_error: string | null;
  quota: Quota;
  due_reviews: number;
}

export interface ReviewItem {
  id: number;
  label_pt: string;
  target_type: "sentence" | "vocabulary_sense";
  due_at: string;
  status: "learning" | "stable";
  mistakes: number;
}

export interface RecallProgress {
  quota: Quota;
  due_reviews: number;
  new: Partial<Record<Verdict, number>>;
  review: Partial<Record<Verdict, number>>;
  words: { total: number; enabled: number; practiced: number; demonstrated: number };
  topics: { topic_id: string; name_pt: string; errors: number; correct: number }[];
  history: {
    id: number;
    mode: "new" | "review";
    sentence_pt: string;
    answer_text: string;
    verdict: Verdict | null;
    score: number | null;
    created_at: string;
    targets: string | null;
  }[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers: { "Content-Type": "application/json" } });
  } catch {
    throw new ApiError("Não foi possível falar com o servidor local. Ele está rodando?", 0);
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      throw new ApiError(detail.message, response.status, detail.code);
    }
    if (Array.isArray(detail)) {
      throw new ApiError(detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, "")).join("; "), response.status);
    }
    throw new ApiError(`Erro ${response.status}`, response.status);
  }
  return body as T;
}

const json = (method: string, data?: unknown): RequestInit => ({
  method,
  body: data === undefined ? undefined : JSON.stringify(data),
});

export const recallApi = {
  vocabulary: () => call<VocabEntry[]>("/api/recall/vocabulary"),
  addWords: (entries: { english_text: string; translation_pt?: string }[]) =>
    call<{ created: VocabEntry[]; skipped: { english_text: string; reason: string }[] }>(
      "/api/recall/vocabulary",
      json("POST", { entries }),
    ),
  updateWord: (id: number, changes: Partial<Pick<VocabEntry, "english_text" | "translation_pt" | "notes" | "enabled">>) =>
    call<VocabEntry>(`/api/recall/vocabulary/${id}`, json("PATCH", changes)),
  deleteWord: (id: number) => call<void>(`/api/recall/vocabulary/${id}`, json("DELETE")),
  newExercise: () => call<RecallExercise>("/api/recall/exercises", json("POST")),
  exercise: (id: number) => call<RecallExercise>(`/api/recall/exercises/${id}`),
  answer: (id: number, answer: string, idempotency_key: string) =>
    call<RecallExercise>(`/api/recall/exercises/${id}/answer`, json("POST", { answer, idempotency_key })),
  skip: (id: number) => call<RecallExercise>(`/api/recall/exercises/${id}/skip`, json("POST")),
  reevaluate: (id: number) => call<RecallExercise>(`/api/recall/exercises/${id}/evaluate`, json("POST")),
  dueReviews: () => call<{ due: ReviewItem[]; upcoming: ReviewItem[] }>("/api/recall/reviews/due"),
  reviewExercise: (itemId: number) => call<RecallExercise>(`/api/recall/reviews/${itemId}/exercise`, json("POST")),
  progress: () => call<RecallProgress>("/api/recall/progress"),
};

export function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
