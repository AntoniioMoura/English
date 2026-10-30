"""Transcrição local do áudio em inglês com faster-whisper (dependência opcional).

O modelo fica carregado no processo depois do primeiro uso. Tenta a GPU (CUDA, float16) e cai
para CPU (int8) se ela não estiver disponível — inclusive quando a falha só aparece durante a
transcrição (DLL do CUDA ausente, GPU sem suporte).
"""

import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from .subtitles import Cue

_lock = threading.Lock()
_models: dict[tuple[str, str], object] = {}
_broken_devices: set[str] = set()


class TranscriptionError(Exception):
    pass


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def _register_cuda_dlls() -> None:
    """No Windows, as DLLs dos pacotes pip nvidia-cublas-cu12/nvidia-cudnn-cu12 não estão no PATH."""
    if os.name != "nt":
        return
    for base in map(Path, sys.path):
        nvidia = base / "nvidia"
        if nvidia.is_dir():
            for bin_dir in nvidia.glob("*/bin"):
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def _devices(device: str) -> list[tuple[str, str]]:
    options = [("cuda", "float16"), ("cpu", "int8")] if device == "auto" else [
        (device, "float16" if device == "cuda" else "int8")]
    return [o for o in options if o[0] not in _broken_devices] or options[-1:]


def _load(model_name: str, dev: str, compute: str):
    from faster_whisper import WhisperModel

    key = (model_name, dev)
    if key not in _models:
        if dev == "cuda":
            _register_cuda_dlls()
        _models[key] = WhisperModel(model_name, device=dev, compute_type=compute)
    return _models[key]


def _read_wav(path: Path):
    """WAV PCM 16 bits mono 16 kHz (gerado pelo FFmpeg) → float32. Evita o decodificador do PyAV."""
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() != 16000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise TranscriptionError("Áudio extraído em formato inesperado.")
        data = wav.readframes(wav.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def _run(model, samples, total: float, on_progress: Callable[[float], None] | None) -> list[Cue]:
    segments, _info = model.transcribe(samples, language="en", vad_filter=True, beam_size=5,
                                       condition_on_previous_text=False, word_timestamps=True)
    cues = []
    for seg in segments:  # gerador: a transcrição acontece durante a iteração
        text = seg.text.strip()
        if text:
            spoken = [(w.word.strip(), float(w.start), float(w.end)) for w in seg.words or []]
            cues.append(Cue(float(seg.start), float(seg.end), text, spoken))
        if on_progress and total:
            on_progress(min(seg.end / total, 1.0))
    return cues


def transcribe(audio: Path, duration: float | None, model_name: str, device: str = "auto",
               on_progress: Callable[[float], None] | None = None) -> list[Cue]:
    if not available():
        raise TranscriptionError(
            "Transcrição local indisponível: instale com `backend\\.venv\\Scripts\\pip install faster-whisper` "
            "ou coloque uma legenda .en.srt ao lado do vídeo."
        )
    samples = _read_wav(audio)
    total = duration or len(samples) / 16000
    last_error: Exception | None = None
    with _lock:  # um modelo grande por vez na GPU
        for dev, compute in _devices(device):
            try:
                return _run(_load(model_name, dev, compute), samples, total, on_progress)
            except Exception as exc:
                last_error = exc
                _models.pop((model_name, dev), None)
                if dev == "cuda":
                    _broken_devices.add("cuda")  # não tenta a GPU de novo até reiniciar o servidor
    raise TranscriptionError(f"Falha na transcrição com o modelo '{model_name}': {last_error}")
