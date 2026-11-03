"""Pós-processamento determinístico da avaliação da IA.

Aqui fica a separação entre os dois eixos:
- erro gramatical (objetivo, entra no contador por tópico);
- desenvolvimento de ideias / oportunidade de melhoria (nunca vira erro).

Também protege o histórico contra respostas ruins do modelo: trechos que não existem
na frase do usuário são descartados, ocorrências repetidas entre V0–V3 contam uma vez
e sugestões de estilo classificadas como erro são remanejadas para "ideias".
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from ..llm.schemas import LLMEvaluation, LLMFinalReview, LLMGrammarError
from .rules import FINAL_VERSION

MIN_VISIBLE_CONFIDENCE = 0.5
MAX_PRIORITY_ADJUSTMENTS = 2
MAX_IDEA_SUGGESTIONS = 1
IGNORED_TOPICS = {"capitalization_punctuation"}

CONNECTORS = [
    "because", "so", "but", "and", "when", "although", "even though", "while", "after", "before",
    "if", "then", "since", "until", "however", "or",
]
TENSE_SHIFTS = {
    "do": "did", "does": "did", "don't": "didn't", "doesn't": "didn't",
    "am": "was", "is": "was", "are": "were", "isn't": "wasn't", "aren't": "weren't",
    "have": "had", "has": "had", "can": "could", "can't": "couldn't",
    "will": "would", "won't": "wouldn't",
}
PAST_MARKERS = {"yesterday", "last", "ago", "earlier", "once"}
TIP_CONNECTORS = [
    ("when", "quando", "I was very happy when I got the job."),
    ("although", "embora", "Although I was tired, I finished my homework."),
    ("after", "depois que", "After I finished work, I went to the gym."),
    ("while", "enquanto", "I listened to music while I was cooking."),
    ("before", "antes de", "I always drink coffee before I go to work."),
]

IDEA_KINDS = {
    "relevant_expansion",
    "cohesion",
    "clarity",
    "connector_variety",
    "elaboration_opportunity",
    "naturalness",
}
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


class GrammarErrorItem(BaseModel):
    topic_id: str
    version_index: int
    original_excerpt: str
    suggested_correction: str
    explanation_pt: str
    severity: str
    confidence: float
    persists_in_final: bool
    visible: bool


class GrammarCorrectItem(BaseModel):
    topic_id: str
    version_index: int
    excerpt: str
    explanation_pt: str


class SelfCorrectionItem(BaseModel):
    topic_id: str
    from_version: int
    to_version: int
    before: str
    after: str
    explanation_pt: str


class IdeaItem(BaseModel):
    version_index: int | None
    kind: str
    is_positive: bool
    comment_pt: str
    suggestion_en: str | None = None
    rerouted_from_grammar: bool = False
    from_final_review: bool = False


class FeedbackAdjustment(BaseModel):
    type: Literal["error", "improvement"]
    message_pt: str
    excerpt: str | None = None
    correction: str | None = None
    suggestion_en: str | None = None


class Feedback(BaseModel):
    highlight: str
    grammar_corrections: list[FeedbackAdjustment]
    idea_suggestions: list[FeedbackAdjustment]
    final_is_correct: bool
    corrected_final_sentence: str | None
    self_corrections: list[str]
    frame_note: str | None
    next_tip: str
    next_tip_example: str | None = None


class DiscardedItem(BaseModel):
    reason: str
    item: dict


class ProcessedEvaluation(BaseModel):
    grammar_errors: list[GrammarErrorItem] = Field(default_factory=list)
    grammar_correct: list[GrammarCorrectItem] = Field(default_factory=list)
    self_corrections: list[SelfCorrectionItem] = Field(default_factory=list)
    ideas: list[IdeaItem] = Field(default_factory=list)
    frame_used_correctly: bool = True
    final_is_correct: bool = True
    feedback: Feedback
    discarded: list[DiscardedItem] = Field(default_factory=list)


# ---------- helpers de texto ----------

def _norm(text: str) -> str:
    text = (text or "").replace("’", "'").replace("‘", "'").lower()
    return re.sub(r"\s+", " ", text).strip()


def _strip_edges(text: str) -> str:
    return _norm(text).strip(" .,!?;:\"")


def _pattern(excerpt: str) -> re.Pattern | None:
    core = _strip_edges(excerpt)
    if not core:
        return None
    return re.compile(r"(?<![\w'])" + re.escape(core) + r"(?![\w'])")


def _versions_containing(excerpt: str, versions: list[str]) -> list[int]:
    pattern = _pattern(excerpt)
    if pattern is None:
        return []
    return [i for i, v in enumerate(versions) if pattern.search(_norm(v))]


def _letters_only(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", "", (text or "").replace("’", "'"))).strip()


def only_case_or_punctuation(original: str, correction: str) -> bool:
    return _letters_only(original).lower() == _letters_only(correction).lower()


def keep_user_case(original: str, correction: str) -> str:
    """Mantém a capitalização do usuário nas palavras que a correção não muda de fato."""
    original_words = {w.lower(): w for w in original.split()}
    return " ".join(original_words.get(w.lower(), w) for w in correction.split())


def apply_corrections(sentence: str, errors: list[GrammarErrorItem]) -> str:
    """Corrige apenas os trechos com erro, preservando as palavras do usuário. Trechos que se sobrepõem
    (a IA às vezes aponta "has 25 years" e também "25 years") valem uma vez só: fica o maior."""
    normalized = sentence.replace("’", "'")
    spans: list[tuple[int, int, str]] = []
    for error in errors:
        core = _strip_edges(error.original_excerpt)
        if not core:
            continue
        regex = re.compile(r"(?<![\w'])" + re.escape(core) + r"(?![\w'])", re.IGNORECASE)
        match = regex.search(normalized)
        if match:
            spans.append((match.start(), match.end(), error.suggested_correction.strip().strip(".!?")))
    chosen: list[tuple[int, int, str]] = []
    for start, end, replacement in sorted(spans, key=lambda s: s[0] - s[1]):  # maiores primeiro
        if all(end <= s or start >= e for s, e, _ in chosen):
            chosen.append((start, end, replacement))
    if not chosen:
        return sentence
    result = normalized
    for start, end, replacement in sorted(chosen, reverse=True):  # da direita para a esquerda
        result = result[:start] + replacement + result[end:]
    return result


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", _norm(text))


def used_connectors(sentence: str) -> list[str]:
    text = " " + " ".join(_words(sentence)) + " "
    return [c for c in CONNECTORS if f" {c} " in text]


def builds_on_sentence(example: str, sentence: str) -> bool:
    """O exemplo precisa ser a frase do usuário com algo a mais, não uma frase solta."""
    base, ex = _words(sentence), _words(example)
    if not base or len(ex) <= len(base):
        return False
    shared = sum(1 for w in set(base) if w in set(ex))
    return shared >= 0.6 * len(set(base))


def _mentions_used_connector(tip: str, used: list[str]) -> bool:
    quoted = {_norm(q) for q in re.findall(r"['\"“‘]([^'\"”’]+)['\"”’]", tip)}
    return any(c in quoted for c in used)


def _fallback_tip(used: list[str]) -> tuple[str, str]:
    for connector, meaning, example in TIP_CONNECTORS:
        if connector not in used:
            return (f"Na próxima, experimente ligar duas ideias com '{connector}' ({meaning}).", example)
    return ("Na próxima, tente acrescentar um detalhe de lugar ou de tempo logo na frase inicial.",
            "I wanted to travel to the beach last summer, but it rained every day.")


def is_optional_tense_shift(excerpt: str, correction: str, sentence: str) -> bool:
    """'don't have' → 'didn't have' sem marcador de passado não é erro: os dois tempos fazem
    sentido ("ainda não tenho" vs. "não tinha"). Com 'yesterday', 'last week' etc. continua sendo erro."""
    before, after = _words(excerpt), _words(correction)
    if len(before) != len(after):
        return False
    diffs = [(b, a) for b, a in zip(before, after) if b != a]
    if len(diffs) != 1 or TENSE_SHIFTS.get(diffs[0][0]) != diffs[0][1]:
        return False
    return not (set(_words(sentence)) & PAST_MARKERS)


def _final_review_errors(review: LLMFinalReview | None) -> list[LLMGrammarError]:
    if review is None:
        return []
    return [
        LLMGrammarError(
            topic_id=c.topic_id,
            version_index=FINAL_VERSION,
            original_excerpt=c.phrase,
            suggested_correction=c.correction,
            explanation_pt=c.explanation_pt or "Ajuste na forma do verbo.",
            severity="medium",
            confidence=0.8,
        )
        for c in review.phrase_checks
        if not c.is_correct and c.correction
    ]


def _contradicted(excerpt: str, review: LLMFinalReview | None) -> bool:
    """Um erro na frase final que a revisão focada considerou correto é descartado."""
    if review is None:
        return False
    pattern = _pattern(excerpt)
    return pattern is not None and any(c.is_correct and pattern.search(_norm(c.phrase)) for c in review.phrase_checks)


def _overlaps(core: str, accepted: list[GrammarErrorItem]) -> bool:
    for e in accepted:
        other = _strip_edges(e.original_excerpt)
        if core in other or other in core:
            return True
    return False


# ---------- pós-processamento ----------

def process_evaluation(
    raw: LLMEvaluation,
    versions: list[str],
    topic_ids: set[str],
    final_review: LLMFinalReview | None = None,
) -> ProcessedEvaluation:
    discarded: list[DiscardedItem] = []
    ideas: list[IdeaItem] = []

    def topic(t: str) -> str:
        t = (t or "").strip().lower()
        return t if t in topic_ids else "other"

    # Eixo 1: erros gramaticais. A revisão focada da frase final vem primeiro (é mais confiável).
    errors: list[GrammarErrorItem] = []
    review_errors = _final_review_errors(final_review)
    for index, err in enumerate(review_errors + raw.grammar_errors):
        from_review = index < len(review_errors)
        if err.category == "style":
            ideas.append(
                IdeaItem(
                    version_index=err.version_index,
                    kind="naturalness",
                    is_positive=False,
                    comment_pt=err.explanation_pt,
                    suggestion_en=err.suggested_correction,
                    rerouted_from_grammar=True,
                )
            )
            continue
        # Maiúsculas e pontuação não ajudam a construir frases: não viram erro nem sugestão.
        if (
            topic(err.topic_id) in IGNORED_TOPICS
            or only_case_or_punctuation(err.original_excerpt, err.suggested_correction)
        ):
            discarded.append(DiscardedItem(reason="capitalization_or_punctuation_only", item=err.model_dump()))
            continue
        found_in = _versions_containing(err.original_excerpt, versions)
        if not found_in:
            discarded.append(DiscardedItem(reason="excerpt_not_in_text", item=err.model_dump()))
            continue
        if is_optional_tense_shift(err.original_excerpt, err.suggested_correction, versions[found_in[0]]):
            discarded.append(DiscardedItem(reason="optional_tense_shift", item=err.model_dump()))
            continue
        key = (topic(err.topic_id), _strip_edges(err.original_excerpt))
        if _overlaps(key[1], errors):
            discarded.append(DiscardedItem(reason="duplicate_across_versions", item=err.model_dump()))
            continue
        if not from_review and FINAL_VERSION in found_in and _contradicted(err.original_excerpt, final_review):
            discarded.append(DiscardedItem(reason="contradicted_by_final_review", item=err.model_dump()))
            continue
        errors.append(
            GrammarErrorItem(
                topic_id=key[0],
                version_index=found_in[0],
                original_excerpt=err.original_excerpt,
                suggested_correction=keep_user_case(err.original_excerpt, err.suggested_correction),
                explanation_pt=err.explanation_pt,
                severity=err.severity,
                confidence=err.confidence,
                persists_in_final=FINAL_VERSION in found_in,
                visible=err.confidence >= MIN_VISIBLE_CONFIDENCE,
            )
        )

    # Acertos: só quando o trecho existe de fato; um por tópico por exercício.
    correct: list[GrammarCorrectItem] = []
    seen_correct: set[str] = set()
    for ev in raw.grammar_correct_evidence:
        found_in = _versions_containing(ev.excerpt, versions)
        if not found_in:
            discarded.append(DiscardedItem(reason="excerpt_not_in_text", item=ev.model_dump()))
            continue
        t = topic(ev.topic_id)
        if t in seen_correct or t in IGNORED_TOPICS:
            continue
        seen_correct.add(t)
        correct.append(
            GrammarCorrectItem(
                topic_id=t, version_index=found_in[0], excerpt=ev.excerpt, explanation_pt=ev.explanation_pt
            )
        )

    # Autocorreções: o trecho antigo existia antes e não está mais na versão final.
    self_corrections: list[SelfCorrectionItem] = []
    seen_sc: set[tuple[str, str]] = set()
    for sc in raw.self_corrections:
        if topic(sc.topic_id) in IGNORED_TOPICS or only_case_or_punctuation(sc.before, sc.after):
            continue
        before_in = _versions_containing(sc.before, versions)
        if not before_in or FINAL_VERSION in before_in:
            discarded.append(DiscardedItem(reason="self_correction_not_verified", item=sc.model_dump()))
            continue
        key = (topic(sc.topic_id), _strip_edges(sc.before))
        if key in seen_sc:
            continue
        seen_sc.add(key)
        after_in = _versions_containing(sc.after, versions)
        to_version = next((i for i in after_in if i > before_in[0]), max(before_in) + 1)
        self_corrections.append(
            SelfCorrectionItem(
                topic_id=key[0],
                from_version=before_in[0],
                to_version=min(to_version, FINAL_VERSION),
                before=sc.before,
                after=sc.after,
                explanation_pt=sc.explanation_pt,
            )
        )

    # Eixo 2: desenvolvimento de ideias (nunca vira erro)
    for item in raw.idea_development:
        kind = item.kind.strip().lower()
        if kind not in IDEA_KINDS:
            kind = "relevant_expansion" if item.is_positive else "elaboration_opportunity"
        ideas.append(
            IdeaItem(
                version_index=item.version_index,
                kind=kind,
                is_positive=item.is_positive,
                comment_pt=item.comment_pt,
                suggestion_en=item.suggestion_en,
            )
        )

    unresolved = [e for e in errors if e.persists_in_final and e.visible]
    final_is_correct = not unresolved
    corrected = None if final_is_correct else apply_corrections(versions[FINAL_VERSION], unresolved)

    # Ideia concreta: a frase final do usuário com um detalhe a mais.
    if final_review:
        # O exemplo não pode repetir os erros que acabamos de apontar.
        example = apply_corrections(final_review.enrichment_example_en.strip(), unresolved)
        if builds_on_sentence(example, versions[FINAL_VERSION]):
            ideas.insert(
                0,
                IdeaItem(
                    version_index=FINAL_VERSION,
                    kind="elaboration_opportunity",
                    is_positive=False,
                    comment_pt=final_review.enrichment_comment_pt,
                    suggestion_en=example,
                    from_final_review=True,
                ),
            )
        else:
            discarded.append(DiscardedItem(reason="enrichment_not_based_on_sentence", item={"example": example}))

    feedback = _build_feedback(
        raw, final_review, versions, unresolved, ideas, correct, self_corrections, final_is_correct, corrected
    )
    return ProcessedEvaluation(
        grammar_errors=errors,
        grammar_correct=correct,
        self_corrections=self_corrections,
        ideas=ideas,
        frame_used_correctly=raw.frame_usage.used_correctly,
        final_is_correct=final_is_correct,
        feedback=feedback,
        discarded=discarded,
    )


def _build_feedback(
    raw: LLMEvaluation,
    final_review: LLMFinalReview | None,
    versions: list[str],
    unresolved: list[GrammarErrorItem],
    ideas: list[IdeaItem],
    correct: list[GrammarCorrectItem],
    self_corrections: list[SelfCorrectionItem],
    final_is_correct: bool,
    corrected: str | None,
) -> Feedback:
    # Acertos verificados no texto do usuário têm prioridade sobre elogios livres do modelo.
    positive_ideas = [i for i in ideas if i.is_positive]
    if correct:
        highlight = correct[0].explanation_pt
    elif raw.highlights:
        highlight = raw.highlights[0]
    elif positive_ideas:
        highlight = positive_ideas[0].comment_pt
    else:
        highlight = "Você completou a frase inicial e as três expansões!"

    priority_errors = sorted(unresolved, key=lambda e: (_SEVERITY_RANK.get(e.severity, 1), -e.confidence))
    grammar_corrections = [
        FeedbackAdjustment(
            type="error", message_pt=e.explanation_pt, excerpt=e.original_excerpt, correction=e.suggested_correction
        )
        for e in priority_errors[:MAX_PRIORITY_ADJUSTMENTS]
    ]
    # Só mostra ideias com exemplo concreto; comentários vagos ficam apenas no histórico.
    opportunities = [
        i for i in ideas if not i.is_positive and i.suggestion_en and (i.from_final_review or i.rerouted_from_grammar)
    ]
    idea_suggestions = [
        FeedbackAdjustment(type="improvement", message_pt=i.comment_pt, suggestion_en=i.suggestion_en)
        for i in opportunities[:MAX_IDEA_SUGGESTIONS]
    ]

    # Dica: não pode mandar usar um conector que a pessoa já usou.
    used = sorted({c for v in versions for c in used_connectors(v)})
    candidates = []
    if final_review:
        candidates.append((final_review.next_tip_pt, final_review.next_tip_example_en))
    candidates.append((raw.next_tip, None))
    next_tip, next_tip_example = next(
        ((tip, ex) for tip, ex in candidates if tip and not _mentions_used_connector(tip, used)),
        _fallback_tip(used),
    )

    frame_note = None if raw.frame_usage.used_correctly else raw.frame_usage.comment_pt
    return Feedback(
        highlight=highlight,
        grammar_corrections=grammar_corrections,
        idea_suggestions=idea_suggestions,
        final_is_correct=final_is_correct,
        corrected_final_sentence=corrected,
        self_corrections=[f"{s.before} → {s.after}" for s in self_corrections[:3]],
        frame_note=frame_note,
        next_tip=next_tip,
        next_tip_example=next_tip_example,
    )
