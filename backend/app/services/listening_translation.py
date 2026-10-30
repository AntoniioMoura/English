"""Tradução das falas para o português com o Ollama local (vídeos sem legenda em português).

Traduz em lotes, mandando algumas falas anteriores como contexto (só para entender, não para traduzir).
Cada lote é gravado assim que fica pronto: se algo falhar, "tentar de novo" continua de onde parou.
"""

import logging
import sqlite3

from pydantic import BaseModel, Field

from ..db import transaction
from ..domain.rules import RuleViolation
from ..llm.client import LLMClient, LLMError
from ..repositories import listening as repo
from . import listening_media as media
from .exercise_service import NotFound

log = logging.getLogger(__name__)

BATCH = 15
CONTEXT = 4

SYSTEM = (
    "Você é tradutor profissional de legendas do inglês para o português do Brasil. "
    "Escreva como um brasileiro falaria naturalmente nessa situação, não palavra por palavra: reorganize a frase "
    'quando precisar ("Thank you so much" = "Muito obrigado"; "I got chills" = "Fiquei arrepiada/arrepiado"). '
    'Confira gênero e concordância ("minhas raízes", "minha jornada"). Fiel ao sentido: não resuma nem acrescente. '
    "Uma fala pode terminar no meio da frase e continuar na próxima: traduza só o pedaço dela, mantendo a "
    "continuidade. Mantenha como estão nomes de pessoas, marcas, títulos de músicas/programas/álbuns e apelidos de "
    "fãs. Hesitações (uh, um) podem ser omitidas. Descrições sonoras entre colchetes/parênteses são traduzidas e "
    'mantêm os colchetes/parênteses. Os travessões que indicam troca de quem fala ("-") são mantidos. '
    "Responda só com o JSON pedido: uma tradução para cada linha numerada, com o mesmo número."
)


class LLMTranslatedLine(BaseModel):
    n: int
    pt: str = Field(max_length=600)


class LLMTranslationBatch(BaseModel):
    translations: list[LLMTranslatedLine]


def _prompt(context: list[str], lines: list[tuple[int, str]]) -> str:
    parts = []
    if context:
        parts.append("Falas anteriores, só para contexto (NÃO traduza):\n" + "\n".join(f"- {t}" for t in context))
    parts.append("Traduza cada linha:\n" + "\n".join(f"{n}: {text}" for n, text in lines))
    return "\n\n".join(parts)


def translate_batch(llm: LLMClient, context: list[str], lines: list[tuple[int, str]]) -> dict[int, str]:
    """Devolve {número da linha: tradução}; linhas que a IA esqueceu ficam de fora."""
    result = llm.generate(SYSTEM, _prompt(context, lines), LLMTranslationBatch, temperature=0.2)
    wanted = {n for n, _ in lines}
    return {t.n: " ".join(t.pt.split()) for t in result.translations if t.n in wanted and t.pt.strip()}


def _require_video(conn: sqlite3.Connection, video_id: int) -> dict:
    video = repo.get_video(conn, video_id)
    if not video:
        raise NotFound("Vídeo não encontrado.")
    return video


def start(conn: sqlite3.Connection, worker: "media.ListeningWorker", video_id: int) -> None:
    video = _require_video(conn, video_id)
    if not media.is_prepared(video):
        raise RuleViolation("not_ready", "O vídeo ainda não foi preparado.")
    if video["translation_source"] in ("external", "embedded"):
        return  # já tem legenda em português
    if video["translation_status"] == "running" and worker.is_queued("translate", video_id):
        return
    with transaction(conn):
        repo.update_video(conn, video_id, {"translation_status": "running", "translation_progress": 0,
                                           "translation_error": None})
    worker.submit("translate", video_id)


def run(conn: sqlite3.Connection, video_id: int, llm: LLMClient) -> None:
    """Traduz as falas ainda sem tradução, lote a lote, gravando o progresso."""
    video = repo.get_video(conn, video_id)
    if not video:
        return
    segments = repo.active_segments(conn, video_id)
    pending = [i for i, s in enumerate(segments) if not s["translation_pt"]]
    total = len(pending) or 1
    try:
        for start_at in range(0, len(pending), BATCH):
            chunk = pending[start_at:start_at + BATCH]
            context = [segments[i]["text"] for i in range(max(0, chunk[0] - CONTEXT), chunk[0])]
            lines = [(i + 1, segments[i]["text"]) for i in chunk]
            done = translate_batch(llm, context, lines)
            missing = [(n, text) for n, text in lines if n not in done]
            if missing:  # a IA pulou linhas: uma segunda chance só para elas
                done.update(translate_batch(llm, context, missing))
            with transaction(conn):
                for n, text in lines:
                    if n in done:
                        repo.update_segment(conn, segments[n - 1]["id"], {"translation_pt": done[n]})
                progress = min((start_at + len(chunk)) / total, 1.0)
                repo.update_video(conn, video_id, {"translation_progress": round(progress, 3)})
        with transaction(conn):
            repo.update_video(conn, video_id, {"translation_status": None, "translation_progress": 1.0,
                                               "translation_source": "ai", "translation_error": None})
    except LLMError as exc:
        with transaction(conn):
            repo.update_video(conn, video_id, {"translation_status": "error", "translation_error": str(exc)})
    except Exception as exc:  # nunca deixa a tradução presa em "gerando"
        log.exception("tradução do vídeo %s", video_id)
        with transaction(conn):
            repo.update_video(conn, video_id, {"translation_status": "error",
                                               "translation_error": f"Erro inesperado: {exc}"})


def recover_interrupted(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE listening_videos SET translation_status = 'error',
                      translation_error = 'Tradução interrompida (o servidor foi fechado). Tente novamente.'
               WHERE translation_status = 'running'""")
