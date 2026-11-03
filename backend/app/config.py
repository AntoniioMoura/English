"""Configuração do processo (caminhos e padrões). Preferências do usuário ficam no banco."""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Segredos locais (chave da API) ficam em backend/.env, fora do git. Variável já definida vence."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if not os.environ.get("ENGLISH_BUILDER_NO_ENV_FILE"):  # os testes nunca usam a chave real
    _load_env_file(BACKEND_DIR / ".env")
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

DB_PATH = Path(os.environ.get("ENGLISH_BUILDER_DB", BACKEND_DIR / "data" / "english_builder.db"))

# Listening: vídeos fornecidos pelo usuário e cache do processamento (miniaturas, legendas, conversões).
VIDEOS_DIR = Path(os.environ.get("LISTENING_VIDEOS_DIR", BACKEND_DIR.parent / "videos"))
LISTENING_CACHE_DIR = Path(os.environ.get("LISTENING_CACHE_DIR", BACKEND_DIR / "data" / "listening"))

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
DEFAULT_OLLAMA_TIMEOUT = 180.0

# Correções (Criador de frases e Anki) pelo Claude quando houver ANTHROPIC_API_KEY; sem ela, Ollama.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
CLAUDE_EFFORT = os.environ.get("CLAUDE_EFFORT", "low")
CLAUDE_TIMEOUT = 120.0
