import json
import sqlite3
from datetime import datetime, timedelta

from ..db import utcnow

SESSION_IDLE_MINUTES = 30


def get_or_create_session(conn: sqlite3.Connection) -> int:
    """Uma sessão de estudo agrupa exercícios feitos com até 30 min de intervalo."""
    now = utcnow()
    row = conn.execute("SELECT id, last_activity_at FROM study_sessions ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        last = datetime.fromisoformat(row["last_activity_at"])
        if datetime.fromisoformat(now) - last <= timedelta(minutes=SESSION_IDLE_MINUTES):
            conn.execute("UPDATE study_sessions SET last_activity_at = ? WHERE id = ?", (now, row["id"]))
            return row["id"]
    cur = conn.execute("INSERT INTO study_sessions (started_at, last_activity_at) VALUES (?, ?)", (now, now))
    return cur.lastrowid


def touch_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute("UPDATE study_sessions SET last_activity_at = ? WHERE id = ?", (utcnow(), session_id))


def create_exercise(conn: sqlite3.Connection, session_id: int, frame_id: str, selection_mode: str, status: str) -> int:
    cur = conn.execute(
        """INSERT INTO exercises (session_id, frame_id, selection_mode, status, started_at)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, frame_id, selection_mode, status, utcnow()),
    )
    return cur.lastrowid


def get_exercise(conn: sqlite3.Connection, exercise_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
    return dict(row) if row else None


def set_status(conn: sqlite3.Connection, exercise_id: int, status: str, completed: bool = False) -> None:
    if completed:
        conn.execute(
            "UPDATE exercises SET status = ?, completed_at = COALESCE(completed_at, ?) WHERE id = ?",
            (status, utcnow(), exercise_id),
        )
    else:
        conn.execute("UPDATE exercises SET status = ? WHERE id = ?", (status, exercise_id))


def delete_exercise(conn: sqlite3.Connection, exercise_id: int) -> None:
    # Versões, dicas, avaliações e observações saem junto (ON DELETE CASCADE).
    conn.execute("DELETE FROM exercises WHERE id = ?", (exercise_id,))


def delete_unfinished(conn: sqlite3.Connection) -> int:
    """Remove exercícios abandonados antes de chegar ao feedback."""
    return conn.execute("DELETE FROM exercises WHERE status = 'in_progress'").rowcount


def list_exercises(
    conn: sqlite3.Connection, limit: int = 50, status: str | None = None, finished_only: bool = False
) -> list[dict]:
    query = """
        SELECT e.*, f.text AS frame_text,
               (SELECT text FROM sentence_versions v WHERE v.exercise_id = e.id
                 ORDER BY version_index DESC LIMIT 1) AS latest_text,
               (SELECT COUNT(*) FROM sentence_versions v WHERE v.exercise_id = e.id) AS version_count
        FROM exercises e JOIN sentence_frames f ON f.id = e.frame_id
    """
    params: list = []
    if status:
        query += " WHERE e.status = ?"
        params.append(status)
    elif finished_only:
        query += " WHERE e.status != 'in_progress'"
    query += " ORDER BY e.id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(query, params)]


# ---------- versões ----------

def list_versions(conn: sqlite3.Connection, exercise_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM sentence_versions WHERE exercise_id = ? ORDER BY version_index", (exercise_id,)
    )
    return [{**dict(r), "hints_opened": bool(r["hints_opened"])} for r in rows]


def insert_version(
    conn: sqlite3.Connection, exercise_id: int, version_index: int, text: str, hints_opened: bool
) -> None:
    conn.execute(
        """INSERT INTO sentence_versions (exercise_id, version_index, text, hints_opened, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (exercise_id, version_index, text, int(hints_opened), utcnow()),
    )


# ---------- dicas ----------

def latest_hints(conn: sqlite3.Connection, exercise_id: int, stage: int) -> list[str] | None:
    row = conn.execute(
        "SELECT hints FROM hint_requests WHERE exercise_id = ? AND stage = ? ORDER BY id DESC LIMIT 1",
        (exercise_id, stage),
    ).fetchone()
    return json.loads(row["hints"]) if row else None


def hints_by_stage(conn: sqlite3.Connection, exercise_id: int) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    for row in conn.execute(
        "SELECT stage, hints FROM hint_requests WHERE exercise_id = ? ORDER BY id", (exercise_id,)
    ):
        result[row["stage"]] = json.loads(row["hints"])
    return result


def insert_hints(
    conn: sqlite3.Connection, exercise_id: int, stage: int, base_text: str, hints: list[str], model: str
) -> None:
    conn.execute(
        """INSERT INTO hint_requests (exercise_id, stage, base_text, hints, model, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (exercise_id, stage, base_text, json.dumps(hints), model, utcnow()),
    )
