"""Catálogo e preparação dos vídeos do Listening.

- Varredura de videos/: registra arquivos novos, detecta conteúdo alterado (fingerprint), arquivos movidos
  (mesmo fingerprint em outro caminho) e ausentes (marcados, nunca apagados com o histórico).
- Metadados/miniatura: logo após a varredura, em segundo plano.
- Preparação (legendas + versão compatível): só quando o usuário abre o vídeo; o resultado fica em cache
  até o conteúdo do arquivo ou a PIPELINE_VERSION mudarem. Dificuldade e sessões nunca reprocessam.
"""

import hashlib
import json
import logging
import queue
import shutil
import sqlite3
import threading
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .. import db
from ..db import transaction
from ..domain.listening import looks_english
from ..domain.rules import RuleViolation
from ..media import ffmpeg, subtitles, transcriber
from ..media.ffmpeg import ENGLISH_TAGS, PORTUGUESE_TAGS, MediaError
from ..media.subtitles import Cue
from ..media.transcriber import TranscriptionError
from ..repositories import listening as repo
from ..repositories import settings as settings_repo
from . import settings_service
from .exercise_service import NotFound

log = logging.getLogger(__name__)

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm"}
# Suba quando a forma de gerar trechos/versão compatível mudar: invalida o cache de todos os vídeos.
PIPELINE_VERSION = 4  # 2: ressincronia pelo áudio; 3: palavras conferidas com o áudio; 4: fala sobreposta não corta a anterior
HASH_CHUNK = 1024 * 1024


class ListeningSettings(BaseModel):
    whisper_model: str = Field(default="large-v3", min_length=1, max_length=80)
    whisper_device: str = Field(default="auto", pattern="^(auto|cuda|cpu)$")


def get_settings(conn: sqlite3.Connection) -> ListeningSettings:
    try:
        return ListeningSettings(**settings_repo.get_all(conn).get("listening", {}))
    except ValidationError:
        return ListeningSettings()


def save_settings(conn: sqlite3.Connection, changes: dict) -> ListeningSettings:
    try:
        new = ListeningSettings(**{**get_settings(conn).model_dump(), **changes})
    except ValidationError as exc:
        raise RuleViolation("invalid_settings", exc.errors()[0]["msg"], 422) from exc
    with transaction(conn):
        settings_repo.set_many(conn, {"listening": new.model_dump()})
    return new


# ---------- identificação ----------

def fingerprint(path: Path, size: int) -> str:
    """Tamanho + SHA-1 do primeiro e do último MB: rápido em arquivos grandes e não muda ao copiar/mover."""
    h = hashlib.sha1()
    with path.open("rb") as f:
        h.update(f.read(HASH_CHUNK))
        if size > 2 * HASH_CHUNK:
            f.seek(-HASH_CHUNK, 2)
            h.update(f.read(HASH_CHUNK))
    return f"{size}-{h.hexdigest()[:20]}"


def is_prepared(video: dict) -> bool:
    return (
        video["status"] == "ready"
        and video["processed_fingerprint"] == video["fingerprint"]
        and video["pipeline_version"] == PIPELINE_VERSION
    )


def effective_status(video: dict) -> str:
    if video["status"] == "ready" and not is_prepared(video):
        return "unprocessed"  # conteúdo ou pipeline mudaram: o cache não vale mais
    return video["status"]


def video_path(videos_dir: Path, video: dict) -> Path:
    path = (videos_dir / video["rel_path"]).resolve()
    if videos_dir.resolve() not in path.parents:
        raise NotFound("Vídeo fora da pasta videos/.")
    return path


def cache_dir_for(cache_dir: Path, video_id: int) -> Path:
    return cache_dir / str(video_id)


# ---------- varredura ----------

