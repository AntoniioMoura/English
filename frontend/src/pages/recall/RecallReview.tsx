import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../api";
import { RecallCard } from "../../components/RecallCard";
import { RecallStatus } from "../../components/RecallStatus";
import { recallApi, RecallExercise, ReviewItem } from "../../recallApi";

const brDateTime = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

export function RecallReview() {
  const [due, setDue] = useState<ReviewItem[] | null>(null);
  const [upcoming, setUpcoming] = useState<ReviewItem[]>([]);
  const [exercise, setExercise] = useState<RecallExercise | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(async () => {
    setLoading(true);
    setError(null);
    setExercise(null);
    try {
      const reviews = await recallApi.dueReviews();
      setDue(reviews.due);
      setUpcoming(reviews.upcoming);
      // Se a IA não conseguir criar a frase de uma revisão, segue para a próxima pendente.
      let lastError: Error | null = null;
      for (const item of reviews.due) {
        try {
          setExercise(await recallApi.reviewExercise(item.id));
          lastError = null;
          break;
        } catch (e) {
          lastError = e as Error;
          if ((e as ApiError).status !== 503) break;
        }
      }
      if (lastError) setError(lastError.message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    start();
  }, [start]);

  const done = exercise?.status === "evaluated";

  return (
    <div className="stack narrow-wide">
      <div className="page-head">
        <h1>Revisar erros</h1>
        <Link to="/recall" className="btn btn-ghost">
          ← Anki Premium
        </Link>
      </div>

      {exercise && <RecallStatus quota={exercise.quota} due={exercise.due_reviews} />}
      {error && (
        <div className="alert alert-error">
          {error}{" "}
          <button className="link" onClick={start}>
            Tentar de novo
          </button>
        </div>
      )}

      {loading && !exercise && (
        <div className="card center">
          <div className="spinner" />
          <p className="muted">Preparando uma frase nova para revisar…</p>
        </div>
      )}

      {due && due.length === 0 && !loading && (
        <div className="card center">
          <p>Nenhuma revisão pendente agora. 🎉</p>
          {upcoming.length > 0 && (
            <div className="stack-sm">
              <span className="muted small">Próximas revisões</span>
              <ul className="plain-list small">
                {upcoming.map((item) => (
                  <li key={item.id}>
                    {item.label_pt} — {brDateTime(item.due_at)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <Link to="/recall/practice" className="btn btn-ghost">
            Praticar frases novas
          </Link>
        </div>
      )}

      {exercise && (
        <RecallCard
          exercise={exercise}
          onChange={setExercise}
          onSkip={async () => {
            await recallApi.skip(exercise.id).catch((e) => setError((e as Error).message));
            start();  // mesma dificuldade, outra frase
          }}
        />
      )}

      {done && (
        <div className="row end">
          <button className="btn btn-primary btn-lg" onClick={start} disabled={loading}>
            {loading ? "Preparando…" : "Próxima revisão →"}
          </button>
        </div>
      )}
    </div>
  );
}
