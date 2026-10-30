import json
import sqlite3

from ..db import utcnow


def fetch_period_data(conn: sqlite3.Connection, start: str | None, end: str) -> dict:
    """Só estudos que chegaram ao feedback (avaliados) entram no relatório."""
    query = """SELECT e.* FROM exercises e
               WHERE e.status = 'evaluated' AND e.completed_at <= ?"""
    params: list = [end]
    if start:
        query += " AND e.completed_at >= ?"
        params.append(start)
    exercises = [dict(r) for r in conn.execute(query + " ORDER BY e.completed_at", params)]
    ids = [e["id"] for e in exercises]
    if not ids:
        return {"exercises": [], "versions": [], "grammar_obs": [], "idea_obs": []}
    marks = ",".join("?" * len(ids))
    versions = [
        {**dict(r), "hints_opened": bool(r["hints_opened"])}
        for r in conn.execute(f"SELECT * FROM sentence_versions WHERE exercise_id IN ({marks})", ids)
    ]
    grammar = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM grammar_observations WHERE exercise_id IN ({marks}) AND review_status != 'superseded'",
            ids,
        )
    ]
    ideas = [
        {**dict(r), "is_positive": bool(r["is_positive"])}
        for r in conn.execute(
            f"SELECT * FROM idea_observations WHERE exercise_id IN ({marks}) AND review_status != 'superseded'",
            ids,
        )
    ]
    return {"exercises": exercises, "versions": versions, "grammar_obs": grammar, "idea_obs": ideas}


def fetch_recall_period_data(conn: sqlite3.Connection, start: str | None, end: str) -> dict:
    """Tentativas avaliadas do Anki Premium no período, com o resultado salvo de cada uma."""
    query = """
        SELECT a.id AS attempt_id, a.exercise_id, a.answer_text, a.verdict, a.created_at,
               e.mode, e.sentence_pt, e.reference_en,
               (SELECT result FROM ai_evaluations ev WHERE ev.attempt_id = a.id AND ev.status = 'completed'
                 ORDER BY ev.id DESC LIMIT 1) AS result
        FROM recall_attempts a JOIN recall_exercises e ON e.id = a.exercise_id
        WHERE a.verdict IS NOT NULL AND a.created_at <= ?"""
    params: list = [end]
    if start:
        query += " AND a.created_at >= ?"
        params.append(start)
    attempts = [dict(r) for r in conn.execute(query + " ORDER BY a.created_at", params)]
    ids = [a["attempt_id"] for a in attempts]
    if not ids:
        return {"attempts": [], "observations": [], "usage": [], "reviews": []}
    marks = ",".join("?" * len(ids))
    observations = [dict(r) for r in conn.execute(
        f"""SELECT o.*, g.name_pt FROM recall_observations o JOIN grammar_topics g ON g.id = o.topic_id
            WHERE o.attempt_id IN ({marks}) AND o.review_status != 'dismissed'""", ids)]
    usage = [dict(r) for r in conn.execute(
        f"""SELECT u.attempt_id, u.vocabulary_id, u.demonstrated, v.english_text
            FROM recall_target_usage u JOIN vocabulary_entries v ON v.id = u.vocabulary_id
            WHERE u.attempt_id IN ({marks})""", ids)]
    reviews = [dict(r) for r in conn.execute("SELECT id, target_type, status, due_at FROM review_items")]
    return {"attempts": attempts, "observations": observations, "usage": usage, "reviews": reviews}


def insert_report(
    conn: sqlite3.Connection,
    period: dict,
    model: str,
    data: dict,
    content_md: str,
    status: str,
    narrative_error: str | None,
) -> int:
    cur = conn.execute(
        """INSERT INTO learning_reports
           (period_start, period_end, period_label, model, metrics, content_md, status, narrative_error, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (period["start"] or "", period["end"], period["label"], model, json.dumps(data, default=str),
         content_md, status, narrative_error, utcnow()),
    )
    return cur.lastrowid


def _row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["data"] = json.loads(data.pop("metrics"))
    return data


def get_report(conn: sqlite3.Connection, report_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM learning_reports WHERE id = ?", (report_id,)).fetchone()
    return _row(row) if row else None


def list_reports(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT id, period_label, period_start, period_end, status, model, created_at,
                  json_extract(metrics, '$.totals.exercises') AS exercises,
                  json_extract(metrics, '$.recall.attempts') AS translations
           FROM learning_reports ORDER BY id DESC LIMIT ?""",
        (limit,),
    )
    return [dict(r) for r in rows]


def delete_report(conn: sqlite3.Connection, report_id: int) -> None:
    conn.execute("DELETE FROM learning_reports WHERE id = ?", (report_id,))
