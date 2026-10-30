"""Relatório: validação da narrativa da IA e exportação em Markdown."""

import re

from ..llm.schemas import LLMReportNarrative

STATE_LABELS = {
    "precisa_de_atencao": "Precisa de atenção",
    "revisar": "Revisar",
    "em_evolucao": "Em evolução",
    "consistente": "Consistente",
    "dados_insuficientes": "Dados insuficientes",
}
NEXT_TOPIC_STATES = {"precisa_de_atencao", "revisar", "em_evolucao", "dados_insuficientes"}


def without_numbers(text: str, fallback: str = "") -> str:
    """Os números do relatório vêm das tabelas; frases da IA com números são removidas."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for s in sentences if not re.search(r"\d", s)]
    return " ".join(kept) or fallback


def grounded_errors_comment(text: str, data: dict) -> str:
    """Remove frases que citam entre aspas algo que não é um erro da frase final
    (ex.: uma autocorreção apresentada como erro) ou que chamam de recorrente o que ocorreu uma vez."""
    known = [
        part.lower()
        for t in data["topics"] for e in t["examples"] for part in (e["excerpt"], e["correction"]) if part
    ]
    any_recurring = any(t["errors"] > 1 for t in data["topics"])
    kept, cites_real_error = [], False
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        quoted = re.findall(r"['\"“‘]([^'\"”’]+)['\"”’]", sentence)
        if any(not any(q.lower() in k or k in q.lower() for k in known) for q in quoted):
            continue
        if "recorrente" in sentence.lower() and not any_recurring:
            continue
        cites_real_error = cites_real_error or bool(quoted)
        kept.append(sentence)
    errors = [(t, e) for t in data["topics"] for e in t["examples"]]
    if not errors:
        return "Não apareceram erros gramaticais nas suas frases finais neste período."
    if cites_real_error:
        return " ".join(kept)
    # Sem citação de um erro real, o comentário da IA não se sustenta: usa os próprios dados.
    listed = "; ".join(f"“{e['excerpt']}” → “{e['correction']}”" for _, e in errors[:3])
    return f"Na frase final ainda apareceram: {listed}."


def clean_narrative(narrative: LLMReportNarrative, data: dict) -> dict:
    """Próximos tópicos só podem ser tópicos que existem nos dados e ainda pedem prática."""
    topics = {t["topic_id"]: t for t in data["topics"]}
    next_topics, seen = [], set()
    for item in narrative.next_topics:
        topic = topics.get(item.topic_id.strip().lower())
        # "Outro" é genérico demais para virar recomendação de estudo.
        if topic and topic["state"] in NEXT_TOPIC_STATES and topic["topic_id"] not in seen | {"other"}:
            seen.add(topic["topic_id"])
            next_topics.append({"topic_id": topic["topic_id"], "name_pt": topic["name_pt"], "reason_pt": item.reason_pt})
    has_builder = data.get("has_builder", True)
    no_builder = "Nenhum estudo do Criador de frases no período."
    return {
        "summary_pt": without_numbers(narrative.summary_pt, "Veja abaixo os números do período."),
        "strengths_pt": [
            s for s in (without_numbers(s) for s in narrative.strengths_pt) if s and "dica" not in s.lower()
        ][:3],
        "errors_comment_pt": grounded_errors_comment(without_numbers(narrative.errors_comment_pt), data)
        if has_builder else no_builder,
        "elaboration_comment_pt": without_numbers(narrative.elaboration_comment_pt) if has_builder else no_builder,
        "evolution_comment_pt": without_numbers(narrative.evolution_comment_pt) if has_builder else no_builder,
        "recall_comment_pt": grounded_recall_comment(without_numbers(narrative.recall_comment_pt), data.get("recall")),
        "next_topics": next_topics[:3],
    }


def grounded_recall_comment(text: str, recall: dict | None) -> str:
    """Comentário do Anki Premium: só cita entre aspas erros e palavras que existem nos dados."""
    if not recall:
        return ""
    known = [x.lower() for e in recall["recurring_errors"] for x in (e["excerpt"], e["correction"], e["sentence_pt"])]
    known += [w.lower() for w in recall["words"]["not_used_examples"]]
    kept, cites_real_error = [], False
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        quoted = re.findall(r"['\"“‘]([^'\"”’]+)['\"”’]", sentence)
        if any(not any(q.lower() in k or k in q.lower() for k in known) for q in quoted):
            continue
        cites_real_error = cites_real_error or bool(quoted)
        kept.append(sentence)
    errors = recall["recurring_errors"]
    if not errors:
        return " ".join(kept) or "As traduções do período não tiveram erros recorrentes."
    if cites_real_error:
        return " ".join(kept)
    # Comentário genérico, sem citar erro real: usa os próprios dados.
    listed = " e ".join(f"“{e['excerpt']}” → “{e['correction']}”" for e in errors[:2])
    return f"Nas traduções, os erros que mais apareceram foram {listed}."


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{round(value * 100)}%"


def _br_date(iso: str) -> str:
    y, m, d = iso[:10].split("-")
    return f"{d}/{m}/{y}"


def to_markdown(data: dict, narrative: dict | None, created_at: str, model: str) -> str:
    p = data["period"]
    lines = [
        "# Relatório de estudo — English Builder",
        "",
        f"**Período:** {p['label']} ({_br_date(p['start_local'])} a {_br_date(p['end_local'])})  ",
        f"**Gerado em:** {_br_date(created_at)} · análise de texto: {model if narrative else 'indisponível'}",
        "",
        "## Resumo",
        "",
    ]
    if narrative:
        lines += [narrative["summary_pt"], ""]
    if narrative and narrative["strengths_pt"]:
        lines += ["**Pontos fortes:**", ""] + [f"- {s}" for s in narrative["strengths_pt"]] + [""]

    lines += ["## Criador de frases", ""]
    if data.get("has_builder", True):
        lines += _builder_markdown(data, narrative)
    else:
        lines += ["Nenhum estudo do Criador de frases no período.", ""]

    lines += ["## Anki Premium", ""]
    if data.get("recall"):
        lines += _recall_markdown(data["recall"], narrative)
    else:
        lines += ["Nenhuma tradução avaliada no Anki Premium no período.", ""]

    if narrative and narrative["next_topics"]:
        lines += ["## Próximos tópicos recomendados", ""]
        lines += [f"- **{n['name_pt']}** — {n['reason_pt']}" for n in narrative["next_topics"]]
        lines.append("")

    limitations = data["limitations"] + (data["recall"]["limitations"] if data.get("recall") else [])
    lines += ["## Limitações", ""] + [f"- {item}" for item in limitations]
    return "\n".join(lines) + "\n"


def _builder_markdown(data: dict, narrative: dict | None) -> list[str]:
    t = data["totals"]
    lines = [
        "| Indicador | Valor |",
        "|---|---|",
        f"| Estudos concluídos | {t['exercises']} |",
        f"| Dias de estudo | {t['study_days']} |",
        f"| Erros gramaticais / oportunidades avaliadas | {t['grammar_errors']} / {t['grammar_opportunities']} |",
        f"| Autocorreções | {t['self_corrections']} |",
        f"| Expansões com dica consultada | {_pct(t['hint_rate'])} |",
        f"| Expansões com informação relevante | {_pct(t['relevant_expansion_rate'])} |",
        f"| Conectores usados | {', '.join(t['distinct_connectors']) or '—'} |",
        "",
        "### Precisão gramatical por tópico",
        "",
    ]
    if data["topics"]:
        lines += ["| Tópico | Erros / oportunidades | Estado |", "|---|---|---|"]
        lines += [f"| {tp['name_pt']} | {tp['errors']} / {tp['opportunities']} | {STATE_LABELS[tp['state']]} |"
                  for tp in data["topics"]]
        lines.append("")
        examples = [(tp, ex) for tp in data["topics"] for ex in tp["examples"]]
        if examples:
            lines += ["**Erros na frase final (exemplos reais):**", ""]
            lines += [f"- {tp['name_pt']}: ~~{ex['excerpt']}~~ → **{ex['correction']}** — {ex['explanation_pt']}"
                      for tp, ex in examples[:8]]
            lines.append("")
    else:
        lines += ["Nenhuma evidência gramatical registrada no período.", ""]
    if narrative:
        lines += [narrative["errors_comment_pt"], ""]

    lines += ["### Oportunidades de elaboração", "", "_Sugestões para enriquecer as frases — não são erros._", ""]
    for ex in data["elaboration_examples"]:
        lines += [f"- {ex['comment_pt']}", f"  - Sua frase: {ex['original']}", f"  - Exemplo: {ex['suggestion_en']}"]
    if data["elaboration_examples"]:
        lines.append("")
    if narrative:
        lines += [narrative["elaboration_comment_pt"], ""]

    if data["self_corrections"]:
        lines += ["### Autocorreções", ""]
        lines += [f"- ~~{s['before']}~~ → **{s['after']}** ({s['topic']}, {_br_date(s['date'])})"
                  for s in data["self_corrections"]]
        lines.append("")

    lines += ["### Evolução semanal", "", "| Semana | Estudos | Taxa de erro | Expansões com dica |",
              "|---|---|---|---|"]
    lines += [f"| {_br_date(w['week_start'])} | {w['exercises']} | {_pct(w['error_rate'])} | {_pct(w['hint_rate'])} |"
              for w in data["weekly"]]
    lines.append("")
    if narrative:
        lines += [narrative["evolution_comment_pt"], ""]
    return lines


def _recall_markdown(r: dict, narrative: dict | None) -> list[str]:
    new, review = r["new"], r["review"]
    lines = [
        "_Tradução de frases com as suas palavras. Traduzir certo é diferente de criar frases livremente._",
        "",
        "| Indicador | Valor |",
        "|---|---|",
        f"| Traduções avaliadas | {r['attempts']} |",
        f"| Frases novas corretas | {new.get('correct', 0)} de {new.get('correct', 0) + new.get('incorrect', 0)} "
        f"({_pct(r['new_accuracy'])}) |",
        f"| Revisões corretas | {review.get('correct', 0)} de {review.get('correct', 0) + review.get('incorrect', 0)} |",
        f"| Nota média das frases | {'—' if r['avg_score'] is None else str(r['avg_score']) + '%'} |",
        f"| Palavras praticadas / usadas | {r['words']['practiced']} / {r['words']['used']} |",
        f"| Revisões pendentes agora | {r['reviews']['pending_now']} |",
        f"| Revisões estáveis | {r['reviews']['stable']} |",
        "",
    ]
    if r["recurring_errors"]:
        lines += ["### Erros mais frequentes", ""]
        for e in r["recurring_errors"]:
            rule = f" — {e['rule_pt']}" if e["rule_pt"] else ""
            lines.append(f"- ~~{e['excerpt']}~~ → **{e['correction']}** ({e['count']}x){rule}")
        lines.append("")
    if r["topics"]:
        lines += ["### Tópicos", "", "| Tópico | Erros | Acertos |", "|---|---|---|"]
        lines += [f"| {t['name_pt']} | {t['errors']} | {t['correct']} |" for t in r["topics"]]
        lines.append("")
    if r["words"]["not_used_examples"]:
        lines += [f"**Palavras que você ainda não usou nas respostas:** {', '.join(r['words']['not_used_examples'])}", ""]
    if narrative and narrative.get("recall_comment_pt"):
        lines += [narrative["recall_comment_pt"], ""]
    return lines
