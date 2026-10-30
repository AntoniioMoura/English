import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ExerciseState } from "../api";
import { FeedbackPanel } from "../components/FeedbackPanel";
import { FrameText } from "../components/FrameText";
import { HintsBox } from "../components/HintsBox";
import { Stepper } from "../components/Stepper";

const draftKey = (id: number, stage: number) => `eb-draft-${id}-${stage}`;

function readDraft(id: number, stage: number): string | null {
  try {
    return window.sessionStorage.getItem(draftKey(id, stage));
  } catch {
    return null;
  }
}

function writeDraft(id: number, stage: number, text: string | null) {
  try {
    if (text === null) window.sessionStorage.removeItem(draftKey(id, stage));
    else window.sessionStorage.setItem(draftKey(id, stage), text);
  } catch {
    /* rascunho é só conveniência */
  }
}

const STAGE_INSTRUCTIONS = [
  "Complete a estrutura com uma frase completa, do seu jeito.",
  "Acrescente uma informação nova (quem, onde, quando…). Você também pode corrigir partes anteriores.",
  "Aprofunde a ideia: um motivo, um detalhe, um sentimento.",
  "Feche a história: uma consequência, um contraste ou uma conclusão.",
];

export function ExercisePage() {
  const { id } = useParams();
  const exerciseId = Number(id);
  const navigate = useNavigate();
  const [state, setState] = useState<ExerciseState | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const stage = state?.next_version_index ?? null;

  const applyState = useCallback((next: ExerciseState) => {
    setState(next);
    const s = next.next_version_index;
    if (s !== null) {
      const previous = s > 0 ? next.versions[s - 1].text : "";
      setDraft(readDraft(next.id, s) ?? previous);
    }
  }, []);

  useEffect(() => {
    setState(null);
    setError(null);
    api.exercise(exerciseId).then(applyState).catch((e) => setError(e.message));
  }, [exerciseId, applyState]);

  useEffect(() => {
    if (stage !== null) textareaRef.current?.focus();
  }, [stage]);

  async function evaluate() {
    setEvaluating(true);
    setError(null);
    try {
      applyState(await api.evaluate(exerciseId));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setEvaluating(false);
    }
  }

  async function submit() {
    if (stage === null || saving) return;
    setSaving(true);
    setError(null);
    try {
      const next = await api.saveVersion(exerciseId, stage, draft);
      writeDraft(exerciseId, stage, null);
      applyState(next);
      if (next.can_evaluate) await evaluate();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function nextSentence() {
    if (state?.selection_mode === "random") {
      try {
        const next = await api.createExercise("random");
        navigate(`/builder/${next.id}`);
      } catch (e) {
        setError((e as Error).message);
      }
    } else {
      navigate("/builder");
    }
  }

  if (!state) {
    return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Carregando…</p>;
  }

  const stepIndex = stage ?? 4;
  const evaluation = state.evaluation;
  const feedback = evaluation?.feedback ?? null;

  return (
    <div className="exercise">
      <section className="frame-header card">
        <div className="frame-header-top">
          <FrameText text={state.frame.text} large />
          <span className="tag">{state.frame.level}</span>
        </div>
        <p className="muted">{state.frame.explanation_pt}</p>
      </section>

      <Stepper current={stepIndex} />

      {state.versions.length > 0 && (
        <ol className="timeline">
          {state.versions.map((v) => (
            <li key={v.version_index}>
              <span className="version-tag">V{v.version_index}</span>
              <span>{v.text}</span>
              {v.hints_opened && (
                <span className="hint-flag" title="Você consultou ideias nesta etapa">
                  💡
                </span>
              )}
            </li>
          ))}
        </ol>
      )}

      {stage !== null && (
        <section className="writer card">
          <div className="writer-head">
            <h2>{state.stage_label}</h2>
            <span className="muted small">
              Etapa {stage + 1} de {state.total_versions}
            </span>
          </div>
          <p className="muted">{STAGE_INSTRUCTIONS[stage]}</p>
          <textarea
            ref={textareaRef}
            value={draft}
            maxLength={400}
            rows={3}
            spellCheck={false}
            placeholder={stage === 0 ? state.frame.text.replace(/___/g, "…") : undefined}
            onChange={(e) => {
              setDraft(e.target.value);
              writeDraft(exerciseId, stage, e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="writer-actions">
            {state.can_request_hints ? (
              <HintsBox key={stage} exerciseId={exerciseId} stage={stage} cached={state.hints[String(stage)]} />
            ) : (
              <span />
            )}
            <div className="row">
              <span className="muted small kbd-hint">Ctrl + Enter</span>
              <button className="btn btn-primary" onClick={submit} disabled={saving || !draft.trim()}>
                {saving ? "Salvando…" : stage === 3 ? "Concluir e avaliar" : "Salvar e continuar"}
              </button>
            </div>
          </div>
        </section>
      )}

      {error && <div className="alert alert-error">{error}</div>}

      {stage === null && (evaluating ? (
        <section className="card center">
          <div className="spinner" />
          <p>Avaliando suas quatro versões…</p>
          <p className="muted small">Isso pode levar alguns segundos com o modelo local.</p>
        </section>
      ) : (
        <>
          {evaluation?.error_message && (
            <div className="alert alert-warn">
              <strong>Não foi possível concluir a avaliação.</strong> {evaluation.error_message} Suas frases
              estão salvas.
            </div>
          )}
          {!feedback && state.status === "awaiting_evaluation" && (
            <section className="card center">
              <p>Suas quatro versões estão salvas e aguardando avaliação.</p>
              <button className="btn btn-primary" onClick={evaluate}>
                {evaluation ? "Reavaliar" : "Avaliar agora"}
              </button>
            </section>
          )}
          {feedback && evaluation && (
            <FeedbackPanel
              feedback={feedback}
              evaluation={evaluation}
              finalSentence={state.versions[state.versions.length - 1].text}
            />
          )}
          <div className="row end">
            {feedback && (
              <button className="btn btn-ghost" onClick={evaluate}>
                Reavaliar
              </button>
            )}
            <Link to="/" className="btn btn-ghost">
              Menu
            </Link>
            <button className="btn btn-primary btn-lg" onClick={nextSentence}>
              Próxima frase →
            </button>
          </div>
        </>
      ))}
    </div>
  );
}