def scan(conn: sqlite3.Connection, videos_dir: Path) -> dict:
    videos_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    for path in videos_dir.rglob("*"):
        if path.suffix.lower() in VIDEO_EXTS and path.is_file() and not path.name.startswith("."):
            files[path.relative_to(videos_dir).as_posix()] = path

    rows = {v["rel_path"]: v for v in repo.list_videos(conn)}
    gone = {v["fingerprint"]: v for rel, v in rows.items() if rel not in files}
    added = moved = changed = missing = 0
    with transaction(conn):
        for rel, path in files.items():
            st = path.stat()
            row = rows.get(rel)
            category = rel.split("/")[0] if "/" in rel else ""
            if row and row["file_size"] == st.st_size and row["file_mtime"] == st.st_mtime:
                if not row["present"]:
                    repo.update_video(conn, row["id"], {"present": 1})
                continue
            fp = fingerprint(path, st.st_size)
            if row:
                fields = {"file_size": st.st_size, "file_mtime": st.st_mtime, "fingerprint": fp, "present": 1}
                if fp != row["fingerprint"]:
                    changed += 1
                    if row["status"] != "processing":
                        fields.update(status="unprocessed", stage=None, progress=None, error_message=None)
                repo.update_video(conn, row["id"], fields)
            elif fp in gone:  # mesmo conteúdo em outro caminho: arquivo movido/renomeado, histórico preservado
                old = gone.pop(fp)
                repo.update_video(conn, old["id"], {"rel_path": rel, "category": category, "file_size": st.st_size,
                                                    "file_mtime": st.st_mtime, "present": 1})
                moved += 1
            else:
                repo.insert_video(conn, {"rel_path": rel, "category": category, "file_size": st.st_size,
                                         "file_mtime": st.st_mtime, "fingerprint": fp})
                added += 1
        for old in gone.values():
            if old["present"]:
                repo.update_video(conn, old["id"], {"present": 0})
                missing += 1
    return {"added": added, "moved": moved, "changed": changed, "missing": missing}


def needs_metadata(video: dict) -> bool:
    return bool(video["present"]) and video["meta_fingerprint"] != video["fingerprint"]


def read_metadata(conn: sqlite3.Connection, video_id: int, videos_dir: Path, cache_dir: Path) -> None:
    video = repo.get_video(conn, video_id)
    if not video or not needs_metadata(video):
        return
    path = video_path(videos_dir, video)
    fields: dict = {"meta_fingerprint": video["fingerprint"]}
    try:
        info = ffmpeg.probe(path)
        fields.update(ffmpeg.summarize(info), probe_json=json.dumps(info))
        thumb = cache_dir_for(cache_dir, video_id) / "thumbnail.jpg"
        try:
            ffmpeg.thumbnail(path, thumb, fields["duration"])
            fields["thumbnail_path"] = str(thumb) if thumb.exists() else None
        except MediaError as exc:  # sem miniatura o vídeo continua utilizável
            log.warning("miniatura de %s: %s", video["rel_path"], exc)
    except MediaError as exc:
        fields.update(status="error", error_message=f"Não foi possível ler o vídeo: {exc}")
    with transaction(conn):
        repo.update_video(conn, video_id, fields)


# ---------- preparação ----------

class _Progress:
    """Grava etapa/percentual sem martelar o banco a cada segmento transcrito."""

    def __init__(self, conn: sqlite3.Connection, video_id: int):
        self.conn, self.video_id, self.last = conn, video_id, -1.0

    def __call__(self, stage: str, value: float, force: bool = False) -> None:
        if force or value - self.last >= 0.01 or value < self.last:
            self.last = value
            with transaction(self.conn):
                repo.update_video(self.conn, self.video_id, {"stage": stage, "progress": round(value, 3)})


def _english_subtitles(path: Path, info: dict, work: Path) -> tuple[list[Cue], str] | None:
    """1º legenda externa em inglês; 2º faixa embutida em inglês. Sem idioma declarado, confere o texto."""
    external = subtitles.external_files(path)
    for lang, sub in sorted(external, key=lambda x: x[0] != "en"):
        if lang in ("en", ""):
            cues = subtitles.read(sub)
            if cues and (lang == "en" or looks_english([c.text for c in cues])):
                return cues, "external"
    streams = ffmpeg.subtitle_streams(info)
    for stream in sorted(streams, key=lambda s: s["language"] not in ENGLISH_TAGS):
        if stream["language"] in ENGLISH_TAGS or stream["language"] in ("", "und"):
            dest = work / f"embedded_{stream['index']}.srt"
            try:
                ffmpeg.extract_subtitle(path, stream["index"], dest)
            except MediaError as exc:
                log.warning("legenda embutida %s: %s", stream["index"], exc)
                continue
            cues = subtitles.read(dest)
            if cues and (stream["language"] in ENGLISH_TAGS or looks_english([c.text for c in cues])):
                # "forced"/"SDH" curtíssimas não servem como transcrição completa
                if len(cues) >= 3 or not info.get("format", {}).get("duration"):
                    return cues, "embedded"
    return None


