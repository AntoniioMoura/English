import json
import sqlite3

from ..db import utcnow

# ---------- vídeos ----------


def list_videos(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM listening_videos ORDER BY rel_path COLLATE NOCASE")]


def get_video(conn: sqlite3.Connection, video_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM listening_videos WHERE id = ?", (video_id,)).fetchone()
    return dict(row) if row else None


def insert_video(conn: sqlite3.Connection, data: dict) -> int:
    now = utcnow()
    cur = conn.execute(
        """INSERT INTO listening_videos (rel_path, category, file_size, file_mtime, fingerprint, created_at, updated_at)
           VALUES (:rel_path, :category, :file_size, :file_mtime, :fingerprint, :now, :now)""",
        {**data, "now": now},
    )
    return cur.lastrowid


def update_video(conn: sqlite3.Connection, video_id: int, fields: dict) -> None:
    if not fields:
        return
    fields = {**fields, "updated_at": utcnow()}
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    conn.execute(f"UPDATE listening_videos SET {assignments} WHERE id = :id", {**fields, "id": video_id})


# ---------- trechos ----------


def active_segments(conn: sqlite3.Connection, video_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM listening_segments WHERE video_id = ? AND active = 1 ORDER BY idx", (video_id,))]


def get_segment(conn: sqlite3.Connection, segment_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM listening_segments WHERE id = ?", (segment_id,)).fetchone()
    return dict(row) if row else None


def replace_segments(conn: sqlite3.Connection, video_id: int, rev: int, segments: list[dict]) -> None:
    """Desativa os trechos anteriores (tentativas antigas continuam apontando para eles) e grava os novos."""
    now = utcnow()
    conn.execute("UPDATE listening_segments SET active = 0 WHERE video_id = ?", (video_id,))
    conn.executemany(
        """INSERT INTO listening_segments
           (video_id, processing_rev, idx, start, end, text, translation_pt, original_text, original_start,
            original_end, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(video_id, rev, i, s["start"], s["end"], s["text"], s.get("translation_pt"), s["text"], s["start"],
          s["end"], now) for i, s in enumerate(segments)],
    )


def update_segment(conn: sqlite3.Connection, segment_id: int, fields: dict) -> None:
    fields = {**fields, "updated_at": utcnow()}
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    conn.execute(f"UPDATE listening_segments SET {assignments} WHERE id = :id", {**fields, "id": segment_id})


# ---------- sessões ----------


def _session(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def get_session(conn: sqlite3.Connection, session_id: int) -> dict | None:
    return _session(conn.execute("SELECT * FROM listening_sessions WHERE id = ?", (session_id,)).fetchone())


def find_active_session(conn: sqlite3.Connection, video_id: int, difficulty: str, mode: str) -> dict | None:
    return _session(conn.execute(
        """SELECT * FROM listening_sessions WHERE video_id = ? AND difficulty = ? AND mode = ? AND status = 'active'
           ORDER BY id DESC LIMIT 1""", (video_id, difficulty, mode)).fetchone())


def active_sessions(conn: sqlite3.Connection, video_id: int | None = None) -> list[dict]:
    query = """SELECT s.*,
                      (SELECT COUNT(*) FROM listening_session_items i WHERE i.session_id = s.id) AS total,
                      (SELECT COUNT(*) FROM listening_session_items i WHERE i.session_id = s.id
                         AND i.status != 'pending') AS done
               FROM listening_sessions s WHERE s.status = 'active'"""
    params: tuple = ()
    if video_id is not None:
        query += " AND s.video_id = ?"
        params = (video_id,)
    return [dict(r) for r in conn.execute(query + " ORDER BY s.updated_at DESC", params)]


def insert_session(conn: sqlite3.Connection, data: dict) -> int:
    now = utcnow()
    cur = conn.execute(
        """INSERT INTO listening_sessions (video_id, difficulty, mode, processing_rev, seed, interval_seconds,
                                          started_at, updated_at)
           VALUES (:video_id, :difficulty, :mode, :processing_rev, :seed, :interval_seconds, :now, :now)""",
        {"interval_seconds": 0, **data, "now": now},
    )
    return cur.lastrowid


def update_session(conn: sqlite3.Connection, session_id: int, fields: dict) -> None:
    fields = {**fields, "updated_at": utcnow()}
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    conn.execute(f"UPDATE listening_sessions SET {assignments} WHERE id = :id", {**fields, "id": session_id})


def insert_items(conn: sqlite3.Connection, session_id: int, items: list[dict]) -> None:
    conn.executemany(
        """INSERT INTO listening_session_items (session_id, segment_id, position, text_snapshot, blanks)
           VALUES (?, ?, ?, ?, ?)""",
        [(session_id, it["segment_id"], i, it["text"], json.dumps(it["blanks"])) for i, it in enumerate(items)],
    )


def session_items(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT i.*, s.start, s.end, s.text AS segment_text, s.translation_pt, s.flagged
           FROM listening_session_items i JOIN listening_segments s ON s.id = i.segment_id
           WHERE i.session_id = ? ORDER BY i.position""", (session_id,))
    return [{**dict(r), "blanks": json.loads(r["blanks"])} for r in rows]


def get_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    row = conn.execute(
        """SELECT i.*, s.start, s.end, s.text AS segment_text, s.translation_pt, s.flagged, s.video_id
           FROM listening_session_items i JOIN listening_segments s ON s.id = i.segment_id
           WHERE i.id = ?""", (item_id,)).fetchone()
    return {**dict(row), "blanks": json.loads(row["blanks"])} if row else None


def update_item(conn: sqlite3.Connection, item_id: int, fields: dict) -> None:
    if "blanks" in fields:
        fields = {**fields, "blanks": json.dumps(fields["blanks"])}
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    conn.execute(f"UPDATE listening_session_items SET {assignments} WHERE id = :id", {**fields, "id": item_id})


# ---------- tentativas ----------


def attempts_for_session(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM listening_word_attempts WHERE session_id = ? ORDER BY id", (session_id,))]


def attempts_for_item(conn: sqlite3.Connection, item_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM listening_word_attempts WHERE item_id = ? ORDER BY id", (item_id,))]


def insert_attempt(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute(
        """INSERT INTO listening_word_attempts
           (session_id, item_id, video_id, segment_id, word_index, expected, expected_norm, typed, is_correct,
            used_help, replays, segment_start, segment_text, created_at)
           VALUES (:session_id, :item_id, :video_id, :segment_id, :word_index, :expected, :expected_norm, :typed,
                   :is_correct, :used_help, :replays, :segment_start, :segment_text, :created_at)""",
        {**data, "created_at": utcnow()},
    )


def word_error_rates(conn: sqlite3.Connection) -> dict[str, float]:
    """Taxa de erro suavizada por palavra (erros ÷ (tentativas + 1)): uma tentativa errada não domina."""
    rows = conn.execute(
        """SELECT expected_norm, COUNT(*) AS attempts, SUM(is_correct = 0) AS errors
           FROM listening_word_attempts GROUP BY expected_norm HAVING errors > 0""")
    return {r["expected_norm"]: r["errors"] / (r["attempts"] + 1) for r in rows}
