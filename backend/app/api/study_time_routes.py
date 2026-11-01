"""Rotas do tempo de estudo (relógio e calendário)."""

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, NonNegativeInt

from ..services import study_time_service as service
from .deps import get_conn

router = APIRouter(prefix="/api/study-time")

Activity = Literal["builder", "anki_practice", "anki_review", "listening"]


class StudyTimeIn(BaseModel):
    seconds: dict[Activity, NonNegativeInt]
    day: str | None = None


@router.get("/today")
def today(conn: sqlite3.Connection = Depends(get_conn)):
    return service.today(conn)


@router.post("")
def add(body: StudyTimeIn, conn: sqlite3.Connection = Depends(get_conn)):
    return service.add(conn, body.seconds, body.day)


@router.get("/month")
def month(month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
          conn: sqlite3.Connection = Depends(get_conn)):
    return service.month(conn, month)
