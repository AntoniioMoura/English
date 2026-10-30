import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { YoutubeDownloads } from "./YoutubeDownloads";
import { DIFFICULTY_LABEL, formatTime, Library, listeningApi, pct, VideoStatus, VideoSummary } from "../../listeningApi";

const STATUS_LABEL: Record<VideoStatus, string> = {
  unprocessed: "Não processado",
  processing: "Processando",
  ready: "Pronto",
  error: "Erro",
};

type Sort = "recent" | "title" | "duration" | "progress";

export function ListeningLibrary() {
  const [lib, setLib] = useState<Library | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [status, setStatus] = useState<VideoStatus | "all" | "missing">("all");
  const [sort, setSort] = useState<Sort>("recent");
  const [downloadOpen, setDownloadOpen] = useState(false);

  const scan = useCallback(async () => {
    setScanning(true);
    setError(null);
    try {
      setLib(await listeningApi.scan());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    scan();
  }, [scan]);

  // Enquanto houver vídeo processando ou miniatura sendo gerada, atualiza o catálogo sozinho.
  const busy =
    lib?.downloads.some((d) => d.status === "queued" || d.status === "downloading") ||
    lib?.videos.some((v) => v.status === "processing" || (v.present && !v.metadata_ready && lib.tools.ffmpeg));
  const reload = () => listeningApi.library().then(setLib).catch(() => undefined);
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(reload, 1500);
    return () => window.clearInterval(timer);
  }, [busy]);

  async function prepare(video: VideoSummary) {
    try {
      const updated = await listeningApi.prepare(video.id, false);
      setLib((prev) => prev && { ...prev, videos: prev.videos.map((v) => (v.id === updated.id ? { ...v, ...updated } : v)) });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const categories = useMemo(
    () => [...new Set((lib?.videos ?? []).map((v) => v.category))].sort((a, b) => a.localeCompare(b)),
    [lib],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const items = (lib?.videos ?? []).filter((v) => {
      if (status === "missing" ? v.present : !v.present) return false;
      if (status !== "all" && status !== "missing" && v.status !== status) return false;
      if (category !== null && v.category !== category) return false;
      return !q || `${v.title} ${v.file_name} ${v.category}`.toLowerCase().includes(q);
    });
    const recent = (v: VideoSummary) => v.study.last_studied_at ?? v.updated_at;
    const progress = (v: VideoSummary) => (v.segment_count ? v.study.items_done / v.segment_count : v.study.items_done);
    const sorters: Record<Sort, (a: VideoSummary, b: VideoSummary) => number> = {
      recent: (a, b) => recent(b).localeCompare(recent(a)),
      title: (a, b) => a.title.localeCompare(b.title, "pt-BR", { numeric: true }),
      duration: (a, b) => (a.duration ?? 0) - (b.duration ?? 0),
      progress: (a, b) => progress(b) - progress(a),
    };
    return [...items].sort(sorters[sort]);
  }, [lib, query, category, status, sort]);

  const continueWatching = (lib?.continue_watching ?? [])
    .map((id) => lib?.videos.find((v) => v.id === id))
    .filter((v): v is VideoSummary => !!v && v.present && v.status === "ready");
  const missingCount = lib?.videos.filter((v) => !v.present).length ?? 0;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Listening com vídeos</h1>
          <p className="muted">Assista e complete as palavras que faltam nas legendas.</p>
        </div>
        <div className="row">
          <Link to="/listening/stats" className="btn btn-ghost">
            Histórico e erros
          </Link>
          <button className="btn btn-ghost" onClick={() => setDownloadOpen((v) => !v)}>
            ⬇ Baixar do YouTube
          </button>
          <button className="btn btn-ghost" onClick={scan} disabled={scanning}>
            {scanning ? "Atualizando…" : "↻ Atualizar catálogo"}
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {lib && !lib.tools.ffmpeg && (
        <div className="alert alert-warn">
          FFmpeg não encontrado: miniaturas, legendas embutidas e conversão ficam indisponíveis. Instale com{" "}
          <code>winget install Gyan.FFmpeg</code> e reinicie o English Builder.
        </div>
      )}
      {lib && !lib.tools.transcriber && (
        <div className="alert alert-info">
          Transcrição local desativada (faster-whisper não instalado). Vídeos sem legenda em inglês não poderão ser
          preparados.
        </div>
      )}
      {lib?.changes && (lib.changes.added > 0 || lib.changes.missing > 0 || lib.changes.moved > 0) && (
        <p className="muted small">
          {[
            lib.changes.added && `${lib.changes.added} novo(s)`,
            lib.changes.moved && `${lib.changes.moved} movido(s)`,
            lib.changes.missing && `${lib.changes.missing} ausente(s)`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}

      {lib && (
        <YoutubeDownloads
          open={downloadOpen}
          available={lib.tools.youtube}
          downloads={lib.downloads}
          onChange={reload}
          onClose={() => setDownloadOpen(false)}
        />
      )}

      {lib && lib.videos.length === 0 && (
        <div className="card center">
          <span className="icon-tile accent-green" aria-hidden>
            🎬
          </span>
          <h2>Nenhum vídeo ainda</h2>
          <p className="muted">
            Coloque arquivos <code>.mp4</code>, <code>.mkv</code>, <code>.mov</code> ou <code>.webm</code> na pasta abaixo
            (subpastas viram categorias). Legendas <code>nome.en.srt</code> ao lado do vídeo são usadas
            automaticamente.
          </p>
          <code className="path">{lib.videos_dir}</code>
          <div className="row">
            <button className="btn btn-primary" onClick={scan} disabled={scanning}>
              Atualizar catálogo
            </button>
            <button className="btn btn-ghost" onClick={() => setDownloadOpen(true)}>
              ⬇ Baixar do YouTube
            </button>
          </div>
        </div>
      )}

      {continueWatching.length > 0 && (
        <section className="stack-sm">
          <h2>Continuar assistindo</h2>
          <div className="shelf">
            {continueWatching.map((v) => (
              <VideoCard key={v.id} video={v} onPrepare={prepare} compact />
            ))}
          </div>
        </section>
      )}

      {lib && lib.videos.length > 0 && (
        <section className="stack-sm">
          <div className="library-toolbar">
            <input
              className="search"
              type="search"
              placeholder="Buscar vídeo…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Buscar vídeo"
            />
            <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)} aria-label="Status">
              <option value="all">Todos os status</option>
              {(Object.keys(STATUS_LABEL) as VideoStatus[]).map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]}
                </option>
              ))}
              {missingCount > 0 && <option value="missing">Arquivo ausente ({missingCount})</option>}
            </select>
            <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Ordenar">
              <option value="recent">Mais recentes</option>
              <option value="title">Título</option>
              <option value="duration">Duração</option>
              <option value="progress">Progresso</option>
            </select>
          </div>
          {categories.length > 1 && (
            <div className="chips">
              <button className={`chip ${category === null ? "chip-active" : ""}`} onClick={() => setCategory(null)}>
                Todas
              </button>
              {categories.map((c) => (
                <button key={c} className={`chip ${category === c ? "chip-active" : ""}`} onClick={() => setCategory(c)}>
                  {c || "Sem categoria"}
                </button>
              ))}
            </div>
          )}
          <div className="video-grid">
            {visible.map((v) => (
              <VideoCard key={v.id} video={v} onPrepare={prepare} />
            ))}
          </div>
          {visible.length === 0 && <p className="muted">Nenhum vídeo com esses filtros.</p>}
        </section>
      )}
    </div>
  );
}

