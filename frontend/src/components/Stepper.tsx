const STEPS = ["Frase inicial", "Expansão 1/3", "Expansão 2/3", "Expansão 3/3", "Feedback"];

export function Stepper({ current }: { current: number }) {
  return (
    <ol className="stepper" aria-label="Progresso do exercício">
      {STEPS.map((label, i) => (
        <li
          key={label}
          className={i < current ? "done" : i === current ? "current" : ""}
          aria-current={i === current ? "step" : undefined}
        >
          <span className="step-dot">{i < current ? "✓" : i === 4 ? "★" : i === 0 ? "V0" : `V${i}`}</span>
          <span className="step-label">{label}</span>
        </li>
      ))}
    </ol>
  );
}
