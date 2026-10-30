"""Download de vídeos do YouTube com yt-dlp (dependência opcional).

Prefere H.264 + AAC em MP4 (toca no navegador sem conversão) e baixa só legendas feitas por pessoas
em inglês e português: as automáticas do YouTube vêm em "rolagem" (cada linha repete a anterior) e
viram exercícios ruins — sem legenda, a transcrição local com Whisper faz melhor.
"""

import re
import shutil
from collections.abc import Callable
from pathlib import Path

from . import ffmpeg

YOUTUBE_ID_RE = re.compile(
    r"^https?://(?:www\.|m\.|music\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/|v/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})(?:[?&#/].*)?$"
)
HEIGHTS = (360, 480, 720, 1080)


class DownloadError(Exception):
    pass


def available() -> bool:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


def video_id(url: str) -> str | None:
    match = YOUTUBE_ID_RE.match(url.strip())
    return match.group(1) if match else None


def canonical_url(youtube_id: str) -> str:
    return f"https://www.youtube.com/watch?v={youtube_id}"


def format_selector(max_height: int) -> str:
    h = max_height
    return (f"bv*[height<={h}][vcodec^=avc1]+ba[acodec^=mp4a]/b[height<={h}][vcodec^=avc1][acodec^=mp4a]"
            f"/bv*[height<={h}]+ba/b[height<={h}]/b")


class _QuietLogger:
    def debug(self, msg: str) -> None:
        pass

    info = warning = debug

    def error(self, msg: str) -> None:
        pass


def _clean_error(exc: Exception) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).replace("ERROR: ", "").strip()
    text = re.sub(r"^\[youtube\] [A-Za-z0-9_-]{11}: ", "", text)
    hint = " Se o erro persistir, atualize o yt-dlp: backend\\.venv\\Scripts\\pip install -U yt-dlp"
    return (text[:400] or "Falha no download.") + hint


def download(youtube_id: str, work_dir: Path, max_height: int,
             on_progress: Callable[[str, float], None] | None = None) -> dict:
    """Baixa para `work_dir` (pasta temporária). Devolve título e arquivos (vídeo + legendas)."""
    if not available():
        raise DownloadError("yt-dlp não está instalado: backend\\.venv\\Scripts\\pip install yt-dlp")
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError as YtDlpError

    ffmpeg_path = ffmpeg.find_tool("ffmpeg")
    if not ffmpeg_path:
        raise DownloadError("FFmpeg não encontrado (necessário para juntar vídeo e áudio).")

    # YouTube exige um runtime JavaScript; o yt-dlp usa o Deno por padrão, o Node também serve.
    runtimes = {name: {} for name in ("deno", "node") if shutil.which(name)}

    phases = {"video": (0.0, 0.8, "Baixando o vídeo"), "audio": (0.8, 0.96, "Baixando o áudio")}

    def hook(d: dict) -> None:
        if not on_progress or d.get("status") != "downloading":
            return
        info = d.get("info_dict") or {}
        if info.get("ext") in ("vtt", "srt", "srv3", "json3"):
            return
        kind = "audio" if info.get("vcodec") == "none" else "video"
        start, end, label = phases[kind]
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if total:
            on_progress(label, start + min(d.get("downloaded_bytes", 0) / total, 1) * (end - start))

    def post_hook(d: dict) -> None:
        if on_progress and d.get("status") == "started" and d.get("postprocessor") == "Merger":
            on_progress("Juntando vídeo e áudio", 0.97)

    opts = {
        "format": format_selector(max_height),
        "outtmpl": str(work_dir / "%(title).120B [%(id)s].%(ext)s"),
        "merge_output_format": "mp4",
        "writesubtitles": True,
        "writeautomaticsub": False,
        "subtitleslangs": ["en.*", "pt.*"],
        "subtitlesformat": "srt/vtt/best",
        "noplaylist": True,
        "windowsfilenames": True,
        "quiet": True,
        "noprogress": True,
        "logger": _QuietLogger(),
        "ffmpeg_location": str(Path(ffmpeg_path).parent),
        "progress_hooks": [hook],
        "postprocessor_hooks": [post_hook],
    }
    if runtimes:
        opts["js_runtimes"] = runtimes
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(canonical_url(youtube_id), download=False)
            if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
                raise DownloadError("Transmissões ao vivo não podem ser baixadas.")
            if on_progress:
                on_progress("Baixando o vídeo", 0.0)
            info = ydl.process_ie_result(info, download=True)
    except YtDlpError as exc:
        raise DownloadError(_clean_error(exc)) from exc

    files = [Path(r["filepath"]) for r in info.get("requested_downloads") or [] if r.get("filepath")]
    video = next((f for f in files if f.is_file()), None)
    if not video:
        raise DownloadError("O download terminou, mas o arquivo de vídeo não foi encontrado.")
    subtitles = [p for p in work_dir.iterdir() if p.suffix.lower() in (".srt", ".vtt") and p.stem.startswith(video.stem)]
    return {"title": info.get("title") or video.stem, "video": video, "subtitles": subtitles}
