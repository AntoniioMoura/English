import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { recallApi, RecallProgress, Verdict } from "../../recallApi";

const VERDICT_LABEL: Record<Verdict, string> = {
  correct: "Correta",
  incorrect: "Com erro",
  needs_review: "Incerta",
};

function Tile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="tile">
      <div className="tile-value">{value}</div>
      <div className="tile-label">{label}</div>
      {hint && <div className="muted tiny">{hint}</div>}
    </div>
  );
}

export function RecallHistory() {
  const [data, setData] = useState<RecallProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    recallApi.progress().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="alert alert-error">{error}</div>;
  if (!data) return <p className="muted">Carregando…</p>;

  const newTotal = Object.values(data.new).reduce((a, b) => a + (b ?? 0), 0);
  const reviewTotal = Object.values(data.review).reduce((a, b) => a + (b ?? 0), 0);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Histórico e progresso</h1>
          <p className="muted">Métricas do Anki Premium (tradução), separadas do Criador de frases.</p>
        </div>
        <Link to="/recall" className="btn btn-ghost">
          ← Anki Premium
        </Link>
      </div>

      <div className="tiles">
        <Tile label="Erros de hoje" value={`${data.quota.errors_today}/${data.quota.limit}`} />
        <Tile label="Revisões pendentes" value={data.due_reviews} />
        <Tile label="Frases novas corretas" value={data.new.correct ?? 0} hint={`de ${newTotal} respondidas`} />
        <Tile label="Revisões corretas" value={data.review.correct ?? 0} hint={`de ${reviewTotal} feitas`} />
        <Tile
          label="Palavras usadas"
          value={data.words.demonstrated}
          hint={`${data.words.practiced} praticadas de ${data.words.total}`}
        />
      </div>

      {data.topics.length > 0 && (
        <section className="stack-sm">
          <h3>Tópicos gramaticais</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Tópico</th>
                  <th className="num">Erros</th>
                  <th className="num">Acertos</th>
                </tr>
              </thead>
              <tbody>
                {data.topics.map((t) => (
                  <tr key={t.topic_id}>
                    <td>{t.name_pt}</td>
                    <td className="num">{t.errors}</td>
                    <td className="num">{t.correct}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="stack-sm">
        <h3>Tentativas</h3>
        {data.history.length === 0 && <p className="muted">Nenhuma tentativa ainda.</p>}
        <ul className="history">
          {data.history.map((h) => (
            <li key={h.id} className="card history-item">
              <div className="history-main">
                <span>{h.sentence_pt}</span>
                <span className="muted small">{h.answer_text}</span>
              </div>
              <div className="history-meta">
                {h.score !== null && <span className="score-chip">{h.score}%</span>}
                <span className={`status verdict-chip-${h.verdict ?? "pending"}`}>
                  {h.verdict ? VERDICT_LABEL[h.verdict] : "Avaliação pendente"}
                </span>
                <span className="muted tiny">
                  {h.mode === "review" ? "Revisão · " : ""}
                  {new Date(h.created_at).toLocaleDateString("pt-BR")}
                  {h.targets ? ` · ${h.targets}` : ""}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
