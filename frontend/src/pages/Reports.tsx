import { useEffect, useState } from "react";
import { api, Report, ReportPeriod, ReportSummary } from "../api";
import { ReportView } from "../components/ReportView";

const PERIODS: { value: ReportPeriod; label: string }[] = [
  { value: "7d", label: "Últimos 7 dias" },
  { value: "30d", label: "Últimos 30 dias" },
  { value: "90d", label: "Últimos 90 dias" },
  { value: "all", label: "Todo o histórico" },
];

function summaryCounts(r: ReportSummary): string {
  const parts = [];
  if (r.exercises) parts.push(`${r.exercises} estudo(s)`);
  if (r.translations) parts.push(`${r.translations} tradução(ões)`);
  return parts.join(" · ") || "sem dados";
}

export function Reports() {
  const [period, setPeriod] = useState<ReportPeriod>("30d");
  const [list, setList] = useState<ReportSummary[]>([]);
  const [current, setCurrent] = useState<Report | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    api
      .reports()
      .then((items) => {
        setList(items);
        if (items[0]) api.report(items[0].id).then(setCurrent);
      })
      .catch((e) => setError(e.message));
  }, []);

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      const report = await api.createReport(period);
      setCurrent(report);
      const summary: ReportSummary = {
        ...report,
        exercises: report.data.totals.exercises,
        translations: report.data.recall?.attempts ?? null,
      };
      setList((prev) => [summary, ...prev]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  async function open(id: number) {
    setError(null);
    try {
      setCurrent(await api.report(id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(report: Report) {
    if (!window.confirm("Excluir este relatório? Seus estudos não serão afetados.")) return;
    try {
      await api.deleteReport(report.id);
      const rest = list.filter((r) => r.id !== report.id);
      setList(rest);
      setCurrent(null);
      if (rest[0]) open(rest[0].id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Relatórios</h1>
          <p className="muted">Relatório completo do Criador de frases e do Anki Premium, com base só no seu histórico.</p>
        </div>
      </div>

      <section className="card row report-controls">
        <label className="field inline">
          <span>Período</span>
          <select value={period} onChange={(e) => setPeriod(e.target.value as ReportPeriod)} disabled={generating}>
            {PERIODS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <button className="btn btn-primary" onClick={generate} disabled={generating}>
          {generating ? "Gerando…" : "Gerar relatório"}
        </button>
        {generating && <span className="muted small">Calculando e escrevendo a análise (cerca de 30 segundos)…</span>}
      </section>

      {error && <div className="alert alert-error">{error}</div>}

      {list.length > 0 && (
        <section className="report-list card" aria-label="Relatórios gerados">
          {(expanded ? list : list.slice(0, 1)).map((r, i) => (
            <button
              key={r.id}
              className={`report-row ${current?.id === r.id ? "report-row-active" : ""}`}
              onClick={() => open(r.id)}
              aria-current={current?.id === r.id}
            >
              <span className="report-row-main">
                <strong>{r.period_label}</strong>
                <span className="muted small">
                  {new Date(r.created_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}
                  {" · "}
                  {summaryCounts(r)}
                </span>
              </span>
              {i === 0 && <span className="tag">Mais recente</span>}
              {current?.id === r.id && <span className="report-row-open">Aberto</span>}
            </button>
          ))}
          {list.length > 1 && (
            <button className="report-list-toggle" onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
              {expanded ? "Ocultar relatórios anteriores ▴" : `Ver relatórios anteriores (${list.length - 1}) ▾`}
            </button>
          )}
        </section>
      )}

      {current ? (
        <ReportView report={current} onDelete={() => remove(current)} />
      ) : (
        !generating &&
        list.length === 0 && (
          <div className="card center">
            <p>Nenhum relatório ainda. Escolha um período e clique em “Gerar relatório”.</p>
          </div>
        )
      )}
    </div>
  );
}
