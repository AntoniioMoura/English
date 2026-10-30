"""Fluxo do Listening: catálogo → preparação → sessão (lacunas por dificuldade) → tentativas → painel.

As lacunas são gravadas na sessão e reaproveitadas nas próximas do mesmo vídeo e dificuldade; trocar de
dificuldade escolhe outras, sem tocar nos trechos processados. Erros contam na conferência, nunca por tecla.
"""

import json
import random
import sqlite3
from pathlib import Path

from ..db import transaction, utcnow
from ..domain import listening as rules
from ..domain.rules import RuleViolation
from ..media import ffmpeg, transcriber, youtube
from ..repositories import listening as repo
from . import listening_downloads
from . import listening_media as media
from .exercise_service import NotFound

DIFFICULTY_LABELS = {"beginner": "Iniciante", "easy": "Fácil", "medium": "Médio", "hard": "Difícil"}


def _require_video(conn: sqlite3.Connection, video_id: int) -> dict:
    video = repo.get_video(conn, video_id)
    if not video:
        raise NotFound("Vídeo não encontrado.")
    return video


def _require_session(conn: sqlite3.Connection, session_id: int) -> dict:
    session = repo.get_session(conn, session_id)
    if not session:
        raise NotFound("Sessão não encontrada.")
    return session


def _require_item(conn: sqlite3.Connection, session: dict, item_id: int) -> dict:
    item = repo.get_item(conn, item_id)
    if not item or item["session_id"] != session["id"]:
        raise NotFound("Trecho não encontrado nesta sessão.")
    return item


def display_title(video: dict) -> str:
    return video["title"] or Path(video["rel_path"]).stem.replace("_", " ").strip()


# ---------- catálogo ----------

def video_summary(video: dict, worker: "media.ListeningWorker | None" = None, sessions: list[dict] | None = None,
                  stats: dict | None = None) -> dict:
    status = media.effective_status(video)
    if worker and status != "processing" and worker.is_queued("prepare", video["id"]):
        status = "processing"
    return {
        "id": video["id"],
        "title": display_title(video),
        "file_name": Path(video["rel_path"]).name,
        "rel_path": video["rel_path"],
        "category": video["category"],
        "present": bool(video["present"]),
        "duration": video["duration"],
        "width": video["width"],
        "height": video["height"],
        "has_thumbnail": bool(video["thumbnail_path"]),
        "metadata_ready": video["meta_fingerprint"] == video["fingerprint"],
        "status": status,
        "stage": video["stage"] if status == "processing" else None,
        "progress": video["progress"] if status == "processing" else None,
        "error_message": video["error_message"] if status == "error" else None,
        "subtitle_source": video["subtitle_source"] if status == "ready" else None,
        "has_translation": bool(video["translation_source"]) and status == "ready",
        "converted": bool(video["playback_path"]),
        "updated_at": video["updated_at"],
        "active_sessions": [
            {"id": s["id"], "difficulty": s["difficulty"], "mode": s["mode"], "interval_seconds": s["interval_seconds"],
             "done": s["done"], "total": s["total"],
             "updated_at": s["updated_at"]}
            for s in (sessions or [])
        ],
        "study": stats or {"items_done": 0, "attempts": 0, "accuracy": None, "last_studied_at": None},
    }


def _study_by_video(conn: sqlite3.Connection) -> dict[int, dict]:
    rows = conn.execute(
        """SELECT s.video_id,
                  (SELECT COUNT(*) FROM listening_session_items i JOIN listening_sessions s2 ON s2.id = i.session_id
                     WHERE s2.video_id = s.video_id AND i.status = 'done') AS items_done,
                  (SELECT COUNT(*) FROM listening_word_attempts a WHERE a.video_id = s.video_id) AS attempts,
                  (SELECT SUM(a.is_correct) FROM listening_word_attempts a WHERE a.video_id = s.video_id) AS correct,
                  MAX(s.updated_at) AS last_studied_at
           FROM listening_sessions s GROUP BY s.video_id""")
    return {
        r["video_id"]: {"items_done": r["items_done"], "attempts": r["attempts"],
                        "accuracy": (r["correct"] or 0) / r["attempts"] if r["attempts"] else None,
                        "last_studied_at": r["last_studied_at"]}
        for r in rows
    }


