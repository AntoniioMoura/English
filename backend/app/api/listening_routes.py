"""Rotas do Listening com vídeos locais."""

import mimetypes
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..llm.client import LLMClient, LLMError
from ..services import listening_downloads as downloads
from ..services import listening_media as media
from ..services import listening_service as service
from .deps import get_conn, get_llm

router = APIRouter(prefix="/api/listening")


def get_worker(request: Request) -> media.ListeningWorker:
    return request.app.state.listening_worker


class VideoPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class PrepareIn(BaseModel):
    force: bool = False


class SegmentPatch(BaseModel):
    text: str | None = Field(default=None, max_length=1000)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    translation_pt: str | None = Field(default=None, max_length=1000)
    flagged: bool | None = None


class SessionIn(BaseModel):
    difficulty: str
    mode: str = Field(default="normal", pattern="^(normal|review)$")
    restart: bool = False
    interval: int = 30  # segundos entre frases-exercício; 0 = todas


class AnswersIn(BaseModel):
    answers: list[str | None] = Field(max_length=200)


class RevealIn(BaseModel):
    blank: int | None = None


class SkipIn(BaseModel):
    mismatch: bool = False


class PositionIn(BaseModel):
    index: int = Field(ge=0)


class DownloadIn(BaseModel):
    url: str = Field(min_length=10, max_length=500)
    category: str | None = Field(default="YouTube", max_length=60)
    max_height: int = 720


class SettingsPatch(BaseModel):
    whisper_model: str | None = None
    whisper_device: str | None = None


# ---------- catálogo e mídia ----------

@router.get("/library")
def library(request: Request, conn: sqlite3.Connection = Depends(get_conn),
            worker: media.ListeningWorker = Depends(get_worker)):
    return service.library(conn, worker, request.app.state.videos_dir)


@router.post("/library/scan")
def scan(request: Request, conn: sqlite3.Connection = Depends(get_conn),
         worker: media.ListeningWorker = Depends(get_worker)):
    return service.refresh_library(conn, worker, request.app.state.videos_dir)


@router.get("/videos/{video_id}")
def video(video_id: int, conn: sqlite3.Connection = Depends(get_conn),
          worker: media.ListeningWorker = Depends(get_worker)):
    return service.video_detail(conn, worker, video_id)


@router.patch("/videos/{video_id}")
def rename(video_id: int, body: VideoPatch, conn: sqlite3.Connection = Depends(get_conn)):
    return service.rename_video(conn, video_id, body.title)


@router.post("/videos/{video_id}/prepare")
def prepare(video_id: int, body: PrepareIn | None = None, conn: sqlite3.Connection = Depends(get_conn),
            worker: media.ListeningWorker = Depends(get_worker)):
    return service.prepare_video(conn, worker, video_id, force=bool(body and body.force))


@router.get("/videos/{video_id}/stream")
def stream(video_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    path = service.media_file(conn, request.app.state.videos_dir, video_id)
    # .mov com H.264 toca como MP4; o FileResponse atende requisições Range (avançar/voltar no vídeo).
    media_type = {".mov": "video/mp4", ".mkv": "video/x-matroska"}.get(
        path.suffix.lower(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@router.get("/videos/{video_id}/thumbnail")
def thumbnail(video_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return FileResponse(service.thumbnail_file(conn, video_id), media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})


@router.get("/videos/{video_id}/segments")
def list_segments(video_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return service.segments(conn, video_id)


@router.patch("/segments/{segment_id}")
def edit_segment(segment_id: int, body: SegmentPatch, conn: sqlite3.Connection = Depends(get_conn)):
    return service.update_segment(conn, segment_id, body.model_dump(exclude_unset=True))


# ---------- sessões ----------

@router.post("/videos/{video_id}/sessions", status_code=201)
def start_session(video_id: int, body: SessionIn, conn: sqlite3.Connection = Depends(get_conn)):
    return service.start_session(conn, video_id, body.difficulty, body.mode, body.restart, body.interval)


@router.get("/sessions/{session_id}")
def get_session(session_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return service.session_state(conn, session_id)


@router.post("/sessions/{session_id}/items/{item_id}/check")
def check(session_id: int, item_id: int, body: AnswersIn, conn: sqlite3.Connection = Depends(get_conn)):
    return service.check_answers(conn, session_id, item_id, body.answers)


@router.post("/sessions/{session_id}/items/{item_id}/reveal")
def reveal(session_id: int, item_id: int, body: RevealIn, conn: sqlite3.Connection = Depends(get_conn)):
    return service.reveal(conn, session_id, item_id, body.blank)


@router.post("/sessions/{session_id}/items/{item_id}/replay")
def replay(session_id: int, item_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return service.replay(conn, session_id, item_id)


@router.post("/sessions/{session_id}/items/{item_id}/translate")
def translate(session_id: int, item_id: int, conn: sqlite3.Connection = Depends(get_conn),
              llm: LLMClient = Depends(get_llm)):
    try:
        return service.translate(conn, llm, session_id, item_id)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail={"code": "llm_error", "message": str(exc)}) from exc


@router.post("/sessions/{session_id}/items/{item_id}/skip")
def skip(session_id: int, item_id: int, body: SkipIn, conn: sqlite3.Connection = Depends(get_conn)):
    return service.skip(conn, session_id, item_id, body.mismatch)


@router.put("/sessions/{session_id}/position")
def position(session_id: int, body: PositionIn, conn: sqlite3.Connection = Depends(get_conn)):
    return service.set_position(conn, session_id, body.index)


@router.post("/sessions/{session_id}/finish")
def finish(session_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return service.finish_session(conn, session_id)


# ---------- downloads do YouTube ----------

@router.get("/downloads")
def list_downloads(conn: sqlite3.Connection = Depends(get_conn)):
    return downloads.list_downloads(conn)


@router.post("/downloads", status_code=201)
def create_download(body: DownloadIn, request: Request, conn: sqlite3.Connection = Depends(get_conn),
                    worker: media.ListeningWorker = Depends(get_worker)):
    return downloads.create_download(conn, worker, request.app.state.videos_dir, body.url, body.category,
                                     body.max_height)


@router.post("/downloads/{download_id}/retry")
def retry_download(download_id: int, conn: sqlite3.Connection = Depends(get_conn),
                   worker: media.ListeningWorker = Depends(get_worker)):
    return downloads.retry(conn, worker, download_id)


@router.delete("/downloads/{download_id}", status_code=204)
def dismiss_download(download_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    downloads.dismiss(conn, download_id)


# ---------- painel e configurações ----------

@router.get("/stats")
def stats(conn: sqlite3.Connection = Depends(get_conn)):
    return service.stats(conn)


@router.get("/settings")
def get_settings(conn: sqlite3.Connection = Depends(get_conn)):
    return media.get_settings(conn)


@router.patch("/settings")
def patch_settings(body: SettingsPatch, conn: sqlite3.Connection = Depends(get_conn)):
    return media.save_settings(conn, body.model_dump(exclude_none=True))
