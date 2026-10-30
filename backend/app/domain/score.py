"""Nota da frase (0–100%): quanto da sua frase já estava certo.

Compara palavra por palavra a sua frase com a versão corrigida (maior subsequência comum).
Maiúscula, pontuação e contrações não contam, como em toda a avaliação. 100% só sem erro real;
avaliação incerta não recebe nota (a incerteza da IA nunca pune).
"""

from .recall import canonical_tokens

MAX_SCORE_WITH_ERRORS = 95


def word_accuracy(original: str, reference: str) -> int:
    a, b = canonical_tokens(original), canonical_tokens(reference)
    if not a or not b:
        return 0
    lcs = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) - 1, -1, -1):
        for j in range(len(b) - 1, -1, -1):
            lcs[i][j] = lcs[i + 1][j + 1] + 1 if a[i] == b[j] else max(lcs[i + 1][j], lcs[i][j + 1])
    return round(100 * lcs[0][0] / max(len(a), len(b)))


def recall_score(verdict: str | None, answer: str, corrected: str | None, alternative: str | None,
                 reference: str) -> int | None:
    if verdict == "correct":
        return 100
    if verdict != "incorrect":
        return None
    # Erro de sentido sem correção pontual: compara com uma tradução válida.
    target = corrected or alternative or reference
    return min(word_accuracy(answer, target), MAX_SCORE_WITH_ERRORS)


def builder_score(final_sentence: str, corrected: str | None, final_is_correct: bool) -> int:
    if final_is_correct or not corrected:
        return 100
    return min(word_accuracy(final_sentence, corrected), MAX_SCORE_WITH_ERRORS)
