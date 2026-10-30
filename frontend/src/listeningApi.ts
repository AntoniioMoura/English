// Cliente da API do Listening. Lacunas, conferência e progresso são decididos pelo backend.
import { ApiError } from "./api";

export type VideoStatus = "unprocessed" | "processing" | "ready" | "error";
export type Difficulty = "beginner" | "easy" | "medium" | "hard";

export const DIFFICULTIES: { id: Difficulty; label: string; range: string }[] = [
  { id: "beginner", label: "Iniciante", range: "10–15% das palavras" },
  { id: "easy", label: "Fácil", range: "25–30% das palavras" },
  { id: "medium", label: "Médio", range: "40–45% das palavras" },
  { id: "hard", label: "Difícil", range: "60% das palavras" },
];
export const DIFFICULTY_LABEL = Object.fromEntries(DIFFICULTIES.map((d) => [d.id, d.label])) as Record<Difficulty, string>;

export interface ActiveSession {
  id: number;
  difficulty: Difficulty;
  mode: "normal" | "review";
  interval_seconds: number;
  done: number;
  total: number;
  updated_at: string;
}

export interface VideoSummary {
  id: number;
  title: string;
  file_name: string;
  rel_path: string;
  category: string;
  present: boolean;
  duration: number | null;
  has_thumbnail: boolean;
  metadata_ready: boolean;
  status: VideoStatus;
  stage: string | null;
  progress: number | null;
  error_message: string | null;
  subtitle_source: "external" | "embedded" | "whisper" | null;
  has_translation: boolean;
  converted: boolean;
  updated_at: string;
  active_sessions: ActiveSession[];
  study: { items_done: number; attempts: number; accuracy: number | null; last_studied_at: string | null };
  segment_count?: number;
  review_count?: number;
}

export interface Download {
  id: number;
  url: string;
  youtube_id: string;
  category: string;
  max_height: number;
  status: "queued" | "downloading" | "done" | "error";
  stage: string | null;
  progress: number | null;
  title: string | null;
  rel_path: string | null;
  video_id: number | null;
  error_message: string | null;
  created_at: string;
}

export interface Library {
  videos_dir: string;
  tools: { ffmpeg: boolean; transcriber: boolean; youtube: boolean };
  downloads: Download[];
  videos: VideoSummary[];
  continue_watching: number[];
  changes?: { added: number; moved: number; changed: number; missing: number };
}

export interface Segment {
  id: number;
  idx: number;
  start: number;
  end: number;
  text: string;
  translation_pt: string | null;
  original_text: string;
  edited: boolean;
  flagged: boolean;
}

export type BlankState = "hidden" | "wrong" | "correct" | "revealed";

export interface Blank {
  blank: number;
  word_index: number;
  state: BlankState;
  length: number;
  errors: number;
  last_typed: string | null;
  answer: string | null;
}

export interface SessionItem {
  id: number;
  position: number;
  segment_id: number;
  start: number;
  end: number;
  status: "pending" | "done" | "skipped";
  replays: number;
  flagged: boolean;
  parts: { text: string | null; blank: number | null }[];
  blanks: Blank[];
  text: string | null;
  translation_pt: string | null;
}

export interface SessionStats {
  total: number;
  done: number;
  skipped: number;
  attempts: number;
  correct: number;
  helped: number;
  accuracy: number | null;
  replays: number;
}

export interface Session {
  id: number;
  status: "active" | "finished" | "abandoned";
  difficulty: Difficulty;
  difficulty_label: string;
  mode: "normal" | "review";
  current_index: number;
  started_at: string;
  interval_seconds: number;
  video: { id: number; title: string; duration: number | null; has_translation: boolean };
  stats: SessionStats;
  items: SessionItem[];
  // Todas as falas do vídeo; as que são exercício vêm sem texto (não entregam a resposta).
  context: { start: number; end: number; text: string | null; translation_pt: string | null }[];
}

export const RHYTHMS = [
  { seconds: 15, label: "Intenso", hint: "uma frase a cada ~15 s" },
  { seconds: 30, label: "Equilibrado", hint: "uma frase a cada ~30 s" },
  { seconds: 60, label: "Leve", hint: "uma frase a cada ~1 min" },
  { seconds: 0, label: "Todas", hint: "todas as frases do vídeo" },
];

export interface ItemResult {
  item: SessionItem;
  session: { status: Session["status"]; stats: SessionStats };
}

