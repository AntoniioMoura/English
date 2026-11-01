import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../api";
import { RecallCard } from "../../components/RecallCard";
import { RecallStatus } from "../../components/RecallStatus";
import { recallApi, RecallExercise } from "../../recallApi";
import { useStudyPause, useStudyTimer } from "../../studyTimer";

type Blocker = { code: string; message: string } | null;

export function RecallPractice() {
  const [exercise, setExercise] = useState<RecallExercise | null>(null);
  const [blocker, setBlocker] = useState<Blocker>(null);
  const [loading, setLoading] = useState(false);

  const next = useCallback(async () => {
    setLoading(true);
    setBlocker(null);
    try {
      setExercise(await recallApi.newExercise());
    } catch (e) {
      const err = e as ApiError;
      setBlocker({ code: err.code ?? "error", message: err.message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    next();
  }, [next]);

  async function skip() {
    if (!exercise) return;
    try {
      await recallApi.skip(exercise.id);
      setExercise(null);
      next();
    } catch (e) {
      setBlocker({ code: "error", message: (e as Error).message });
    }
  }

  const done = exercise?.status === "evaluated";
  const blocked = blocker?.code === "daily_limit" || (done && exercise?.quota.blocked);

  // Sem frase para fazer (limite do dia, nenhuma palavra cadastrada, erro) ou lendo o resultado, o tempo não conta.
  useStudyTimer("anki_practice", !done && !blocked && !(blocker && !exercise));
  useStudyPause(loading);

  return (
    <div className="stack narrow-wide">
      <div className="page-head">
        <h1>Praticar</h1>
        <Link to="/recall" className="btn btn-ghost">
          ← Anki Premium
        </Link>
      </div>

      {exercise && <RecallStatus quota={exercise.quota} due={exercise.due_reviews} />}

      {loading && !exercise && (
        <div className="card center">
          <div className="spinner" />
          <p className="muted">Criando uma frase com as suas palavras…</p>
        </div>
      )}

      {blocker && !blocked && (
        <div className={`alert ${blocker.code === "no_vocabulary" ? "alert-info" : "alert-error"}`}>
          {blocker.message}{" "}
          {blocker.code === "no_vocabulary" ? (
            <Link to="/recall/words" className="link">
              Ir para Minhas palavras
            </Link>
          ) : (
            <button className="link" onClick={next}>
              Tentar de novo
            </button>
          )}
        </div>
      )}

      {exercise && !(blocker && !done) && (
        <RecallCard exercise={exercise} onChange={setExercise} onSkip={skip} />
      )}

      {blocked && (
        <div className="alert alert-warn">Limite diário atingido. Você ainda pode revisar seus erros.</div>
      )}

      {(done || blocked) && (
        <div className="row end">
          <Link to="/recall/review" className={`btn ${blocked ? "btn-primary btn-lg" : "btn-ghost"}`}>
            Revisar erros
          </Link>
          <button className="btn btn-primary btn-lg" onClick={next} disabled={loading || blocked}>
            {loading ? "Criando…" : "Próxima frase →"}
          </button>
        </div>
      )}
    </div>
  );
}
