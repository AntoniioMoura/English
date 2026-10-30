"""Rotas do Sentence Recall."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..llm.client import LLMClient, LLMError
from ..repositories import recall as repo
from ..services import recall_service as service
from .deps import get_conn, get_llm

router = APIRouter(prefix="/api/recall")


class VocabBatchIn(BaseModel):
    # Validado item a item no serviço: uma palavra inválida não derruba o lote inteiro.
    entries: list[dict] = Field(min_length=1, max_length=50)


class VocabPatch(BaseModel):
    english_text: str | None = Field(default=None, max_length=60)
    translation_pt: str | None = Field(default=None, max_length=80)
    part_of_speech: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


class AnswerIn(BaseModel):
    answer: str = Field(max_length=600)
    idempotency_key: str = Field(min_length=8, max_length=64)


class SettingsPatch(BaseModel):
    daily_error_limit: int | None = None
    timezone: str | None = None


def _llm_call(fn, *args):
    try:
        return fn(*args)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail={"code": "llm_error", "message": str(exc)}) from exc


# ---------- vocabulário ----------

@router.get("/vocabulary")
def list_vocabulary(conn: sqlite3.Connection = Depends(get_conn)):
    return repo.list_vocab(conn)


@router.post("/vocabulary", status_code=201)
def add_vocabulary(body: VocabBatchIn, conn: sqlite3.Connection = Depends(get_conn)):
    return service.add_vocab_batch(conn, body.entries)


@router.patch("/vocabulary/{vocab_id}")
def edit_vocabulary(vocab_id: int, body: VocabPatch, conn: sqlite3.Connection = Depends(get_conn)):
    return service.update_vocab(conn, vocab_id, body.model_dump(exclude_unset=True))


@router.delete("/vocabulary/{vocab_id}", status_code=204)
def delete_vocabulary(vocab_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    service.delete_vocab(conn, vocab_id)


# ---------- exercícios ----------

@router.post("/exercises", status_code=201)
def new_exercise(conn: sqlite3.Connection = Depends(get_conn), llm: LLMClient = Depends(get_llm)):
    return _llm_call(service.create_new_exercise, conn, llm)


@router.get("/exercises/{exercise_id}")
def get_exercise(exercise_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return service.get_state(conn, exercise_id)


@router.post("/exercises/{exercise_id}/answer")
def answer(exercise_id: int, body: AnswerIn, conn: sqlite3.Connection = Depends(get_conn),
           llm: LLMClient = Depends(get_llm)):
    return service.answer(conn, llm, exercise_id, body.answer, body.idempotency_key)


@router.post("/exercises/{exercise_id}/skip")
def skip(exercise_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return service.skip(conn, exercise_id)


@router.post("/exercises/{exercise_id}/evaluate")
def reevaluate(exercise_id: int, conn: sqlite3.Connection = Depends(get_conn), llm: LLMClient = Depends(get_llm)):
    return service.reevaluate(conn, llm, exercise_id)


# ---------- revisão ----------

@router.get("/reviews/due")
def due_reviews(conn: sqlite3.Connection = Depends(get_conn)):
    return service.due_reviews(conn)


@router.post("/reviews/{item_id}/exercise", status_code=201)
def review_exercise(item_id: int, conn: sqlite3.Connection = Depends(get_conn), llm: LLMClient = Depends(get_llm)):
    return _llm_call(service.create_review_exercise, conn, llm, item_id)


# ---------- progresso e configurações ----------

@router.get("/progress")
def progress(conn: sqlite3.Connection = Depends(get_conn)):
    return service.progress(conn)


@router.get("/settings")
def get_settings(conn: sqlite3.Connection = Depends(get_conn)):
    return service.get_settings(conn)


@router.patch("/settings")
def patch_settings(body: SettingsPatch, conn: sqlite3.Connection = Depends(get_conn)):
    try:
        return service.save_settings(conn, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_settings", "message": str(exc)}) from exc
