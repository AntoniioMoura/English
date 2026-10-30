import json
import sqlite3


def get_all(conn: sqlite3.Connection) -> dict:
    return {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM app_settings")}


def set_many(conn: sqlite3.Connection, values: dict) -> None:
    conn.executemany(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [(k, json.dumps(v)) for k, v in values.items()],
    )
