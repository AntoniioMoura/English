import { useEffect, useState } from "react";
import { api, StudyActivity, StudyDay, StudyMonth } from "../api";
import { formatDuration, syncStudyTime } from "../studyTimer";

const ACTIVITIES: { id: StudyActivity; label: string; accent: string }[] = [
  { id: "builder", label: "Criador de frases", accent: "accent-indigo" },
  { id: "anki_practice", label: "Anki: praticar", accent: "accent-violet" },
  { id: "anki_review", label: "Anki: revisar", accent: "accent-amber" },
  { id: "listening", label: "Listening", accent: "accent-green" },
];

const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

function shiftMonth(month: string, delta: number): string {
  const [year, m] = month.split("-").map(Number);
  const date = new Date(year, m - 1 + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(month: string): string {
  const [year, m] = month.split("-").map(Number);
  const label = new Date(year, m - 1, 1).toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
  return label[0].toUpperCase() + label.slice(1);
}

function dayLabel(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
}

export function StudyCalendar() {
  const [data, setData] = useState<StudyMonth | null>(null);
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    syncStudyTime() // segundos ainda não enviados aparecem no calendário
      .then(() => api.studyMonth(month))
      .then((next) => {
        if (cancelled) return;
        setData(next);
        setSelected(next.today.startsWith(next.month) ? next.today : null);
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [month]);

  if (!data) {
    return error ? <div className="alert alert-error">{error}</div> : <div className="spinner" />;
  }

  const byDate = new Map(data.days.map((d) => [d.date, d]));
  const [year, monthNumber] = data.month.split("-").map(Number);
  const firstWeekday = new Date(year, monthNumber - 1, 1).getDay();
  const daysInMonth = new Date(year, monthNumber, 0).getDate();
  const busiest = Math.max(...data.days.map((d) => d.total_seconds), 1);
  const studied = data.days.length;
  const selectedDay = selected ? byDate.get(selected) : undefined;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Calendário de estudos</h1>
          <p className="muted">Tempo estudado por dia e por tipo de exercício.</p>
        </div>
        <div className="study-month-nav">
          <button className="btn btn-ghost" onClick={() => setMonth(shiftMonth(data.month, -1))} aria-label="Mês anterior">
            ‹
          </button>
          <strong>{monthLabel(data.month)}</strong>
          <button
            className="btn btn-ghost"
            onClick={() => setMonth(shiftMonth(data.month, 1))}
            disabled={data.today.startsWith(data.month)}
            aria-label="Próximo mês"
          >
            ›
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="tiles">
        <div className="tile">
          <div className="tile-value">{formatDuration(data.total_seconds)}</div>
          <div className="tile-label">estudados no mês</div>
        </div>
        <div className="tile">
          <div className="tile-value">{studied}</div>
          <div className="tile-label">{studied === 1 ? "dia de estudo" : "dias de estudo"}</div>
        </div>
        <div className="tile">
          <div className="tile-value">{formatDuration(studied ? Math.round(data.total_seconds / studied) : 0)}</div>
          <div className="tile-label">média por dia estudado</div>
        </div>
      </div>

      <section className="card study-calendar">
        {WEEKDAYS.map((weekday) => (
          <span key={weekday} className="study-weekday">
            {weekday}
          </span>
        ))}
        {Array.from({ length: firstWeekday }, (_, n) => (
          <span key={`empty-${n}`} />
        ))}
        {Array.from({ length: daysInMonth }, (_, n) => {
          const date = `${data.month}-${String(n + 1).padStart(2, "0")}`;
          const day = byDate.get(date);
          const future = date > data.today;
          const classes = ["study-day"];
          if (day) classes.push("study-day-done");
          if (date === data.today) classes.push("study-day-today");
          if (date === selected) classes.push("study-day-selected");
          return (
            <button
              key={date}
              className={classes.join(" ")}
              disabled={future}
              onClick={() => setSelected(date)}
              style={day ? ({ "--level": 0.12 + 0.48 * (day.total_seconds / busiest) } as React.CSSProperties) : undefined}
              aria-label={`${dayLabel(date)}: ${day ? formatDuration(day.total_seconds) : "sem estudo"}`}
            >
              <span className="study-day-number">{n + 1}</span>
              {day && <span className="study-day-time">{formatDuration(day.total_seconds)}</span>}
            </button>
          );
        })}
      </section>

      {selected && <DayDetail date={selected} day={selectedDay} />}
    </div>
  );
}

function DayDetail({ date, day }: { date: string; day?: StudyDay }) {
  const total = day?.total_seconds ?? 0;
  return (
    <section className="card stack-sm">
      <div className="study-detail-head">
        <h2>{dayLabel(date)}</h2>
        {day && <strong>{formatDuration(total)}</strong>}
      </div>
      {!day && <p className="muted">Nenhum estudo registrado neste dia.</p>}
      {day &&
        ACTIVITIES.filter((a) => day.activities[a.id]).map((a) => {
          const seconds = day.activities[a.id] ?? 0;
          return (
            <div key={a.id} className={`study-activity ${a.accent}`}>
              <span>{a.label}</span>
              <span className="bar bar-lg">
                <span style={{ width: `${(seconds / total) * 100}%` }} />
              </span>
              <span className="study-activity-time">{formatDuration(seconds)}</span>
            </div>
          );
        })}
    </section>
  );
}
