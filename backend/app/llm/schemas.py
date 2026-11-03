"""Schemas Pydantic das respostas estruturadas do Ollama.

Os validadores são tolerantes (truncam textos, limitam listas, normalizam enums)
para que pequenos desvios do modelo não descartem uma avaliação inteira; tipos
inválidos continuam gerando erro de validação, o que dispara a nova tentativa.
"""

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, field_validator

EVALUATION_SCHEMA_VERSION = 2


def _truncate(limit: int):
    def inner(value: Any) -> Any:
        if isinstance(value, str):
            value = " ".join(value.split())
            return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"
        return value

    return BeforeValidator(inner)


def _clamp_index(value: Any) -> Any:
    try:
        return min(3, max(0, int(value)))
    except (TypeError, ValueError):
        return value


def _clamp_unit(value: Any) -> Any:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return value


Short = Annotated[str, _truncate(160)]
Medium = Annotated[str, _truncate(300)]
VersionIndex = Annotated[int, BeforeValidator(_clamp_index)]
Unit = Annotated[float, BeforeValidator(_clamp_unit)]


class HintsResult(BaseModel):
    hints: list[Annotated[str, _truncate(120)]] = Field(min_length=1)


class LLMGrammarError(BaseModel):
    topic_id: str
    version_index: VersionIndex
    original_excerpt: Short
    suggested_correction: Short
    explanation_pt: Medium
    severity: str = "medium"
    confidence: Unit = 0.7
    category: str = Field(
        default="grammar",
        description="'grammar' para erro objetivo; 'style' para algo correto que poderia soar melhor",
    )

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, v: Any) -> str:
        v = str(v or "").lower()
        return v if v in {"low", "medium", "high"} else "medium"

    @field_validator("category", mode="before")
    @classmethod
    def _category(cls, v: Any) -> str:
        return "style" if str(v or "").lower() in {"style", "naturalness", "improvement"} else "grammar"


class LLMGrammarCorrect(BaseModel):
    topic_id: str
    version_index: VersionIndex
    excerpt: Short
    explanation_pt: Medium


class LLMIdeaItem(BaseModel):
    version_index: VersionIndex | None = None
    kind: str
    is_positive: bool
    comment_pt: Medium
    suggestion_en: Short | None = None


class LLMSelfCorrection(BaseModel):
    topic_id: str
    from_version: VersionIndex
    to_version: VersionIndex
    before: Short
    after: Short
    explanation_pt: Medium


class LLMFrameUsage(BaseModel):
    used_correctly: bool
    comment_pt: Medium


class LLMPhraseCheck(BaseModel):
    phrase: Short
    is_correct: bool
    correction: Short | None = None
    topic_id: str = "other"
    explanation_pt: Medium = ""


class LLMFinalReview(BaseModel):
    """Revisão focada só na frase final: o modelo pequeno acerta mais com uma tarefa por vez."""

    # Lista vazia = o modelo pulou a checagem; falha de validação força nova tentativa.
    phrase_checks: list[LLMPhraseCheck] = Field(min_length=1)
    enrichment_comment_pt: Medium
    enrichment_example_en: Annotated[str, _truncate(450)]
    next_tip_pt: Medium
    next_tip_example_en: Short

    @field_validator("phrase_checks", mode="after")
    @classmethod
    def _limit_checks(cls, v: list) -> list:
        return v[:12]


RECALL_PROMPT_VERSION = 1
RECALL_SCHEMA_VERSION = 1


class LLMRecallTarget(BaseModel):
    english_text: Short
    meaning_pt: Short


class LLMRecallPrompt(BaseModel):
    """Frase em português para o usuário traduzir. A referência nunca é exibida antes da resposta.

    Os alvos vêm primeiro: definir o sentido em português antes de escrever a frase evita que o
    modelo deixe a palavra em inglês dentro do enunciado."""

    targets: list[LLMRecallTarget] = Field(default_factory=list)
    sentence_pt: Annotated[str, _truncate(240)]
    reference_en: Annotated[str, _truncate(240)]
    grammar_tags: list[str] = Field(default_factory=list)


