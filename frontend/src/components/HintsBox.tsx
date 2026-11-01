import { useState } from "react";
import { api } from "../api";
import { useStudyPause } from "../studyTimer";

interface Props {
  exerciseId: number;
  stage: number;
  cached?: string[];
}

// Dicas ficam ocultas por padrão; o backend registra que foram abertas.
export function HintsBox({ exerciseId, stage, cached }: Props) {
  const [open, setOpen] = useState(false);
  const [hints, setHints] = useState<string[] | null>(cached ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useStudyPause(loading);

  async function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (hints) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.hints(exerciseId);
      setHints(result.hints);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="hints">
      <button className="btn btn-ghost" onClick={toggle} aria-expanded={open}>
        💡 {open ? "Ocultar ideias" : "Mostrar ideias"}
      </button>
      {open && (
        <div className="hints-box" aria-live="polite">
          {loading && <span className="muted small">Pensando em ideias para a etapa {stage}…</span>}
          {error && <span className="error-text small">{error}</span>}
          {hints && (
            <ul>
              {hints.map((hint) => (
                <li key={hint}>{hint}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
