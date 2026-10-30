import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { formatTime, listeningApi, ListeningStats as Stats, pct } from "../../listeningApi";

export function ListeningStats() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    listeningApi.stats().then(setStats).catch((e) => setError(e.message));
  }, []);

  async function review(videoId: number) {
    try {
      const session = await listeningApi.startSession(videoId, "easy", "review");
      navigate(`/listening/session/${session.id}`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Histórico do Listening</h1>
          <p className="muted">Acertos, palavras difíceis e onde você parou em cada vídeo.</p>
        </div>
        <Link to="/listening" className="btn btn-ghost">
          ← Catálogo
        </Link>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {stats && stats.totals.attempts === 0 && (
        <div className="card center">
          <p>Nenhuma tentativa registrada ainda.</p>
          <Link to="/listening" className="btn btn-primary">
            Escolher um vídeo
          </Link>
        </div>
      )}

      {stats && stats.totals.attempts > 0 && (
        <>
          <div className="tiles">
            <div className="tile">
              <div className="tile-value">{pct(stats.totals.accuracy)}</div>
              <div className="tile-label">acerto nas tentativas</div>
            </div>
            <div className="tile">
              <div className="tile-value">{stats.totals.segments_done}</div>
              <div className="tile-label">falas concluídas</div>
            </div>
            <div className="tile">
              <div className="tile-value">{stats.totals.helped}</div>
              <div className="tile-label">palavras reveladas</div>
            </div>
          </div>

          <section className="stack-sm">
            <h2>Onde você parou</h2>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Vídeo</th>
                    <th className="num">Falas concluídas</th>
                    <th>Última sessão</th>
                    <th className="num">Para revisar</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {stats.progress.map((p) => (
                    <tr key={p.video_id}>
                      <td>
                        <Link to={`/listening/video/${p.video_id}`} className="table-link">
                          {p.title}
                        </Link>
                      </td>
                      <td className="num">
                        {p.segments_done}/{p.segments_total}
                      </td>
                      <td className="small">
                        {p.stopped_at ? (
                          <>
                            fala {p.stopped_at.position}/{p.stopped_at.items} · {formatTime(p.stopped_at.time)}
                            {p.stopped_at.status === "active" && (
                              <>
                                {" · "}
                                <Link className="link" to={`/listening/session/${p.stopped_at.session_id}`}>
                                  retomar
                                </Link>
                              </>
                            )}
                          </>
                        ) : (
                          "–"
                        )}
                      </td>
                      <td className="num">{p.to_review || "–"}</td>
                      <td className="num">
                        {p.to_review > 0 && (
                          <button className="link small" onClick={() => review(p.video_id)}>
                            Revisar
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="stack-sm">
            <h2>Acerto por vídeo e dificuldade</h2>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Vídeo</th>
                    <th>Dificuldade</th>
                    <th className="num">Tentativas</th>
                    <th className="num">Com ajuda</th>
                    <th className="num">Acerto</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.by_video_difficulty.map((r) => (
                    <tr key={`${r.video_id}-${r.difficulty}`}>
                      <td>{r.title}</td>
                      <td>{r.difficulty_label}</td>
                      <td className="num">{r.attempts}</td>
                      <td className="num">{r.helped}</td>
                      <td className="num">
                        <strong>{pct(r.accuracy)}</strong>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="stack-sm">
            <h2>Palavras mais erradas</h2>
            <p className="muted small">Ordenadas pela proporção de erros nas tentativas (revelar conta como erro).</p>
            {stats.words.length === 0 ? (
              <p className="muted">Nenhum erro até agora.</p>
            ) : (
              <div className="word-stats">
                {stats.words.map((w) => (
                  <div key={w.word} className="word-stat" title={`${w.helped} revelada(s)`}>
                    <span className="mono">{w.word}</span>
                    <span className="word-ratio">
                      {w.errors}/{w.attempts}
                    </span>
                    <span className="bar">
                      <span style={{ width: `${w.error_rate * 100}%` }} className="bar-error" />
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="stack-sm">
            <h2>Evolução por sessão</h2>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Vídeo</th>
                    <th>Dificuldade</th>
                    <th className="num">Falas</th>
                    <th className="num">Repetições</th>
                    <th className="num">Acerto</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.sessions.map((s) => (
                    <tr key={s.id}>
                      <td className="small">{new Date(s.started_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</td>
                      <td>
                        <Link to={`/listening/session/${s.id}`} className="table-link">
                          {s.title}
                        </Link>
                      </td>
                      <td className="small">
                        {s.difficulty_label}
                        {s.mode === "review" ? " · revisão" : ""}
                      </td>
                      <td className="num">
                        {s.done}/{s.items}
                      </td>
                      <td className="num">{s.replays}</td>
                      <td className="num">
                        <strong>{pct(s.accuracy)}</strong>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
