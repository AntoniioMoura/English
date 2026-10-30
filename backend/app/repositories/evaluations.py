import json
import sqlite3

from ..db import utcnow
from ..domain.evaluation import ProcessedEvaluation

REVIEW_STATUSES = {"pending", "uncertain", "confirmed", "dismissed"}


def insert_failed(conn: sqlite3.Connection, exercise_id: int, schema_version: int, model: str, error: str) -> int:
    cur = conn.execute(
        """INSERT INTO exercise_evaluations (exercise_id, status, schema_version, model, error_message, created_at)
           VALUES (?, 'failed', ?, ?, ?, ?)""",
        (exercise_id, schema_version, model, error, utcnow()),
    )
    return cur.lastrowid


def insert_success(
    conn: sqlite3.Connection,
    exercise_id: int,
    schema_version: int,
    model: str,
    raw: dict,
    processed: ProcessedEvaluation,
) -> int:
    now = utcnow()
    # Reavaliação: observações anteriores deixam de valer, mas continuam no histórico.
    conn.execute(
        "UPDATE grammar_observations SET review_status = 'superseded' WHERE exercise_id = ?", (exercise_id,)
    )
    conn.execute("UPDATE idea_observations SET review_status = 'superseded' WHERE exercise_id = ?", (exercise_id,))

    cur = conn.execute(
        """INSERT INTO exercise_evaluations
           (exercise_id, status, schema_version, model, raw_result, result, created_at)
           VALUES (?, 'ok', ?, ?, ?, ?, ?)""",
        (exercise_id, schema_version, model, json.dumps(raw), processed.model_dump_json(), now),
    )
    evaluation_id = cur.lastrowid

    rows = []
    for e in processed.grammar_errors:
        rows.append(
            (e.topic_id, exercise_id, evaluation_id, e.version_index, "error", e.original_excerpt,
             e.suggested_correction, e.explanation_pt, e.severity, e.confidence,
             int(not e.persists_in_final), "pending" if e.visible else "uncertain", now)
        )
    for c in processed.grammar_correct:
        rows.append(
            (c.topic_id, exercise_id, evaluation_id, c.version_index, "correct", c.excerpt,
             None, c.explanation_pt, None, 1.0, 0, "pending", now)
        )
    for s in processed.self_corrections:
        rows.append(
            (s.topic_id, exercise_id, evaluation_id, s.to_version, "self_correction", s.before,
             s.after, s.explanation_pt, None, 1.0, 1, "pending", now)
        )
    conn.executemany(
        """INSERT INTO grammar_observations
           (topic_id, exercise_id, evaluation_id, version_index, evidence_type, original_excerpt,
            suggested_correction, explanation_pt, severity, confidence, resolved_in_final, review_status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.executemany(
        """INSERT INTO idea_observations
           (exercise_id, evaluation_id, version_index, kind, is_positive, comment_pt, suggestion_en,
            review_status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        [
            (exercise_id, evaluation_id, i.version_index, i.kind, int(i.is_positive), i.comment_pt,
             i.suggestion_en, now)
            for i in processed.ideas
        ],
    )
    return evaluation_id


def latest_evaluation(conn: sqlite3.Connection, exercise_id: int, status: str | None = None) -> dict | None:
    query = "SELECT * FROM exercise_evaluations WHERE exercise_id = ?"
    params: list = [exercise_id]
    if status:
        query += " AND status = ?"
        params.append(status)
    row = conn.execute(query + " ORDER BY id DESC LIMIT 1", params).fetchone()
    if not row:
        return None
    data = dict(row)
    data["result"] = json.loads(data["result"]) if data["result"] else None
    data["raw_result"] = json.loads(data["raw_result"]) if data["raw_result"] else None
    return data


def list_observations(conn: sqlite3.Connection, exercise_id: int, include_superseded: bool = False) -> list[dict]:
    query = "SELECT * FROM grammar_observations WHERE exercise_id = ?"
    if not include_superseded:
        query += " AND review_status != 'superseded'"
    return [dict(r) for r in conn.execute(query + " ORDER BY id", (exercise_id,))]


def list_idea_observations(conn: sqlite3.Connection, exercise_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM idea_observations WHERE exercise_id = ? AND review_status != 'superseded' ORDER BY id",
        (exercise_id,),
    )
    return [{**dict(r), "is_positive": bool(r["is_positive"])} for r in rows]


def get_observation(conn: sqlite3.Connection, observation_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM grammar_observations WHERE id = ?", (observation_id,)).fetchone()
    return dict(row) if row else None


def set_observation_review(conn: sqlite3.Connection, observation_id: int, review_status: str) -> None:
    conn.execute("UPDATE grammar_observations SET review_status = ? WHERE id = ?", (review_status, observation_id))
