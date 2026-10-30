import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { DIFFICULTIES, DIFFICULTY_LABEL, Difficulty, formatTime, listeningApi, pct, RHYTHMS, VideoSummary } from "../../listeningApi";

const RHYTHM_KEY = "listening.rhythm";

function savedRhythm(): number {
  try {
    const value = Number(localStorage.getItem(RHYTHM_KEY));
    return RHYTHMS.some((r) => r.seconds === value) && localStorage.getItem(RHYTHM_KEY) !== null ? value : 30;
  } catch {
    return 30;
  }
}

const SOURCE_LABEL = {
  external: "legenda externa",
  embedded: "legenda embutida",
  whisper: "transcrição automática (Whisper)",
};

export function ListeningVideo() {
  const { id } = useParams();
  const videoId = Number(id);
  const navigate = useNavigate();
  const [video, setVideo] = useState<VideoSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [title, setTitle] = useState("");
  const asked = useRef(false);
  const [rhythm, setRhythm] = useState(savedRhythm);

  function chooseRhythm(seconds: number) {
    setRhythm(seconds);
    try {
      localStorage.setItem(RHYTHM_KEY, String(seconds)); // lembra o último ritmo usado
    } catch {
      /* sem armazenamento: vale só nesta visita */
    }
  }

  const load = useCallback(async () => {
    try {
      setVideo(await listeningApi.video(videoId));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [videoId]);

  // Ao abrir: se já está pronto, nada é reprocessado; senão, a preparação entra na fila (uma vez).
  useEffect(() => {
    (async () => {
      try {
        const v = await listeningApi.video(videoId);
        setVideo(v);
        if (!asked.current && v.present && v.status === "unprocessed") {
          asked.current = true;
          setVideo(await listeningApi.prepare(videoId));
        }
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, [videoId]);

  useEffect(() => {
    if (video?.status !== "processing") return;
    const timer = window.setInterval(load, 1200);
    return () => window.clearInterval(timer);
  }, [video?.status, load]);

  async function retry(force = false) {
    setError(null);
    try {
      setVideo(await listeningApi.prepare(videoId, force));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function start(difficulty: Difficulty, mode: "normal" | "review" = "normal", restart = false) {
    setStarting(true);
    setError(null);
    try {
      const session = await listeningApi.startSession(videoId, difficulty, mode, restart, rhythm);
      navigate(`/listening/session/${session.id}`);
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  }

  async function saveTitle() {
    if (!video) return;
    try {
      setVideo({ ...video, ...(await listeningApi.rename(video.id, title)) });
      setEditingTitle(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!video) {
    return error ? <div className="alert alert-error">{error}</div> : <div className="spinner" />;
  }

  const sessionsByDifficulty = new Map(video.active_sessions.filter((s) => s.mode === "normal").map((s) => [s.difficulty, s]));
  const review = video.active_sessions.find((s) => s.mode === "review");

  return (
    <div className="stack">
      <div className="page-head">
        <Link to="/listening" className="btn btn-ghost">
          ← Catálogo
        </Link>
      </div>

      <section className="video-hero card">
        <div className="thumb video-hero-thumb">
          {video.has_thumbnail ? <img src={listeningApi.thumbnailUrl(video)} alt="" /> : <div className="thumb-placeholder">🎬</div>}
        </div>
        <div className="stack-sm video-hero-info">
          {editingTitle ? (
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                saveTitle();
              }}
            >
              <input className="inline-input title-input" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus maxLength={200} />
              <button className="btn btn-primary">Salvar</button>
              <button type="button" className="btn btn-ghost" onClick={() => setEditingTitle(false)}>
                Cancelar
              </button>
            </form>
          ) : (
            <h1 className="row">
              {video.title}
              <button
                className="link small"
                onClick={() => {
                  setTitle(video.title);
                  setEditingTitle(true);
                }}
              >
                Renomear
              </button>
            </h1>
          )}
          <p className="muted small">
            {[video.category || null, formatTime(video.duration), video.file_name].filter(Boolean).join(" · ")}
          </p>
          {video.status === "ready" && (
            <p className="muted small">
              {video.segment_count} falas · {video.subtitle_source && SOURCE_LABEL[video.subtitle_source]}
              {video.has_translation
                ? video.translation_source === "ai"
                  ? " · tradução gerada por IA"
                  : " · com tradução"
                : " · sem tradução (o botão PT do player gera uma)"}
              {video.converted ? " · versão convertida para o navegador" : ""}
              {video.study.accuracy != null && ` · ${pct(video.study.accuracy)} de acerto`}
            </p>
          )}
          {!video.present && <div className="alert alert-warn">O arquivo não está mais na pasta videos/. O histórico foi mantido.</div>}
        </div>
      </section>

      {error && <div className="alert alert-error">{error}</div>}

      {video.status === "processing" && (
        <div className="card stack-sm">
          <div className="row">
            <span className="spinner spinner-sm" />
            <strong>{video.stage ?? "Na fila"}</strong>
            <span className="muted small">{Math.round((video.progress ?? 0) * 100)}%</span>
          </div>
          <div className="bar bar-lg">
            <span style={{ width: `${Math.round((video.progress ?? 0) * 100)}%` }} />
          </div>
          <p className="muted small">
            Preparando legendas e vídeo. Isso acontece só na primeira vez — você pode voltar ao catálogo enquanto isso.
          </p>
        </div>
      )}

      {video.status === "error" && (
        <div className="alert alert-error stack-sm">
          <strong>Não foi possível preparar este vídeo.</strong>
          <span>{video.error_message}</span>
          {video.present && (
            <div>
              <button className="btn btn-primary" onClick={() => retry()}>
                Tentar novamente
              </button>
            </div>
          )}
        </div>
      )}

      {video.status === "ready" && (
        <>
          {video.active_sessions.length > 0 && (
            <section className="stack-sm">
              <h2>Continuar</h2>
              <div className="resume-list">
                {video.active_sessions.map((s) => (
                  <Link key={s.id} to={`/listening/session/${s.id}`} className="card resume-card">
                    <div>
                      <strong>
                        {DIFFICULTY_LABEL[s.difficulty]}
                        {s.mode === "review" ? " · revisão" : ""}
                      </strong>
                      <p className="muted small">
                        {s.done} de {s.total} frases
                        {s.mode === "normal" && ` · ${RHYTHMS.find((r) => r.seconds === s.interval_seconds)?.label ?? ""}`}
                      </p>
                    </div>
                    <div className="bar">
                      <span style={{ width: `${(s.done / Math.max(s.total, 1)) * 100}%` }} />
                    </div>
                    <span className="mode-cta">Retomar →</span>
                  </Link>
                ))}
              </div>
            </section>
          )}

          <section className="stack-sm">
            <h2>Ritmo</h2>
            <p className="muted small">
              O vídeo corre com a legenda completa e para só nas frases para completar
              {video.segment_count ? ` (o vídeo tem ${video.segment_count} falas)` : ""}.
            </p>
            <div className="chips">
              {RHYTHMS.map((r) => (
                <button
                  key={r.seconds}
                  className={`chip ${rhythm === r.seconds ? "chip-active" : ""}`}
                  onClick={() => chooseRhythm(r.seconds)}
                  title={r.hint}
                >
                  {r.label} <span className="muted tiny">· {r.hint}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="stack-sm">
            <h2>Escolha a dificuldade</h2>
            <p className="muted small">
              As palavras ocultas são escolhidas na primeira vez e ficam fixas; cada dificuldade tem as suas.
            </p>
            <div className="difficulty-grid">
              {DIFFICULTIES.map((d) => {
                const active = sessionsByDifficulty.get(d.id);
                const resumable = active && active.interval_seconds === rhythm;
                return (
                  <div key={d.id} className="card difficulty-card">
                    <h3>{d.label}</h3>
                    <p className="muted small">{d.range}</p>
                    <button className="btn btn-primary" disabled={starting} onClick={() => start(d.id)}>
                      {resumable ? `Retomar (${active.done}/${active.total})` : "Começar"}
                    </button>
                    {active && !resumable && (
                      <p className="muted tiny">Começar com outro ritmo encerra a sessão em andamento desta dificuldade.</p>
                    )}
                    {resumable && (
                      <button
                        className="link small"
                        disabled={starting}
                        onClick={() =>
                          window.confirm("Começar do início? As lacunas continuam as mesmas e o histórico fica salvo.") &&
                          start(d.id, "normal", true)
                        }
                      >
                        Recomeçar do início
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          <section className="menu-grid">
            <button
              className={`card menu-card menu-button ${video.review_count ? "menu-primary" : "menu-disabled"}`}
              disabled={!video.review_count || starting}
              onClick={() => (review ? navigate(`/listening/session/${review.id}`) : start("easy", "review"))}
            >
              <span className="menu-icon" aria-hidden>
                🔁
              </span>
              <div>
                <h2>Revisar trechos errados</h2>
                <p className="muted">
                  {video.review_count ? `${video.review_count} fala(s) com erro ou ajuda.` : "Nenhum erro para revisar ainda."}
                </p>
              </div>
            </button>
            <Link to={`/listening/video/${video.id}/edit`} className="card menu-card">
              <span className="menu-icon" aria-hidden>
                ✏️
              </span>
              <div>
                <h2>Corrigir legendas</h2>
                <p className="muted">Ajuste texto e horários de falas imprecisas, sem transcrever de novo.</p>
              </div>
            </Link>
          </section>

          <p className="muted tiny">
            Legenda errada do começo ao fim?{" "}
            <button
              className="link tiny"
              onClick={() =>
                window.confirm("Preparar o vídeo de novo? As correções manuais das legendas serão substituídas.") && retry(true)
              }
            >
              Preparar novamente
            </button>
          </p>
        </>
      )}
    </div>
  );
}
