import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { formatTime, listeningApi, Segment, VideoSummary } from "../../listeningApi";

type Draft = { text: string; start: string; end: string; translation_pt: string };

const toDraft = (s: Segment): Draft => ({
  text: s.text,
  start: s.start.toFixed(2),
  end: s.end.toFixed(2),
  translation_pt: s.translation_pt ?? "",
});

export function ListeningEditor() {
  const { id } = useParams();
  const videoId = Number(id);
  const location = useLocation();
  const [video, setVideo] = useState<VideoSummary | null>(null);
  const [segments, setSegments] = useState<Segment[] | null>(null);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [saving, setSaving] = useState<number | null>(null);
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [query, setQuery] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number | null>(null);

  useEffect(() => {
    listeningApi.video(videoId).then(setVideo).catch(() => undefined);
    listeningApi.segments(videoId).then((list) => {
      setSegments(list);
      setDrafts(Object.fromEntries(list.map((s) => [s.id, toDraft(s)])));
      setOnlyFlagged(list.some((s) => s.flagged) && !location.hash);
    });
  }, [videoId, location.hash]);

  useEffect(() => {
    if (!segments || !location.hash) return;
    window.setTimeout(() => document.querySelector(location.hash)?.scrollIntoView({ block: "center" }), 50);
  }, [segments, location.hash]);

  function play(start: number, end: number) {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(start - 0.15, 0);
    stopAt.current = end;
    video.play().catch(() => undefined);
  }

  async function save(segment: Segment) {
    const draft = drafts[segment.id];
    const start = Number(draft.start.replace(",", "."));
    const end = Number(draft.end.replace(",", "."));
    if (!isFinite(start) || !isFinite(end)) {
      setErrors((e) => ({ ...e, [segment.id]: "Use segundos, por exemplo 12.5" }));
      return;
    }
    setSaving(segment.id);
    try {
      const updated = await listeningApi.updateSegment(segment.id, {
        text: draft.text,
        start,
        end,
        translation_pt: draft.translation_pt,
        flagged: false,
      });
      setSegments((list) => list?.map((s) => (s.id === updated.id ? updated : s)) ?? null);
      setDrafts((d) => ({ ...d, [updated.id]: toDraft(updated) }));
      setErrors(({ [segment.id]: _, ...rest }) => rest);
    } catch (e) {
      setErrors((prev) => ({ ...prev, [segment.id]: (e as Error).message }));
    } finally {
      setSaving(null);
    }
  }

  const dirty = (s: Segment) => {
    const d = drafts[s.id];
    return d && JSON.stringify(d) !== JSON.stringify(toDraft(s));
  };
  const q = query.trim().toLowerCase();
  const visible = (segments ?? []).filter(
    (s) => (!onlyFlagged || s.flagged) && (!q || s.text.toLowerCase().includes(q) || s.original_text.toLowerCase().includes(q)),
  );
  const flaggedCount = segments?.filter((s) => s.flagged).length ?? 0;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Corrigir legendas</h1>
          <p className="muted">{video?.title}</p>
        </div>
        <Link to={`/listening/video/${videoId}`} className="btn btn-ghost">
          ← Voltar ao vídeo
        </Link>
      </div>

      <div className="editor-layout">
        <div className="editor-video">
          <video
            ref={videoRef}
            src={listeningApi.streamUrl(videoId)}
            controls
            preload="metadata"
            onTimeUpdate={(e) => {
              if (stopAt.current != null && e.currentTarget.currentTime >= stopAt.current) {
                e.currentTarget.pause();
                stopAt.current = null;
              }
            }}
          />
          <p className="muted tiny">
            Correções valem para as próximas sessões e para falas ainda não respondidas. A transcrição não é refeita.
          </p>
        </div>

        <div className="stack-sm">
          <div className="library-toolbar">
            <input className="search" type="search" placeholder="Buscar no texto…" value={query} onChange={(e) => setQuery(e.target.value)} />
            {flaggedCount > 0 && (
              <label className="row small">
                <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} />
                Só sinalizadas ({flaggedCount})
              </label>
            )}
          </div>
          {segments === null && <div className="spinner" />}
          <ol className="segment-list">
            {visible.map((s) => {
              const d = drafts[s.id];
              return (
                <li key={s.id} id={`segment-${s.id}`} className={`card segment-row ${s.flagged ? "segment-flagged" : ""}`}>
                  <div className="segment-times">
                    <button className="icon-btn" title="Ouvir trecho" onClick={() => play(Number(d.start), Number(d.end))}>
                      ▶
                    </button>
                    <span className="muted tiny">#{s.idx + 1}</span>
                    <input
                      className="inline-input time-input"
                      value={d.start}
                      onChange={(e) => setDrafts((all) => ({ ...all, [s.id]: { ...d, start: e.target.value } }))}
                      aria-label="Início (s)"
                      title={formatTime(Number(d.start), true)}
                    />
                    <span className="muted">→</span>
                    <input
                      className="inline-input time-input"
                      value={d.end}
                      onChange={(e) => setDrafts((all) => ({ ...all, [s.id]: { ...d, end: e.target.value } }))}
                      aria-label="Fim (s)"
                      title={formatTime(Number(d.end), true)}
                    />
                    {s.flagged && <span className="vstatus vstatus-error">Sinalizada</span>}
                    {s.edited && <span className="vstatus vstatus-ready">Editada</span>}
                  </div>
                  <textarea
                    className="inline-input"
                    rows={2}
                    value={d.text}
                    onChange={(e) => setDrafts((all) => ({ ...all, [s.id]: { ...d, text: e.target.value } }))}
                    aria-label="Texto em inglês"
                  />
                  <input
                    className="inline-input"
                    value={d.translation_pt}
                    placeholder="Tradução (opcional)"
                    onChange={(e) => setDrafts((all) => ({ ...all, [s.id]: { ...d, translation_pt: e.target.value } }))}
                    aria-label="Tradução"
                  />
                  {s.edited && s.original_text !== s.text && <p className="muted tiny">Original: {s.original_text}</p>}
                  {errors[s.id] && <p className="error-text small">{errors[s.id]}</p>}
                  {(dirty(s) || s.flagged) && (
                    <div className="row end">
                      {dirty(s) && (
                        <button className="btn btn-ghost" onClick={() => setDrafts((all) => ({ ...all, [s.id]: toDraft(s) }))}>
                          Desfazer
                        </button>
                      )}
                      <button className="btn btn-primary" onClick={() => save(s)} disabled={saving === s.id}>
                        {saving === s.id ? "Salvando…" : s.flagged && !dirty(s) ? "Marcar como correta" : "Salvar"}
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </div>
  );
}
