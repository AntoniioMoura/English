"""Operações de IA do Sentence Recall. O backend valida tudo o que a IA devolve."""

from ..domain.recall import normalize_vocab, repeats_itself, target_demonstrated, validate_sentence_pt
from ..seed_data import GRAMMAR_TOPICS
from . import recall_prompts as prompts
from .client import LLMClient, LLMError, LLMUnavailable
from .operations import _with_one_retry
from .schemas import LLMRecallEvaluation, LLMRecallPrompt, LLMReferenceCheck

MAX_GENERATION_ATTEMPTS = 3
LEAK = "a frase em português continha a palavra em inglês"
NO_TARGET = "a tradução de referência não usa a palavra-alvo"
NO_REVIEW_TARGET = "a tradução de referência não usa a palavra revisada"
NONSENSE = "it does not make sense as a real situation, or the translation was wrong"
NATIVE_SKIPS_TARGET = ("a native speaker would say this sentence WITHOUT the target word (they would rephrase "
                       "it). Choose a situation where the most natural English uses the target")
REASONS_EN = {
    LEAK: "the Portuguese sentence contains the English word (use its Portuguese meaning instead)",
    NO_TARGET: "the English translation does not use the target word",
    NO_REVIEW_TARGET: "the English translation does not contain the exact word being reviewed "
                      "(a similar word, like their instead of theirs, does not count)",
}


def _topics(topic_ids: list[str]) -> str:
    return ", ".join(t for t in topic_ids if t != "capitalization_punctuation")


def _topic_lines(topic_ids: list[str]) -> str:
    """Tópicos com descrição: sem isso o modelo pequeno classifica quase tudo como 'other'."""
    described = {tid: f"{name}: {desc}" for tid, name, desc in GRAMMAR_TOPICS}
    return "\n".join(f"- {t} ({described.get(t, t)})" for t in topic_ids if t != "capitalization_punctuation")


def _reveals_answer(result: LLMRecallPrompt, entries: list[dict]) -> str | None:
    """A frase em português não pode trazer a palavra-alvo em inglês (seria a resposta pronta)."""
    for e in entries:
        # Alvos curtos (do, no, me, so) também são palavras do português: não dá para checar.
        if len(e["english_text"]) >= 4 and target_demonstrated(e["english_text"], result.sentence_pt):
            return LEAK
    return None


def _verified(llm: LLMClient, result: LLMRecallPrompt, check) -> tuple[LLMRecallPrompt | None, str]:
    """Confere a tradução de referência e se a forma mais natural da frase usa a palavra-alvo.
    Devolve a frase aprovada (a referência vira a forma nativa) ou None e o motivo em inglês."""
    try:
        verdict = llm.generate(
            prompts.CHECK_REFERENCE_SYSTEM,
            prompts.check_reference_user_prompt(result.sentence_pt, result.reference_en),
            LLMReferenceCheck,
        )
    except LLMError:
        return result, ""  # a checagem é uma proteção extra; sem ela, segue a referência gerada
    if not verdict.portuguese_makes_sense:
        return None, NONSENSE  # frase absurda ou forçada: gera outra
    native = verdict.native_en.strip()
    if native:
        # "Como um nativo diria" é o que você leva da correção: precisa praticar a palavra.
        candidate = result.model_copy(update={"reference_en": native})
        if check(candidate) is not None:
            return None, NATIVE_SKIPS_TARGET
        return candidate, ""
    if verdict.is_correct or not verdict.corrected_en.strip():
        return result, ""
    fixed = result.model_copy(update={"reference_en": verdict.corrected_en.strip()})
    return (fixed, "") if check(fixed) is None else (None, NONSENSE)


