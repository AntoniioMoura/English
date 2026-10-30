"""Métricas do relatório, calculadas só a partir dos registros. A IA nunca produz números.

As observações antigas passam pelos mesmos filtros da avaliação atual: maiúscula/pontuação,
troca opcional de tempo verbal, observações descartadas pelo usuário ou de baixa confiança
não contam como erro. Ideias de elaboração ficam separadas e nunca entram na precisão.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from .evaluation import (
    IGNORED_TOPICS,
    apply_corrections,
    builds_on_sentence,
    is_optional_tense_shift,
    only_case_or_punctuation,
    used_connectors,
)
from .rules import FINAL_VERSION

MIN_OPPORTUNITIES = 3            # abaixo disso: dados insuficientes
NEEDS_ATTENTION_RATE = 0.5       # metade ou mais das oportunidades com erro
CONSISTENT_RATE = 0.25
CONSISTENT_MIN_OPPORTUNITIES = 4
CONSISTENT_MIN_DAYS = 2          # acertos em dias diferentes
IMPROVEMENT_DELTA = 0.25         # queda da taxa de erro entre a 1ª e a 2ª metade
REPORTABLE_REVIEW = {"pending", "confirmed"}
SMALL_SAMPLE = 5

STATE_ORDER = ["precisa_de_atencao", "revisar", "em_evolucao", "consistente", "dados_insuficientes"]


def local_date(iso: str) -> date:
    return datetime.fromisoformat(iso).astimezone().date()


def is_reportable(obs: dict, version_text: str) -> bool:
    """Aplica às observações salvas os critérios atuais do que é (ou não) erro gramatical."""
    if obs["review_status"] not in REPORTABLE_REVIEW or obs["topic_id"] in IGNORED_TOPICS:
        return False
    if obs["evidence_type"] in ("error", "self_correction") and obs["suggested_correction"]:
        before, after = obs["original_excerpt"], obs["suggested_correction"]
        if only_case_or_punctuation(before, after) or is_optional_tense_shift(before, after, version_text):
            return False
    return True


def topic_state(sequence: list[bool], correct_days: int) -> str:
    """`sequence`: oportunidades em ordem cronológica, True = erro."""
    total = len(sequence)
    if total < MIN_OPPORTUNITIES:
        return "dados_insuficientes"
    rate = sum(sequence) / total
    half = total // 2
    early, late = sequence[:half], sequence[half:]
    early_rate, late_rate = sum(early) / len(early), sum(late) / len(late)
    if early_rate - late_rate >= IMPROVEMENT_DELTA and late_rate < NEEDS_ATTENTION_RATE:
        return "em_evolucao"
    if rate >= NEEDS_ATTENTION_RATE:
        return "precisa_de_atencao"
    if (
        total >= CONSISTENT_MIN_OPPORTUNITIES
        and rate <= CONSISTENT_RATE
        and correct_days >= CONSISTENT_MIN_DAYS
        and not sequence[-1]
    ):
        return "consistente"
    return "revisar"


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def compute_report(
    period: dict,
    exercises: list[dict],
    versions: list[dict],
    grammar_obs: list[dict],
    idea_obs: list[dict],
    topic_names: dict[str, str],
) -> dict:
    ex_by_id = {e["id"]: e for e in exercises}
    text_of: dict[int, dict[int, dict]] = defaultdict(dict)
    for v in versions:
        text_of[v["exercise_id"]][v["version_index"]] = v
    day_of = {e["id"]: local_date(e["completed_at"] or e["started_at"]) for e in exercises}

    # ---------- precisão gramatical ----------
    reportable: list[dict] = []
    dismissed = 0
    for obs in grammar_obs:
        if obs["exercise_id"] not in ex_by_id:
            continue
        if obs["review_status"] == "dismissed":
            dismissed += 1
        version = text_of[obs["exercise_id"]].get(obs["version_index"])
        if is_reportable(obs, version["text"] if version else ""):
            reportable.append({**obs, "day": day_of[obs["exercise_id"]]})

    # Um erro que não chegou à frase final foi corrigido por você: conta como autocorreção (avanço).
    by_topic: dict[str, list[dict]] = defaultdict(list)
    self_corrections: list[dict] = []
    for obs in sorted(reportable, key=lambda o: o["evidence_type"] != "self_correction"):
        is_resolved_error = obs["evidence_type"] == "error" and obs["resolved_in_final"]
        if obs["evidence_type"] == "self_correction" or is_resolved_error:
            excerpt = obs["original_excerpt"].lower()
            duplicate = any(
                s["exercise_id"] == obs["exercise_id"]
                and (excerpt in s["original_excerpt"].lower() or s["original_excerpt"].lower() in excerpt)
                for s in self_corrections
            )
            if not duplicate:
                self_corrections.append(obs)
        elif obs["evidence_type"] in ("error", "correct"):
            by_topic[obs["topic_id"]].append(obs)

    topics = []
    for topic_id, items in by_topic.items():
        items.sort(key=lambda o: (o["day"], o["exercise_id"], o["id"]))
        sequence = [o["evidence_type"] == "error" for o in items]
        errors = [o for o in items if o["evidence_type"] == "error"]
        correct_days = len({o["day"] for o in items if o["evidence_type"] == "correct"})
        examples, seen = [], set()
        for o in reversed(errors):
            key = o["original_excerpt"].lower()
            if key in seen:
                continue
            seen.add(key)
            examples.append({
                "excerpt": o["original_excerpt"],
                "correction": o["suggested_correction"],
                "explanation_pt": o["explanation_pt"],
                "date": o["day"].isoformat(),
                "exercise_id": o["exercise_id"],
            })
        topics.append({
            "topic_id": topic_id,
            "name_pt": topic_names.get(topic_id, topic_id),
            "errors": len(errors),
            "correct": len(items) - len(errors),
            "opportunities": len(items),
            "error_rate": _ratio(len(errors), len(items)),
            "self_corrections": sum(1 for s in self_corrections if s["topic_id"] == topic_id),
            "state": topic_state(sequence, correct_days),
            "examples": examples[:3],
        })
    topics.sort(key=lambda t: (STATE_ORDER.index(t["state"]), -t["errors"], t["name_pt"]))

    # ---------- desenvolvimento de ideias ----------
    expansions = [v for e in exercises for i, v in text_of[e["id"]].items() if i >= 1]
    hinted = sum(1 for v in expansions if v["hints_opened"])
    # Só mede expansões que a IA de fato avaliou; sem avaliação, o indicador fica vazio (não 0%).
    assessed_expansions = {
        (o["exercise_id"], o["version_index"])
        for o in idea_obs
        if o["exercise_id"] in ex_by_id and o["version_index"] and o["version_index"] >= 1
    }
    relevant = {
        (o["exercise_id"], o["version_index"])
        for o in idea_obs
        if (o["exercise_id"], o["version_index"]) in assessed_expansions
        and o["is_positive"] and o["kind"] == "relevant_expansion"
    }
    unresolved_by_exercise: dict[int, list[SimpleNamespace]] = defaultdict(list)
    for items in by_topic.values():
        for o in items:
            if o["evidence_type"] == "error":
                unresolved_by_exercise[o["exercise_id"]].append(
                    SimpleNamespace(original_excerpt=o["original_excerpt"], suggested_correction=o["suggested_correction"])
                )
    finals = {e["id"]: text_of[e["id"]].get(FINAL_VERSION, {}).get("text", "") for e in exercises}
    connectors_per_sentence = [used_connectors(t) for t in finals.values() if t]
    all_connectors = sorted({c for cs in connectors_per_sentence for c in cs})

    elaboration = []
    for o in sorted(idea_obs, key=lambda o: -o["id"]):
        final = finals.get(o["exercise_id"])
        if final and not o["is_positive"] and o["suggestion_en"] and builds_on_sentence(o["suggestion_en"], final):
            elaboration.append({
                "comment_pt": o["comment_pt"],
                "original": final,
                # O exemplo não pode repetir erros da frase (avaliações antigas às vezes repetiam).
                "suggestion_en": apply_corrections(o["suggestion_en"], unresolved_by_exercise[o["exercise_id"]]),
                "date": day_of[o["exercise_id"]].isoformat(),
            })
    self_correction_list = [
        {
            "before": s["original_excerpt"],
            "after": s["suggested_correction"],
            "topic": topic_names.get(s["topic_id"], s["topic_id"]),
            "date": s["day"].isoformat(),
        }
        for s in sorted(self_corrections, key=lambda s: s["day"], reverse=True)
    ]

    # ---------- evolução semanal ----------
    weeks: dict[date, dict] = {}
    for e in exercises:
        start = day_of[e["id"]] - timedelta(days=day_of[e["id"]].weekday())
        weeks.setdefault(start, {"exercises": 0, "errors": 0, "opportunities": 0, "expansions": 0, "hinted": 0})
        w = weeks[start]
        w["exercises"] += 1
        for i, v in text_of[e["id"]].items():
            if i >= 1:
                w["expansions"] += 1
                w["hinted"] += int(v["hints_opened"])
    for items in by_topic.values():
        for o in items:
            d = o["day"]
            w = weeks[d - timedelta(days=d.weekday())]
            w["opportunities"] += 1
            w["errors"] += int(o["evidence_type"] == "error")
    weekly = [
        {
            "week_start": start.isoformat(),
            "exercises": w["exercises"],
            "error_rate": _ratio(w["errors"], w["opportunities"]),
            "opportunities": w["opportunities"],
            "hint_rate": _ratio(w["hinted"], w["expansions"]),
        }
        for start, w in sorted(weeks.items())
    ]

    study_days = len(set(day_of.values()))
    totals = {
        "exercises": len(exercises),
        "study_days": study_days,
        "sessions": len({e["session_id"] for e in exercises}),
        "expansions": len(expansions),
        "hint_rate": _ratio(hinted, len(expansions)),
        "relevant_expansion_rate": _ratio(len(relevant), len(assessed_expansions)),
        "distinct_connectors": all_connectors,
        "avg_connectors_per_sentence": (
            round(sum(len(c) for c in connectors_per_sentence) / len(connectors_per_sentence), 1)
            if connectors_per_sentence else None
        ),
        "grammar_errors": sum(t["errors"] for t in topics),
        "grammar_opportunities": sum(t["opportunities"] for t in topics),
        "self_corrections": len(self_corrections),
        "dismissed_by_you": dismissed,
    }

    limitations = []
    if len(exercises) < SMALL_SAMPLE:
        limitations.append(
            f"Amostra pequena: {len(exercises)} estudo(s) concluído(s). As tendências ainda são pouco confiáveis."
        )
    if study_days < 2:
        limitations.append("Todos os estudos são do mesmo dia; não dá para medir evolução ao longo do tempo.")
    insufficient = [t["name_pt"] for t in topics if t["state"] == "dados_insuficientes"]
    if insufficient:
        limitations.append("Dados insuficientes para: " + ", ".join(insufficient) + ".")
    limitations.append(
        "Só contam tópicos que você realmente usou; estruturas não usadas não são avaliadas."
    )
    limitations.append(
        "As avaliações vêm de um modelo local e podem conter enganos. Maiúsculas, pontuação e "
        "correções que você marcou como equivocadas não contam como erro. Este relatório não define nível CEFR."
    )

    return {
        "period": period,
        "totals": totals,
        "topics": topics,
        "elaboration_examples": elaboration[:3],
        "self_corrections": self_correction_list[:6],
        "weekly": weekly,
        "limitations": limitations,
    }
