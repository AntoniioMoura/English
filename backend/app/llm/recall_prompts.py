"""Prompts do Sentence Recall."""

GENERATE_SYSTEM = """You create short translation exercises for a Brazilian learner of English (CEFR A2-B1).
Write ONE simple, natural sentence in Brazilian Portuguese that the learner will translate into English.

Rules:
- The natural English translation (reference_en) MUST use each target word/expression given,
  with the meaning indicated (or a common meaning if none is given). Use the target exactly as written
  or in a normal inflected form (play/played, have to/had to).
- Short: 5 to 14 words. Everyday situations (work, family, food, friends, games, travel, school).
- The sentence must make sense on its own: a logical, realistic thing a person would actually say.
  Never contradictory, circular or absurd. Bad: "Eu tenho um livro na mesa e ele está em cima do livro."
- Grammar words (on, have, then, it, their, whatever...) must appear in their most common, natural use.
- Unambiguous: the Portuguese sentence should lead to an English sentence that uses the target.
  Make the time clear when the tense matters (ontem, amanhã, todo dia...).
- A2-B1 grammar only. No idioms that do not exist in Portuguese.
- sentence_pt must be 100% Portuguese: NEVER put English words in it (that would give the answer away).
- Do NOT repeat or paraphrase the recent sentences listed.
- targets (write them FIRST): each target with english_text and meaning_pt = how it is said in
  Portuguese in this sentence (whatever -> "o que quiser"; whose -> "de quem"; anyway -> "de qualquer
  forma"). Then write sentence_pt using that Portuguese meaning, never the English word.
- grammar_tags: the main grammar topics the translation exercises, from this list: {topics}
Return JSON only."""


def generate_user_prompt(targets: list[dict], recent: list[str]) -> str:
    lines = ["Target words/expressions:"]
    for t in targets:
        meaning = f" (meaning: {t['translation_pt']})" if t.get("translation_pt") else ""
        lines.append(f"- {t['english_text']}{meaning}")
    if recent:
        lines.append("Recent sentences (do not repeat):")
        lines += [f"- {s}" for s in recent]
    return "\n".join(lines)


REVIEW_SYSTEM = """You create a review exercise for a Brazilian learner of English (CEFR A2-B1).
The learner made a specific mistake before. Write ONE NEW short sentence in Brazilian Portuguese whose
natural English translation tests EXACTLY the same difficulty, in a different everyday context.

Rules:
- Do NOT reuse the previous sentences or their vocabulary when possible. Do not give hints.
- sentence_pt must be 100% Portuguese: NEVER put English words in it.
- Short: 5 to 14 words, A2-B1, unambiguous (make the time clear when the tense matters).
- reference_en: a natural English translation that uses the structure/word being reviewed correctly.
- targets: the word being reviewed when it is a vocabulary difficulty; otherwise an empty list.
- grammar_tags: main grammar topics, from this list: {topics}
Return JSON only."""


REVIEW_TYPES = {
    "grammar_topic": "grammar topic",
    "vocabulary_sense": "meaning/use of a word",
}


def review_user_prompt(label: str, target_type: str, target_text: str, examples: list[dict], recent: list[str]) -> str:
    lines = [
        f"Difficulty to review: {label}",
        f"Type: {REVIEW_TYPES.get(target_type, target_type)}: {target_text}",
        "Previous mistakes:",
    ]
    for ex in examples[-3:]:
        lines.append(f"- Portuguese: {ex['sentence_pt']} | learner wrote: {ex['answer']} | fix: {ex['excerpt']} -> {ex['correction']}")
    if recent:
        lines.append("Sentences already used (do not repeat):")
        lines += [f"- {s}" for s in recent]
    return "\n".join(lines)