def _generate_validated(llm: LLMClient, system: str, user: str, recent: list[str], check,
                        checker: LLMClient | None = None) -> LLMRecallPrompt:
    """Gera e valida; uma frase inválida (longa, repetida, sem o alvo) conta como falha e é refeita.
    `checker` confere a forma nativa: o modelo das correções (o Claude, quando ligado) julga melhor."""
    recent_norm = {normalize_vocab(s) for s in recent}
    last_problem = "frase inválida"
    feedback = ""
    for attempt in range(MAX_GENERATION_ATTEMPTS):
        try:
            # Sem esse retorno o modelo repete a mesma frase recusada a cada tentativa.
            result = llm.generate(system, user + feedback, LLMRecallPrompt, temperature=0.5 + 0.2 * attempt)
        except LLMUnavailable:
            raise
        except LLMError as exc:
            last_problem = str(exc)
            continue
        sentence = result.sentence_pt.strip()
        if not validate_sentence_pt(sentence) or not result.reference_en.strip():
            last_problem, reason = "frase longa demais ou vazia", "too long or empty"
        elif normalize_vocab(sentence) in recent_norm:
            last_problem, reason = "frase repetida", "it repeats a recent sentence"
        elif repeats_itself(sentence) or repeats_itself(result.reference_en):
            last_problem, reason = "a frase repetia o mesmo trecho", "it repeats the same words twice"
        elif (problem := check(result)) is not None:
            last_problem, reason = problem, REASONS_EN.get(problem, problem)
        else:
            verified, reason = _verified(checker or llm, result, check)
            if verified is not None:
                return verified
            last_problem = ("um nativo diria a frase sem a palavra-alvo" if reason == NATIVE_SKIPS_TARGET
                            else "a frase não fazia sentido ou a tradução estava incorreta")
        feedback = (f"\n\nYour previous sentence was REJECTED because {reason}: \"{sentence}\". "
                    "Write a completely different, natural sentence.")
    raise LLMError(f"A IA não conseguiu criar uma frase adequada ({last_problem}). Tente de novo.")


def generate_recall_prompt(llm: LLMClient, entries: list[dict], recent: list[str], topic_ids: list[str],
                           checker: LLMClient | None = None) -> dict:
    system = prompts.GENERATE_SYSTEM.replace("{topics}", _topics(topic_ids))
    user = prompts.generate_user_prompt(entries, recent)

    def check(result: LLMRecallPrompt) -> str | None:
        if not any(target_demonstrated(e["english_text"], result.reference_en) for e in entries):
            return NO_TARGET
        return _reveals_answer(result, entries)

    result = _generate_validated(llm, system, user, recent, check, checker)
    meanings = {normalize_vocab(t.english_text): t.meaning_pt for t in result.targets}
    targets = [
        {
            "vocabulary_id": e["id"],
            "english_text": e["english_text"],
            "intended_meaning": e.get("translation_pt") or meanings.get(normalize_vocab(e["english_text"])),
        }
        for e in entries
        if target_demonstrated(e["english_text"], result.reference_en)  # só alvos que cabem na frase
    ]
    return {
        "sentence_pt": result.sentence_pt.strip(),
        "reference_en": result.reference_en.strip(),
        "targets": targets,
        "grammar_tags": [t for t in result.grammar_tags if t in topic_ids],
    }


def generate_targeted_review(
    llm: LLMClient, item: dict, target_text: str, entry: dict | None, recent: list[str], topic_ids: list[str],
    checker: LLMClient | None = None,
) -> dict:
    system = prompts.REVIEW_SYSTEM.replace("{topics}", _topics(topic_ids))
    user = prompts.review_user_prompt(item["label_pt"], item["target_type"], target_text, item["examples"], recent)

    def check(result: LLMRecallPrompt) -> str | None:
        if entry and not target_demonstrated(entry["english_text"], result.reference_en):
            return NO_REVIEW_TARGET
        return _reveals_answer(result, [entry] if entry else [])

    result = _generate_validated(llm, system, user, recent, check, checker)
    targets = []
    if entry:
        targets.append({"vocabulary_id": entry["id"], "english_text": entry["english_text"],
                        "intended_meaning": entry.get("translation_pt")})
    tags = [t for t in result.grammar_tags if t in topic_ids]
    return {"sentence_pt": result.sentence_pt.strip(), "reference_en": result.reference_en.strip(),
            "targets": targets, "grammar_tags": tags}


def evaluate_recall_answer(
    llm: LLMClient, sentence_pt: str, reference_en: str, targets: list[str], answer: str, topic_ids: list[str]
) -> LLMRecallEvaluation:
    system = prompts.EVALUATE_SYSTEM.replace("{topics}", _topic_lines(topic_ids))
    user = prompts.evaluate_user_prompt(sentence_pt, reference_en, targets, answer)
    return _with_one_retry(lambda: llm.generate(system, user, LLMRecallEvaluation))
