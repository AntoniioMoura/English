import { KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatTime, ItemResult, listeningApi, pct, Session, SessionItem } from "../../listeningApi";
import { setSoundEnabled, soundEnabled, sounds } from "../../sounds";

const PREROLL = 0.15; // começa um pouco antes para não cortar a primeira sílaba
const TRANSLATION_KEY = "listening.translation";

// Conferência em tempo real: ignora só maiúsculas e o tipo de apóstrofo.
const fold = (value: string) => value.toLowerCase().replace(/[’‘`´]/g, "'");
type Live = "empty" | "ok" | "bad" | "done";

function liveState(expected: string, typed: string): Live {
  if (!typed) return "empty";
  const want = fold(expected);
  const got = fold(typed);
  if (!want.startsWith(got)) return "bad";
  return got.length === want.length ? "done" : "ok";
}

const blankKey = (itemId: number, k: number) => `${itemId}:${k}`;

// De onde o vídeo corre até a frase `i`: do fim da frase-exercício anterior (com a legenda completa no meio).
function runStart(session: Session, i: number): number {
  const it = session.items[i];
  if (session.mode === "review") return Math.max(it.start - PREROLL, 0);
  if (i === 0) return Math.max(Math.min(session.context[0]?.start ?? it.start, it.start) - 0.5, 0);
  return Math.max(Math.min(session.items[i - 1].end, it.start - PREROLL), 0);
}

export function ListeningPlayer() {
  const { id } = useParams();
  const sessionId = Number(id);
  const [session, setSession] = useState<Session | null>(null);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<number, string[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [soundOn, setSoundOn] = useState(soundEnabled);
  const [showTranslation, setShowTranslation] = useState(() => {
    try {
      return localStorage.getItem(TRANSLATION_KEY) === "on";
    } catch {
      return false;
    }
  });

  function toggleTranslation() {
    setShowTranslation((on) => {
      try {
        localStorage.setItem(TRANSLATION_KEY, on ? "off" : "on"); // lembra a escolha entre sessões
      } catch {
        /* sem armazenamento: vale só nesta visita */
      }
      return !on;
    });
  }
  // Frase concluída agora (anima só na hora; revisitar uma frase mostra o resumo sem festa).
  const [celebrating, setCelebrating] = useState<number | null>(null);
  const lastStatus = useRef<Record<number, SessionItem["status"]>>({});
  const [needsGesture, setNeedsGesture] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [skipMenu, setSkipMenu] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number | null>(null);
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const nextButton = useRef<HTMLButtonElement>(null);
  const focusedBlank = useRef(0);
  // Lacunas acertadas aqui que o servidor ainda não confirmou (a digitação não espera a rede).
  const [solved, setSolved] = useState<Set<string>>(new Set());
  const submissions = useRef<Promise<unknown>>(Promise.resolve());

  useEffect(() => {
    listeningApi
      .session(sessionId)
      .then((s) => {
        setSession(s);
        setIndex(s.current_index);
        lastStatus.current = Object.fromEntries(s.items.map((i) => [i.id, i.status]));
      })
      .catch((e) => setError(e.message));
  }, [sessionId]);

  const item: SessionItem | undefined = session?.items[index];

  // ---------- vídeo ----------

  // Pausa no fim do trecho. Devolve true se pausou.
  const checkStop = useCallback(() => {
    const video = videoRef.current;
    if (!video) return true;
    setTime(video.currentTime);
    if (stopAt.current != null && video.currentTime >= stopAt.current) {
      video.pause();
      stopAt.current = null;
      return true;
    }
    return false;
  }, []);

  const tick = useCallback(() => {
    if (!checkStop() && !videoRef.current?.paused) requestAnimationFrame(tick);
  }, [checkStop]);

  // Toca de `from` até o fim da frase `it` e pausa lá.
  const playUntil = useCallback(async (it: SessionItem, from: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = from;
    stopAt.current = it.end;
    try {
      await video.play();
      setNeedsGesture(false);
    } catch {
      setNeedsGesture(true); // navegador bloqueou a reprodução automática: espera um clique
    }
  }, []);

  const playSegment = useCallback((it: SessionItem) => playUntil(it, Math.max(it.start - PREROLL, 0)), [playUntil]);

  // Ao trocar de frase: o vídeo corre (com a legenda completa) desde a frase anterior e para no fim desta.
  useEffect(() => {
    if (!item || !session) return;
    setCelebrating(null);
    if (item.status === "pending") {
      setTime(runStart(session, index));
      playUntil(item, runStart(session, index));
    } else {
      setTime(item.start);
      playSegment(item); // revisitando uma frase concluída: só ela
    }
    setSkipMenu(false);
    setAnswers((prev) =>
      prev[item.id] ? prev : { ...prev, [item.id]: item.blanks.map((b) => (b.state === "wrong" ? b.last_typed ?? "" : "")) },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id]);

  // Enquanto o vídeo ainda não chegou na frase-exercício, mostra a legenda completa das falas em volta.
  const watching = !!item && time < item.start - PREROLL - 0.05;
  useEffect(() => {
    if (item && !watching) window.setTimeout(() => focusFirstOpen(item), 30);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watching, item?.id]);

  const isOpen = (it: SessionItem, k: number, done: Set<string> = solved) =>
    ["hidden", "wrong"].includes(it.blanks[k].state) && !done.has(blankKey(it.id, k));

  useEffect(() => {
    if (item && item.status !== "pending") window.setTimeout(() => nextButton.current?.focus(), 30);
  }, [item?.status, item?.id]);

  // A frase acabou de ser concluída (pendente → feita): som e animação de recompensa.
  useEffect(() => {
    if (!item) return;
    const before = lastStatus.current[item.id];
    lastStatus.current[item.id] = item.status;
    if (before === "pending" && item.status === "done") {
      const perfect = isPerfect(item);
      sounds.sentence(perfect);
      setCelebrating(item.id);
    }
  }, [item?.status, item?.id, item]);

  function focusFirstOpen(it: SessionItem, done: Set<string> = solved) {
    const open = it.blanks.find((b) => isOpen(it, b.blank, done));
    if (open) {
      const el = inputs.current[open.blank];
      el?.focus();
      el?.select();
    } else {
      nextButton.current?.focus();
    }
  }

  async function replay() {
    if (!item || !session) return;
    playSegment(item);
    try {
      const { replays } = await listeningApi.replay(session.id, item.id);
      updateItem({ ...item, replays });
    } catch {
      /* a contagem de repetições não deve atrapalhar o estudo */
    }
  }

  function togglePlay() {
    const video = videoRef.current;
    if (!video || !item) return;
    if (!video.paused) {
      video.pause();
      return;
    }
    const beforeEnd = video.currentTime < item.end - 0.05 && video.currentTime >= runStart(session!, index) - 0.05;
    if (beforeEnd) {
      stopAt.current = item.end;
      video.play().catch(() => setNeedsGesture(true));
    } else {
      playSegment(item);
    }
  }

  // ---------- estado da sessão ----------

  function updateItem(updated: SessionItem, stats?: ItemResult["session"]) {
    setSession((prev) => {
      if (!prev) return prev;
      const items = prev.items.map((i) => (i.id === updated.id ? updated : i));
      return stats ? { ...prev, items, status: stats.status, stats: stats.stats } : { ...prev, items };
    });
  }

  async function goTo(next: number) {
    if (!session) return;
    const bounded = Math.max(0, Math.min(next, session.items.length - 1));
    setIndex(bounded);
    listeningApi.position(session.id, bounded).catch(() => undefined);
  }

  function nextPending() {
    if (!session) return;
    const after = session.items.findIndex((i, n) => n > index && i.status === "pending");
    const any = session.items.findIndex((i) => i.status === "pending");
    goTo(after >= 0 ? after : any >= 0 ? any : index + 1);
  }

  async function run(action: () => Promise<ItemResult>) {
    setBusy(true);
    setError(null);
    try {
      await submissions.current; // acertos digitados agora entram antes de revelar/pular
      const result = await action();
      updateItem(result.item, result.session);
      setAnswers((prev) => ({
        ...prev,
        [result.item.id]: result.item.blanks.map((b, k) =>
          b.state === "wrong" ? prev[result.item.id]?.[k] ?? b.last_typed ?? "" : b.state === "hidden" ? prev[result.item.id]?.[k] ?? "" : "",
        ),
      }));
      window.setTimeout(() => focusFirstOpen(result.item), 30);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Envia uma lacuna completa ao servidor (que valida e registra). Em fila, para não embaralhar respostas.
  function submit(it: SessionItem, k: number, typed: string) {
    if (!session) return;
    const sessionId = session.id;
    submissions.current = submissions.current.then(async () => {
      try {
        const result = await listeningApi.check(sessionId, it.id, it.blanks.map((_, n) => (n === k ? typed : null)));
        updateItem(result.item, result.session);
      } catch (e) {
        setError((e as Error).message);
      }
    });
  }

  const reveal = (blank: number | null) => {
    if (!item || !session || item.status !== "pending") return;
    run(() => listeningApi.reveal(session.id, item.id, blank));
  };

  // Mostra a frase inteira (conta como ajuda) e toca de novo para você ouvir sabendo a resposta.
  const showAnswer = async () => {
    if (!item || !session || item.status !== "pending") return;
    await run(() => listeningApi.reveal(session.id, item.id, null));
    playSegment(item);
  };

  const skip = (mismatch: boolean) => {
    if (!item || !session) return;
    run(async () => {
      const result = await listeningApi.skip(session.id, item.id, mismatch);
      return result;
    });
    setSkipMenu(false);
  };

  // ---------- teclado ----------

  // Cada tecla é conferida na hora: verde enquanto está certo, vermelho no primeiro erro.
  // Palavra completa e certa → trava e o cursor vai para a próxima lacuna.
  // Palavra completa e errada → conta um erro e o cursor fica (apague e tente de novo).
  function onBlankChange(it: SessionItem, k: number, raw: string) {
    const expected = it.blanks[k].expected;
    const value = raw.replace(/\s+/g, "").slice(0, expected.length);
    const typedMore = value.length > (answers[it.id]?.[k] ?? "").length;
    setAnswers((prev) => {
      const list = [...(prev[it.id] ?? it.blanks.map(() => ""))];
      list[k] = value;
      return { ...prev, [it.id]: list };
    });
    const live = liveState(expected, value);
    if (typedMore && live !== "done") (live === "bad" ? sounds.wrongKey : sounds.key)();
    if (live === "done") {
      sounds.word();
      const done = new Set(solved).add(blankKey(it.id, k));
      setSolved(done);
      submit(it, k, value);
      const next = it.blanks.find((b) => b.blank > k && isOpen(it, b.blank, done)) ?? it.blanks.find((b) => isOpen(it, b.blank, done));
      // Foco já nesta tecla (sem esperar a nova renderização): nenhuma letra digitada rápido se perde.
      if (next) inputs.current[next.blank]?.focus();
    } else if (live === "bad" && value.length === expected.length) {
      submit(it, k, value);
    }
  }

  function onBlankKey(e: KeyboardEvent<HTMLInputElement>, k: number) {
    const value = (e.target as HTMLInputElement).value;
    if (e.key === " " && !e.ctrlKey) {
      e.preventDefault(); // palavras não têm espaço
    } else if (e.key === "Backspace" && !value) {
      e.preventDefault();
      moveFocus(k, -1);
    }
  }

  function moveFocus(k: number, dir: 1 | -1) {
    if (!item) return;
    for (let n = k + dir; n >= 0 && n < item.blanks.length; n += dir) {
      if (isOpen(item, n)) {
        inputs.current[n]?.focus();
        inputs.current[n]?.select();
        return;
      }
    }
  }

  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if (!item || busy) return;
      if (e.ctrlKey && e.code === "Space") {
        e.preventDefault();
        replay();
      } else if (e.ctrlKey && e.key === "Enter") {
        e.preventDefault();
        reveal(focusedBlank.current);
      } else if (e.key === "Enter" && !e.ctrlKey && !e.shiftKey) {
        const target = e.target as HTMLElement;
        if (target.tagName === "BUTTON" && target !== nextButton.current) return;
        e.preventDefault();
        if (!watching && item.status !== "pending") nextPending();
      } else if (e.key === "PageDown") {
        e.preventDefault();
        if (index < frontier) goTo(index + 1);
      } else if (e.key === "PageUp") {
        e.preventDefault();
        goTo(index - 1);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // "›" só navega entre frases já concluídas (até a última feita); avançar para a próxima é o "Continuar".
  const frontier = useMemo(() => {
    if (!session) return -1;
    let last = -1;
    session.items.forEach((i, n) => i.status !== "pending" && (last = n));
    return last;
  }, [session]);

  const progress = useMemo(() => {
    if (!session) return 0;
    return (session.stats.done + session.stats.skipped) / Math.max(session.stats.total, 1);
  }, [session]);

  if (!session) {
    return error ? <div className="alert alert-error">{error}</div> : <div className="spinner" />;
  }

  const finished = session.status !== "active";
  const translationOn = showTranslation && session.video.has_translation;
  const contextLine = watching
    ? [...session.context].reverse().find((c) => c.text && time >= c.start - 0.05 && time <= c.end + 0.4)
    : undefined;

  return (
    <div className="player">
      <div className="player-head">
        <Link to={`/listening/video/${session.video.id}`} className="btn btn-ghost">
          ← {session.video.title}
        </Link>
        <span className="tag">
          {session.difficulty_label}
          {session.mode === "review" ? " · revisão" : ""}
        </span>
      </div>

      <div className="video-frame">
        <video
          ref={videoRef}
          src={listeningApi.streamUrl(session.video.id)}
          preload="auto"
          playsInline
          onPlay={() => {
            setPlaying(true);
            requestAnimationFrame(tick);
          }}
          onPause={() => setPlaying(false)}
          onTimeUpdate={checkStop} // garantia: requestAnimationFrame para quando a aba fica em segundo plano
          onClick={togglePlay}
          onLoadedMetadata={() => item && !playing && videoRef.current && (videoRef.current.currentTime = runStart(session, index))}
          onError={() => setError("O navegador não conseguiu reproduzir este vídeo. Tente prepará-lo novamente.")}
        />
        {(needsGesture || (!playing && !finished)) && (
          <button
            className="video-play"
            onClick={needsGesture && item ? () => playUntil(item, videoRef.current?.currentTime ?? item.start) : togglePlay}
            aria-label="Reproduzir"
          >
            ▶
          </button>
        )}
      </div>

      <div className="player-bar">
        <div className="player-progress">
          <span className="eyebrow-label">
            Frase{session.interval_seconds ? ` · uma a cada ~${session.interval_seconds} s` : ""}
          </span>
          <strong>
            {index + 1}/{session.items.length}
          </strong>
        </div>
        <div className="player-controls">
          <IconButton label="Frase anterior (PageUp)" onClick={() => goTo(index - 1)} disabled={index === 0}>
            ‹
          </IconButton>
          <IconButton label={playing ? "Pausar" : "Reproduzir"} onClick={togglePlay}>
            {playing ? "❚❚" : "▶"}
          </IconButton>
          <IconButton label="Repetir a frase (Ctrl+Espaço)" onClick={replay}>
            ↻
          </IconButton>
          <IconButton
            label="Próxima frase concluída (PageDown)"
            onClick={() => goTo(index + 1)}
            disabled={index >= frontier}
          >
            ›
          </IconButton>
          <IconButton
            label="Revelar palavra em foco (Ctrl+Enter)"
            onClick={() => reveal(focusedBlank.current)}
            disabled={busy || item?.status !== "pending"}
          >
            💡
          </IconButton>
          <IconButton
            label={soundOn ? "Silenciar sons de digitação" : "Ativar sons de digitação"}
            onClick={() => {
              setSoundEnabled(!soundOn);
              setSoundOn(!soundOn);
            }}
          >
            {soundOn ? "🔊" : "🔇"}
          </IconButton>
          <IconButton
            label={
              !session.video.has_translation
                ? "Este vídeo não tem legenda em português (coloque um .pt-BR.srt ao lado do vídeo)"
                : showTranslation
                  ? "Ocultar tradução"
                  : "Mostrar tradução"
            }
            onClick={toggleTranslation}
            disabled={!session.video.has_translation}
            active={showTranslation && session.video.has_translation}
          >
            PT
          </IconButton>
        </div>
      </div>
      <div className="player-track">
        <div className="bar">
          <span style={{ width: `${progress * 100}%` }} />
        </div>
        <span className="mono tiny muted">
          {formatTime(time)} / {formatTime(session.video.duration)}
        </span>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {item && watching && (
        <section className="sentence-area">
          {translationOn && <p className="translation-above">{contextLine?.translation_pt ?? " "}</p>}
          <p className="sentence sentence-context" aria-live="polite">
            {contextLine?.text ?? "\u00a0"}
          </p>
        </section>
      )}

      {item && !watching && (
        <section className={`sentence-area ${item.status !== "pending" ? "sentence-done" : ""}`}>
          {translationOn && <p className="translation-above">{item.translation_pt ?? " "}</p>}
          <p className={`sentence ${celebrating === item.id && isPerfect(item) ? "sentence-celebrate" : ""}`} aria-live="polite">
            {item.parts.map((part, n) => {
              if (part.blank === null) {
                return part.unheard ? (
                  <span key={n} className="word-unheard" title="Está na legenda, mas não é dito no áudio">
                    {part.text}
                  </span>
                ) : (
                  <span key={n}>{part.text}</span>
                );
              }
              const blank = item.blanks[part.blank];
              const k = part.blank;
              const solvedHere = solved.has(blankKey(item.id, k));
              if (blank.state === "correct" || blank.state === "revealed" || solvedHere || part.text !== null) {
                const state = blank.state === "revealed" ? "revealed" : "correct";
                return (
                  <span key={n} className={`word word-${state}`} style={{ "--i": k } as React.CSSProperties} title={state === "revealed" ? "Revelada (com ajuda)" : undefined}>
                    {part.text ?? blank.expected}
                  </span>
                );
              }
              const value = answers[item.id]?.[k] ?? "";
              return (
                <input
                  key={`${item.id}-${k}`}
                  ref={(el) => (inputs.current[k] = el)}
                  className={`blank-input blank-${liveState(blank.expected, value)}`}
                  style={{ width: `${Math.max(blank.expected.length, 2) + 0.6}ch` }}
                  value={value}
                  maxLength={blank.expected.length}
                  placeholder={"•".repeat(blank.expected.length)}
                  onChange={(e) => onBlankChange(item, k, e.target.value)}
                  onFocus={() => (focusedBlank.current = k)}
                  onKeyDown={(e) => onBlankKey(e, k)}
                  disabled={busy || item.status !== "pending"}
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  aria-label={`Palavra ${k + 1} de ${item.blanks.length}`}
                />
              );
            })}
          </p>
          {item.parts.some((p) => p.unheard) && (
            <p className="muted tiny center-text">Palavras riscadas estão na legenda, mas não são ditas no áudio.</p>
          )}

          {item.status === "pending" ? (
            <div className="sentence-actions">
              <>
                <div className="skip-wrap">
                  <button className="link small" onClick={() => setSkipMenu((v) => !v)}>
                    Pular…
                  </button>
                  {skipMenu && (
                    <div className="skip-menu card">
                      <button className="link small" onClick={() => skip(false)}>
                        Pular esta fala
                      </button>
                      <button className="link small" onClick={() => skip(true)}>
                        A legenda não corresponde ao áudio
                      </button>
                    </div>
                  )}
                </div>
                <button
                  className="btn btn-ghost"
                  onClick={showAnswer}
                  disabled={busy}
                  title="Mostra a frase inteira e toca de novo (conta como ajuda)"
                >
                  Mostrar resposta
                </button>
              </>
            </div>
          ) : (
            // Concluída: o resultado logo abaixo da frase e, embaixo dele, o "Continuar".
            <div className="done-actions">
              {item.status === "done" ? (
                <Reward item={item} streak={streakAt(session, index)} animate={celebrating === item.id} />
              ) : (
                <span className="muted small">
                  {item.flagged ? "Fala sinalizada: corrija-a em “Corrigir legendas”." : "Fala pulada."}
                </span>
              )}
              {item.flagged && (
                <Link className="link small" to={`/listening/video/${session.video.id}/edit#segment-${item.segment_id}`}>
                  Corrigir legenda
                </Link>
              )}
              {!finished && (
                <button ref={nextButton} className="btn btn-primary btn-lg" onClick={nextPending}>
                  Continuar
                </button>
              )}
            </div>
          )}
        </section>
      )}

      {finished && (
        <section className="card stack-sm session-summary">
          <h2>Sessão concluída 🎉</h2>
          <div className="tiles">
            <Tile value={pct(session.stats.accuracy)} label="acerto nas tentativas" />
            <Tile value={`${session.stats.done}/${session.stats.total}`} label="frases concluídas" />
            <Tile value={String(session.stats.helped)} label="palavras com ajuda" />
          </div>
          <div className="row end">
            <Link to="/listening/stats" className="btn btn-ghost">
              Ver histórico
            </Link>
            <Link to={`/listening/video/${session.video.id}`} className="btn btn-primary">
              Revisar ou mudar a dificuldade
            </Link>
          </div>
        </section>
      )}

    </div>
  );
}

