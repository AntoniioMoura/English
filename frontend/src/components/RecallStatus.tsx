import { Quota } from "../recallApi";

// Linha discreta com a cota do dia e as revisões pendentes.
export function RecallStatus({ quota, due }: { quota: Quota; due: number }) {
  return (
    <p className="muted small recall-status">
      Erros de hoje: <strong>{quota.errors_today}/{quota.limit}</strong> · Revisões pendentes: <strong>{due}</strong>
    </p>
  );
}
