"""Gera relatórios: métricas no backend, texto pela IA (opcional), exportação em Markdown."""

import sqlite3
from datetime import datetime, timedelta, timezone

from ..db import transaction
from ..domain.report_markdown import clean_narrative, to_markdown
from ..domain.recall_report import compute_recall_section
from ..domain.report_metrics import compute_report
from ..domain.rules import RuleViolation
from ..llm import operations
from ..llm.client import LLMClient, LLMError
from ..repositories import frames as frames_repo
from ..repositories import reports as reports_repo
from .exercise_service import NotFound

PERIODS = {
    "7d": (7, "Últimos 7 dias"),
    "30d": (30, "Últimos 30 dias"),
    "90d": (90, "Últimos 90 dias"),
    "all": (None, "Todo o histórico"),
}


def _period(key: str, now: datetime) -> dict:
    days, label = PERIODS[key]
    start = now - timedelta(days=days) if days else None
    return {
        "key": key,
        "label": label,
        "start": start.isoformat(timespec="seconds") if start else None,
        "end": now.isoformat(timespec="seconds"),
    }


def generate(conn: sqlite3.Connection, llm: LLMClient, period_key: str) -> dict:
    if period_key not in PERIODS:
        raise RuleViolation("invalid_period", "Período inválido.", 422)
    now = datetime.now(timezone.utc)
    period = _period(period_key, now)
    rows = reports_repo.fetch_period_data(conn, period["start"], period["end"])
    recall_rows = reports_repo.fetch_recall_period_data(conn, period["start"], period["end"])
    if not rows["exercises"] and not recall_rows["attempts"]:
        raise RuleViolation("no_data", "Nenhum estudo concluído nesse período. Faça alguns exercícios primeiro.", 422)

    first = min([e["completed_at"] for e in rows["exercises"]] + [a["created_at"] for a in recall_rows["attempts"]])
    period["start_local"] = datetime.fromisoformat(period["start"] or first).astimezone().date().isoformat()
    period["end_local"] = now.astimezone().date().isoformat()

    # Criador de frases e Anki Premium ficam em seções separadas: métricas de cada modo não se misturam.
    data = compute_report(period, topic_names=frames_repo.topic_names(conn), **rows)
    data["has_builder"] = bool(rows["exercises"])
    if not data["has_builder"]:
        data["limitations"] = ["Nenhum estudo do Criador de frases no período."]
    data["recall"] = compute_recall_section(recall_rows, now.isoformat(timespec="seconds"))

    # O texto é um extra: se a IA falhar, o relatório com os números é salvo mesmo assim.
    narrative, narrative_error = None, None
    try:
        narrative = clean_narrative(operations.generate_report(llm, data), data)
    except LLMError as exc:
        narrative_error = str(exc)
    data["narrative"] = narrative

    created_at = now.isoformat(timespec="seconds")
    content_md = to_markdown(data, narrative, created_at, llm.model)
    with transaction(conn):
        report_id = reports_repo.insert_report(
            conn, period, llm.model, data, content_md,
            "complete" if narrative else "numbers_only", narrative_error,
        )
    return get(conn, report_id)


def get(conn: sqlite3.Connection, report_id: int) -> dict:
    report = reports_repo.get_report(conn, report_id)
    if not report:
        raise NotFound(f"Relatório {report_id} não encontrado.")
    return report


def delete(conn: sqlite3.Connection, report_id: int) -> None:
    get(conn, report_id)
    with transaction(conn):
        reports_repo.delete_report(conn, report_id)
