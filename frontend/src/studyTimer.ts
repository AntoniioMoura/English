// Relógio de estudo: conta os segundos da tela ativa e envia em lotes para o backend, que decide o dia.
import { useEffect, useSyncExternalStore } from "react";
import { api, StudyActivity, StudyToday } from "./api";

const SYNC_EVERY = 10; // segundos acumulados antes de enviar

type Seconds = Partial<Record<StudyActivity, number>>;

const sum = (seconds: Seconds) => Object.values(seconds).reduce((total, n) => total + (n ?? 0), 0);

let day: string | null = null;
let savedSeconds = 0;
let resetAt = 0; // 0: ainda não falou com o backend
let pending: Seconds = {};
let sending = 0;
let syncing: Promise<void> | null = null;
let activity: StudyActivity | null = null;
let aiRequests = 0; // chamadas de IA em andamento
let snapshot = { seconds: 0, running: false };
let ticker: number | null = null;
const listeners = new Set<() => void>();

const counting = () => activity !== null && aiRequests === 0 && !document.hidden;

function publish() {
  snapshot = { seconds: savedSeconds + sending + sum(pending), running: counting() };
  listeners.forEach((listener) => listener());
}

function apply(today: StudyToday) {
  day = today.day;
  savedSeconds = today.total_seconds;
  resetAt = Date.now() + today.seconds_until_reset * 1000;
}

async function send() {
  const batch = pending;
  pending = {};
  sending = sum(batch);
  try {
    apply(sending > 0 && day ? await api.addStudyTime(day, batch) : await api.studyToday());
  } catch {
    // Servidor fora do ar: os segundos ficam guardados para o próximo envio.
    for (const [name, amount] of Object.entries(batch) as [StudyActivity, number][]) {
      pending[name] = (pending[name] ?? 0) + amount;
    }
  } finally {
    sending = 0;
    publish();
  }
}

export function syncStudyTime(): Promise<void> {
  syncing = (syncing ?? Promise.resolve()).then(send).finally(() => {
    syncing = null;
  });
  return syncing;
}

function tick() {
  if (Date.now() >= resetAt) {
    if (!syncing) syncStudyTime(); // meia-noite: fecha o dia e zera o relógio
    return;
  }
  // Soma um segundo por tique: com o computador suspenso, a aba escondida ou a IA processando, nada conta.
  if (activity && counting()) {
    pending[activity] = (pending[activity] ?? 0) + 1;
    publish();
    if (sum(pending) >= SYNC_EVERY && !syncing) syncStudyTime();
  }
}

function start() {
  ticker = window.setInterval(tick, 1000);
  tick();
  document.addEventListener("visibilitychange", () => {
    publish();
    if (document.hidden && sum(pending) > 0) syncStudyTime();
  });
  window.addEventListener("pagehide", () => {
    if (day && sum(pending) > 0) api.addStudyTime(day, pending, true).catch(() => undefined);
    pending = {};
  });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (ticker === null) start();
  return () => {
    listeners.delete(listener);
  };
}

export function useStudyClock() {
  return useSyncExternalStore(subscribe, () => snapshot);
}

// Enquanto a tela estiver montada e `enabled`, o tempo conta para `kind`.
export function useStudyTimer(kind: StudyActivity, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    activity = kind;
    publish();
    return () => {
      activity = null;
      publish();
      if (sum(pending) > 0) syncStudyTime();
    };
  }, [kind, enabled]);
}

// Pausa o relógio enquanto `waiting` for verdadeiro (a IA está processando e você só aguarda).
export function useStudyPause(waiting: boolean) {
  useEffect(() => {
    if (!waiting) return;
    aiRequests++;
    publish();
    return () => {
      aiRequests--;
      publish();
    };
  }, [waiting]);
}

export function formatClock(total: number): string {
  const part = (n: number) => String(n).padStart(2, "0");
  return `${part(Math.floor(total / 3600))}:${part(Math.floor(total / 60) % 60)}:${part(total % 60)}`;
}

export function formatDuration(total: number): string {
  if (total < 60) return `${total}s`;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor(total / 60) % 60;
  return hours ? `${hours}h ${String(minutes).padStart(2, "0")}min` : `${minutes}min`;
}
