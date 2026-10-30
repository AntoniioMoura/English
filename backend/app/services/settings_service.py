import sqlite3

from pydantic import BaseModel, Field, field_validator

from .. import config
from ..llm.client import OllamaClient, OllamaSettings
from ..repositories import settings as settings_repo


class OllamaConfig(BaseModel):
    base_url: str = Field(default=config.DEFAULT_OLLAMA_URL, max_length=200)
    model: str = Field(default=config.DEFAULT_OLLAMA_MODEL, min_length=1, max_length=100)
    timeout_seconds: float = Field(default=config.DEFAULT_OLLAMA_TIMEOUT, ge=10, le=900)

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("O endereço deve começar com http:// ou https://")
        return v

    @field_validator("model")
    @classmethod
    def _model(cls, v: str) -> str:
        return v.strip()


def get_ollama_config(conn: sqlite3.Connection) -> OllamaConfig:
    stored = settings_repo.get_all(conn).get("ollama", {})
    return OllamaConfig(**stored)


def save_ollama_config(conn: sqlite3.Connection, cfg: OllamaConfig) -> OllamaConfig:
    settings_repo.set_many(conn, {"ollama": cfg.model_dump()})
    conn.commit()
    return cfg


def build_client(conn: sqlite3.Connection) -> OllamaClient:
    cfg = get_ollama_config(conn)
    return OllamaClient(OllamaSettings(cfg.base_url, cfg.model, cfg.timeout_seconds))
