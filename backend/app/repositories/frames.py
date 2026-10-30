import json
import sqlite3


def _to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["grammar_tags"] = json.loads(data["grammar_tags"])
    data["examples"] = json.loads(data["examples"])
    data["enabled"] = bool(data["enabled"])
    return data


def list_frames(conn: sqlite3.Connection, level: str | None = None, include_disabled: bool = False) -> list[dict]:
    query = "SELECT * FROM sentence_frames WHERE 1=1"
    params: list = []
    if not include_disabled:
        query += " AND enabled = 1"
    if level:
        query += " AND level = ?"
        params.append(level)
    query += " ORDER BY level, rowid"
    return [_to_dict(r) for r in conn.execute(query, params)]


def get_frame(conn: sqlite3.Connection, frame_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM sentence_frames WHERE id = ?", (frame_id,)).fetchone()
    return _to_dict(row) if row else None


def random_frame(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM sentence_frames WHERE enabled = 1 ORDER BY RANDOM() LIMIT 1").fetchone()
    return _to_dict(row) if row else None


def topic_ids(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT id FROM grammar_topics ORDER BY rowid")]


def topic_names(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["id"]: r["name_pt"] for r in conn.execute("SELECT id, name_pt FROM grammar_topics")}
