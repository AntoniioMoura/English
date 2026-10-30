import json
import sqlite3
from datetime import datetime, timezone

from ..db import utcnow

# ---------- vocabulário ----------

VOCAB_STATS = """
    SELECT v.*,
           (SELECT COUNT(*) FROM recall_exercise_targets t WHERE t.vocabulary_id = v.id) AS times_used,
           (SELECT COUNT(*) FROM recall_target_usage u WHERE u.vocabulary_id = v.id AND u.demonstrated = 1)
               AS times_demonstrated,
           (SELECT MAX(e.id) FROM recall_exercise_targets t JOIN recall_exercises e ON e.id = t.exercise_id
             WHERE t.vocabulary_id = v.id) AS last_exercise_id
    FROM vocabulary_entries v
    WHERE v.deleted_at IS NULL
"""


def _vocab(row: sqlite3.Row) -> dict:
    return {**dict(row), "enabled": bool(row["enabled"])}


def list_vocab(conn: sqlite3.Connection, only_enabled: bool = False) -> list[dict]:
    query = VOCAB_STATS + (" AND v.enabled = 1" if only_enabled else "") + " ORDER BY v.english_text COLLATE NOCASE"
    return [_vocab(r) for r in conn.execute(query)]


def get_vocab(conn: sqlite3.Connection, vocab_id: int) -> dict | None:
    row = conn.execute(VOCAB_STATS + " AND v.id = ?", (vocab_id,)).fetchone()
    return _vocab(row) if row else None


def find_duplicate(conn: sqlite3.Connection, normalized: str, translation: str | None, exclude_id: int | None) -> bool:
    rows = conn.execute(
        "SELECT id, translation_pt FROM vocabulary_entries WHERE deleted_at IS NULL AND normalized_text = ?",
        (normalized,),
    )
    want = (translation or "").strip().lower()
    return any(r["id"] != exclude_id and (r["translation_pt"] or "").strip().lower() == want for r in rows)


