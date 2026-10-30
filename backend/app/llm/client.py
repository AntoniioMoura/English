"""Cliente HTTP do Ollama com saída estruturada (JSON Schema)."""

import json
from dataclasses import dataclass
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Falha de geração, conexão ou validação. A mensagem é exibida ao usuário."""


class LLMUnavailable(LLMError):
    pass


class LLMClient(Protocol):
    model: str

    def generate(self, system: str, user: str, schema: type[T], temperature: float | None = None) -> T: ...


@dataclass
class OllamaSettings:
    base_url: str
    model: str
    timeout_seconds: float


class OllamaClient:
    def __init__(self, settings: OllamaSettings):
        self.settings = settings
        self.model = settings.model

    def generate(self, system: str, user: str, schema: type[T], temperature: float | None = None) -> T:
        """`temperature` baixa (padrão) para avaliar; mais alta para criar frases variadas."""
        payload = {
            "model": self.settings.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema.model_json_schema(),
            "stream": False,
            "think": False,
            "options": {"temperature": 0.2 if temperature is None else temperature},
        }
        url = self.settings.base_url.rstrip("/") + "/api/chat"
        try:
            response = httpx.post(url, json=payload, timeout=self.settings.timeout_seconds)
        except httpx.ConnectError as exc:
            raise LLMUnavailable(
                f"Não foi possível conectar ao Ollama em {self.settings.base_url}. Verifique se ele está aberto."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMError("O Ollama demorou demais para responder.") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Erro de comunicação com o Ollama: {exc}") from exc

        if response.status_code == 404:
            raise LLMUnavailable(f"Modelo '{self.settings.model}' não encontrado no Ollama.")
        if response.status_code >= 400:
            raise LLMError(f"O Ollama respondeu com erro {response.status_code}: {response.text[:200]}")

        content = response.json().get("message", {}).get("content", "")
        try:
            return schema.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMError("A IA devolveu uma resposta fora do formato esperado.") from exc


def check_ollama(base_url: str, timeout: float = 5.0) -> list[str]:
    """Lista os modelos instalados; levanta LLMUnavailable se o Ollama não responder."""
    try:
        response = httpx.get(base_url.rstrip("/") + "/api/tags", timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"Ollama indisponível em {base_url}.") from exc
    return sorted(m["name"] for m in response.json().get("models", []))
