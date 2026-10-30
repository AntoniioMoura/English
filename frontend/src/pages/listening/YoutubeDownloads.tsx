import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { Download, listeningApi } from "../../listeningApi";

const QUALITIES = [360, 480, 720, 1080];

// Formulário "Baixar do YouTube" + lista dos downloads recentes (o catálogo já atualiza a lista sozinho).
export function YoutubeDownloads(props: {
  open: boolean;
  available: boolean;
  downloads: Download[];
  onChange: () => void;
  onClose: () => void;
}) {
  const [url, setUrl] = useState("");
  const [category, setCategory] = useState("YouTube");
  const [quality, setQuality] = useState(720);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSending(true);
    setError(null);
    try {
      await listeningApi.download(url.trim(), category, quality);
      setUrl("");
      props.onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSending(false);
    }
  }

  async function act(action: () => Promise<unknown>) {
    try {
      await action();
      props.onChange();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!props.open && props.downloads.length === 0) return null;

  return (
    <section className="stack-sm">
      {props.open && (
        <form className="card stack-sm download-form" onSubmit={submit}>
          <div className="row">
            <h2>Baixar do YouTube</h2>
            <button type="button" className="link small download-close" onClick={props.onClose}>
              Fechar
            </button>
          </div>
          {!props.available ? (
            <div className="alert alert-warn">
              yt-dlp não está instalado. Rode <code>backend\.venv\Scripts\pip install yt-dlp</code> e reinicie.
            </div>
          ) : (
            <>
              <div className="download-fields">
                <label className="field download-url">
                  Link do vídeo
                  <input
                    type="url"
                    required
                    placeholder="https://www.youtube.com/watch?v=…"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    autoFocus
                  />
                </label>
                <label className="field">
                  Categoria (subpasta)
                  <input value={category} onChange={(e) => setCategory(e.target.value)} maxLength={60} />
                </label>
                <label className="field">
                  Qualidade máx.
                  <select value={quality} onChange={(e) => setQuality(Number(e.target.value))}>
                    {QUALITIES.map((q) => (
                      <option key={q} value={q}>
                        {q}p
                      </option>
                    ))}
                  </select>
                </label>
                <button className="btn btn-primary" disabled={sending || !url.trim()}>
                  {sending ? "Enviando…" : "Baixar"}
                </button>
              </div>
              <p className="muted tiny">
                O vídeo vai para <code>videos/{category || "…"}</code> com as legendas em inglês/português feitas pelo autor
                (se houver) e já é preparado para estudo. Sem legenda, a transcrição local cuida disso. Baixe apenas
                vídeos que você tem direito de guardar.
              </p>
            </>
          )}
          {error && <div className="alert alert-error">{error}</div>}
        </form>
      )}

      {props.downloads.length > 0 && (
        <ul className="download-list">
          {props.downloads.map((d) => (
            <li key={d.id} className="card download-item">
              <div className="download-main">
                <strong className="clamp-2">{d.title ?? d.url}</strong>
                {(d.status === "queued" || d.status === "downloading") && (
                  <div className="mini-progress">
                    <span className="muted tiny">
                      {d.stage ?? "Na fila"} · {Math.round((d.progress ?? 0) * 100)}%
                    </span>
                    <div className="bar">
                      <span style={{ width: `${Math.round((d.progress ?? 0) * 100)}%` }} />
                    </div>
                  </div>
                )}
                {d.status === "error" && <p className="error-text tiny">{d.error_message}</p>}
                {d.status === "done" && (
                  <p className="muted tiny">
                    Salvo em <code>videos/{d.rel_path}</code>
                  </p>
                )}
              </div>
              <div className="row">
                {d.status === "done" && d.video_id && (
                  <Link className="btn btn-ghost" to={`/listening/video/${d.video_id}`}>
                    Abrir
                  </Link>
                )}
                {d.status === "error" && (
                  <button className="btn btn-ghost" onClick={() => act(() => listeningApi.retryDownload(d.id))}>
                    Tentar novamente
                  </button>
                )}
                {(d.status === "done" || d.status === "error") && (
                  <button className="link small" onClick={() => act(() => listeningApi.dismissDownload(d.id))} title="Tirar da lista">
                    ✕
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