function isPerfect(item: SessionItem): boolean {
  return item.status === "done" && item.blanks.every((b) => b.state === "correct" && b.errors === 0);
}

// Frases perfeitas seguidas até a frase `index` (inclusive).
function streakAt(session: Session, index: number): number {
  let streak = 0;
  for (let i = index; i >= 0 && isPerfect(session.items[i]); i--) streak++;
  return streak;
}

const CONFETTI_COLORS = ["#22c55e", "#4f46e5", "#f59e0b", "#ec4899", "#06b6d4", "#a855f7"];

function Reward({ item, streak, animate }: { item: SessionItem; streak: number; animate: boolean }) {
  const perfect = isPerfect(item);
  const helped = item.blanks.filter((b) => b.state === "revealed").length;
  const errors = item.blanks.reduce((sum, b) => sum + b.errors, 0);
  const confetti = useMemo(
    () =>
      Array.from({ length: 22 }, (_, n) => {
        const angle = (n / 22) * Math.PI * 2 + Math.random() * 0.4;
        const distance = 60 + Math.random() * 70;
        return {
          "--x": `${Math.cos(angle) * distance * 1.6}px`,
          "--y": `${Math.sin(angle) * distance - 30}px`,
          "--r": `${Math.random() * 540 - 270}deg`,
          background: CONFETTI_COLORS[n % CONFETTI_COLORS.length],
          animationDelay: `${Math.random() * 0.08}s`,
        } as React.CSSProperties;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [item.id, animate],
  );

  if (perfect) {
    return (
      <div className={`reward reward-perfect ${animate ? "reward-animate" : ""}`} role="status">
        {animate && confetti.map((style, n) => <span key={n} className="confetti" style={style} />)}
        <span className="reward-title">Perfeito!</span>
        {streak > 1 && <span className="reward-streak">🔥 {streak} seguidas</span>}
      </div>
    );
  }
  return (
    <div className={`reward reward-ok ${animate ? "reward-animate" : ""}`} role="status">
      <span className="reward-title">Frase concluída</span>
      <span className="reward-detail">
        {[errors && `${errors} erro${errors > 1 ? "s" : ""}`, helped && `${helped} com ajuda`].filter(Boolean).join(" · ")}
      </span>
    </div>
  );
}

function IconButton(props: { label: string; onClick: () => void; disabled?: boolean; active?: boolean; children: React.ReactNode }) {
  return (
    <button
      className={`icon-btn ${props.active ? "icon-btn-active" : ""}`}
      onClick={props.onClick}
      onMouseDown={(e) => e.preventDefault()} // o foco fica na lacuna: Enter continua conferindo
      disabled={props.disabled}
      title={props.label}
      aria-label={props.label}
    >
      {props.children}
    </button>
  );
}

function Tile({ value, label }: { value: string; label: string }) {
  return (
    <div className="tile">
      <div className="tile-value">{value}</div>
      <div className="tile-label">{label}</div>
    </div>
  );
}
