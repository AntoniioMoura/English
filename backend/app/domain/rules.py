"""Regras de progressão do Sentence Builder.

O exercício tem exatamente quatro versões: V0 (frase inicial) e V1–V3 (expansões).
Toda decisão sobre etapas é tomada aqui; nem a IA nem o frontend podem pular ou criar rodadas.
"""

import re
from enum import Enum

FINAL_VERSION = 3
VERSION_COUNT = FINAL_VERSION + 1
MAX_SENTENCE_CHARS = 400


class ExerciseStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    AWAITING_EVALUATION = "awaiting_evaluation"
    EVALUATED = "evaluated"


class RuleViolation(Exception):
    """Ação proibida pelas regras do exercício (mapeada para HTTP 409/422)."""

    def __init__(self, code: str, message: str, http_status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def stage_label(stage: int) -> str:
    if stage == 0:
        return "Frase inicial"
    if 1 <= stage <= FINAL_VERSION:
        return f"Expansão {stage}/{FINAL_VERSION}"
    return "Avaliação"


def normalize_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def comparable(text: str) -> str:
    return normalize_sentence(text).lower().rstrip(".!?")


def status_after_versions(saved_count: int) -> ExerciseStatus:
    return ExerciseStatus.IN_PROGRESS if saved_count < VERSION_COUNT else ExerciseStatus.AWAITING_EVALUATION


def validate_version_submission(
    status: str, saved_versions: list[str], version_index: int, text: str
) -> str:
    """Valida o envio de uma versão e devolve o texto normalizado."""
    if status != ExerciseStatus.IN_PROGRESS.value or len(saved_versions) >= VERSION_COUNT:
        raise RuleViolation("exercise_closed", "Este exercício já tem as quatro versões salvas.")
    expected = len(saved_versions)
    if version_index != expected:
        raise RuleViolation(
            "wrong_stage",
            f"A próxima versão esperada é V{expected} ({stage_label(expected)}); recebido V{version_index}.",
        )
    clean = normalize_sentence(text)
    if not clean:
        raise RuleViolation("empty_text", "Escreva uma frase antes de continuar.", 422)
    if len(clean) > MAX_SENTENCE_CHARS:
        raise RuleViolation("too_long", f"A frase pode ter no máximo {MAX_SENTENCE_CHARS} caracteres.", 422)
    if not re.search(r"[A-Za-z]", clean):
        raise RuleViolation("no_letters", "A frase precisa conter palavras em inglês.", 422)
    if expected > 0 and comparable(clean) == comparable(saved_versions[-1]):
        raise RuleViolation(
            "unchanged",
            "A expansão precisa trazer alguma mudança: acrescente uma informação nova ou aprofunde a ideia.",
            422,
        )
    return clean


def validate_hint_request(status: str, saved_count: int) -> int:
    """Dicas existem apenas durante as expansões; devolve a etapa atual (1–3)."""
    if status != ExerciseStatus.IN_PROGRESS.value:
        raise RuleViolation("exercise_closed", "As dicas só ficam disponíveis durante as expansões.")
    if saved_count == 0:
        raise RuleViolation("no_hints_for_v0", "Crie a frase inicial sozinho; as ideias aparecem nas expansões.")
    return saved_count


def validate_can_evaluate(status: str, saved_count: int) -> None:
    if saved_count < VERSION_COUNT or status == ExerciseStatus.IN_PROGRESS.value:
        raise RuleViolation(
            "not_finished", "A avaliação só acontece depois da frase inicial e das três expansões."
        )
