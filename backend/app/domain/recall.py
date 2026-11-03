"""Regras do Sentence Recall: normalização, uso da palavra-alvo e pós-processamento da avaliação.

Segue os mesmos critérios do Sentence Builder: maiúscula, pontuação e contrações
(did not / didn't) não são erro; estilo nunca vira erro; trecho que não está na
resposta é descartado; incerteza da IA nunca pune o usuário.
"""

import re
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, Field

from ..llm.schemas import LLMRecallEvaluation
from .evaluation import IGNORED_TOPICS, apply_corrections, keep_user_case, only_case_or_punctuation

Verdict = Literal["correct", "incorrect", "needs_review"]
MAX_ANSWER_CHARS = 300
MAX_SENTENCE_CHARS = 180
MAX_SENTENCE_WORDS = 22
MIN_CONFIDENCE = 0.5
MIN_CONFIDENCE_TO_OVERRIDE_CORRECT = 0.7
ERROR_CATEGORIES = {"grammar", "lexical", "meaning", "spelling"}

CONTRACTIONS = {
    "didn't": "did not", "don't": "do not", "doesn't": "does not", "isn't": "is not", "aren't": "are not",
    "wasn't": "was not", "weren't": "were not", "can't": "cannot", "couldn't": "could not",
    "won't": "will not", "wouldn't": "would not", "shouldn't": "should not", "haven't": "have not",
    "hasn't": "has not", "hadn't": "had not", "i'm": "i am", "you're": "you are", "we're": "we are",
    "they're": "they are", "he's": "he is", "she's": "she is", "it's": "it is", "that's": "that is",
    "there's": "there is", "i've": "i have", "you've": "you have", "we've": "we have", "they've": "they have",
    "i'll": "i will", "you'll": "you will", "he'll": "he will", "she'll": "she will", "we'll": "we will",
    "they'll": "they will", "it'll": "it will", "i'd": "i would", "let's": "let us",
}
IRREGULAR = {
    "went": "go", "gone": "go", "goes": "go", "had": "have", "has": "have", "was": "be", "were": "be",
    "is": "be", "are": "be", "am": "be", "been": "be", "did": "do", "does": "do", "done": "do",
    "got": "get", "gotten": "get", "made": "make", "took": "take", "taken": "take", "bought": "buy",
    "thought": "think", "felt": "feel", "found": "find", "came": "come", "saw": "see", "seen": "see",
    "said": "say", "told": "tell", "left": "leave", "knew": "know", "known": "know", "ate": "eat",
    "eaten": "eat", "wrote": "write", "written": "write", "spoke": "speak", "spoken": "speak",
    "began": "begin", "begun": "begin", "brought": "bring", "kept": "keep", "slept": "sleep",
    "met": "meet", "paid": "pay", "sent": "send", "spent": "spend", "stood": "stand", "understood": "understand",
    "won": "win", "lost": "lose", "ran": "run", "sat": "sit", "gave": "give", "given": "give",
    "drank": "drink", "drunk": "drink", "drove": "drive", "driven": "drive", "forgot": "forget",
    "forgotten": "forget", "heard": "hear", "taught": "teach", "caught": "catch", "fell": "fall",
    "fallen": "fall", "chose": "choose", "chosen": "choose", "children": "child", "people": "person",
    "better": "good", "best": "good", "worse": "bad", "worst": "bad",
}


# ---------- texto ----------

def canonical_tokens(text: str) -> list[str]:
    """Minúsculas, sem pontuação, contrações expandidas: 'I didn't go.' == 'i did not go'."""
    text = (text or "").replace("’", "'").replace("‘", "'").lower()
    text = re.sub(r"[^\w'\s]", " ", text)
    tokens: list[str] = []
    for word in text.split():
        word = word.strip("'")
        tokens.extend(CONTRACTIONS.get(word, word).split())
    joined = " ".join(tokens).replace("can not", "cannot")
    return joined.split()


def same_meaning_form(a: str, b: str) -> bool:
    return canonical_tokens(a) == canonical_tokens(b)


