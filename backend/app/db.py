"""Conexão SQLite e execução de migrações numeradas."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import config


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.DB_PATH)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def migrate(conn: sqlite3.Connection, migrations_dir: Path = config.MIGRATIONS_DIR) -> list[int]:
    """Aplica, em ordem, os arquivos NNN_nome.sql ainda não aplicados."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    newly_applied = []
    for file in sorted(migrations_dir.glob("*.sql")):
        version = int(file.name.split("_", 1)[0])
        if version in applied:
            continue
        conn.executescript(file.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (version, utcnow()))
        conn.commit()
        newly_applied.append(version)
    return newly_applied


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    from .seed_data import seed

    conn = connect(db_path)
    migrate(conn)
    seed(conn)
    return conn
