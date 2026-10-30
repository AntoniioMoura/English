"""Leitura de legendas SRT/VTT, busca de arquivos externos e alinhamento de traduções."""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from ..domain.listening import normalize_word, split_parts, words
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
    words: list[tuple[str, float, float]] | None = field(default=None, compare=False)  # só na transcrição


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


# Legendas (sobretudo as do YouTube) costumam entrar atrasadas e com atraso variável de fala para fala.
UNMATCHED_WORD = 0.3   # tempo estimado por palavra da legenda que o Whisper não reconheceu
LEAD_IN, TAIL = 0.1, 0.15
MAX_SHIFT = 10.0       # deslocamento maior que isso indica pareamento errado: fica o horário original


def align_to_words(cues: list[Cue], spoken: list[tuple[str, float, float]], min_match: float = 0.5) -> list[Cue]:
    """Ressincroniza cada fala pelos horários das palavras ditas no áudio (texto da legenda intacto).

    Pareia as palavras da legenda com as reconhecidas pelo Whisper (na ordem) e usa a primeira/última
    palavra pareada de cada fala como início/fim. Se menos de `min_match` das palavras parearem
    (legenda de outro corte, outro idioma…), devolve as falas como estavam.
    """
    tokens: list[str] = []
    ranges: list[tuple[int, int]] = []
    for cue in cues:
        first = len(tokens)
        # [MUSIC], (laughs): não são falados, não entram no pareamento
        tokens += [normalize_word(p.text) for p in split_parts(cue.text) if p.eligible]
        ranges.append((first, len(tokens)))
    heard = [normalize_word(w) for w, _, _ in spoken]
    if not tokens or not heard:
        return cues
    pairs: dict[int, int] = {}
    for a, b, size in SequenceMatcher(None, tokens, heard, autojunk=False).get_matching_blocks():
        pairs.update((a + k, b + k) for k in range(size))
    if len(pairs) < min_match * len(tokens):
        return cues

    aligned: list[Cue] = []
    for cue, (first, last) in zip(cues, ranges):
        matched = [i for i in range(first, last) if i in pairs]
        start, end = cue.start, cue.end
        if matched:
            new_start = spoken[pairs[matched[0]]][1] - UNMATCHED_WORD * (matched[0] - first)
            new_end = spoken[pairs[matched[-1]]][2] + UNMATCHED_WORD * (last - 1 - matched[-1])
            if abs(new_start - cue.start) <= MAX_SHIFT:
                start, end = max(new_start - LEAD_IN, 0.0), new_end + TAIL
        aligned.append(Cue(start, max(end, start + 0.3), cue.text))
    for cur, nxt in zip(aligned, aligned[1:]):  # não invade a fala seguinte
        if cur.start < nxt.start < cur.end:
            cur.end = max(nxt.start, cur.start + 0.3)
    return aligned
