"""Operações independentes de IA: suggest_hints e evaluate_exercise (generate_report na Fase 2)."""

import json
import re
from typing import Callable, TypeVar

from . import prompts
from .client import LLMClient, LLMError, LLMUnavailable
from .schemas import HintsResult, LLMEvaluation, LLMFinalReview, LLMReportNarrative

T = TypeVar("T")


def _with_one_retry(call: Callable[[], T]) -> T:
    """Em erro de geração/JSON tenta mais uma vez. Ollama fora do ar não justifica repetir."""
    try:
        return call()
    except LLMUnavailable:
        raise
    except LLMError:
        return call()


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z']+", text.lower()))


def suggest_hints(llm: LLMClient, frame_text: str, current_sentence: str, stage: int) -> list[str]:
    result = _with_one_retry(
        lambda: llm.generate(
            prompts.HINTS_SYSTEM,
            prompts.hints_user_prompt(frame_text, current_sentence, stage),
            HintsResult,
        )
    )
    base_words = _words(current_sentence)
    hints: list[str] = []
    for hint in result.hints:
        hint = hint.strip()
        if not hint or hint in hints:
            continue
        # Descarta "dicas" que são a frase do usuário já reescrita (frase pronta).
        hint_words = _words(hint)
        if base_words and len(hint_words & base_words) >= max(4, int(0.7 * len(base_words))):
            continue
        hints.append(hint)
    if not hints:
        raise LLMError("A IA não gerou ideias utilizáveis. Tente novamente.")
    return hints[:3]


def evaluate_exercise(
    llm: LLMClient,
    frame_text: str,
    frame_explanation: str,
    versions: list[str],
    topic_ids: list[str],
) -> LLMEvaluation:
    system = prompts.EVALUATION_SYSTEM.replace("{topics}", ", ".join(_prompt_topics(topic_ids)))
    user = prompts.evaluation_user_prompt(frame_text, frame_explanation, versions)
    return _with_one_retry(lambda: llm.generate(system, user, LLMEvaluation))


def review_final_sentence(
    llm: LLMClient, frame_text: str, final_sentence: str, used_connectors: list[str], topic_ids: list[str]
) -> LLMFinalReview:
    system = prompts.FINAL_REVIEW_SYSTEM.replace("{topics}", ", ".join(_prompt_topics(topic_ids)))
    user = prompts.final_review_user_prompt(frame_text, final_sentence, used_connectors)
    return _with_one_retry(lambda: llm.generate(system, user, LLMFinalReview))


def generate_report(llm: LLMClient, report_data: dict) -> LLMReportNarrative:
    """Recebe agregados e evidências já selecionadas; devolve só a análise textual."""
    recall = report_data.get("recall")
    compact = {
        "periodo": report_data["period"]["label"],
        "criador_de_frases": report_data.get("has_builder", True),
        "anki_premium": None if not recall else {
            k: recall[k] for k in ("attempts", "new", "review", "new_accuracy", "avg_score", "words", "reviews")
        } | {
            "erros_mais_frequentes": [f"{e['excerpt']} -> {e['correction']} ({e['count']}x)"
                                      for e in recall["recurring_errors"]],
            "topicos": [f"{t['name_pt']}: {t['errors']} erro(s)" for t in recall["topics"]],
        },
        "totais": report_data["totals"],
        "topicos": [
            {k: t[k] for k in ("topic_id", "name_pt", "state", "errors", "correct")}
            | {"erros_que_ficaram_na_frase_final": [f"{e['excerpt']} -> {e['correction']}" for e in t["examples"][:2]]}
            for t in report_data["topics"]
        ],
        "exemplos_de_elaboracao": [e["suggestion_en"] for e in report_data["elaboration_examples"]],
        "autocorrecoes_ja_corrigidas_por_voce_nao_sao_erros": [
            f"{s['before']} -> {s['after']}" for s in report_data["self_corrections"]
        ],
        "semanas": report_data["weekly"],
        "limitacoes": report_data["limitations"],
    }
    user = prompts.report_user_prompt(json.dumps(compact, ensure_ascii=False, default=str))
    return _with_one_retry(lambda: llm.generate(prompts.REPORT_SYSTEM, user, LLMReportNarrative))


def _prompt_topics(topic_ids: list[str]) -> list[str]:
    return [t for t in topic_ids if t != "capitalization_punctuation"]
