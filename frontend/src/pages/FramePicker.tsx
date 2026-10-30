import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, Frame } from "../api";
import { FrameText } from "../components/FrameText";

export function FramePicker() {
  const navigate = useNavigate();
  const [frames, setFrames] = useState<Frame[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.frames().then(setFrames).catch((e) => setError(e.message));
  }, []);

  async function start(mode: "manual" | "random", frameId?: string) {
    setBusy(true);
    setError(null);
    try {
      const exercise = await api.createExercise(mode, frameId);
      navigate(`/builder/${exercise.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Criador de frases</h1>
          <p className="muted">Escolha a estrutura da frase de hoje.</p>
        </div>
        <div className="row">
          <Link to="/progress" className="btn btn-ghost">
            📈 Meu progresso
          </Link>
          <button className="btn btn-primary" disabled={busy} onClick={() => start("random")}>
            🎲 Aleatório
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="frame-grid">
        {frames.map((frame) => (
          <button key={frame.id} className="card frame-card" disabled={busy} onClick={() => start("manual", frame.id)}>
            <div className="frame-card-top">
              <FrameText text={frame.text} />
              <span className="tag">{frame.level}</span>
            </div>
            <p className="muted small">{frame.explanation_pt}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