def _portuguese_subtitles(path: Path, info: dict, work: Path) -> tuple[list[Cue], str] | None:
    for lang, sub in subtitles.external_files(path):
        if lang == "pt" and (cues := subtitles.read(sub)):
            return cues, "external"
    for stream in ffmpeg.subtitle_streams(info):
        if stream["language"] in PORTUGUESE_TAGS:
            dest = work / f"embedded_{stream['index']}.srt"
            try:
                ffmpeg.extract_subtitle(path, stream["index"], dest)
            except MediaError:
                continue
            if cues := subtitles.read(dest):
                return cues, "embedded"
    return None


def prepare(conn: sqlite3.Connection, video_id: int, videos_dir: Path, cache_dir: Path) -> None:
    video = repo.get_video(conn, video_id)
    if not video:
        return
    progress = _Progress(conn, video_id)
    work = cache_dir_for(cache_dir, video_id)
    work.mkdir(parents=True, exist_ok=True)
    settings = get_settings(conn)
    try:
        path = video_path(videos_dir, video)
        if not path.is_file():
            raise MediaError("Arquivo não encontrado na pasta videos/.")
        progress("Lendo o vídeo", 0.02, force=True)
        info = ffmpeg.probe(path)
        duration = ffmpeg.summarize(info)["duration"]
        plan = ffmpeg.playback_plan(path, info)

        found = _english_subtitles(path, info, work)
        stream = ffmpeg.choose_audio_stream(info)
        sync = found is not None and stream is not None and transcriber.available()
        span = (0.05, 0.75) if found is None or sync else (0.05, 0.10)
        translation = _portuguese_subtitles(path, info, work)

        def listen(label: str) -> list[Cue]:
            if stream is None:
                raise MediaError("O vídeo não tem áudio nem legenda em inglês.")
            progress("Extraindo o áudio", 0.04, force=True)
            audio = work / "audio.wav"
            ffmpeg.extract_audio(path, audio, stream["index"])
            progress(label, span[0], force=True)
            try:
                return transcriber.transcribe(audio, duration, settings.whisper_model, settings.whisper_device,
                                              lambda p: progress(label, span[0] + p * (span[1] - span[0])))
            finally:
                audio.unlink(missing_ok=True)

        if found:
            cues, source = found
            # a tradução tem o mesmo atraso da legenda original: pareia antes de ressincronizar
            aligned = subtitles.align_translation(cues, translation[0]) if translation else [None] * len(cues)
            if sync:
                try:
                    heard = listen("Sincronizando a legenda com o áudio (Whisper)")
                    cues = subtitles.align_to_words(cues, [w for c in heard for w in c.words or []])
                except TranscriptionError as exc:  # sem sincronia, fica o horário da legenda
                    log.warning("sincronização da legenda de %s: %s", video["rel_path"], exc)
        else:
            cues = listen("Transcrevendo o áudio (Whisper)")
            source = "whisper"
            aligned = subtitles.align_translation(cues, translation[0]) if translation else [None] * len(cues)
        if not cues:
            raise MediaError("Nenhuma fala em inglês foi encontrada neste vídeo.")
        (work / "subtitles.en.srt").write_text(subtitles.to_srt(cues), encoding="utf-8")

        playback_path = None
        if plan != "original":
            dest = work / "playback.mp4"
            label = "Ajustando o vídeo para o navegador" if plan == "remux" else "Convertendo o vídeo para o navegador"
            start = span[1]
            progress(label, start, force=True)
            ffmpeg.convert_for_playback(path, dest, info, plan, lambda p: progress(label, start + p * (0.98 - start)))
            playback_path = str(dest)
        else:
            (work / "playback.mp4").unlink(missing_ok=True)

        if not video["thumbnail_path"]:
            try:
                ffmpeg.thumbnail(path, work / "thumbnail.jpg", duration)
            except MediaError:
                pass

        segments = [{"start": c.start, "end": c.end, "text": c.text, "translation_pt": t,
                     "word_audio": json.dumps(c.audio) if c.audio else None}
                    for c, t in zip(cues, aligned)]
        current = repo.get_video(conn, video_id)
        rev = current["processing_rev"] + 1
        with transaction(conn):
            repo.replace_segments(conn, video_id, rev, segments)
            conn.execute("UPDATE listening_sessions SET status = 'abandoned' WHERE video_id = ? AND status = 'active'",
                         (video_id,))
            repo.update_video(conn, video_id, {
                "status": "ready", "stage": None, "progress": 1.0, "error_message": None,
                "processed_fingerprint": current["fingerprint"], "pipeline_version": PIPELINE_VERSION,
                "processing_rev": rev, "playback_path": playback_path, "subtitle_source": source,
                "translation_source": translation[1] if translation else None,
                "translation_status": None, "translation_progress": None, "translation_error": None,
                "thumbnail_path": current["thumbnail_path"] or (
                    str(work / "thumbnail.jpg") if (work / "thumbnail.jpg").exists() else None),
            })
    except (MediaError, TranscriptionError, OSError, NotFound) as exc:
        with transaction(conn):
            repo.update_video(conn, video_id, {"status": "error", "stage": None, "error_message": str(exc)})
    except Exception as exc:  # nunca deixa o vídeo preso em "processando"
        log.exception("falha inesperada ao preparar o vídeo %s", video_id)
        with transaction(conn):
            repo.update_video(conn, video_id, {"status": "error", "stage": None,
                                               "error_message": f"Erro inesperado: {exc}"})