def insert_vocab(conn: sqlite3.Connection, data: dict, normalized: str) -> int:
    now = utcnow()
    cur = conn.execute(
        """INSERT INTO vocabulary_entries
           (english_text, normalized_text, part_of_speech, translation_pt, notes, enabled, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
        (data["english_text"], normalized, data.get("part_of_speech"), data.get("translation_pt"),
         data.get("notes"), now, now),
    )
    return cur.lastrowid


def update_vocab(conn: sqlite3.Connection, vocab_id: int, fields: dict) -> None:
    if not fields:
        return
    fields = {**fields, "updated_at": utcnow()}
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE vocabulary_entries SET {sets} WHERE id = ?", (*fields.values(), vocab_id))


def soft_delete_vocab(conn: sqlite3.Connection, vocab_id: int) -> None:
    now = utcnow()
    conn.execute("UPDATE vocabulary_entries SET deleted_at = ?, enabled = 0, updated_at = ? WHERE id = ?",
                 (now, now, vocab_id))


# ---------- exercícios ----------

def insert_exercise(
    conn: sqlite3.Connection, mode: str, review_item_id: int | None, data: dict, model: str, prompt_version: int
) -> int:
    cur = conn.execute(
        """INSERT INTO recall_exercises
           (mode, review_item_id, sentence_pt, reference_en, grammar_tags, status, model, prompt_version, created_at)
           VALUES (?, ?, ?, ?, ?, 'pending_answer', ?, ?, ?)""",
        (mode, review_item_id, data["sentence_pt"], data["reference_en"], json.dumps(data["grammar_tags"]),
         model, prompt_version, utcnow()),
    )
    exercise_id = cur.lastrowid
    conn.executemany(
        """INSERT INTO recall_exercise_targets (exercise_id, vocabulary_id, english_text, intended_meaning)
           VALUES (?, ?, ?, ?)""",
        [(exercise_id, t["vocabulary_id"], t["english_text"], t.get("intended_meaning")) for t in data["targets"]],
    )
    return exercise_id


def get_exercise(conn: sqlite3.Connection, exercise_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM recall_exercises WHERE id = ?", (exercise_id,)).fetchone()
    if not row:
        return None
    return {**dict(row), "grammar_tags": json.loads(row["grammar_tags"])}


def get_targets(conn: sqlite3.Connection, exercise_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM recall_exercise_targets WHERE exercise_id = ? ORDER BY vocabulary_id", (exercise_id,)
    )]


def set_exercise_status(conn: sqlite3.Connection, exercise_id: int, status: str) -> None:
    conn.execute("UPDATE recall_exercises SET status = ? WHERE id = ?", (status, exercise_id))


def pending_exercise(conn: sqlite3.Connection, mode: str, review_item_id: int | None = None) -> int | None:
    query = "SELECT id FROM recall_exercises WHERE mode = ? AND status = 'pending_answer'"
    params: list = [mode]
    if review_item_id is not None:
        query += " AND review_item_id = ?"
        params.append(review_item_id)
    row = conn.execute(query + " ORDER BY id DESC LIMIT 1", params).fetchone()
    return row["id"] if row else None


def recent_sentences(conn: sqlite3.Connection, limit: int = 15, review_item_id: int | None = None) -> list[str]:
    if review_item_id is not None:
        rows = conn.execute(
            "SELECT sentence_pt FROM recall_exercises WHERE review_item_id = ? ORDER BY id DESC LIMIT ?",
            (review_item_id, limit),
        )
    else:
        rows = conn.execute("SELECT sentence_pt FROM recall_exercises ORDER BY id DESC LIMIT ?", (limit,))
    return [r["sentence_pt"] for r in rows]


def recently_used_vocab(conn: sqlite3.Connection, last_exercises: int = 3) -> set[int]:
    rows = conn.execute(
        """SELECT DISTINCT vocabulary_id FROM recall_exercise_targets
           WHERE exercise_id IN (SELECT id FROM recall_exercises ORDER BY id DESC LIMIT ?)""",
        (last_exercises,),
    )
    return {r["vocabulary_id"] for r in rows}


# ---------- tentativas e avaliações ----------

def get_attempt(conn: sqlite3.Connection, exercise_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM recall_attempts WHERE exercise_id = ?", (exercise_id,)).fetchone()
    return dict(row) if row else None


def get_attempt_by_key(conn: sqlite3.Connection, key: str) -> dict | None:
    row = conn.execute("SELECT * FROM recall_attempts WHERE idempotency_key = ?", (key,)).fetchone()
    return dict(row) if row else None


def insert_attempt(conn: sqlite3.Connection, exercise_id: int, key: str, answer: str, local_date: str) -> int:
    cur = conn.execute(
        """INSERT INTO recall_attempts (exercise_id, idempotency_key, answer_text, local_date, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (exercise_id, key, answer, local_date, utcnow()),
    )
    return cur.lastrowid


def set_attempt_verdict(conn: sqlite3.Connection, attempt_id: int, verdict: str, counts: bool) -> None:
    conn.execute(
        "UPDATE recall_attempts SET verdict = ?, counts_toward_quota = ?, evaluated_at = ? WHERE id = ?",
        (verdict, int(counts), utcnow(), attempt_id),
    )


def insert_ai_evaluation(
    conn: sqlite3.Connection, attempt_id: int, status: str, schema_version: int, model: str,
    raw: dict | None, result: dict | None, error: str | None,
) -> int:
    cur = conn.execute(
        """INSERT INTO ai_evaluations
           (source_mode, attempt_id, status, schema_version, model, raw_result, result, error_message, created_at)
           VALUES ('sentence_recall', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (attempt_id, status, schema_version, model, json.dumps(raw) if raw else None,
         json.dumps(result) if result else None, error, utcnow()),
    )
    return cur.lastrowid


def latest_ai_evaluation(conn: sqlite3.Connection, attempt_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ai_evaluations WHERE attempt_id = ? ORDER BY id DESC LIMIT 1", (attempt_id,)
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["result"] = json.loads(data["result"]) if data["result"] else None
    return data


def insert_observations(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        """INSERT INTO recall_observations
           (topic_id, exercise_id, attempt_id, evidence_type, category, excerpt, correction, explanation_pt, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(*r, utcnow()) for r in rows],
    )


def insert_target_usage(conn: sqlite3.Connection, attempt_id: int, usage: list[tuple[int, bool]]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO recall_target_usage (attempt_id, vocabulary_id, demonstrated) VALUES (?, ?, ?)",
        [(attempt_id, vocab_id, int(demonstrated)) for vocab_id, demonstrated in usage],
    )


def quota_errors(conn: sqlite3.Connection, local_date: str) -> int:
    """Calculado a partir das tentativas persistidas: uma frase nova errada conta uma vez."""
    row = conn.execute(
        """SELECT COUNT(DISTINCT a.exercise_id) FROM recall_attempts a
           JOIN recall_exercises e ON e.id = a.exercise_id
           WHERE a.local_date = ? AND a.counts_toward_quota = 1 AND e.mode = 'new'""",
        (local_date,),
    ).fetchone()
    return row[0]


def history(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT e.id, e.mode, e.sentence_pt, e.status, a.answer_text, a.verdict, a.created_at,
                  (SELECT GROUP_CONCAT(t.english_text, ', ') FROM recall_exercise_targets t
                    WHERE t.exercise_id = e.id) AS targets
           FROM recall_exercises e JOIN recall_attempts a ON a.exercise_id = e.id
           ORDER BY a.id DESC LIMIT ?""",
        (limit,),
    )
    return [dict(r) for r in rows]


def verdict_counts(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """SELECT e.mode, a.verdict, COUNT(*) AS n FROM recall_attempts a
           JOIN recall_exercises e ON e.id = a.exercise_id WHERE a.verdict IS NOT NULL GROUP BY e.mode, a.verdict"""
    )
    counts: dict = {}
    for r in rows:
        counts.setdefault(r["mode"], {})[r["verdict"]] = r["n"]
    return counts


def topic_errors(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT o.topic_id, g.name_pt,
                  SUM(o.evidence_type = 'error') AS errors, SUM(o.evidence_type = 'correct') AS correct
           FROM recall_observations o JOIN grammar_topics g ON g.id = o.topic_id
           WHERE o.review_status != 'dismissed' AND o.topic_id != 'other'
           GROUP BY o.topic_id ORDER BY errors DESC, correct DESC"""
    )
    return [dict(r) for r in rows]


# ---------- revisão ----------

def _item(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["scheduler_state"] = json.loads(data["scheduler_state"])
    data["examples"] = json.loads(data["examples"])
    return data


def get_review_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    return _item(row) if row else None


def get_review_item_by_target(conn: sqlite3.Connection, target_type: str, target_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM review_items WHERE target_type = ? AND target_id = ?", (target_type, target_id)
    ).fetchone()
    return _item(row) if row else None


def _precise_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def insert_review_item(
    conn: sqlite3.Connection, target_type: str, target_id: str, label: str, state: dict, due_at: str,
    examples: list, local_date: str, target_text: str | None = None,
) -> int:
    now = utcnow()
    cur = conn.execute(
        """INSERT INTO review_items (target_type, target_id, target_text, label_pt, status, scheduler_state, due_at,
                                     examples, last_event_local_date, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'learning', ?, ?, ?, ?, ?, ?)""",
        (target_type, target_id, target_text, label, json.dumps(state), due_at, json.dumps(examples), local_date,
         now, now),
    )
    return cur.lastrowid


def update_review_item(conn: sqlite3.Connection, item_id: int, **fields) -> None:
    for key in ("scheduler_state", "examples"):
        if key in fields:
            fields[key] = json.dumps(fields[key])
    fields["updated_at"] = _precise_now()  # desempate da fila: quem acabou de errar vai para o fim
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE review_items SET {sets} WHERE id = ?", (*fields.values(), item_id))


def insert_review_event(
    conn: sqlite3.Connection, item_id: int, outcome: str, due_before: str | None, due_after: str,
    exercise_id: int | None = None, attempt_id: int | None = None,
) -> None:
    conn.execute(
        """INSERT INTO review_events (review_item_id, exercise_id, attempt_id, outcome, due_before, due_after, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (item_id, exercise_id, attempt_id, outcome, due_before, due_after, utcnow()),
    )


def due_review_items(conn: sqlite3.Connection, now_iso: str) -> list[dict]:
    # Empate de horário: quem acabou de ser errado vai para o fim da fila.
    rows = conn.execute("SELECT * FROM review_items WHERE due_at <= ? ORDER BY due_at, updated_at, id", (now_iso,))
    return [_item(r) for r in rows]


def upcoming_review_items(conn: sqlite3.Connection, now_iso: str, limit: int = 10) -> list[dict]:
    rows = conn.execute("SELECT * FROM review_items WHERE due_at > ? ORDER BY due_at LIMIT ?", (now_iso, limit))
    return [_item(r) for r in rows]
