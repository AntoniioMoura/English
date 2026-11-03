import { useEffect, useState } from "react";
import { api, ClaudeStatus } from "../api";

/** Liga as correções do Criador de frases e do Anki pelo Claude (gasta créditos da API). */
export function ClaudeSwitch() {
  const [status, setStatus] = useState<ClaudeStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.claudeStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  if (!status) return null;

  async function toggle() {
    if (!status || saving) return;
    setSaving(true);
    setError(null);
    try {
      setStatus(await api.setClaude(!status.enabled));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const on = status.active;
  const title = error
    ? error
    : !status.key_configured
      ? "Para usar o Claude nas correções, coloque a chave da API em backend/.env e reinicie o app."
      : on
        ? `Correções do Criador e do Anki pelo ${status.model} (gasta créditos da API). Clique para voltar ao ${status.fallback_model}.`
        : `Correções pelo ${status.fallback_model}, local e grátis. Clique para usar o Claude (gasta créditos da API).`;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      className={`claude-switch ${on ? "claude-switch-on" : ""} ${error ? "claude-switch-error" : ""}`}
      onClick={toggle}
      disabled={saving || !status.key_configured}
      title={title}
      aria-label={`Correções pelo Claude: ${on ? "ligado" : "desligado"}`}
    >
      <span className="claude-switch-track" aria-hidden>
        <span className="claude-switch-thumb" />
      </span>
      Claude
    </button>
  );
}
