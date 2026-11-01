import sqlite3

from ..db import transaction, utcnow


def add_seconds(conn: sqlite3.Connection, local_date: str, seconds: dict[str, int]) -> None:
    with transaction(conn):
        for activity, amount in seconds.items():
            conn.execute(
                """INSERT INTO study_time (local_date, activity, seconds, updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT (local_date, activity)
                   DO UPDATE SET seconds = seconds + excluded.seconds, updated_at = excluded.updated_at""",
                (local_date, activity, amount, utcnow()),
            )


def total_for_day(conn: sqlite3.Connection, local_date: str) -> int:
    row = conn.execute("SELECT COALESCE(SUM(seconds), 0) FROM study_time WHERE local_date = ?", (local_date,)).fetchone()
    return row[0]


def rows_for_month(conn: sqlite3.Connection, month: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT local_date, activity, seconds FROM study_time WHERE local_date LIKE ? AND seconds > 0 ORDER BY local_date",
        (f"{month}-%",),
    ).fetchall()