def library(conn: sqlite3.Connection, worker: "media.ListeningWorker", videos_dir: Path) -> dict:
    by_video: dict[int, list[dict]] = {}
    for s in repo.active_sessions(conn):
        by_video.setdefault(s["video_id"], []).append(s)
    study = _study_by_video(conn)
    videos = [video_summary(v, worker, by_video.get(v["id"]), study.get(v["id"])) for v in repo.list_videos(conn)]
    continue_ids = [s["video_id"] for s in repo.active_sessions(conn)]
    seen: list[int] = []
    for vid in continue_ids:
        if vid not in seen:
            seen.append(vid)
    return {
        "videos_dir": str(videos_dir),
        "tools": {
            "ffmpeg": ffmpeg.available(),
            "transcriber": transcriber.available(),
            "youtube": youtube.available(),
        },
        "downloads": listening_downloads.list_downloads(conn, limit=8),
        "videos": videos,
        "continue_watching": seen[:12],
    }


def refresh_library(conn: sqlite3.Connection, worker: "media.ListeningWorker", videos_dir: Path) -> dict:
    changes = media.scan(conn, videos_dir)
    if ffmpeg.available():
        for video in repo.list_videos(conn):
            if media.needs_metadata(video):
                worker.submit("meta", video["id"])
    return {**library(conn, worker, videos_dir), "changes": changes}


def rename_video(conn: sqlite3.Connection, video_id: int, title: str | None) -> dict:
    _require_video(conn, video_id)
    title = (title or "").strip() or None
    with transaction(conn):
        repo.update_video(conn, video_id, {"title": title})
    return video_summary(_require_video(conn, video_id))


def prepare_video(conn: sqlite3.Connection, worker: "media.ListeningWorker", video_id: int,
                  force: bool = False) -> dict:
    """Pronto e válido → nada a fazer (não reprocessa). Senão, entra na fila de preparação."""
    video = _require_video(conn, video_id)
    if not video["present"]:
        raise RuleViolation("missing_file", "O arquivo deste vídeo não está mais na pasta videos/.")
    if not ffmpeg.available():
        raise RuleViolation("ffmpeg_missing", "FFmpeg não encontrado. Instale com `winget install Gyan.FFmpeg`.", 503)
    if media.is_prepared(video) and not force:
        return video_summary(video, worker)
    if video["status"] != "processing":
        with transaction(conn):
            repo.update_video(conn, video_id, {"status": "processing", "stage": "Na fila", "progress": 0,
                                               "error_message": None})
    worker.submit("prepare", video_id)
    return video_summary(_require_video(conn, video_id), worker)


def video_detail(conn: sqlite3.Connection, worker: "media.ListeningWorker", video_id: int) -> dict:
    video = _require_video(conn, video_id)
    summary = video_summary(video, worker, repo.active_sessions(conn, video_id), _study_by_video(conn).get(video_id))
    segments = repo.active_segments(conn, video_id) if media.is_prepared(video) else []
    summary["segment_count"] = len(segments)
    summary["review_count"] = len(_segments_to_review(conn, video_id)) if segments else 0
    return summary


def media_file(conn: sqlite3.Connection, videos_dir: Path, video_id: int) -> Path:
    video = _require_video(conn, video_id)
    if video["playback_path"] and media.is_prepared(video):
        path = Path(video["playback_path"])
    else:
        path = media.video_path(videos_dir, video)
    if not path.is_file():
        raise NotFound("Arquivo de vídeo não encontrado.")
    return path


def thumbnail_file(conn: sqlite3.Connection, video_id: int) -> Path:
    video = _require_video(conn, video_id)
    if not video["thumbnail_path"] or not Path(video["thumbnail_path"]).is_file():
        raise NotFound("Miniatura indisponível.")
    return Path(video["thumbnail_path"])


# ---------- trechos (correção manual) ----------

def segments(conn: sqlite3.Connection, video_id: int) -> list[dict]:
    _require_video(conn, video_id)
    return [_segment_out(s) for s in repo.active_segments(conn, video_id)]


def _segment_out(s: dict) -> dict:
    return {k: s[k] for k in ("id", "idx", "start", "end", "text", "translation_pt", "original_text", "edited")} | {
        "edited": bool(s["edited"]), "flagged": bool(s["flagged"])}


