import { Link } from "react-router-dom";
import { MENU } from "../modes";

export function Home() {
  const modes = MENU.filter((m) => m.kind === "study_mode");
  const tools = MENU.filter((m) => m.kind === "tool");

  return (
    <div className="home">
      <section className="hero">
        <span className="eyebrow">Inglês do A2 ao B1</span>
        <h1>Construa frases, passo a passo.</h1>
        <p className="muted">
          Escreva, traduza e revise com autonomia. A correção chega no final, com regras claras para a
          próxima tentativa.
        </p>
      </section>

      <section className="modes-grid" aria-label="Modos de estudo">
        {modes.map((m) => (
          <Link key={m.id} to={m.path} className={`mode-card accent-${m.accent}`}>
            <span className="icon-tile" aria-hidden>
              {m.icon}
            </span>
            <h2>{m.title}</h2>
            <p className="muted">{m.description}</p>
            <span className="mode-cta">Começar →</span>
          </Link>
        ))}
      </section>

      {tools.map((t) => (
        <Link key={t.id} to={t.path} className={`report-cta accent-${t.accent}`}>
          <span className="icon-tile" aria-hidden>
            {t.icon}
          </span>
          <div className="report-cta-text">
            <h2>{t.title}</h2>
            <p className="muted">{t.description}</p>
          </div>
          <span className="btn btn-primary btn-lg report-cta-button">Gerar relatório →</span>
        </Link>
      ))}
    </div>
  );
}