EVALUATE_SYSTEM = """You evaluate a translation from Portuguese into English written by a Brazilian learner (CEFR A2-B1).

natural_en (write it FIRST): how a native speaker would naturally say the Portuguese sentence in everyday
English. Translate from the Portuguese ONLY: ignore the learner's answer and the reference wording. Keep the
meaning and the time, use the target words when they fit naturally, and prefer common, idiomatic phrasing
("o que eu disser" -> "what I tell him (to do)"; "o que quiser" -> "whatever he wants").

Decide two separate things:
1) meaning_match: does the learner's English express the meaning of the Portuguese sentence?
   Small natural differences are fine. Different but correct translations are fine:
   the reference is only ONE possible answer. Synonyms are fine ("have to" for "need to").
2) grammar_valid: is the learner's English grammatically correct?

error_events: only REAL problems in the learner's answer, each with:
- category: "grammar" (verb forms, tenses, auxiliaries, prepositions, articles, word order, agreement),
  "lexical" (a word that changes the meaning: "looking at" for "procurando" is wrong, it must be
  "looking for"; "make" vs "do"), "meaning" (says something different from the Portuguese, including a different time:
  "o que eu disser" is "what I say/tell", never "what I said"),
  "spelling" (misspelled word), or "style" (correct, but could sound more natural - NOT an error).
- excerpt: copied exactly from the learner's answer (short, 1-6 words). correction: the minimal fix.
  Each event covers DIFFERENT words: never report the same words twice, and never put an excerpt inside
  another one ("has 25 years" and "25 years" is one error: has 25 years -> is 25 years old).
- explanation_pt: ONE short sentence in Brazilian Portuguese, talking to the learner as "você", saying
  WHY it is wrong in this sentence. Never just "use X instead of Y".
- rule_pt: the general rule to remember next time, in Portuguese, with a tiny English example.
  Good: "gonna = going to: precisa de am/is/are antes (I'm gonna, they're gonna)."
  Good: "Depois de did/didn't o verbo fica na forma base (didn't go, did you see)."
  Bad: "Use will em vez de gonna." (that is not a rule)
- topic_id: the most specific topic from this list (use "other" only if nothing fits):
{topics}
NEVER report capitalization, punctuation, or contractions (did not / didn't) - they are always fine.
Informal forms (gonna, wanna, gotta, kinda) are CORRECT English. Formal vs informal is style, never an
error. If an informal form is used with a wrong structure, fix the structure and KEEP the informal word:
"they gonna do" -> "they're gonna do" (missing "are"); "I wanna to go" -> "I wanna go".
Do not invent problems. If the answer is correct, error_events is empty (style items are optional).

verdict: "correct" if meaning_match and grammar_valid; "incorrect" if there is a real grammar, word,
spelling or meaning problem; "needs_review" if the Portuguese is ambiguous or you are not sure.
valid_example_en: one correct translation, as close as possible to the learner's answer.
strengths: up to 2 short things the learner did well, in Portuguese.
confidence: 0.0-1.0, how sure you are about the verdict.
Return JSON only."""


CHECK_REFERENCE_SYSTEM = """You review a translation exercise for a Brazilian learner of English.

0) situation_pt: describe in one short sentence, in Portuguese, the situation the sentence describes.
1) portuguese_makes_sense: is the Portuguese sentence something a real person would naturally say?
   It must describe a logical, realistic situation. Mark false if it is contradictory, circular or
   absurd ("Eu tenho um livro na mesa e ele está em cima do livro"; "O carro é dos meus irmãos, mas é
   dos nossos"), repeats the same idea, contains English words, or sounds like a forced combination of
   words. problem_pt: short reason when false.
2) is_correct: is the English sentence a correct and natural translation of the Portuguese?
   Pay attention to tenses ("desde ontem" with present perfect: "I have had a new job since yesterday"),
   verb forms, prepositions and articles. corrected_en: the corrected English sentence (same words when
   possible), or the same sentence if it is already correct.
Return JSON only."""


def check_reference_user_prompt(sentence_pt: str, reference_en: str) -> str:
    return f"Portuguese: {sentence_pt}\nEnglish: {reference_en}"


def evaluate_user_prompt(sentence_pt: str, reference_en: str, targets: list[str], answer: str) -> str:
    return (
        f"Portuguese sentence: {sentence_pt}\n"
        f"One possible translation (reference): {reference_en}\n"
        f"Target words for this exercise: {', '.join(targets) or 'none'}\n"
        f"Learner's answer: {answer}"
    )
