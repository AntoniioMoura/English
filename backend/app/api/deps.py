import sqlite3
from typing import Iterator

from fastapi import Depends, Request

from .. import config, db
from ..llm.claude_client import ClaudeClient, FallbackClient
from ..llm.client import LLMClient
from ..services import settings_service


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_llm(conn: sqlite3.Connection = Depends(get_conn)) -> LLMClient:
    return settings_service.build_client(conn)


def get_corrector(conn: sqlite3.Connection = Depends(get_conn)) -> LLMClient:
    """Correções do Criador de frases e do Anki: Claude quando ligado nas configurações e com a chave em
    backend/.env (Ollama como reserva); senão, Ollama."""
    ollama = settings_service.build_client(conn)
    if not settings_service.claude_status(conn)["active"]:
        return ollama
    claude = ClaudeClient(config.ANTHROPIC_API_KEY, config.CLAUDE_MODEL, config.CLAUDE_EFFORT, config.CLAUDE_TIMEOUT)
    return FallbackClient(claude, ollama)
