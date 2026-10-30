"""Configuração do processo (caminhos e padrões). Preferências do usuário ficam no banco."""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

DB_PATH = Path(os.environ.get("ENGLISH_BUILDER_DB", BACKEND_DIR / "data" / "english_builder.db"))

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
DEFAULT_OLLAMA_TIMEOUT = 180.0
