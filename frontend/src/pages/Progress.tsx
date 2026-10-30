import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ExerciseStatus, ExerciseSummary } from "../api";

const STATUS_LABEL: Record<ExerciseStatus, string> = {
  in_progress: "Em andamento",
  awaiting_evaluation: "Aguardando avaliação",
  evaluated: "Concluído",
};

export function Progress() {
  const [items, setItems] = useState<ExerciseSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.finishedExercises().then(setItems).catch((e) => setError(e.message));
  }, []);

  async function remove(item: ExerciseSummary) {
    const ok = window.confirm(
      `Excluir este estudo?\n\n"${item.latest_text ?? item.frame_text}"\n\nAs frases e a avaliação serão apagadas permanentemente.`,
    );
    if (!ok) return;
    setError(null);
    try {
      await api.deleteExercise(item.id);
      setItems((prev) => prev?.filter((i) => i.id !== item.id) ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Meu progresso</h1>
          <p className="muted">Seus estudos concluídos no Criador de frases.</p>
        </div>
        <Link to="/builder" className="btn btn-ghost">
          ← Criador de frases
        </Link>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {items && items.length === 0 && (
        <div className="card center">
          <p>Nenhum estudo concluído ainda.</p>
          <Link to="/builder" className="btn btn-primary">
            Começar agora
          </Link>
        </div>
      )}

      <ul className="history">
        {items?.map((item) => (
          <li key={item.id} className="card history-item">
            <Link to={`/builder/${item.id}`} className="history-main">
              <span className="muted small">{item.frame_text}</span>
              <span>{item.latest_text}</span>
            </Link>
            <div className="history-meta">
              <span className={`status status-${item.status}`}>{STATUS_LABEL[item.status]}</span>
              <span className="muted tiny">{new Date(item.started_at).toLocaleDateString("pt-BR")}</span>
              <button className="link small danger" onClick={() => remove(item)}>
                Excluir
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