# Pronomes e determinantes não se flexionam: "theirs" não é "their" + s, nem "its" é "it" + s.
NO_INFLECTION = {
    "it", "its", "he", "his", "her", "hers", "our", "ours", "your", "yours", "their", "theirs", "my", "mine",
    "us", "this", "these", "those", "whose", "was", "is", "has", "as", "yes", "less",
}


def _forms(word: str) -> set[str]:
    forms = {word, IRREGULAR.get(word, word)}
    if word in NO_INFLECTION:
        return forms
    for suffix, repl in (("ies", "y"), ("ied", "y"), ("ing", ""), ("ing", "e"), ("ed", ""), ("ed", "e"),
                         ("es", ""), ("s", ""), ("d", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            base = word[: -len(suffix)] + repl
            forms.add(base)
            if len(base) > 2 and base[-1] == base[-2] and base[-1] not in "aeiouls":
                forms.add(base[:-1])  # running -> runn -> run
    return forms


def target_demonstrated(target: str, answer: str) -> bool:
    """A palavra/expressão-alvo aparece na resposta (aceita flexões: play/played, have to/had to)."""
    goal = canonical_tokens(target)
    words = canonical_tokens(answer)
    if not goal:
        return False
    for start in range(len(words) - len(goal) + 1):
        window = words[start : start + len(goal)]
        if all(_forms(g) & _forms(w) for g, w in zip(goal, window)):
            return True
    return False


def normalize_vocab(text: str) -> str:
    return " ".join(canonical_tokens(text))


def validate_sentence_pt(sentence: str) -> bool:
    return 0 < len(sentence) <= MAX_SENTENCE_CHARS and len(sentence.split()) <= MAX_SENTENCE_WORDS


def repeats_itself(sentence: str, size: int = 4) -> bool:
    """'O livro é dos meus irmãos e é dos meus irmãos': o mesmo trecho de 4 palavras aparece duas vezes."""
    words = canonical_tokens(sentence)
    grams = [tuple(words[i : i + size]) for i in range(len(words) - size + 1)]
    return len(grams) != len(set(grams))


PREPOSITIONS = {"in", "on", "at", "to", "for", "with", "from", "of", "about", "by", "into", "since"}
ARTICLES = {"a", "an", "the"}
AUXILIARIES = {"do", "does", "did"}
PERFECT = {"have", "has"}


def infer_topic(excerpt: str, correction: str) -> str:
    """Quando a IA não classifica (topic 'other'), deduz o tópico pela diferença entre trecho e correção."""
    before, after = canonical_tokens(excerpt), canonical_tokens(correction)
    removed = [w for w in before if w not in after]
    added = [w for w in after if w not in before]
    changed = set(removed) | set(added)
    if (AUXILIARIES & set(before + after)) and "not" in before + after:
        return "auxiliaries_negation"
    if PERFECT & set(added):
        return "present_perfect"
    if changed and changed <= ARTICLES:
        return "articles"
    if changed and changed <= PREPOSITIONS - {"to"}:
        return "prepositions"
    if "to" in added or "to" in removed:
        return "verb_forms"
    if len(removed) == 1 and len(added) == 1 and _forms(removed[0]) & _forms(added[0]):
        return "verb_forms"  # mesma palavra em outra forma: went/go, plays/play
    if before != after and sorted(before) == sorted(after):
        return "word_order"
    return "other"


# ---------- avaliação ----------

class RecallError(BaseModel):
    category: str
    topic_id: str
    excerpt: str
    correction: str
    explanation_pt: str
    rule_pt: str = ""


INFORMAL = {"gonna", "wanna", "gotta", "kinda", "gimme", "lemme"}
BE_FOR_PRONOUN = {"i": "I'm", "you": "you're", "we": "we're", "they": "they're",
                  "he": "he's", "she": "she's", "it": "it's"}
GONNA_RULE = "gonna = going to: precisa de am/is/are antes (I'm gonna, she's gonna, they're gonna)."


def drops_informal_form(excerpt: str, correction: str) -> bool:
    """'gonna' → 'will': troca de registro (formal/informal), não correção de erro."""
    before, after = set(canonical_tokens(excerpt)), set(canonical_tokens(correction))
    return bool(before & INFORMAL) and not (after & INFORMAL)


def missing_be_before_gonna(answer: str) -> list[RecallError]:
    """'they gonna do' → "they're gonna do": erro objetivo, detectado sem depender da IA."""
    errors = []
    words = re.findall(r"[A-Za-z']+", answer)
    for i in range(1, len(words)):
        subject = words[i - 1]
        if words[i].lower() == "gonna" and subject.lower() in BE_FOR_PRONOUN:
            fixed = BE_FOR_PRONOUN[subject.lower()]
            if subject[0].islower():
                fixed = fixed[0].lower() + fixed[1:]
            errors.append(RecallError(
                category="grammar", topic_id="future_going_to", excerpt=f"{subject} gonna",
                correction=f"{fixed} gonna",
                explanation_pt="Falta o verbo be: “gonna” é “going to”, que sempre vem depois de am/is/are.",
                rule_pt=GONNA_RULE,
            ))
    return errors


class TargetUsage(BaseModel):
    vocabulary_id: int
    english_text: str
    demonstrated: bool


class Suggestion(BaseModel):
    comment_pt: str
    example_en: str


class ProcessedRecall(BaseModel):
    verdict: Verdict
    meaning_match: bool
    errors: list[RecallError] = Field(default_factory=list)
    corrected_answer: str | None = None
    alternative_en: str | None = None
    natural_en: str | None = None
    target_usage: list[TargetUsage] = Field(default_factory=list)
    suggestion: Suggestion | None = None
    message_pt: str | None = None
    discarded: list[dict] = Field(default_factory=list)


def _excerpt_in(excerpt: str, answer: str) -> bool:
    core = " ".join(canonical_tokens(excerpt))
    return bool(core) and re.search(r"(?<!\S)" + re.escape(core) + r"(?!\S)", " ".join(canonical_tokens(answer)))


def alternative_using_targets(alternative: str | None, reference: str, answer: str,
                              usage_list: list["TargetUsage"]) -> str | None:
    """Se você não usou a palavra-alvo, a tradução válida mostrada deve usá-la: senão a etiqueta
    'não usada' fica sem exemplo. Prefere a alternativa da IA; cai para a referência."""
    missing = [u.english_text for u in usage_list if not u.demonstrated]
    if not missing:
        return alternative
    for candidate in (alternative, reference):
        if candidate and all(target_demonstrated(m, candidate) for m in missing):
            return None if same_meaning_form(candidate, answer) else candidate
    return alternative


def natural_version(natural: str | None, reference: str, answer: str, shown: list[str | None]) -> str | None:
    """Como um nativo diria, sem partir da sua resposta. Avaliações antigas não têm: usa a referência.
    Some quando repete o que já está na tela."""
    candidate = (natural or reference or "").strip()
    if not candidate or any(t and same_meaning_form(candidate, t) for t in [answer, *shown]):
        return None
    return candidate


def exact_match_result(answer: str, reference: str, targets: list[dict]) -> ProcessedRecall:
    """Resposta igual à referência (ignorando maiúsculas, pontuação e contrações): correta sem IA."""
    return ProcessedRecall(verdict="correct", meaning_match=True, target_usage=usage(targets, answer))


def usage(targets: list[dict], answer: str) -> list[TargetUsage]:
    return [
        TargetUsage(vocabulary_id=t["vocabulary_id"], english_text=t["english_text"],
                    demonstrated=target_demonstrated(t["english_text"], answer))
        for t in targets
    ]


def process_recall_evaluation(
    raw: LLMRecallEvaluation, answer: str, reference: str, targets: list[dict], topic_ids: set[str]
) -> ProcessedRecall:
    discarded: list[dict] = []
    errors: list[RecallError] = []
    suggestion: Suggestion | None = None

    for event in raw.error_events:
        category = event.category.strip().lower()
        if category == "style":
            if suggestion is None and event.correction:
                suggestion = Suggestion(comment_pt=event.explanation_pt, example_en=event.correction)
            continue
        if category not in ERROR_CATEGORIES:
            category = "grammar"
        if event.excerpt and event.correction and drops_informal_form(event.excerpt, event.correction):
            # Trocar 'gonna' por 'will' é registro (formal × informal), não erro: no máximo uma sugestão.
            discarded.append({"reason": "informal_is_not_an_error", **event.model_dump()})
            if suggestion is None:
                suggestion = Suggestion(comment_pt="“gonna” é informal e correto. Uma alternativa mais neutra:",
                                        example_en=event.correction)
            continue
        if event.excerpt and event.correction and (
            only_case_or_punctuation(event.excerpt, event.correction) or same_meaning_form(event.excerpt, event.correction)
        ):
            discarded.append({"reason": "case_punctuation_or_contraction", **event.model_dump()})
            continue
        if category != "meaning" and not _excerpt_in(event.excerpt, answer):
            discarded.append({"reason": "excerpt_not_in_answer", **event.model_dump()})
            continue
        topic = event.topic_id.strip().lower()
        if topic not in topic_ids or topic in IGNORED_TOPICS:
            topic = "other"
        if topic == "other" and category == "grammar":
            topic = infer_topic(event.excerpt, event.correction)
        if any(e.excerpt.lower() == event.excerpt.lower() for e in errors):
            continue
        errors.append(RecallError(
            category=category, topic_id=topic, excerpt=event.excerpt,
            correction=keep_user_case(event.excerpt, event.correction) if event.correction else "",
            explanation_pt=event.explanation_pt,
            rule_pt=event.rule_pt,
        ))

    # Erros objetivos detectados pelo próprio sistema (não dependem da IA).
    certain = [e for e in missing_be_before_gonna(answer)
               if not any(_excerpt_in(e.excerpt, x.excerpt) or _excerpt_in(x.excerpt, e.excerpt) for x in errors)]
    errors = certain + errors

    # Julgamento consistente: a IA insegura ou contraditória nunca pune.
    meaning_errors = [e for e in errors if e.category == "meaning"]
    if certain:
        verdict: Verdict = "incorrect"
    elif raw.confidence < MIN_CONFIDENCE or raw.verdict == "needs_review":
        verdict = "needs_review"
    elif not errors:
        verdict = "correct" if raw.meaning_match or raw.verdict == "correct" else "needs_review"
    elif raw.verdict == "correct" and raw.confidence < MIN_CONFIDENCE_TO_OVERRIDE_CORRECT:
        verdict = "needs_review"
    else:
        verdict = "incorrect"

    fixable = [e for e in errors if e.category != "meaning" and e.correction]
    corrected = (
        apply_corrections(answer, [SimpleNamespace(original_excerpt=e.excerpt, suggested_correction=e.correction)
                                   for e in fixable])
        if verdict == "incorrect" and fixable else None
    )
    if corrected and same_meaning_form(corrected, answer):
        corrected = None

    alternative = (raw.valid_example_en or reference).strip()
    if same_meaning_form(alternative, answer) or (corrected and same_meaning_form(alternative, corrected)):
        alternative = None
    target_usage = usage(targets, answer)
    alternative = alternative_using_targets(alternative, reference, answer, target_usage)

    message = None
    if verdict == "needs_review":
        message = "Não tenho certeza dessa avaliação, então ela não conta como erro."
    elif verdict == "incorrect" and meaning_errors and not fixable:
        message = meaning_errors[0].explanation_pt

    return ProcessedRecall(
        verdict=verdict,
        meaning_match=raw.meaning_match and not meaning_errors,
        errors=errors[:2] if verdict == "incorrect" else [],
        corrected_answer=corrected,
        alternative_en=alternative,
        natural_en=raw.natural_en.strip() or None,
        target_usage=target_usage,
        suggestion=suggestion if verdict != "needs_review" else None,
        message_pt=message,
        discarded=discarded,
    )