def clear_cache(cache_dir: Path, video_id: int) -> None:
    shutil.rmtree(cache_dir_for(cache_dir, video_id), ignore_errors=True)


# ---------- fila em segundo plano ----------

class ListeningWorker:
    """Filas: metadados/miniaturas (rápidas), preparação (pesada, uma de cada vez), downloads e traduções.

    Com `inline=True` (testes) o trabalho roda na hora, na própria chamada.
    """

    KINDS = ("meta", "prepare", "download", "translate")

    def __init__(self, db_path: Path | str, videos_dir: Path, cache_dir: Path, inline: bool = False):
        self.db_path, self.videos_dir, self.cache_dir, self.inline = db_path, videos_dir, cache_dir, inline
        self._queues = {kind: queue.Queue() for kind in self.KINDS}
        self._pending: dict[str, set[int]] = {kind: set() for kind in self.KINDS}
        # Cliente do Ollama para as traduções (os testes trocam por um simulado).
        self.llm_factory = settings_service.build_client
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def _job(self, kind: str, video_id: int) -> None:  # em "download", o id é o do download
        conn = db.connect(self.db_path)
        try:
            if kind == "meta":
                read_metadata(conn, video_id, self.videos_dir, self.cache_dir)
            elif kind == "download":
                from .listening_downloads import run_download

                run_download(conn, video_id, self.videos_dir, self.cache_dir, self)
            elif kind == "translate":
                from . import listening_translation

                listening_translation.run(conn, video_id, self.llm_factory(conn))
            else:
                prepare(conn, video_id, self.videos_dir, self.cache_dir)
        finally:
            conn.close()

    def _loop(self, kind: str) -> None:
        q = self._queues[kind]
        while True:
            video_id = q.get()
            try:
                self._job(kind, video_id)
            except Exception:
                log.exception("tarefa %s do vídeo %s", kind, video_id)
            finally:
                with self._lock:
                    self._pending[kind].discard(video_id)

    def submit(self, kind: str, video_id: int) -> None:
        if self.inline:
            self._job(kind, video_id)
            return
        with self._lock:
            if video_id in self._pending[kind]:
                return
            self._pending[kind].add(video_id)
            if kind not in self._threads:
                t = threading.Thread(target=self._loop, args=(kind,), name=f"listening-{kind}", daemon=True)
                self._threads[kind] = t
                t.start()
        self._queues[kind].put(video_id)

    def is_queued(self, kind: str, video_id: int) -> bool:
        with self._lock:
            return video_id in self._pending[kind]


def recover_interrupted(conn: sqlite3.Connection) -> None:
    """Na inicialização: preparo interrompido pelo fechamento do servidor vira erro recuperável."""
    with transaction(conn):
        conn.execute(
            """UPDATE listening_videos SET status = 'error', stage = NULL,
                      error_message = 'Preparação interrompida (o servidor foi fechado). Tente novamente.'
               WHERE status = 'processing'""")