def update_segment(conn: sqlite3.Connection, segment_id: int, changes: dict) -> dict:
    segment = repo.get_segment(conn, segment_id)
    if not segment or not segment["active"]:
        raise NotFound("Trecho não encontrado.")
    fields = {k: v for k, v in changes.items() if v is not None or k == "translation_pt"}
    if "text" in fields:
        fields["text"] = " ".join(fields["text"].split())
        if not fields["text"]:
            raise RuleViolation("empty_text", "O texto do trecho não pode ficar vazio.", 422)
    start = fields.get("start", segment["start"])
    end = fields.get("end", segment["end"])
    if start < 0 or end <= start:
        raise RuleViolation("invalid_time", "O fim do trecho precisa ser depois do início.", 422)
    if "translation_pt" in fields:
        fields["translation_pt"] = (fields["translation_pt"] or "").strip() or None
    if "flagged" in fields:
        fields["flagged"] = int(bool(fields["flagged"]))
    changed_text = "text" in fields and fields["text"] != segment["text"]
    if changed_text:
        fields["word_audio"] = None  # corrigido por você: o texto passa a ser a referência
    if any(fields.get(k, segment[k]) != segment[k] for k in ("text", "start", "end")):
        fields["edited"] = 1
        fields.setdefault("flagged", 0)  # corrigido: deixa de estar sinalizado
    with transaction(conn):
        repo.update_segment(conn, segment_id, fields)
        if changed_text:
            _refresh_pending_items(conn, segment_id, fields["text"])
    return _segment_out(repo.get_segment(conn, segment_id))


def _refresh_pending_items(conn: sqlite3.Connection, segment_id: int, text: str) -> None:
    """Sessões em andamento sem tentativa neste trecho passam a usar o texto corrigido."""
    rows = conn.execute(
        """SELECT i.id, s.video_id, s.difficulty FROM listening_session_items i
           JOIN listening_sessions s ON s.id = i.session_id
           WHERE i.segment_id = ? AND i.status = 'pending' AND s.status = 'active'
             AND NOT EXISTS (SELECT 1 FROM listening_word_attempts a WHERE a.item_id = i.id)""", (segment_id,))
    for r in rows.fetchall():
        allowed = rules.hideable_words(text, _names(conn, r["video_id"]))
        blanks = rules.choose_blanks(text, r["difficulty"], _segment_rng(r["video_id"], r["difficulty"], segment_id),
                                     allowed=allowed)
        repo.update_item(conn, r["id"], {"text_snapshot": text, "blanks": blanks})


# ---------- palavras que contam ----------

def _names(conn: sqlite3.Connection, video_id: int) -> set[str]:
    """Nomes e termos de nicho do vídeo (Lilies, BLINKs): nunca viram lacuna nem erro para revisar."""
    return rules.proper_names([s["text"] for s in repo.active_segments(conn, video_id)])


def _word_audio(raw: str | None) -> list[str | None] | None:
    return json.loads(raw) if raw else None


def _allowed(segment: dict, names: set[str]) -> set[int]:
    return rules.hideable_words(segment["text"], names, _word_audio(segment.get("word_audio")))