function VideoCard({ video: v, onPrepare, compact }: { video: VideoSummary; onPrepare: (v: VideoSummary) => void; compact?: boolean }) {
  const navigate = useNavigate();
  const session = v.active_sessions[0];
  const progress = session ? session.done / Math.max(session.total, 1) : null;
  const open = () => v.present && navigate(`/listening/video/${v.id}`);

  return (
    <article
      className={`video-card ${!v.present ? "video-missing" : ""} ${compact ? "video-card-compact" : ""}`}
      onClick={open}
      role="link"
      tabIndex={v.present ? 0 : -1}
      onKeyDown={(e) => e.key === "Enter" && open()}
      aria-label={v.title}
    >
      <div className="thumb">
        {v.has_thumbnail ? (
          <img src={listeningApi.thumbnailUrl(v)} alt="" loading="lazy" />
        ) : (
          <div className="thumb-placeholder" aria-hidden>
            {v.metadata_ready || !v.present ? "🎬" : <span className="spinner spinner-sm" />}
          </div>
        )}
        {v.duration != null && <span className="thumb-duration">{formatTime(v.duration)}</span>}
        {progress != null && (
          <span className="thumb-progress" aria-hidden>
            <span style={{ width: `${Math.max(progress * 100, 3)}%` }} />
          </span>
        )}
      </div>
      <div className="video-body">
        <h3 title={v.file_name}>{v.title}</h3>
        <div className="video-meta">
          {v.category && <span>{v.category}</span>}
          {!v.present ? (
            <span className="vstatus vstatus-error">Arquivo ausente</span>
          ) : (
            <span className={`vstatus vstatus-${v.status}`}>{STATUS_LABEL[v.status]}</span>
          )}
          {v.study.accuracy != null && <span>{pct(v.study.accuracy)} de acerto</span>}
        </div>
        {session && (
          <p className="muted tiny">
            {DIFFICULTY_LABEL[session.difficulty]}
            {session.mode === "review" ? " · revisão" : ""} · {session.done}/{session.total} falas
          </p>
        )}
        {v.status === "processing" && (
          <div className="mini-progress" title={v.stage ?? undefined}>
            <span className="muted tiny">{v.stage ?? "Na fila"}</span>
            <div className="bar">
              <span style={{ width: `${Math.round((v.progress ?? 0) * 100)}%` }} />
            </div>
          </div>
        )}
        {v.status === "error" && v.present && (
          <p className="error-text tiny clamp-2" title={v.error_message ?? undefined}>
            {v.error_message}
          </p>
        )}
        {v.present && (v.status === "unprocessed" || v.status === "error") && !compact && (
          <button
            className="link small"
            onClick={(e) => {
              e.stopPropagation();
              onPrepare(v);
            }}
          >
            {v.status === "error" ? "Tentar novamente" : "Preparar agora"}
          </button>
        )}
      </div>
    </article>
  );
}
