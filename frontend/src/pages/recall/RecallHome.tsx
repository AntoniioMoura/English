import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RecallStatus } from "../../components/RecallStatus";
import { recallApi, RecallProgress } from "../../recallApi";

export function RecallHome() {
  const [progress, setProgress] = useState<RecallProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    recallApi.progress().then(setProgress).catch((e) => setError(e.message));
  }, []);

  const blocked = progress?.quota.blocked;
  const due = progress?.due_reviews ?? 0;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Anki Premium</h1>
          <p className="muted">Traduza frases em português que usam as suas palavras. Os erros viram revisões.</p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {progress && <RecallStatus quota={progress.quota} due={due} />}
      {blocked && <div className="alert alert-warn">Limite diário atingido. Você ainda pode revisar seus erros.</div>}

      <section className="menu-grid">
        <Link
          to="/recall/practice"
          className={`card menu-card ${blocked ? "menu-disabled" : "menu-primary"}`}
          aria-disabled={blocked}
          onClick={(e) => blocked && e.preventDefault()}
        >
          <span className="menu-icon" aria-hidden>✍️</span>
          <div>
            <h2>Praticar</h2>
            <p className="muted">{blocked ? "Novas frases liberadas amanhã." : "Frases novas com as suas palavras."}</p>
          </div>
        </Link>
        <Link to="/recall/review" className={`card menu-card ${blocked && due ? "menu-primary" : ""}`}>
          <span className="menu-icon" aria-hidden>🔁</span>
          <div>
            <h2>Revisar erros</h2>
            <p className="muted">{due ? `${due} dificuldade(s) para revisar agora.` : "Nenhuma revisão pendente agora."}</p>
          </div>
        </Link>
        <Link to="/recall/words" className="card menu-card">
          <span className="menu-icon" aria-hidden>📚</span>
          <div>
            <h2>Minhas palavras</h2>
            <p className="muted">
              {progress ? `${progress.words.enabled} ativa(s) de ${progress.words.total}.` : "Cadastre palavras e expressões."}
            </p>
          </div>
        </Link>
        <Link to="/recall/history" className="card menu-card">
          <span className="menu-icon" aria-hidden>🗂️</span>
          <div>
            <h2>Histórico e progresso</h2>
            <p className="muted">Tentativas, palavras praticadas e tópicos com dificuldade.</p>
          </div>
        </Link>
      </section>
    </div>
  );
}
