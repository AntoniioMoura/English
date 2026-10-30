import { KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatTime, ItemResult, listeningApi, pct, Session, SessionItem } from "../../listeningApi";

const PREROLL = 0.15; // começa um pouco antes para não cortar a primeira sílaba

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
  const [showTranslation, setShowTranslation] = useState(false);
  const [needsGesture, setNeedsGesture] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [skipMenu, setSkipMenu] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number | null>(null);
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const nextButton = useRef<HTMLButtonElement>(null);
  const focusedBlank = useRef(0);

  useEffect(() => {
    listeningApi
      .session(sessionId)
      .then((s) => {
        setSession(s);
        setIndex(s.current_index);
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
    setTime(runStart(session, index));
    playUntil(item, runStart(session, index));
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

  function focusFirstOpen(it: SessionItem) {
    const open = it.blanks.find((b) => b.state === "hidden" || b.state === "wrong");
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

  const check = () => {
    if (!item || !session || item.status !== "pending") return;
    const typed = answers[item.id] ?? [];
    if (!typed.some((t, k) => t.trim() && ["hidden", "wrong"].includes(item.blanks[k].state))) return;
    run(() => listeningApi.check(session.id, item.id, typed.map((t) => t || null)));
  };

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

  // Lacunas não têm espaço: digitar/colar "word word" distribui as palavras pelas lacunas seguintes.
  function onBlankChange(it: SessionItem, k: number, value: string) {
    const open = it.blanks.filter((b) => b.blank >= k && ["hidden", "wrong"].includes(b.state)).map((b) => b.blank);
    const pieces = value.split(/\s+/);
    setAnswers((prev) => {
      const list = [...(prev[it.id] ?? it.blanks.map(() => ""))];
      if (pieces.length === 1) {
        list[k] = value;
      } else {
        const words = pieces.filter(Boolean);
        open.forEach((blank, n) => n < words.length && (list[blank] = words[n]));
      }
      return { ...prev, [it.id]: list };
    });
    if (pieces.length > 1) {
      const filled = pieces.filter(Boolean).length;
      const target = open[Math.min(value.endsWith(" ") || !pieces[0] ? filled : filled - 1, open.length - 1)];
      if (target !== undefined && target !== k) window.setTimeout(() => inputs.current[target]?.focus(), 0);
    }
  }

  function onBlankKey(e: KeyboardEvent<HTMLInputElement>, k: number) {
    const value = (e.target as HTMLInputElement).value;
    if (e.key === " " && !e.ctrlKey && !value.trim()) {
      e.preventDefault(); // espaço numa lacuna vazia não faz nada
    } else if (e.key === "Backspace" && !value) {
      e.preventDefault();
      moveFocus(k, -1);
    }
  }

  function moveFocus(k: number, dir: 1 | -1) {
    if (!item) return;
    for (let n = k + dir; n >= 0 && n < item.blanks.length; n += dir) {
      if (["hidden", "wrong"].includes(item.blanks[n].state)) {
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
        if (watching) playSegment(item); // pula o contexto e vai direto à frase
        else if (item.status === "pending") check();
        else nextPending();
      } else if (e.key === "PageDown") {
        e.preventDefault();
        goTo(index + 1);
      } else if (e.key === "PageUp") {
        e.preventDefault();
        goTo(index - 1);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const progress = useMemo(() => {
    if (!session) return 0;
    return (session.stats.done + session.stats.skipped) / Math.max(session.stats.total, 1);
  }, [session]);

  if (!session) {
    return error ? <div className="alert alert-error">{error}</div> : <div className="spinner" />;
  }

  const finished = session.status !== "active";
  const translationAvailable = session.video.has_translation && !!item?.translation_pt;
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
          <IconButton label="Próxima frase (PageDown)" onClick={() => goTo(index + 1)} disabled={index >= session.items.length - 1}>
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
            label={showTranslation ? "Ocultar tradução" : "Mostrar tradução"}
            onClick={() => setShowTranslation((v) => !v)}
            disabled={!session.video.has_translation}
            active={showTranslation}
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
          <p className="sentence sentence-context" aria-live="polite">
            {contextLine?.text ?? "\u00a0"}
          </p>
          {showTranslation && contextLine?.translation_pt && <p className="translation">{contextLine.translation_pt}</p>}
          <div className="sentence-actions">
            <span className="muted small">
              {playing
                ? `Assistindo… a próxima frase para completar chega em ${Math.max(Math.ceil(item.start - time), 1)} s.`
                : "Pausado."}
            </span>
            <button className="btn btn-ghost" onClick={() => playSegment(item)}>
              Ir direto para a frase →
            </button>
          </div>
        </section>
      )}

      {item && !watching && (
        <section className={`sentence-area ${item.status !== "pending" ? "sentence-done" : ""}`}>
          <p className="sentence" aria-live="polite">
            {item.parts.map((part, n) => {
              if (part.blank === null) return <span key={n}>{part.text}</span>;
              const blank = item.blanks[part.blank];
              if (blank.state === "correct" || blank.state === "revealed" || part.text !== null) {
                return (
                  <span key={n} className={`word word-${blank.state}`} title={blank.state === "revealed" ? "Revelada (com ajuda)" : undefined}>
                    {part.text ?? blank.answer}
                  </span>
                );
              }
              const k = part.blank;
              return (
                <input
                  key={`${item.id}-${k}`}
                  ref={(el) => (inputs.current[k] = el)}
                  className={`blank-input ${blank.state === "wrong" ? "blank-wrong" : ""}`}
                  style={{ width: `${Math.max(blank.length, 2) + 0.6}ch` }}
                  value={answers[item.id]?.[k] ?? ""}
                  placeholder={"•".repeat(blank.length)}
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
          {showTranslation && (
            <p className="translation">{translationAvailable ? item.translation_pt : "Sem tradução para esta fala."}</p>
          )}

          <div className="sentence-actions">
            {item.status === "pending" ? (
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
                <span className="muted tiny">Enter confere · Espaço vai para a próxima lacuna</span>
                <button
                  className="btn btn-ghost"
                  onClick={showAnswer}
                  disabled={busy}
                  title="Mostra a frase inteira e toca de novo (conta como ajuda)"
                >
                  Mostrar resposta
                </button>
                <button className="btn btn-primary" onClick={check} disabled={busy}>
                  Conferir
                </button>
              </>
            ) : (
              <>
                <span className={item.status === "done" && summarize(item).startsWith("Perfeito") ? "ok-text small" : "muted small"}>
                  {item.status === "skipped"
                    ? item.flagged
                      ? "Fala sinalizada: corrija-a em “Corrigir legendas”."
                      : "Fala pulada."
                    : summarize(item)}
                </span>
                {item.flagged && (
                  <Link className="link small" to={`/listening/video/${session.video.id}/edit#segment-${item.segment_id}`}>
                    Corrigir legenda
                  </Link>
                )}
                {!finished && (
                  <button ref={nextButton} className="btn btn-primary" onClick={nextPending}>
                    Próxima →
                  </button>
                )}
              </>
            )}
          </div>
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

      <p className="muted tiny shortcuts">
        Atalhos: Enter conferir/próxima · Ctrl+Espaço repetir a frase · Ctrl+Enter revelar a palavra em foco ·
        PageUp/PageDown navegar{item ? ` · repetições desta frase: ${item.replays}` : ""}
      </p>
    </div>
  );
}

function summarize(item: SessionItem): string {
  const helped = item.blanks.filter((b) => b.state === "revealed").length;
  const errors = item.blanks.reduce((sum, b) => sum + b.errors, 0);
  if (!helped && !errors) return "Perfeito! ✓";
  return [errors && `${errors} erro(s)`, helped && `${helped} com ajuda`].filter(Boolean).join(" · ");
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
