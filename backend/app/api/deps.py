import sqlite3
from typing import Iterator

from fastapi import Depends, Request

from .. import db
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
