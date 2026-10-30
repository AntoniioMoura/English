import { useEffect, useState } from "react";
import { api, OllamaStatus } from "../api";

export function OllamaBadge() {
  const [status, setStatus] = useState<OllamaStatus | null>(null);

  useEffect(() => {
    const load = () => api.ollamaStatus().then(setStatus).catch(() => setStatus(null));
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, []);

  const ok = status?.reachable && status.model_available;
  const label = !status ? "Verificando IA…" : ok ? "IA conectada" : "IA indisponível";
  return (
    <span className={`badge ${!status ? "" : ok ? "badge-ok" : "badge-warn"}`} title={status?.message ?? "Ollama local"}>
      <span className="dot" /> {label}
    </span>
  );
}
