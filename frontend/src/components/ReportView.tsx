import { RecallReport, Report, TopicState } from "../api";
import { DiffText } from "./DiffText";

export const STATE_LABEL: Record<TopicState, string> = {
  precisa_de_atencao: "Precisa de atenção",
  revisar: "Revisar",
  em_evolucao: "Em evolução",
  consistente: "Consistente",
  dados_insuficientes: "Dados insuficientes",
};

const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);
const brDate = (iso: string) => new Date(iso.length === 10 ? `${iso}T12:00:00` : iso).toLocaleDateString("pt-BR");

function Tile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="tile">
      <div className="tile-value">{value}</div>
      <div className="tile-label">{label}</div>
      {hint && <div className="muted tiny">{hint}</div>}
    </div>
  );
}

function SectionHeader({ icon, title, subtitle, accent }: { icon: string; title: string; subtitle: string; accent: string }) {
  return (
    <div className={`report-section-head accent-${accent}`}>
      <span className="icon-tile icon-tile-sm" aria-hidden>
        {icon}
      </span>
      <div>
        <h2>{title}</h2>
        <p className="muted small">{subtitle}</p>
      </div>
    </div>
  );
}

function BuilderSection({ report }: { report: Report }) {
  const { data } = report;
  const t = data.totals;
  const n = data.narrative;
  return (
    <>
      <div className="tiles">
        <Tile label="Estudos concluídos" value={t.exercises} />
        <Tile label="Dias de estudo" value={t.study_days} />
        <Tile label="Erros gramaticais" value={t.grammar_errors} hint={`em ${t.grammar_opportunities} oportunidades avaliadas`} />
        <Tile label="Autocorreções" value={t.self_corrections} />
        <Tile label="Expansões com dica" value={pct(t.hint_rate)} hint="quanto menor, mais autonomia" />
        <Tile label="Conectores usados" value={t.distinct_connectors.length} hint={t.distinct_connectors.join(", ")} />
      </div>

      <section className="stack-sm">
        <h3>Precisão gramatical por tópico</h3>
        {data.topics.length === 0 ? (
          <p className="muted">Nenhuma evidência gramatical registrada no período.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Tópico</th>
                  <th className="num">Erros / oportunidades</th>
                  <th>Estado</th>
                  <th>Exemplos reais</th>
                </tr>
              </thead>
              <tbody>
                {data.topics.map((topic) => (
                  <tr key={topic.topic_id}>
                    <td>{topic.name_pt}</td>
                    <td className="num">
                      {topic.errors} / {topic.opportunities}
                    </td>
                    <td>
                      <span className={`state state-${topic.state}`}>{STATE_LABEL[topic.state]}</span>
                    </td>
                    <td className="small">
                      {topic.examples.length === 0 && <span className="muted">—</span>}
                      {topic.examples.map((ex) => (
                        <div key={ex.excerpt} className="diff">
                          <del>{ex.excerpt}</del> → <ins>{ex.correction}</ins>
                        </div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {n && <p>{n.errors_comment_pt}</p>}
      </section>

      <section className="stack-sm">
        <h3>Oportunidades de elaboração</h3>
        <p className="muted small">Sugestões para enriquecer suas frases — não são erros.</p>
        {data.elaboration_examples.map((ex, i) => (
          <div key={i} className="fb-card fb-improve">
            <p>{ex.comment_pt}</p>
            <p className="suggestion">
              <DiffText base={ex.original} text={ex.suggestion_en} />
            </p>
          </div>
        ))}
        {n && <p>{n.elaboration_comment_pt}</p>}
      </section>

      {data.self_corrections.length > 0 && (
        <section className="stack-sm">
          <h3>Autocorreções</h3>
          <ul className="plain-list">
            {data.self_corrections.map((s, i) => (
              <li key={i} className="diff">
                <del>{s.before}</del> → <ins>{s.after}</ins> <span className="muted small">· {s.topic}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="stack-sm">
        <h3>Evolução semanal</h3>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Semana de</th>
                <th className="num">Estudos</th>
                <th className="num">Taxa de erro</th>
                <th className="num">Expansões com dica</th>
              </tr>
            </thead>
            <tbody>
              {data.weekly.map((w) => (
                <tr key={w.week_start}>
                  <td>{brDate(w.week_start)}</td>
                  <td className="num">{w.exercises}</td>
                  <td className="num">{pct(w.error_rate)}</td>
                  <td className="num">{pct(w.hint_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {n && <p>{n.evolution_comment_pt}</p>}
      </section>
    </>
  );
}

function RecallSection({ r, comment }: { r: RecallReport; comment?: string }) {
  const newDone = (r.new.correct ?? 0) + (r.new.incorrect ?? 0);
  const reviewDone = (r.review.correct ?? 0) + (r.review.incorrect ?? 0);
  return (
    <>
      <div className="tiles">
        <Tile label="Traduções avaliadas" value={r.attempts} />
        <Tile label="Frases novas corretas" value={pct(r.new_accuracy)} hint={`${r.new.correct ?? 0} de ${newDone}`} />
        <Tile label="Nota média" value={r.avg_score === null ? "—" : `${r.avg_score}%`} hint="quanto da frase já estava certo" />
        <Tile label="Revisões corretas" value={`${r.review.correct ?? 0}/${reviewDone}`} />
        <Tile label="Palavras usadas" value={`${r.words.used}/${r.words.practiced}`} hint="usadas / praticadas" />
        <Tile label="Revisões pendentes" value={r.reviews.pending_now} hint={`${r.reviews.stable} estável(is)`} />
      </div>

      {r.recurring_errors.length > 0 && (
        <section className="stack-sm">
          <h3>Erros mais frequentes</h3>
          {r.recurring_errors.map((e) => (
            <div key={`${e.excerpt}-${e.correction}`} className="fb-card fb-error">
              <p className="diff">
                <del>{e.excerpt}</del> → <ins>{e.correction}</ins>{" "}
                <span className="muted small">· {e.count}x</span>
              </p>
              {e.rule_pt && (
                <p className="rule">
                  <span className="rule-tag">Regra</span> {e.rule_pt}
                </p>
              )}
            </div>
          ))}
        </section>
      )}

      {r.topics.length > 0 && (
        <section className="stack-sm">
          <h3>Tópicos nas traduções</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Tópico</th>
                  <th className="num">Erros</th>
                  <th className="num">Acertos</th>
                </tr>
              </thead>
              <tbody>
                {r.topics.map((t) => (
                  <tr key={t.topic_id}>
                    <td>{t.name_pt}</td>
                    <td className="num">{t.errors}</td>
                    <td className="num">{t.correct}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {r.words.not_used_examples.length > 0 && (
        <p className="small">
          <strong>Palavras que você ainda não usou nas respostas:</strong> {r.words.not_used_examples.join(", ")}
        </p>
      )}
      {comment && <p>{comment}</p>}
    </>
  );
}

export function ReportView({ report, onDelete }: { report: Report; onDelete: () => void }) {
  const { data } = report;
  const n = data.narrative;
  const hasBuilder = data.has_builder !== false;
  const limitations = [...data.limitations, ...(data.recall?.limitations ?? [])];

  return (
    <article className="report stack">
      <header className="report-head">
        <div>
          <h2>{data.period.label}</h2>
          <p className="muted small">
            {brDate(data.period.start_local)} a {brDate(data.period.end_local)} · gerado em{" "}
            {new Date(report.created_at).toLocaleString("pt-BR")}
          </p>
        </div>
        <div className="row">
          <a className="btn btn-ghost" href={`/api/reports/${report.id}/markdown`} download>
            ⬇ Exportar Markdown
          </a>
          <button className="link small danger" onClick={onDelete}>
            Excluir
          </button>
        </div>
      </header>

      {!n && (
        <div className="alert alert-warn">
          A análise em texto não pôde ser gerada{report.narrative_error ? ` (${report.narrative_error})` : ""}. Os números
          abaixo vêm direto do seu histórico; gere de novo quando a IA estiver disponível.
        </div>
      )}

      {n && (
        <section className="card stack-sm">
          <h3>Resumo</h3>
          <p>{n.summary_pt}</p>
          {n.strengths_pt.length > 0 && (
            <ul className="plain-list">
              {n.strengths_pt.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="report-section stack">
        <SectionHeader icon="🧱" title="Criador de frases" subtitle="Produção livre: escrever e expandir ideias." accent="indigo" />
        {hasBuilder ? <BuilderSection report={report} /> : <p className="muted">Nenhum estudo do Criador de frases no período.</p>}
      </section>

      <section className="report-section stack">
        <SectionHeader icon="🔁" title="Anki Premium" subtitle="Tradução com as suas palavras e revisão espaçada." accent="violet" />
        {data.recall ? (
          <RecallSection r={data.recall} comment={n?.recall_comment_pt} />
        ) : (
          <p className="muted">
            {"recall" in data
              ? "Nenhuma tradução avaliada no Anki Premium no período."
              : "Este relatório foi gerado antes da inclusão do Anki Premium. Gere um novo para ver esta seção."}
          </p>
        )}
      </section>

      {n && n.next_topics.length > 0 && (
        <section className="fb-card fb-tip">
          <span className="fb-tag">Próximos tópicos</span>
          <ul>
            {n.next_topics.map((topic) => (
              <li key={topic.topic_id}>
                <strong>{topic.name_pt}</strong> — {topic.reason_pt}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="stack-sm">
        <h3>Limitações</h3>
        <ul className="plain-list muted small">
          {limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </section>
    </article>
  );
}
