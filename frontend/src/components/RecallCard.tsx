import { useEffect, useMemo, useRef, useState } from "react";
import { newIdempotencyKey, recallApi, RecallExercise } from "../recallApi";
import { useStudyPause } from "../studyTimer";
import { DiffText } from "./DiffText";
import { ScoreMeter } from "./ScoreMeter";

interface Props {
  exercise: RecallExercise;
  onChange: (exercise: RecallExercise) => void;
  onSkip: () => void;
}

const VERDICT = {
  correct: { label: "✓ Correto", className: "verdict-ok" },
  incorrect: { label: "Precisa de ajuste", className: "verdict-error" },
  needs_review: { label: "Avaliação incerta — não conta como erro", className: "verdict-unsure" },
};

export function RecallCard({ exercise, onChange, onSkip }: Props) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useStudyPause(busy);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Uma chave por exercício: duplo clique ou reenvio de rede não registram duas tentativas.
  const key = useMemo(() => newIdempotencyKey(), [exercise.id]);

  useEffect(() => {
    setDraft("");
    setError(null);
    if (exercise.status === "pending_answer") inputRef.current?.focus();
  }, [exercise.id, exercise.status]);

  async function submit() {
    if (busy || !draft.trim()) return;
    setBusy(true);
    setError(null);
    try {
      onChange(await recallApi.answer(exercise.id, draft, key));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reevaluate() {
    setBusy(true);
    setError(null);
    try {
      onChange(await recallApi.reevaluate(exercise.id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const result = exercise.result;
  const answer = exercise.answer ?? "";

  return (
    <section className="recall-card stack">
      {exercise.review && (
        <div className="alert alert-info small">
          🔁 Revisão:{" "}
          {exercise.review.target_type === "sentence"
            ? "esta é uma frase que você errou antes. Ela volta até você acertar."
            : `frase nova para praticar uma palavra que você errou antes (${exercise.review.label_pt}).`}
        </div>
      )}

      <div className="card recall-prompt">
        <span className="muted small">Traduza para o inglês</span>
        <p className="recall-sentence">{exercise.sentence_pt}</p>
      </div>

      {exercise.status === "pending_answer" && (
        <div className="card writer">
          <textarea
            ref={inputRef}
            value={draft}
            rows={2}
            maxLength={300}
            spellCheck={false}
            placeholder="Escreva sua tradução em inglês…"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="row end">
            <button
              className="link small skip-link"
              onClick={onSkip}
              disabled={busy}
              title="Frase estranha ou ambígua? Pule sem contar como erro."
            >
              Pular frase
            </button>
            <span className="muted small kbd-hint">Enter</span>
            <button className="btn btn-primary" onClick={submit} disabled={busy || !draft.trim()}>
              {busy ? "Verificando…" : "Verificar"}
            </button>
          </div>
        </div>
      )}

      {exercise.status === "awaiting_evaluation" && (
        <div className="card stack-sm">
          <div className="muted small">Sua resposta</div>
          <p className="final-sentence">{answer}</p>
          {busy ? (
            <p className="muted">Avaliando…</p>
          ) : (
            <div className="alert alert-warn">
              <strong>A avaliação não pôde ser concluída.</strong> {exercise.evaluation_error} Sua resposta está salva
              e não conta como erro.{" "}
              <button className="link" onClick={reevaluate}>
                Reavaliar
              </button>
            </div>
          )}
        </div>
      )}

      {result && (
        <div className="stack">
          <ScoreMeter score={exercise.score} />
          {result.verdict !== "needs_review" && (
            <div className={`verdict ${VERDICT[result.verdict].className}`}>{VERDICT[result.verdict].label}</div>
          )}

          <div className="card">
            <div className="muted small">Sua resposta</div>
            <p className="final-sentence">{answer}</p>
            {result.corrected_answer && (
              <>
                <div className="muted small">Versão corrigida</div>
                <p className="final-sentence corrected">
                  <DiffText base={answer} text={result.corrected_answer} />
                </p>
              </>
            )}
            {result.alternative_en && (
              <>
                <div className="muted small">{result.verdict === "correct" ? "Outra forma correta" : "Tradução válida"}</div>
                <p className="final-sentence">
                  <DiffText base={result.corrected_answer ?? answer} text={result.alternative_en} />
                </p>
              </>
            )}
            {result.natural_en && (
              <>
                <div className="muted small">Como um nativo diria</div>
                <p className="final-sentence">{result.natural_en}</p>
              </>
            )}
          </div>

          {result.message_pt && <div className="alert alert-info">{result.message_pt}</div>}

          {result.errors.length > 0 && (
            <div className="stack-sm">
              {result.errors.map((e, i) => (
                <div key={i} className="fb-card fb-error">
                  <span className="fb-tag">{e.category === "meaning" ? "Sentido" : "Erro"}</span>
                  {e.excerpt && e.correction && (
                    <p className="diff">
                      <del>{e.excerpt}</del> → <ins>{e.correction}</ins>
                    </p>
                  )}
                  <p>{e.explanation_pt}</p>
                  {e.rule_pt && (
                    <p className="rule">
                      <span className="rule-tag">Regra</span> {e.rule_pt}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          {result.suggestion && (
            <div className="fb-card fb-improve">
              <span className="fb-tag">Pode melhorar</span>
              <p>{result.suggestion.comment_pt}</p>
              <p className="suggestion">
                <span className="muted small">Exemplo: </span>“{result.suggestion.example_en}”
              </p>
            </div>
          )}

          {result.target_usage.length > 0 && (
            <div className="targets">
              {result.target_usage.map((t) => {
                const meaning = t.meaning_pt ? ` (${t.meaning_pt})` : "";
                const showsUsage = !t.demonstrated && result.alternative_en;
                return (
                  <span key={t.vocabulary_id} className={`target ${t.demonstrated ? "target-ok" : "target-miss"}`}>
                    {t.demonstrated ? "✓" : "○"} <strong>{t.english_text}</strong>
                    {meaning} — {t.demonstrated ? "usada" : "não usada nesta resposta"}
                    {showsUsage && <span className="muted">. Veja como usar na tradução válida acima.</span>}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      )}

      {error && <div className="alert alert-error">{error}</div>}
    </section>
  );
}
