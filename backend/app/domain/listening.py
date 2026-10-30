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


# ---------- quais palavras podem virar lacuna ----------

# Hesitações: o Whisper costuma omiti-las mesmo quando são faladas, então não contam como "não ouvidas".
FILLERS = frozenset("uh um uhm umm oh ah er erm hmm mm mhm huh".split())
# Nomes comuns que vale a pena praticar mesmo com maiúscula.
USEFUL_CAPITALIZED = frozenset(
    "i i'm i'll i've i'd monday tuesday wednesday thursday friday saturday sunday january february march april "
    "may june july august september october november december christmas god english american british "
    "korean japanese chinese thai french spanish italian german portuguese brazilian mexican canadian "
    "australian indian african european asian".split()
)
CONTRACTION_ENDINGS = ("'ll", "'re", "'ve", "'d", "'m", "n't")  # We'll no começo de uma linha da legenda
SENTENCE_END = re.compile(r"[.!?:;\"“”\-–—♪]\s*$")


def proper_names(texts: list[str]) -> set[str]:
    """Nomes e termos de nicho do vídeo (Lilies, BLINKs, SaWaDiKa): não viram lacuna.

    - maiúsculas misturadas no meio da palavra (BLINKs, SaWaDiKa) ou palavra toda em maiúsculas;
    - com inicial maiúscula fora do começo da frase e nunca escrita em minúscula no vídeo.
    """
    capitalized_mid: set[str] = set()
    lowercase: set[str] = set()
    names: set[str] = set()
    for text in texts:
        pos = 0
        for p in split_parts(text):
            if p.word_index is None:
                pos += len(p.text)
                continue
            word, norm = p.text, normalize_word(p.text)
            before = text[:pos]
            initial = not before.strip() or SENTENCE_END.search(before) is not None
            pos += len(word)
            if not p.eligible or norm in USEFUL_CAPITALIZED or norm.endswith(CONTRACTION_ENDINGS):
                continue  # [CROWD CHEERS] e números não dizem nada sobre nomes
            letters = [ch for ch in word if ch.isalpha()]
            if (len(letters) > 1 and all(ch.isupper() for ch in letters)) or any(ch.isupper() for ch in word[1:]):
                names.add(norm)
            elif word[0].isupper():
                if not initial:
                    capitalized_mid.add(norm)
            else:
                lowercase.add(norm)
    return names | (capitalized_mid - lowercase)


def hideable_words(text: str, names: set[str], word_audio: list[str | None] | None = None) -> set[int]:
    """Índices das palavras que podem virar lacuna: palavras de verdade, ouvidas no áudio, que não são nomes."""
    allowed = set()
    for p in split_parts(text):
        if not p.eligible or normalize_word(p.text) in names:
            continue
        status = word_audio[p.word_index] if word_audio and p.word_index < len(word_audio) else None
        if status in (None, "heard"):
            allowed.add(p.word_index)
    return allowed


def unheard_ratio(text: str, word_audio: list[str | None] | None) -> float:
    """Parte das palavras da legenda que não aparece no áudio (legenda "arrumada" por quem a escreveu)."""
    if not word_audio:
        return 0.0
    eligible = [p for p in split_parts(text) if p.eligible]
    if not eligible:
        return 0.0
    missing = sum(1 for p in eligible if p.word_index < len(word_audio) and word_audio[p.word_index] == "unheard")
    return missing / len(eligible)


def choose_blanks(
    text: str,
    difficulty: str,
    rng: random.Random,
    difficulty_by_word: dict[str, float] | None = None,
    focus_words: set[str] | None = None,
    allowed: set[int] | None = None,
) -> list[int]:
    """Escolhe os índices das palavras ocultas.

    - `difficulty_by_word`: taxa de erro histórica (0–1) por palavra normalizada; aumenta a chance
      de a palavra ser escolhida, mas é um peso, não uma regra — as lacunas continuam variando.
    - `focus_words`: na revisão, as palavras erradas antes são ocultadas primeiro.
    - `allowed`: só estes índices podem virar lacuna (ver `hideable_words`).
    """
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"Dificuldade desconhecida: {difficulty}")
    candidates = [p for p in split_parts(text) if p.eligible and (allowed is None or p.word_index in allowed)]
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


# ---------- frases-exercício ----------

INTERVALS = (0, 15, 30, 60)  # segundos entre frases-exercício; 0 = todas as frases
MIN_EXERCISE_WORDS = 3


MAX_UNHEARD = 0.25  # acima disso a legenda não é a fala literal: a frase não vira exercício


def _line_score(seg: dict) -> float:
    """Frases de tamanho médio, com palavras de verdade e fiéis ao áudio, são os melhores exercícios.

    `seg` pode trazer `allowed` (índices que podem virar lacuna) e `word_audio`.
    """
    allowed = seg.get("allowed")
    n = len(allowed) if allowed is not None else sum(1 for p in split_parts(seg["text"]) if p.eligible)
    if n < MIN_EXERCISE_WORDS or unheard_ratio(seg["text"], seg.get("word_audio")) > MAX_UNHEARD:
        return 0.0
    return min(n, 12) - max(0, n - 20) * 0.5


def select_exercise_lines(segments: list[dict], interval: int) -> list[int]:
    """Escolhe as falas que viram exercício: a melhor de cada janela de `interval` segundos do vídeo.

    Determinístico (mesmas falas → mesma escolha). Entre dois exercícios fica pelo menos meio
    intervalo de vídeo corrido. Com `interval` 0, toda fala com palavra para completar vira exercício.
    """
    if interval <= 0:
        def has_words(s: dict) -> bool:
            if s.get("allowed") is not None:
                return bool(s["allowed"])
            return any(p.eligible for p in split_parts(s["text"]))

        return [s["id"] for s in segments if has_words(s)]
    windows: dict[int, list[dict]] = {}
    for seg in segments:
        if _line_score(seg) > 0:
            windows.setdefault(int(seg["start"] // interval), []).append(seg)
    chosen: list[int] = []
    last_end = float("-inf")
    for key in sorted(windows):
        options = [s for s in windows[key] if s["start"] >= last_end + interval / 2]
        if options:
            best = max(options, key=lambda s: (_line_score(s), -s["start"]))
            chosen.append(best["id"])
            last_end = best["end"]
    return chosen