export interface ListeningStats {
  totals: { attempts: number; correct: number; helped: number; accuracy: number | null; segments_done: number };
  by_video_difficulty: {
    video_id: number;
    title: string;
    difficulty: Difficulty;
    difficulty_label: string;
    attempts: number;
    correct: number;
    helped: number;
    accuracy: number | null;
  }[];
  progress: {
    video_id: number;
    title: string;
    segments_done: number;
    segments_total: number;
    to_review: number;
    stopped_at: {
      session_id: number;
      difficulty: Difficulty;
      status: Session["status"];
      position: number;
      items: number;
      time: number | null;
      updated_at: string;
    } | null;
  }[];
  words: { word: string; attempts: number; errors: number; helped: number; error_rate: number }[];
  sessions: {
    id: number;
    video_id: number;
    title: string;
    difficulty: Difficulty;
    difficulty_label: string;
    mode: "normal" | "review";
    status: Session["status"];
    started_at: string;
    items: number;
    done: number;
    replays: number;
    attempts: number;
    correct: number;
    helped: number;
    accuracy: number | null;
  }[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers: { "Content-Type": "application/json" } });
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

const send = (method: string, data?: unknown): RequestInit => ({
  method,
  body: data === undefined ? undefined : JSON.stringify(data),
});

const item = (sessionId: number, itemId: number, action: string) =>
  `/api/listening/sessions/${sessionId}/items/${itemId}/${action}`;

export const listeningApi = {
  library: () => call<Library>("/api/listening/library"),
  scan: () => call<Library>("/api/listening/library/scan", send("POST")),
  video: (id: number) => call<VideoSummary>(`/api/listening/videos/${id}`),
  rename: (id: number, title: string) => call<VideoSummary>(`/api/listening/videos/${id}`, send("PATCH", { title })),
  prepare: (id: number, force = false) =>
    call<VideoSummary>(`/api/listening/videos/${id}/prepare`, send("POST", { force })),
  segments: (id: number) => call<Segment[]>(`/api/listening/videos/${id}/segments`),
  updateSegment: (id: number, changes: Partial<Pick<Segment, "text" | "start" | "end" | "translation_pt" | "flagged">>) =>
    call<Segment>(`/api/listening/segments/${id}`, send("PATCH", changes)),
  startSession: (videoId: number, difficulty: Difficulty, mode: "normal" | "review" = "normal", restart = false, interval = 30) =>
    call<Session>(`/api/listening/videos/${videoId}/sessions`, send("POST", { difficulty, mode, restart, interval })),
  session: (id: number) => call<Session>(`/api/listening/sessions/${id}`),
  check: (sessionId: number, itemId: number, answers: (string | null)[]) =>
    call<ItemResult>(item(sessionId, itemId, "check"), send("POST", { answers })),
  reveal: (sessionId: number, itemId: number, blank: number | null) =>
    call<ItemResult>(item(sessionId, itemId, "reveal"), send("POST", { blank })),
  replay: (sessionId: number, itemId: number) => call<{ replays: number }>(item(sessionId, itemId, "replay"), send("POST")),
  skip: (sessionId: number, itemId: number, mismatch: boolean) =>
    call<ItemResult>(item(sessionId, itemId, "skip"), send("POST", { mismatch })),
  position: (sessionId: number, index: number) =>
    call<{ current_index: number }>(`/api/listening/sessions/${sessionId}/position`, send("PUT", { index })),
  finish: (sessionId: number) => call<Session>(`/api/listening/sessions/${sessionId}/finish`, send("POST")),
  stats: () => call<ListeningStats>("/api/listening/stats"),
  download: (url: string, category: string, max_height: number) =>
    call<Download>("/api/listening/downloads", send("POST", { url, category, max_height })),
  retryDownload: (id: number) => call<Download>(`/api/listening/downloads/${id}/retry`, send("POST")),
  dismissDownload: async (id: number) => {
    const response = await fetch(`/api/listening/downloads/${id}`, { method: "DELETE" });
    if (!response.ok) throw new ApiError("Não foi possível remover o download da lista.", response.status);
  },
  streamUrl: (id: number) => `/api/listening/videos/${id}/stream`,
  thumbnailUrl: (v: Pick<VideoSummary, "id" | "updated_at">) =>
    `/api/listening/videos/${v.id}/thumbnail?v=${encodeURIComponent(v.updated_at)}`,
};

export function formatTime(seconds: number | null | undefined, precise = false): string {
  if (seconds == null || !isFinite(seconds)) return "–";
  const s = Math.max(0, seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = precise ? (s % 60).toFixed(1).padStart(4, "0") : String(Math.floor(s % 60)).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

export const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`);
