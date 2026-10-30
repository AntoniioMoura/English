"""Leitura de legendas SRT/VTT, busca de arquivos externos e alinhamento de traduções."""

import re
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg import ENGLISH_TAGS, PORTUGUESE_TAGS

SUBTITLE_EXTS = (".srt", ".vtt")
TIME_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
ARROW_RE = re.compile(rf"({TIME_RE.pattern})\s*-->\s*({TIME_RE.pattern})")
TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")


@dataclass
class Cue:
    start: float
    end: float
    text: str


def _seconds(match: re.Match, offset: int) -> float:
    h, m, s, ms = (match.group(offset + i) for i in range(4))
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse(content: str) -> list[Cue]:
    """SRT e WebVTT. Tags (<i>, {\\an8}) saem; quebras de linha viram espaço; o texto não é reescrito."""
    content = content.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", content):
        lines = block.strip("\n").split("\n")
        for i, line in enumerate(lines):
            m = ARROW_RE.search(line)
            if not m:
                continue
            start, end = _seconds(m, 2), _seconds(m, 7)
            text = " ".join(TAG_RE.sub("", t).strip() for t in lines[i + 1:])
            text = re.sub(r"\s+", " ", text).strip()
            if text and end > start:
                cues.append(Cue(start, end, text))
            break
    cues.sort(key=lambda c: c.start)
    return cues


def read(path: Path) -> list[Cue]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return parse(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    return []


def language_of(video: Path, sub: Path) -> str:
    """Idioma pelo sufixo: `ep.en.srt` → 'en'; `ep.pt-BR.vtt` → 'pt'; `ep.srt` → '' (desconhecido)."""
    middle = sub.name[len(video.stem):-len(sub.suffix)].strip(".").lower()
    tags = set(re.split(r"[._\s]+", middle)) | {middle}
    if tags & ENGLISH_TAGS or any(t.startswith("en-") for t in tags):
        return "en"
    if tags & PORTUGUESE_TAGS or any(t.startswith("pt") for t in tags):
        return "pt"
    return "" if not middle else "other"


def external_files(video: Path) -> list[tuple[str, Path]]:
    """Legendas na mesma pasta com o mesmo nome-base do vídeo, com o idioma de cada uma."""
    found = []
    for sub in sorted(video.parent.iterdir()):
        if sub.suffix.lower() not in SUBTITLE_EXTS:
            continue
        if sub.stem == video.stem or sub.name.startswith(video.stem + "."):
            found.append((language_of(video, sub), sub))
    return found


def align_translation(segments: list[Cue], translation: list[Cue]) -> list[str | None]:
    """Para cada trecho em inglês, junta as falas traduzidas que acontecem (majoritariamente) nele."""
    result: list[str | None] = []
    for seg in segments:
        texts = []
        for cue in translation:
            overlap = min(seg.end, cue.end) - max(seg.start, cue.start)
            if overlap > 0 and overlap >= 0.5 * min(cue.end - cue.start, seg.end - seg.start):
                texts.append(cue.text)
        result.append(" ".join(texts) or None)
    return result


def to_srt(cues: list[Cue]) -> str:
    def stamp(t: float) -> str:
        ms = round(t * 1000)
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"

    return "\n".join(f"{i}\n{stamp(c.start)} --> {stamp(c.end)}\n{c.text}\n" for i, c in enumerate(cues, 1))
