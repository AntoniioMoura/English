"""Cliente do Claude (API da Anthropic) com a mesma interface do Ollama, usado nas correções."""

import logging
from typing import TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from .client import LLMClient, LLMError, LLMUnavailable

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)


class ClaudeClient:
    def __init__(self, api_key: str, model: str, effort: str, timeout: float):
        self.model = model
        self.effort = effort
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)

    def generate(self, system: str, user: str, schema: type[T], temperature: float | None = None) -> T:
        """`temperature` existe só pela interface: a API atual não aceita mais esse parâmetro."""
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config={"effort": self.effort},
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LLMUnavailable("A chave da API do Claude foi recusada. Confira o backend/.env.") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("Não foi possível conectar ao Claude. Verifique a internet.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("O Claude está com limite de uso atingido. Tente de novo em instantes.") from exc
        except anthropic.APIStatusError as exc:
            # 400 com saldo zerado, 5xx etc.: a mensagem da API diz o motivo.
            raise LLMError(f"O Claude respondeu com erro {exc.status_code}: {exc.message}") from exc
        except ValidationError as exc:
            raise LLMError("O Claude devolveu uma resposta fora do formato esperado.") from exc
        if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
            raise LLMError(f"O Claude não concluiu a resposta ({response.stop_reason}).")
        return response.parsed_output


class FallbackClient:
    """Tenta o Claude; se ele falhar (sem internet, sem saldo, chave inválida), usa o Ollama.
    `model` passa a ser o do modelo que de fato respondeu, para ficar registrado na avaliação."""

    def __init__(self, primary: LLMClient, backup: LLMClient):
        self.primary = primary
        self.backup = backup
        self.model = primary.model

    def generate(self, system: str, user: str, schema: type[T], temperature: float | None = None) -> T:
        try:
            result = self.primary.generate(system, user, schema, temperature)
            self.model = self.primary.model
            return result
        except LLMError as exc:
            log.warning("Claude indisponível, usando o Ollama: %s", exc)
        result = self.backup.generate(system, user, schema, temperature)
        self.model = self.backup.model
        return result
