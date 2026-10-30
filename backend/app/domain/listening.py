"""Regras do Listening: palavras de uma fala, lacunas por dificuldade e comparação de respostas.

Tudo aqui é determinístico e sem E/S. A seleção de lacunas depende só do texto, da dificuldade,
de uma semente e (opcionalmente) do histórico de erros; nunca altera os dados processados.
"""

import math
import random
import re
from dataclasses import dataclass

# Faixa de palavras ocultas por fala (o sorteio usa o meio da faixa).
DIFFICULTIES: dict[str, tuple[float, float]] = {
    "beginner": (0.10, 0.15),
    "easy": (0.25, 0.30),
    "medium": (0.40, 0.45),
    "hard": (0.60, 0.60),
}

# Palavras: letras/dígitos com apóstrofos internos (don't, rock'n'roll). Hífen separa palavras.
WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
# Descrições sonoras ([MUSIC], (laughs)) e notas musicais não viram lacunas.
SOUND_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|♪")
APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'"})

COMMON_ENGLISH = frozenset(
    "the a an and or but to of in on at for with is are was were be been it this that you i he she we they "
    "my your his her our their not do does did have has had will would can could what who when where why how "
    "there here so if just all me him them us no yes oh okay ok get got go going know like".split()
)


@dataclass(frozen=True)
class Part:
    """Pedaço da fala: uma palavra (candidata a lacuna) ou o texto entre palavras."""

    text: str
    word_index: int | None  # índice entre as palavras da fala; None = pontuação/espaço
    eligible: bool = False  # pode virar lacuna


def split_parts(text: str) -> list[Part]:
    parts: list[Part] = []
    sound_spans = [m.span() for m in SOUND_RE.finditer(text)]
    pos = 0
    word_index = 0
    for m in WORD_RE.finditer(text):
        if m.start() > pos:
            parts.append(Part(text[pos:m.start()], None))
        in_sound = any(a <= m.start() < b for a, b in sound_spans)
        word = m.group()
        eligible = not in_sound and any(ch.isalpha() for ch in word)  # números ("10" ou "ten"?) ficam visíveis
        parts.append(Part(word, word_index, eligible))
        word_index += 1
        pos = m.end()
    if pos < len(text):
        parts.append(Part(text[pos:], None))
    return parts


def words(text: str) -> list[str]:
    return [p.text for p in split_parts(text) if p.word_index is not None]


def normalize_word(value: str) -> str:
    """Ignora só maiúsculas, apóstrofo tipográfico e pontuação nas pontas. `dont` ≠ `don't`."""
    value = value.strip().translate(APOSTROPHES).lower()
    value = re.sub(r"^[^\w']+|[^\w']+$", "", value)
    return value.strip("'")


def is_correct(expected: str, typed: str) -> bool:
    typed_norm = normalize_word(typed)
    return bool(typed_norm) and typed_norm == normalize_word(expected)


def looks_english(texts: list[str]) -> bool:
    """Heurística para legendas sem idioma declarado: proporção de palavras muito comuns do inglês."""
    tokens = [normalize_word(w) for t in texts[:200] for w in words(t)]
    if len(tokens) < 8:
        return bool(tokens) and sum(t in COMMON_ENGLISH for t in tokens) >= len(tokens) / 3
    return sum(t in COMMON_ENGLISH for t in tokens) / len(tokens) >= 0.18


def blank_count(eligible: int, difficulty: str, rng: random.Random) -> int:
    """Quantidade de lacunas: meio da faixa, com arredondamento aleatório para a média bater no vídeo todo."""
    if eligible == 0:
        return 0
    low, high = DIFFICULTIES[difficulty]
    target = eligible * (low + high) / 2
    n = math.floor(target + rng.random())
    return max(1, min(eligible, n))


def choose_blanks(
    text: str,
    difficulty: str,
    rng: random.Random,
    difficulty_by_word: dict[str, float] | None = None,
    focus_words: set[str] | None = None,
) -> list[int]:
    """Escolhe os índices das palavras ocultas.

    - `difficulty_by_word`: taxa de erro histórica (0–1) por palavra normalizada; aumenta a chance
      de a palavra ser escolhida, mas é um peso, não uma regra — as lacunas continuam variando.
    - `focus_words`: na revisão, as palavras erradas antes são ocultadas primeiro.
    """
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"Dificuldade desconhecida: {difficulty}")
    candidates = [p for p in split_parts(text) if p.eligible]
    n = blank_count(len(candidates), difficulty, rng)
    if n == 0:
        return []
    history = difficulty_by_word or {}
    chosen: list[int] = []
    pool = list(candidates)
    if focus_words:
        focused = [p for p in pool if normalize_word(p.text) in focus_words]
        chosen = [p.word_index for p in focused][: max(n, len(focused))]
        pool = [p for p in pool if p.word_index not in chosen]
        n = max(0, n - len(chosen))
    for _ in range(n):
        weights = []
        for p in pool:
            base = 1.0 if len(p.text) >= 3 else 0.5  # "a", "I", "to" aparecem menos como lacuna
            weights.append(base * (1 + 3 * history.get(normalize_word(p.text), 0.0)))
        pick = rng.choices(range(len(pool)), weights=weights)[0]
        chosen.append(pool.pop(pick).word_index)
    return sorted(chosen)
