import { useState } from "react";
import { Adjustment, api, Evaluation, Feedback } from "../api";
import { DiffText } from "./DiffText";
import { ScoreMeter } from "./ScoreMeter";

interface Props {
  feedback: Feedback;
  evaluation: Evaluation;
  finalSentence: string;
}

export function FeedbackPanel({ feedback, evaluation, finalSentence }: Props) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const observationFor = (item: Adjustment) =>
    evaluation.grammar_observations.find(
      (o) => o.evidence_type === "error" && o.original_excerpt === item.excerpt,
    );

  async function dismiss(item: Adjustment) {
    const obs = observationFor(item);
    if (!obs || !item.excerpt) return;
    await api.reviewObservation(obs.id, "dismissed");
    setDismissed((prev) => new Set(prev).add(item.excerpt!));
  }

  return (
    <section className="feedback stack">
      <ScoreMeter score={evaluation.score} caption="da sua frase final já estava correta" />
      <div className="card">
        <div className="muted small">Sua frase final</div>
        <p className="final-sentence">{finalSentence}</p>
        {feedback.final_is_correct ? (
          <p className="ok-text">✓ Sua frase final está gramaticalmente correta.</p>
        ) : (
          feedback.corrected_final_sentence && (
            <>
              <div className="muted small">Versão corrigida</div>
              <p className="final-sentence corrected">
                <DiffText base={finalSentence} text={feedback.corrected_final_sentence} />
              </p>
            </>
          )
        )}
      </div>

      {feedback.grammar_corrections.length > 0 && (
        <div className="stack-sm">
          <h3>Correções gramaticais</h3>
          {feedback.grammar_corrections.map((item, i) => {
            const isDismissed = !!item.excerpt && dismissed.has(item.excerpt);
            return (
              <div key={i} className={`fb-card fb-error ${isDismissed ? "fb-dismissed" : ""}`}>
                <span className="fb-tag">Erro</span>
                {item.excerpt && (
                  <p className="diff">
                    <del>{item.excerpt}</del> → <ins>{item.correction}</ins>
                  </p>
                )}
                <p>{item.message_pt}</p>
                {observationFor(item) && (
                  <button className="link small" disabled={isDismissed} onClick={() => dismiss(item)}>
                    {isDismissed ? "Marcado como avaliação equivocada" : "Discordo desta correção"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {feedback.idea_suggestions.length > 0 && (
        <div className="stack-sm">
          <h3>Ideias para enriquecer sua frase</h3>
          {feedback.idea_suggestions.map((item, i) => (
            <div key={i} className="fb-card fb-improve">
              <span className="fb-tag">Pode melhorar</span>
              <p>{item.message_pt}</p>
              {item.suggestion_en && (
                <p className="suggestion">
                  <span className="muted small">Exemplo: </span>
                  <DiffText base={finalSentence} text={item.suggestion_en} />
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {feedback.self_corrections.length > 0 && (
        <div className="fb-card fb-success">
          <span className="fb-tag">Autocorreção</span>
          <p>Você mesmo corrigiu entre as versões:</p>
          <ul>
            {feedback.self_corrections.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}

      {feedback.frame_note && <div className="alert alert-info">{feedback.frame_note}</div>}

      <p className="muted tiny">
        Avaliado por {evaluation.model} em {new Date(evaluation.created_at).toLocaleString("pt-BR")}
      </p>
    </section>
  );
}
