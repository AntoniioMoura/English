"""Chamadas ao FFmpeg/FFprobe: inspeção, miniatura, extração de legenda/áudio e conversão.

Os executáveis são procurados em FFMPEG_DIR, no PATH e na pasta de pacotes do winget
(o PATH de um processo já aberto não enxerga instalações feitas depois).
"""

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path


class MediaError(Exception):
    pass


# Combinações que tocam no player HTML5 dos navegadores atuais sem conversão.
PLAYABLE = {
    "mp4": ({"h264"}, {"aac", "mp3"}),
    "mov": ({"h264"}, {"aac", "mp3"}),
    "webm": ({"vp8", "vp9", "av1"}, {"opus", "vorbis"}),
}
TEXT_SUBTITLE_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
ENGLISH_TAGS = {"en", "eng", "english"}
PORTUGUESE_TAGS = {"pt", "por", "pob", "pt-br", "ptbr", "portuguese"}

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@lru_cache(maxsize=None)
def find_tool(name: str) -> str | None:
    exe = name + (".exe" if os.name == "nt" else "")
    if custom := os.environ.get("FFMPEG_DIR"):
        candidate = Path(custom) / exe
        if candidate.is_file():
            return str(candidate)
    if found := shutil.which(name):
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for candidate in sorted(Path(local, "Microsoft", "WinGet").glob(f"**/{exe}"), reverse=True):
            return str(candidate)
    return None


def available() -> bool:
    return bool(find_tool("ffmpeg") and find_tool("ffprobe"))


def _tool(name: str) -> str:
    path = find_tool(name)
    if not path:
        raise MediaError(
            f"{name} não encontrado. Instale o FFmpeg (ex.: `winget install Gyan.FFmpeg`) e reinicie o English Builder."
        )
    return path


def _run(args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            args, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{Path(args[0]).stem} demorou demais e foi interrompido.") from exc
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-3:]
        raise MediaError(f"{Path(args[0]).stem} falhou: {' '.join(tail) or result.returncode}")
    return result


def probe(path: Path) -> dict:
    result = _run([_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                  timeout=60)
    return json.loads(result.stdout or "{}")


def _lang(stream: dict) -> str:
    return (stream.get("tags") or {}).get("language", "").lower()


def summarize(info: dict) -> dict:
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = choose_audio_stream(info)
    try:
        duration = float(info.get("format", {}).get("duration") or 0) or None
    except ValueError:
        duration = None
    return {
        "duration": duration,
        "width": video.get("width") if video else None,
        "height": video.get("height") if video else None,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
    }


def audio_streams(info: dict) -> list[dict]:
    return [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]


def choose_audio_stream(info: dict) -> dict | None:
    """Faixa de áudio em inglês, se houver; senão a padrão; senão a primeira."""
    streams = audio_streams(info)
    for s in streams:
        if _lang(s) in ENGLISH_TAGS:
            return s
    for s in streams:
        if (s.get("disposition") or {}).get("default"):
            return s
    return streams[0] if streams else None


def subtitle_streams(info: dict) -> list[dict]:
    """Legendas em texto embutidas, com o idioma declarado (bitmap como PGS não é aproveitável)."""
    return [
        {"index": s["index"], "language": _lang(s), "codec": s.get("codec_name"),
         "title": (s.get("tags") or {}).get("title", "")}
        for s in info.get("streams", [])
        if s.get("codec_type") == "subtitle" and s.get("codec_name") in TEXT_SUBTITLE_CODECS
    ]


def playback_plan(path: Path, info: dict) -> str:
    """'original' (toca como está), 'remux' (só troca o contêiner/áudio) ou 'transcode'."""
    ext = path.suffix.lower().lstrip(".")
    summary = summarize(info)
    vcodec, acodec = summary["video_codec"], summary["audio_codec"]
    chosen = choose_audio_stream(info)
    streams = audio_streams(info)
    default_audio_ok = not streams or chosen is streams[0]  # o navegador toca a primeira faixa
    allowed = PLAYABLE.get(ext)
    if allowed and vcodec in allowed[0] and (acodec is None or acodec in allowed[1]) and default_audio_ok:
        return "original"
    if vcodec == "h264":
        return "remux"
    return "transcode"


def thumbnail(src: Path, dest: Path, duration: float | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    at = min(max((duration or 0) * 0.1, 0), 60)
    _run([_tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1",
          "-vf", "scale=480:-2", "-q:v", "4", str(dest)], timeout=120)
    if not dest.exists():  # vídeo curtíssimo: tenta o primeiro quadro
        _run([_tool("ffmpeg"), "-y", "-v", "error", "-i", str(src), "-frames:v", "1", "-vf", "scale=480:-2",
              str(dest)], timeout=120)


def extract_subtitle(src: Path, stream_index: int, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run([_tool("ffmpeg"), "-y", "-v", "error", "-i", str(src), "-map", f"0:{stream_index}", "-f", "srt", str(dest)],
         timeout=600)


def extract_audio(src: Path, dest: Path, stream_index: int | None) -> None:
    """WAV mono 16 kHz, o formato que o Whisper usa internamente."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    mapping = ["-map", f"0:{stream_index}"] if stream_index is not None else []
    _run([_tool("ffmpeg"), "-y", "-v", "error", "-i", str(src), *mapping, "-vn", "-ac", "1", "-ar", "16000",
          "-c:a", "pcm_s16le", str(dest)], timeout=3600)


def convert_for_playback(src: Path, dest: Path, info: dict, plan: str,
                         on_progress: Callable[[float], None] | None = None) -> None:
    """Gera um MP4 (H.264 + AAC) que toca no navegador. O original nunca é alterado."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.mp4")
    audio = choose_audio_stream(info)
    summary = summarize(info)
    args = [_tool("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", str(src),
            "-map", "0:v:0"]
    if audio:
        args += ["-map", f"0:{audio['index']}"]
    if plan == "remux":
        args += ["-c:v", "copy"]
    else:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "copy"] if summary["audio_codec"] in {"aac", "mp3"} else ["-c:a", "aac", "-b:a", "160k", "-ac", "2"]
    args += ["-sn", "-dn", "-movflags", "+faststart", str(tmp)]

    duration = summary["duration"] or 0
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW,
                            encoding="utf-8", errors="replace")
    assert proc.stdout is not None
    for line in proc.stdout:
        m = re.match(r"out_time_us=(\d+)", line.strip())
        if m and duration and on_progress:
            on_progress(min(int(m.group(1)) / 1e6 / duration, 1.0))
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        tmp.unlink(missing_ok=True)
        raise MediaError(f"Falha ao converter o vídeo: {' '.join(stderr.strip().splitlines()[-3:])}")
    tmp.replace(dest)
