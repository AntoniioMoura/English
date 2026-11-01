"""Tempo de estudo: o frontend mede os segundos; o backend decide o dia e guarda o histórico."""

import math
import sqlite3
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..repositories import study_time as repo
from . import recall_service

MAX_SECONDS_PER_REQUEST = 86_400


def _local_now(conn: sqlite3.Connection) -> datetime:
    return recall_service.now().astimezone(ZoneInfo(recall_service.get_settings(conn).timezone))


def today(conn: sqlite3.Connection) -> dict:
    current = _local_now(conn)
    midnight = datetime.combine(current.date() + timedelta(days=1), time.min, tzinfo=current.tzinfo)
    remaining = midnight.astimezone(timezone.utc) - current.astimezone(timezone.utc)
    local_date = current.date().isoformat()
    return {
        "day": local_date,
        "total_seconds": repo.total_for_day(conn, local_date),
        "seconds_until_reset": math.ceil(remaining.total_seconds()),
    }


def add(conn: sqlite3.Connection, seconds: dict[str, int], day: str | None) -> dict:
    """Soma os segundos medidos. `day` é o dia em que foram medidos: um envio feito logo depois da
    meia-noite ainda conta para ontem; qualquer data mais antiga cai em hoje."""
    current = _local_now(conn).date()
    valid_days = {current.isoformat(), (current - timedelta(days=1)).isoformat()}
    target = day if day in valid_days else current.isoformat()
    clean = {activity: min(amount, MAX_SECONDS_PER_REQUEST) for activity, amount in seconds.items() if amount > 0}
    repo.add_seconds(conn, target, clean)
    return today(conn)


def month(conn: sqlite3.Connection, month_key: str | None) -> dict:
    current = _local_now(conn).date()
    key = month_key or current.strftime("%Y-%m")
    days: dict[str, dict] = {}
    for row in repo.rows_for_month(conn, key):
        entry = days.setdefault(row["local_date"], {"date": row["local_date"], "total_seconds": 0, "activities": {}})
        entry["total_seconds"] += row["seconds"]
        entry["activities"][row["activity"]] = row["seconds"]
    return {
        "month": key,
        "today": current.isoformat(),
        "total_seconds": sum(d["total_seconds"] for d in days.values()),
        "days": list(days.values()),
    }
