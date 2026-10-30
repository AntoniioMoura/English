"""Downloads do YouTube para videos/: fila em segundo plano, progresso e entrada automática no catálogo.

O yt-dlp baixa numa pasta temporária do cache; só o MP4 final e as legendas vão para videos/, para a
varredura do catálogo nunca enxergar arquivos parciais. Depois, o vídeo é catalogado e preparado.
"""

import re
import shutil
import sqlite3
from pathlib import Path

from ..db import transaction, utcnow
from ..domain.rules import RuleViolation
from ..media import ffmpeg, youtube
from ..media.youtube import DownloadError
from ..repositories import listening as repo
from . import listening_media as media
from .exercise_service import NotFound

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _row(conn: sqlite3.Connection, download_id: int) -> dict:
    row = conn.execute("SELECT * FROM listening_downloads WHERE id = ?", (download_id,)).fetchone()
    if not row:
        raise NotFound("Download não encontrado.")
    return dict(row)


def _update(conn: sqlite3.Connection, download_id: int, fields: dict) -> None:
    fields = {**fields, "updated_at": utcnow()}
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    with transaction(conn):
        conn.execute(f"UPDATE listening_downloads SET {assignments} WHERE id = :id", {**fields, "id": download_id})


def _out(row: dict) -> dict:
    return {k: row[k] for k in ("id", "url", "youtube_id", "category", "max_height", "status", "stage", "progress",
                                "title", "rel_path", "video_id", "error_message", "created_at", "updated_at")}


def clean_category(value: str | None) -> str:
    """Uma subpasta de videos/ (vira a categoria). Sem caminhos: '..' e barras não passam."""
    value = INVALID_CHARS.sub("", (value or "").strip()).strip(". ")
    return value[:60]


def list_downloads(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM listening_downloads WHERE dismissed = 0 ORDER BY id DESC LIMIT ?", (limit,))
    return [_out(dict(r)) for r in rows]


def create_download(conn: sqlite3.Connection, worker: "media.ListeningWorker", videos_dir: Path, url: str,
                    category: str | None, max_height: int) -> dict:
    if not youtube.available():
        raise RuleViolation("ytdlp_missing", "yt-dlp não está instalado: backend\\.venv\\Scripts\\pip install yt-dlp", 503)
    if not ffmpeg.available():
        raise RuleViolation("ffmpeg_missing", "FFmpeg não encontrado. Instale com `winget install Gyan.FFmpeg`.", 503)
    if max_height not in youtube.HEIGHTS:
        raise RuleViolation("invalid_quality", "Qualidade inválida.", 422)
    yt_id = youtube.video_id(url)
    if not yt_id:
        raise RuleViolation("invalid_url", "Cole o link de um vídeo do YouTube (youtube.com/watch?v=… ou youtu.be/…).", 422)

    active = conn.execute(
        "SELECT * FROM listening_downloads WHERE youtube_id = ? AND status IN ('queued', 'downloading')",
        (yt_id,)).fetchone()
    if active:
        return _out(dict(active))
    marker = f"[{yt_id}]"
    if videos_dir.exists() and any(marker in p.name for p in videos_dir.rglob(f"*{marker}*")
                                   if p.suffix.lower() in media.VIDEO_EXTS):
        raise RuleViolation("already_downloaded", "Este vídeo já está na pasta videos/.")

    now = utcnow()
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO listening_downloads (url, youtube_id, category, max_height, stage, progress, created_at,
                                                updated_at)
               VALUES (?, ?, ?, ?, 'Na fila', 0, ?, ?)""",
            (youtube.canonical_url(yt_id), yt_id, clean_category(category), max_height, now, now))
    download_id = cur.lastrowid
    worker.submit("download", download_id)
    return _out(_row(conn, download_id))


def retry(conn: sqlite3.Connection, worker: "media.ListeningWorker", download_id: int) -> dict:
    row = _row(conn, download_id)
    if row["status"] != "error":
        return _out(row)
    _update(conn, download_id, {"status": "queued", "stage": "Na fila", "progress": 0, "error_message": None})
    worker.submit("download", download_id)
    return _out(_row(conn, download_id))


def dismiss(conn: sqlite3.Connection, download_id: int) -> None:
    row = _row(conn, download_id)
    if row["status"] in ("queued", "downloading"):
        raise RuleViolation("download_running", "Espere o download terminar.")
    _update(conn, download_id, {"dismissed": 1})


def _unique(dest: Path) -> Path:
    n = 2
    candidate = dest
    while candidate.exists():
        candidate = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        n += 1
    return candidate


def run_download(conn: sqlite3.Connection, download_id: int, videos_dir: Path, cache_dir: Path,
                 worker: "media.ListeningWorker") -> None:
    row = _row(conn, download_id)
    work = cache_dir / "downloads" / str(download_id)
    shutil.rmtree(work, ignore_errors=True)
    last = {"value": -1.0}

    def progress(stage: str, value: float) -> None:
        if value - last["value"] >= 0.01 or value < last["value"] or stage == "Juntando vídeo e áudio":
            last["value"] = value
            _update(conn, download_id, {"stage": stage, "progress": round(value, 3)})

    _update(conn, download_id, {"status": "downloading", "stage": "Consultando o YouTube", "progress": 0})
    try:
        result = youtube.download(row["youtube_id"], work, row["max_height"], progress)
        target_dir = videos_dir / row["category"] if row["category"] else videos_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        video_dest = _unique(target_dir / result["video"].name)
        shutil.move(str(result["video"]), video_dest)
        for sub in result["subtitles"]:  # mesmo nome-base do vídeo: o pipeline encontra sozinho
            suffix = sub.name[len(result["video"].stem):]
            shutil.move(str(sub), _unique(target_dir / f"{video_dest.stem}{suffix}"))
        rel = video_dest.relative_to(videos_dir).as_posix()

        media.scan(conn, videos_dir)
        video = conn.execute("SELECT * FROM listening_videos WHERE rel_path = ?", (rel,)).fetchone()
        if video:
            with transaction(conn):
                repo.update_video(conn, video["id"], {"title": result["title"]})
        _update(conn, download_id, {"status": "done", "stage": None, "progress": 1.0, "title": result["title"],
                                    "rel_path": rel, "video_id": video["id"] if video else None})
        if video:
            worker.submit("meta", video["id"])
            with transaction(conn):  # já deixa legendas/vídeo prontos para estudar
                repo.update_video(conn, video["id"], {"status": "processing", "stage": "Na fila", "progress": 0})
            worker.submit("prepare", video["id"])
    except (DownloadError, OSError) as exc:
        _update(conn, download_id, {"status": "error", "stage": None, "error_message": str(exc)})
    finally:
        shutil.rmtree(work, ignore_errors=True)


def recover_interrupted(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE listening_downloads SET status = 'error', stage = NULL,
                      error_message = 'Download interrompido (o servidor foi fechado). Tente novamente.'
               WHERE status IN ('queued', 'downloading')""")
