import { Link } from "react-router-dom";
import { formatClock, useStudyClock } from "../studyTimer";

export function StudyClock() {
  const { seconds, running } = useStudyClock();
  return (
    <Link
      to="/study"
      className={`study-clock ${running ? "study-clock-running" : ""}`}
      title={`Tempo estudado hoje${running ? "" : " (pausado)"}. Clique para ver o calendário.`}
      aria-label={`Tempo estudado hoje: ${formatClock(seconds)}. Abrir calendário de estudos.`}
    >
      <span className="dot" />
      {formatClock(seconds)}
    </Link>
  );
}