class LLMReferenceCheck(BaseModel):
    # Primeiro o português: descrever a situação antes de julgar ajuda o modelo a notar contradições.
    situation_pt: Short = ""
    portuguese_makes_sense: bool = True
    problem_pt: Short = ""
    is_correct: bool
    corrected_en: Annotated[str, _truncate(240)]


class LLMRecallErrorEvent(BaseModel):
    category: str = Field(description="grammar | lexical | meaning | spelling | style")
    topic_id: str = "other"
    excerpt: Short = ""
    correction: Short = ""
    explanation_pt: Medium = ""
    rule_pt: Medium = Field(default="", description="regra geral para lembrar na próxima vez, com mini exemplo")


class LLMRecallEvaluation(BaseModel):
    model_config = {"json_schema_extra": lambda schema: schema.setdefault("required", []).insert(0, "natural_en")}

    # Primeiro campo: a IA escreve a forma natural antes de analisar a sua resposta, sem se ancorar nela.
    # Obrigatório no schema enviado ao Ollama (senão ele omite o campo); vazio continua aceito na leitura.
    natural_en: Annotated[str, _truncate(240)] = ""
    error_events: list[LLMRecallErrorEvent] = Field(default_factory=list)
    meaning_match: bool
    grammar_valid: bool
    verdict: str
    strengths: list[Medium] = Field(default_factory=list)
    valid_example_en: Annotated[str, _truncate(240)] = ""
    confidence: Unit = 0.7

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, v: Any) -> str:
        v = str(v or "").strip().lower()
        return v if v in {"correct", "incorrect", "needs_review"} else "needs_review"

    @field_validator("error_events", mode="after")
    @classmethod
    def _limit_events(cls, v: list) -> list:
        return v[:6]


Long = Annotated[str, _truncate(700)]


class LLMNextTopic(BaseModel):
    topic_id: str
    reason_pt: Medium


class LLMReportNarrative(BaseModel):
    """Texto do relatório. Números e exemplos vêm do backend; a IA só interpreta."""

    summary_pt: Long
    strengths_pt: list[Medium] = Field(default_factory=list)
    errors_comment_pt: Long
    elaboration_comment_pt: Long
    evolution_comment_pt: Long
    recall_comment_pt: Long = ""
    next_topics: list[LLMNextTopic] = Field(default_factory=list)

    @field_validator("strengths_pt", "next_topics", mode="after")
    @classmethod
    def _limit(cls, v: list) -> list:
        return v[:4]


class LLMSentenceReview(BaseModel):
    version_index: VersionIndex
    grammar_problems: Medium = Field(description="every objective grammar problem in this version, or 'none'")


class LLMEvaluation(BaseModel):
    # A ordem dos campos define a ordem de geração: revisar cada versão antes de
    # listar erros funciona como um raciocínio curto e melhora a detecção.
    sentence_review: list[LLMSentenceReview] = Field(default_factory=list)
    grammar_errors: list[LLMGrammarError] = Field(default_factory=list)
    grammar_correct_evidence: list[LLMGrammarCorrect] = Field(default_factory=list)
    self_corrections: list[LLMSelfCorrection] = Field(default_factory=list)
    idea_development: list[LLMIdeaItem] = Field(default_factory=list)
    frame_usage: LLMFrameUsage
    highlights: list[Medium] = Field(default_factory=list)
    corrected_final_sentence: Annotated[str, _truncate(450)] | None = None
    next_tip: Medium

    @field_validator("highlights", "grammar_correct_evidence", "self_corrections", mode="after")
    @classmethod
    def _limit_short_lists(cls, v: list) -> list:
        return v[:6]

    @field_validator("grammar_errors", "idea_development", mode="after")
    @classmethod
    def _limit_long_lists(cls, v: list) -> list:
        return v[:10]
