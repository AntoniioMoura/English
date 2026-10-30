"""Operação de IA do Listening: traduzir a frase atual (ajuda pontual para tirar uma dúvida)."""

from pydantic import BaseModel, Field

from .client import LLMClient, LLMError

SYSTEM = (
    "Você é tradutor profissional de legendas do inglês para o português do Brasil. "
    "Traduza a frase pedida como um brasileiro falaria naturalmente nessa situação, não palavra por palavra "
    '("Thank you so much" = "Muito obrigado"; "I got chills" = "Fiquei arrepiada/arrepiado"), com gênero e '
    "concordância certos. Fiel ao sentido: não resuma nem acrescente. A frase pode ser só um pedaço de uma fala "
    "maior: traduza só ela. Mantenha como estão nomes de pessoas, marcas, títulos de músicas/programas/álbuns e "
    "apelidos de fãs. Hesitações (uh, um) podem ser omitidas. As falas anteriores servem só de contexto."
)


class LLMSentenceTranslation(BaseModel):
    pt: str = Field(min_length=1, max_length=600)


def translate_sentence(llm: LLMClient, sentence: str, context: list[str]) -> str:
    parts = []
    if context:
        parts.append("Falas anteriores, só para contexto (NÃO traduza):\n" + "\n".join(f"- {t}" for t in context))
    parts.append(f"Traduza esta frase:\n{sentence}")
    result = llm.generate(SYSTEM, "\n\n".join(parts), LLMSentenceTranslation, temperature=0.2)
    text = " ".join(result.pt.split())
    if not text:
        raise LLMError("A IA devolveu uma tradução vazia.")
    return text
