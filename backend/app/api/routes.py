"""Rotas HTTP. Apenas traduzem requisições para os serviços; as regras ficam no domínio."""

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..domain.rules import MAX_SENTENCE_CHARS
from ..llm.client import LLMClient, LLMError, LLMUnavailable, check_ollama
from ..repositories import exercises as ex_repo
from ..repositories import frames as frames_repo
from ..repositories import reports as reports_repo
from ..services import exercise_service, report_service, settings_service
from ..services.settings_service import ClaudeSettings, OllamaConfig
from .deps import get_conn, get_corrector, get_llm

router = APIRouter(prefix="/api")


class CreateExerciseIn(BaseModel):
    selection_mode: Literal["manual", "random"]
    frame_id: str | None = Field(default=None, max_length=64)


class VersionIn(BaseModel):
    version_index: int = Field(ge=0, le=3)
    # Margem acima do limite de negócio: o domínio devolve a mensagem amigável.
    text: str = Field(max_length=MAX_SENTENCE_CHARS * 2)


class HintsIn(BaseModel):
    refresh: bool = False


class ReviewIn(BaseModel):
    review_status: Literal["pending", "confirmed", "dismissed"]


# ---------- frames ----------

@router.get("/frames")
def list_frames(level: str | None = Query(default=None, max_length=4), conn: sqlite3.Connection = Depends(get_conn)):
    return frames_repo.list_frames(conn, level=level)


@router.get("/grammar-topics")
def list_topics(conn: sqlite3.Connection = Depends(get_conn)):
    return [dict(r) for r in conn.execute("SELECT * FROM grammar_topics ORDER BY rowid")]


# ---------- exercícios ----------

@router.post("/exercises", status_code=201)
def create_exercise(body: CreateExerciseIn, conn: sqlite3.Connection = Depends(get_conn)):
    return exercise_service.create_exercise(conn, body.selection_mode, body.frame_id)


@router.get("/exercises")
def list_exercises(
    status: Literal["in_progress", "awaiting_evaluation", "evaluated"] | None = None,
    finished_only: bool = False,
    limit: int = Query(default=30, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return ex_repo.list_exercises(conn, limit=limit, status=status, finished_only=finished_only)


@router.delete("/exercises/{exercise_id}", status_code=204)
def delete_exercise(exercise_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    exercise_service.delete_exercise(conn, exercise_id)


@router.get("/exercises/{exercise_id}")
def get_exercise(exercise_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return exercise_service.get_state(conn, exercise_id)


@router.post("/exercises/{exercise_id}/versions")
def save_version(exercise_id: int, body: VersionIn, conn: sqlite3.Connection = Depends(get_conn)):
    return exercise_service.save_version(conn, exercise_id, body.version_index, body.text)


@router.post("/exercises/{exercise_id}/hints")
def hints(
    exercise_id: int,
    body: HintsIn | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
    llm: LLMClient = Depends(get_llm),
):
    try:
        return exercise_service.request_hints(conn, llm, exercise_id, refresh=bool(body and body.refresh))
    except LLMError as exc:
        raise HTTPException(status_code=503, detail={"code": "llm_error", "message": str(exc)}) from exc


@router.post("/exercises/{exercise_id}/evaluate")
def evaluate(exercise_id: int, conn: sqlite3.Connection = Depends(get_conn), llm: LLMClient = Depends(get_corrector)):
    return exercise_service.evaluate(conn, llm, exercise_id)


@router.patch("/observations/{observation_id}")
def review_observation(observation_id: int, body: ReviewIn, conn: sqlite3.Connection = Depends(get_conn)):
    return exercise_service.review_observation(conn, observation_id, body.review_status)


# ---------- relatórios ----------

class ReportIn(BaseModel):
    period: Literal["7d", "30d", "90d", "all"] = "30d"


@router.post("/reports", status_code=201)
def create_report(body: ReportIn, conn: sqlite3.Connection = Depends(get_conn), llm: LLMClient = Depends(get_llm)):
    return report_service.generate(conn, llm, body.period)


@router.get("/reports")
def list_reports(conn: sqlite3.Connection = Depends(get_conn)):
    return reports_repo.list_reports(conn)


@router.get("/reports/{report_id}")
def get_report(report_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return report_service.get(conn, report_id)


@router.get("/reports/{report_id}/markdown")
def report_markdown(report_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    report = report_service.get(conn, report_id)
    filename = f"relatorio-english-builder-{report['created_at'][:10]}.md"
    return PlainTextResponse(
        report["content_md"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    report_service.delete(conn, report_id)


# ---------- configurações ----------

@router.get("/settings/ollama")
def get_ollama_settings(conn: sqlite3.Connection = Depends(get_conn)):
    return settings_service.get_ollama_config(conn)


@router.put("/settings/ollama")
def put_ollama_settings(body: OllamaConfig, conn: sqlite3.Connection = Depends(get_conn)):
    return settings_service.save_ollama_config(conn, body)


@router.get("/settings/claude")
def get_claude_settings(conn: sqlite3.Connection = Depends(get_conn)):
    return settings_service.claude_status(conn)


@router.put("/settings/claude")
def put_claude_settings(body: ClaudeSettings, conn: sqlite3.Connection = Depends(get_conn)):
    try:
        return settings_service.save_claude_settings(conn, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "no_api_key", "message": str(exc)}) from exc


@router.get("/settings/ollama/status")
def ollama_status(conn: sqlite3.Connection = Depends(get_conn)):
    cfg = settings_service.get_ollama_config(conn)
    try:
        models = check_ollama(cfg.base_url)
    except LLMUnavailable as exc:
        return {"reachable": False, "model_available": False, "models": [], "message": str(exc)}
    available = cfg.model in models or f"{cfg.model}:latest" in models
    return {
        "reachable": True,
        "model_available": available,
        "models": models,
        "message": None if available else f"O modelo '{cfg.model}' não está instalado no Ollama.",
    }
