// Nota da frase: número grande + barra + rótulo em texto (a cor nunca é a única pista).

function band(score: number) {
  if (score === 100) return { label: "Frase correta", tone: "ok" };
  if (score >= 80) return { label: "Quase lá", tone: "good" };
  if (score >= 50) return { label: "Bom caminho", tone: "mid" };
  return { label: "Continue praticando", tone: "low" };
}

export function ScoreMeter({ score, caption }: { score: number | null; caption?: string }) {
  if (score === null) {
    return (
      <div className="score score-none">
        <div className="score-value">—</div>
        <div className="score-text">
          <strong>Sem nota</strong>
          <span className="muted small">Avaliação incerta: não conta como erro.</span>
        </div>
      </div>
    );
  }
  const { label, tone } = band(score);
  return (
    <div className={`score score-${tone}`} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={score}>
      <div className="score-value">{score}%</div>
      <div className="score-text">
        <strong>{label}</strong>
        <div className="score-bar">
          <div className="score-fill" style={{ width: `${score}%` }} />
        </div>
        <span className="muted small">{caption ?? "da sua frase já estava correta"}</span>
      </div>
    </div>
  );
}