class _WordFilter:
    """Decide se uma tentativa registrada conta no histórico (nomes e palavras não faladas não contam)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.names: dict[int, set[str]] = {}
        self.allowed: dict[tuple[int, str], set[int]] = {}

    def counts(self, attempt: dict, segment_text: str, word_audio: str | None) -> bool:
        vid = attempt["video_id"]
        if vid not in self.names:
            self.names[vid] = _names(self.conn, vid)
        key = (attempt["segment_id"], attempt["segment_text"])
        if key not in self.allowed:
            audio = _word_audio(word_audio) if segment_text == attempt["segment_text"] else None
            self.allowed[key] = rules.hideable_words(attempt["segment_text"], self.names[vid], audio)
        return attempt["word_index"] in self.allowed[key]


# ---------- sessões ----------

def _segment_rng(video_id: int, difficulty: str, segment_id: int) -> random.Random:
    """Sorteio estável: a mesma fala, no mesmo vídeo e dificuldade, sempre esconde as mesmas palavras."""
    return random.Random(f"{video_id}:{difficulty}:{segment_id}")


def _segments_to_review(conn: sqlite3.Connection, video_id: int) -> dict[int, set[str]]:
    """Trechos cuja última conclusão teve erro ou ajuda → palavras a focar na revisão."""
    rows = conn.execute(
        """SELECT i.id, i.segment_id, g.text, g.word_audio FROM listening_session_items i
           JOIN listening_sessions s ON s.id = i.session_id
           JOIN listening_segments g ON g.id = i.segment_id
           WHERE s.video_id = ? AND g.active = 1 AND i.status = 'done'
           ORDER BY i.completed_at, i.id""", (video_id,))
    last_item: dict[int, dict] = {}
    for r in rows:
        last_item[r["segment_id"]] = dict(r)
    words = _WordFilter(conn)
    result: dict[int, set[str]] = {}
    for segment_id, row in last_item.items():
        missed = {a["expected_norm"] for a in repo.attempts_for_item(conn, row["id"])
                  if not a["is_correct"] and words.counts(a, row["text"], row["word_audio"])}
        if missed:
            result[segment_id] = missed
    return result


def _previous_blanks(conn: sqlite3.Connection, video: dict, difficulty: str) -> dict[int, tuple[str, list[int]]]:
    """Lacunas já usadas neste vídeo e dificuldade (a sessão mais recente vence)."""
    rows = conn.execute(
        """SELECT i.segment_id, i.text_snapshot, i.blanks FROM listening_session_items i
           JOIN listening_sessions s ON s.id = i.session_id
           WHERE s.video_id = ? AND s.difficulty = ? AND s.mode = 'normal' AND s.processing_rev = ?
           ORDER BY s.id DESC""", (video["id"], difficulty, video["processing_rev"]))
    found: dict[int, tuple[str, list[int]]] = {}
    for r in rows:
        found.setdefault(r["segment_id"], (r["text_snapshot"], json.loads(r["blanks"])))
    return found


def start_session(conn: sqlite3.Connection, video_id: int, difficulty: str, mode: str = "normal",
                  restart: bool = False, interval: int = 30) -> dict:
    """Retoma a sessão ativa (mesma dificuldade e ritmo) ou cria uma nova.

    Só algumas falas viram exercício (uma a cada ~`interval` s); o resto do vídeo corre com a legenda.
    As lacunas são fixas: a primeira sessão de um vídeo numa dificuldade sorteia (com mais peso para as
    palavras que você já errou) e as seguintes reaproveitam a mesma escolha.
    """
    if difficulty not in rules.DIFFICULTIES:
        raise RuleViolation("invalid_difficulty", "Dificuldade inválida.", 422)
    if interval not in rules.INTERVALS:
        raise RuleViolation("invalid_interval", "Ritmo inválido.", 422)
    video = _require_video(conn, video_id)
    if not media.is_prepared(video):
        raise RuleViolation("not_ready", "O vídeo ainda não foi preparado.")
    if mode == "review":
        interval = 0  # a revisão toca só as falas erradas, uma após a outra
    existing = repo.find_active_session(conn, video_id, difficulty, mode)
    if existing and (existing["processing_rev"] != video["processing_rev"]
                     or existing["interval_seconds"] != interval):
        with transaction(conn):
            repo.update_session(conn, existing["id"], {"status": "abandoned"})
        existing = None
    if existing and not restart:
        return session_state(conn, existing["id"])

    focus = _segments_to_review(conn, video_id) if mode == "review" else {}
    names = _names(conn, video_id)
    segs = [{**s, "allowed": _allowed(s, names), "word_audio": _word_audio(s["word_audio"])}
            for s in repo.active_segments(conn, video_id) if not s["flagged"]]
    if mode == "review":
        segs = [s for s in segs if s["id"] in focus]
        if not segs:
            raise RuleViolation("nothing_to_review", "Nenhum trecho errado para revisar neste vídeo.")
    else:
        picked = set(rules.select_exercise_lines(segs, interval))
        segs = [s for s in segs if s["id"] in picked]
    history = repo.word_error_rates(conn)
    previous = _previous_blanks(conn, video, difficulty) if mode == "normal" else {}
    items = []
    for s in segs:
        reuse = previous.get(s["id"])
        if reuse and reuse[0] == s["text"] and set(reuse[1]) <= s["allowed"]:
            blanks = reuse[1]
        else:
            blanks = rules.choose_blanks(s["text"], difficulty, _segment_rng(video_id, difficulty, s["id"]),
                                         history, focus.get(s["id"]), allowed=s["allowed"])
        if blanks:  # trecho sem palavra adequada (só [MUSIC], números) não vira exercício
            items.append({"segment_id": s["id"], "text": s["text"], "blanks": blanks})
    if not items:
        raise RuleViolation("no_items", "Nenhum trecho deste vídeo tem palavras para completar.")
    with transaction(conn):
        if existing:
            repo.update_session(conn, existing["id"], {"status": "abandoned"})
        session_id = repo.insert_session(conn, {"video_id": video_id, "difficulty": difficulty, "mode": mode,
                                                "processing_rev": video["processing_rev"], "seed": 0,
                                                "interval_seconds": interval})
        repo.insert_items(conn, session_id, items)
    return session_state(conn, session_id)


def _blank_states(item: dict, attempts: list[dict]) -> list[dict]:
    word_list = rules.words(item["text_snapshot"])
    states = []
    for k, wi in enumerate(item["blanks"]):
        mine = [a for a in attempts if a["word_index"] == wi]
        if any(a["is_correct"] for a in mine):
            state = "correct"
        elif any(a["used_help"] for a in mine):
            state = "revealed"
        elif mine:
            state = "wrong"
        else:
            state = "hidden"
        typed = [a["typed"] for a in mine if a["typed"] is not None]
        states.append({
            "blank": k, "word_index": wi, "state": state, "length": len(word_list[wi]),
            "errors": sum(1 for a in mine if not a["is_correct"] and not a["used_help"]),
            "last_typed": typed[-1] if typed else None,
            "answer": word_list[wi] if state in ("correct", "revealed") or item["status"] == "skipped" else None,
            # o player confere letra a letra em tempo real; o servidor continua validando e registrando
            "expected": word_list[wi],
        })
    return states


def item_state(item: dict, attempts: list[dict]) -> dict:
    blanks = _blank_states(item, attempts)
    by_word = {b["word_index"]: b for b in blanks}
    finished = item["status"] != "pending"
    audio = _word_audio(item.get("word_audio")) if item["text_snapshot"] == item["segment_text"] else None
    parts = []
    for p in rules.split_parts(item["text_snapshot"]):
        b = by_word.get(p.word_index) if p.word_index is not None else None
        if b:
            parts.append({"text": b["answer"] if b["answer"] is not None else None, "blank": b["blank"]})
        else:
            unheard = bool(audio and p.word_index is not None and p.word_index < len(audio)
                           and audio[p.word_index] == "unheard")
            parts.append({"text": p.text, "blank": None, "unheard": unheard})
    return {
        "id": item["id"],
        "position": item["position"],
        "segment_id": item["segment_id"],
        "start": item["start"],
        "end": item["end"],
        "status": item["status"],
        "replays": item["replays"],
        "flagged": bool(item["flagged"]),
        "parts": parts,
        "blanks": blanks,
        "text": item["text_snapshot"] if finished else None,
        "translation_pt": item["translation_pt"],
    }


def session_state(conn: sqlite3.Connection, session_id: int) -> dict:
    session = _require_session(conn, session_id)
    video = _require_video(conn, session["video_id"])
    items = repo.session_items(conn, session_id)
    attempts = repo.attempts_for_session(conn, session_id)
    by_item: dict[int, list[dict]] = {}
    for a in attempts:
        by_item.setdefault(a["item_id"], []).append(a)
    return {
        "id": session["id"],
        "status": session["status"],
        "difficulty": session["difficulty"],
        "difficulty_label": DIFFICULTY_LABELS[session["difficulty"]],
        "mode": session["mode"],
        "current_index": min(session["current_index"], len(items) - 1),
        "started_at": session["started_at"],
        "interval_seconds": session["interval_seconds"],
        "video": {"id": video["id"], "title": display_title(video), "duration": video["duration"],
                  "has_translation": bool(video["translation_source"])},
        "stats": _session_stats(items, attempts),
        "items": [item_state(i, by_item.get(i["id"], [])) for i in items],
        "context": _context_lines(conn, session, items),
    }


def _context_lines(conn: sqlite3.Connection, session: dict, items: list[dict]) -> list[dict]:
    """Legenda completa das falas entre os exercícios (o vídeo corre com ela até a próxima lacuna).

    Falas que são exercício vão sem texto, para não entregarem a resposta.
    """
    if session["mode"] == "review":
        return []
    exercise = {i["segment_id"] for i in items}
    return [
        {"start": s["start"], "end": s["end"], "text": None if s["id"] in exercise else s["text"],
         "translation_pt": None if s["id"] in exercise else s["translation_pt"]}
        for s in repo.active_segments(conn, session["video_id"])
    ]


def _session_stats(items: list[dict], attempts: list[dict]) -> dict:
    correct = sum(a["is_correct"] for a in attempts)
    return {
        "total": len(items),
        "done": sum(1 for i in items if i["status"] == "done"),
        "skipped": sum(1 for i in items if i["status"] == "skipped"),
        "attempts": len(attempts),
        "correct": correct,
        "helped": sum(a["used_help"] for a in attempts),
        "accuracy": correct / len(attempts) if attempts else None,
        "replays": sum(i["replays"] for i in items),
    }


def _require_open(session: dict) -> None:
    if session["status"] != "active":
        raise RuleViolation("session_closed", "Esta sessão já foi encerrada.")


def _after_item_change(conn: sqlite3.Connection, session: dict, item: dict) -> dict:
    """Fecha o trecho quando todas as lacunas estão resolvidas; fecha a sessão quando não sobra trecho."""
    attempts = repo.attempts_for_item(conn, item["id"])
    blanks = _blank_states(item, attempts)
    with transaction(conn):
        if item["status"] == "pending" and all(b["state"] in ("correct", "revealed") for b in blanks):
            repo.update_item(conn, item["id"], {"status": "done", "completed_at": utcnow()})
        pending = conn.execute(
            "SELECT COUNT(*) FROM listening_session_items WHERE session_id = ? AND status = 'pending'",
            (session["id"],)).fetchone()[0]
        fields: dict = {}
        if pending == 0:
            fields = {"status": "finished", "finished_at": utcnow()}
        repo.update_session(conn, session["id"], fields)
    return _answer_state(conn, session["id"], item["id"])


def _answer_state(conn: sqlite3.Connection, session_id: int, item_id: int) -> dict:
    session = _require_session(conn, session_id)
    item = repo.get_item(conn, item_id)
    items = repo.session_items(conn, session_id)
    attempts = repo.attempts_for_session(conn, session_id)
    return {
        "item": item_state(item, [a for a in attempts if a["item_id"] == item_id]),
        "session": {"status": session["status"], "stats": _session_stats(items, attempts)},
    }


def _attempt_row(session: dict, item: dict, word_index: int, typed: str | None, correct: bool, helped: bool) -> dict:
    expected = rules.words(item["text_snapshot"])[word_index]
    return {
        "session_id": session["id"], "item_id": item["id"], "video_id": session["video_id"],
        "segment_id": item["segment_id"], "word_index": word_index, "expected": expected,
        "expected_norm": rules.normalize_word(expected), "typed": typed, "is_correct": int(correct),
        "used_help": int(helped), "replays": item["replays"], "segment_start": item["start"],
        "segment_text": item["text_snapshot"],
    }


def check_answers(conn: sqlite3.Connection, session_id: int, item_id: int, answers: list[str | None]) -> dict:
    """Confere as lacunas ainda abertas que foram preenchidas. Cada conferência é uma tentativa por lacuna."""
    session = _require_session(conn, session_id)
    _require_open(session)
    item = _require_item(conn, session, item_id)
    if item["status"] != "pending":
        raise RuleViolation("item_closed", "Este trecho já foi concluído.")
    blanks = _blank_states(item, repo.attempts_for_item(conn, item_id))
    word_list = rules.words(item["text_snapshot"])
    with transaction(conn):
        for b in blanks:
            typed = answers[b["blank"]] if b["blank"] < len(answers) else None
            if b["state"] in ("correct", "revealed") or not typed or not typed.strip():
                continue
            if b["state"] == "wrong" and rules.normalize_word(typed) == rules.normalize_word(b["last_typed"] or ""):
                continue  # mesma resposta errada de novo: não conta um segundo erro
            ok = rules.is_correct(word_list[b["word_index"]], typed)
            repo.insert_attempt(conn, _attempt_row(session, item, b["word_index"], typed.strip(), ok, False))
    return _after_item_change(conn, session, item)


def reveal(conn: sqlite3.Connection, session_id: int, item_id: int, blank: int | None) -> dict:
    """Mostra a palavra: fica registrado que ela precisou de ajuda (não conta como acerto)."""
    session = _require_session(conn, session_id)
    _require_open(session)
    item = _require_item(conn, session, item_id)
    if item["status"] != "pending":
        raise RuleViolation("item_closed", "Este trecho já foi concluído.")
    blanks = _blank_states(item, repo.attempts_for_item(conn, item_id))
    targets = [b for b in blanks if b["state"] not in ("correct", "revealed") and (blank is None or b["blank"] == blank)]
    with transaction(conn):
        for b in targets:
            repo.insert_attempt(conn, _attempt_row(session, item, b["word_index"], None, False, True))
    return _after_item_change(conn, session, item)


def replay(conn: sqlite3.Connection, session_id: int, item_id: int) -> dict:
    session = _require_session(conn, session_id)
    item = _require_item(conn, session, item_id)
    with transaction(conn):
        repo.update_item(conn, item_id, {"replays": item["replays"] + 1})
    return {"replays": item["replays"] + 1}


def skip(conn: sqlite3.Connection, session_id: int, item_id: int, mismatch: bool) -> dict:
    """Pula o trecho; com `mismatch`, sinaliza que a legenda não corresponde ao áudio (aparece no editor)."""
    session = _require_session(conn, session_id)
    _require_open(session)
    item = _require_item(conn, session, item_id)
    with transaction(conn):
        if item["status"] == "pending":
            repo.update_item(conn, item_id, {"status": "skipped", "completed_at": utcnow()})
        if mismatch:
            repo.update_segment(conn, item["segment_id"], {"flagged": 1})
    item = _require_item(conn, session, item_id)
    return _after_item_change(conn, session, item)


def set_position(conn: sqlite3.Connection, session_id: int, index: int) -> dict:
    session = _require_session(conn, session_id)
    total = conn.execute("SELECT COUNT(*) FROM listening_session_items WHERE session_id = ?",
                         (session_id,)).fetchone()[0]
    with transaction(conn):
        repo.update_session(conn, session_id, {"current_index": max(0, min(index, total - 1))})
    return {"current_index": max(0, min(index, total - 1))}


def finish_session(conn: sqlite3.Connection, session_id: int) -> dict:
    session = _require_session(conn, session_id)
    if session["status"] == "active":
        with transaction(conn):
            repo.update_session(conn, session_id, {"status": "finished", "finished_at": utcnow()})
    return session_state(conn, session_id)


# ---------- painel ----------

def stats(conn: sqlite3.Connection) -> dict:
    videos = {v["id"]: v for v in repo.list_videos(conn)}
    by_video_diff = []
    for r in conn.execute(
        """SELECT s.video_id, s.difficulty, COUNT(a.id) AS attempts, COALESCE(SUM(a.is_correct), 0) AS correct,
                  COALESCE(SUM(a.used_help), 0) AS helped
           FROM listening_sessions s JOIN listening_word_attempts a ON a.session_id = s.id
           GROUP BY s.video_id, s.difficulty ORDER BY s.video_id"""):
        by_video_diff.append({
            "video_id": r["video_id"], "title": display_title(videos[r["video_id"]]),
            "difficulty": r["difficulty"], "difficulty_label": DIFFICULTY_LABELS[r["difficulty"]],
            "attempts": r["attempts"], "correct": r["correct"], "helped": r["helped"],
            "accuracy": r["correct"] / r["attempts"] if r["attempts"] else None,
        })

    progress = []
    for vid, video in videos.items():
        done = conn.execute(
            """SELECT COUNT(DISTINCT i.segment_id) FROM listening_session_items i
               JOIN listening_sessions s ON s.id = i.session_id
               JOIN listening_segments g ON g.id = i.segment_id
               WHERE s.video_id = ? AND i.status = 'done' AND g.active = 1""", (vid,)).fetchone()[0]
        if not done and not conn.execute("SELECT 1 FROM listening_sessions WHERE video_id = ?", (vid,)).fetchone():
            continue
        total = conn.execute("SELECT COUNT(*) FROM listening_segments WHERE video_id = ? AND active = 1",
                             (vid,)).fetchone()[0]
        last = conn.execute(
            """SELECT s.id, s.difficulty, s.status, s.current_index, s.updated_at,
                      (SELECT COUNT(*) FROM listening_session_items i WHERE i.session_id = s.id) AS items
               FROM listening_sessions s WHERE s.video_id = ? ORDER BY s.updated_at DESC, s.id DESC LIMIT 1""",
            (vid,)).fetchone()
        stopped_at = None
        if last:
            row = conn.execute(
                """SELECT g.start FROM listening_session_items i JOIN listening_segments g ON g.id = i.segment_id
                   WHERE i.session_id = ? AND i.position = ?""", (last["id"], last["current_index"])).fetchone()
            stopped_at = {"session_id": last["id"], "difficulty": last["difficulty"], "status": last["status"],
                          "position": last["current_index"] + 1, "items": last["items"],
                          "time": row["start"] if row else None, "updated_at": last["updated_at"]}
        progress.append({"video_id": vid, "title": display_title(video), "segments_done": done,
                         "segments_total": total, "stopped_at": stopped_at,
                         "to_review": len(_segments_to_review(conn, vid)) if total else 0})

    word_filter = _WordFilter(conn)
    tally: dict[str, dict] = {}
    for r in conn.execute(
        """SELECT a.*, g.text AS current_text, g.word_audio FROM listening_word_attempts a
           JOIN listening_segments g ON g.id = a.segment_id"""):
        a = dict(r)
        if not word_filter.counts(a, a["current_text"], a["word_audio"]):
            continue
        t = tally.setdefault(a["expected_norm"], {"word": a["expected_norm"], "attempts": 0, "errors": 0, "helped": 0})
        t["attempts"] += 1
        t["errors"] += 0 if a["is_correct"] else 1
        t["helped"] += a["used_help"]
    words = sorted(
        ({**t, "error_rate": t["errors"] / t["attempts"]} for t in tally.values() if t["errors"]),
        key=lambda t: (-t["error_rate"], -t["errors"], t["word"]),
    )[:30]

    sessions = []
    for r in conn.execute(
        """SELECT s.*, (SELECT COUNT(*) FROM listening_session_items i WHERE i.session_id = s.id) AS items,
                  (SELECT COUNT(*) FROM listening_session_items i WHERE i.session_id = s.id AND i.status = 'done')
                      AS done,
                  (SELECT COALESCE(SUM(i.replays), 0) FROM listening_session_items i WHERE i.session_id = s.id)
                      AS replays,
                  (SELECT COUNT(*) FROM listening_word_attempts a WHERE a.session_id = s.id) AS attempts,
                  (SELECT COALESCE(SUM(a.is_correct), 0) FROM listening_word_attempts a WHERE a.session_id = s.id)
                      AS correct,
                  (SELECT COALESCE(SUM(a.used_help), 0) FROM listening_word_attempts a WHERE a.session_id = s.id)
                      AS helped
           FROM listening_sessions s
           WHERE EXISTS (SELECT 1 FROM listening_word_attempts a WHERE a.session_id = s.id)
           ORDER BY s.started_at DESC, s.id DESC LIMIT 50"""):
        sessions.append({
            "id": r["id"], "video_id": r["video_id"], "title": display_title(videos[r["video_id"]]),
            "difficulty": r["difficulty"], "difficulty_label": DIFFICULTY_LABELS[r["difficulty"]],
            "mode": r["mode"], "status": r["status"], "started_at": r["started_at"], "updated_at": r["updated_at"],
            "items": r["items"], "done": r["done"], "replays": r["replays"], "attempts": r["attempts"],
            "correct": r["correct"], "helped": r["helped"],
            "accuracy": r["correct"] / r["attempts"] if r["attempts"] else None,
        })

    totals = conn.execute(
        """SELECT COUNT(*) AS attempts, COALESCE(SUM(is_correct), 0) AS correct, COALESCE(SUM(used_help), 0) AS helped,
                  COUNT(DISTINCT item_id) AS items
           FROM listening_word_attempts""").fetchone()
    return {
        "totals": {"attempts": totals["attempts"], "correct": totals["correct"], "helped": totals["helped"],
                   "accuracy": totals["correct"] / totals["attempts"] if totals["attempts"] else None,
                   "segments_done": conn.execute(
                       "SELECT COUNT(*) FROM listening_session_items WHERE status = 'done'").fetchone()[0]},
        "by_video_difficulty": by_video_diff,
        "progress": progress,
        "words": words,
        "sessions": sessions,
    }
