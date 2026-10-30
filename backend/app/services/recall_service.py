"""Fluxo do Sentence Recall: palavras → frase pt-BR → tradução → avaliação → registro → próxima/revisão.

O backend controla cota, modos, tentativas e repetição espaçada. A IA só gera frases e avalia.
"""

import random
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..db import transaction
from ..domain import recall as rules
from ..domain.evaluation import IGNORED_TOPICS
from ..domain.rules import RuleViolation
from ..domain.scheduler import SchedulerState, scheduler
from ..domain.score import recall_score
from ..llm import recall_operations as ai
from ..llm.client import LLMClient, LLMError
from ..llm.schemas import RECALL_PROMPT_VERSION, RECALL_SCHEMA_VERSION
from ..repositories import frames as frames_repo
from ..repositories import recall as repo
from ..repositories import settings as settings_repo
from .exercise_service import NotFound

LIMIT_MESSAGE = "Limite diário atingido. Você ainda pode revisar seus erros."
MAX_EXAMPLES = 5


def now() -> datetime:
    """Relógio injetável (os testes simulam a virada do dia)."""
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------- configurações ----------

class RecallSettings(BaseModel):
    daily_error_limit: int = Field(default=10, ge=1, le=100)
    timezone: str = "America/Sao_Paulo"

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Fuso horário inválido.") from exc
        return v


def get_settings(conn: sqlite3.Connection) -> RecallSettings:
    return RecallSettings(**settings_repo.get_all(conn).get("recall", {}))


def save_settings(conn: sqlite3.Connection, changes: dict) -> RecallSettings:
    merged = RecallSettings(**{**get_settings(conn).model_dump(), **changes})
    settings_repo.set_many(conn, {"recall": merged.model_dump()})
    conn.commit()
    return merged


def local_today(conn: sqlite3.Connection) -> str:
    return now().astimezone(ZoneInfo(get_settings(conn).timezone)).date().isoformat()


def quota(conn: sqlite3.Connection) -> dict:
    limit = get_settings(conn).daily_error_limit
    errors = repo.quota_errors(conn, local_today(conn))
    return {"errors_today": errors, "limit": limit, "blocked": errors >= limit}


# ---------- vocabulário ----------

class VocabIn(BaseModel):
    english_text: str = Field(min_length=1, max_length=60)
    translation_pt: str | None = Field(default=None, max_length=80)
    part_of_speech: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=200)

    @field_validator("english_text")
    @classmethod
    def _english(cls, v: str) -> str:
        v = " ".join(v.split())
        if not any(c.isalpha() for c in v) or len(v.split()) > 5:
            raise ValueError("Use uma palavra ou expressão curta em inglês (até 5 palavras).")
        return v

    @field_validator("translation_pt", "part_of_speech", "notes")
    @classmethod
    def _optional(cls, v: str | None) -> str | None:
        v = " ".join((v or "").split())
        return v or None


def add_vocab(conn: sqlite3.Connection, entry: VocabIn) -> dict:
    normalized = rules.normalize_vocab(entry.english_text)
    if repo.find_duplicate(conn, normalized, entry.translation_pt, None):
        raise RuleViolation("duplicate", f"“{entry.english_text}” já está cadastrada com esse sentido.")
    with transaction(conn):
        vocab_id = repo.insert_vocab(conn, entry.model_dump(), normalized)
    return repo.get_vocab(conn, vocab_id)


def add_vocab_batch(conn: sqlite3.Connection, raw_entries: list[dict]) -> dict:
    """Cadastra várias palavras; duplicadas ou inválidas são puladas com o motivo, sem barrar as outras."""
    created, skipped, seen = [], [], set()
    for raw in raw_entries:
        text = str(raw.get("english_text", "")).strip()
        try:
            entry = VocabIn(**raw)
        except ValidationError as exc:
            reason = exc.errors()[0]["msg"].replace("Value error, ", "")
            skipped.append({"english_text": text, "reason": reason})
            continue
        key = (rules.normalize_vocab(entry.english_text), (entry.translation_pt or "").lower())
        if key in seen:
            skipped.append({"english_text": entry.english_text, "reason": "repetida na lista"})
            continue
        seen.add(key)
        try:
            created.append(add_vocab(conn, entry))
        except RuleViolation:
            skipped.append({"english_text": entry.english_text, "reason": "já cadastrada"})
    if not created and skipped and len(raw_entries) == 1:  # uma palavra só: erro direto, como antes
        duplicate = skipped[0]["reason"] == "já cadastrada"
        raise RuleViolation("duplicate" if duplicate else "invalid",
                            f"“{skipped[0]['english_text']}”: {skipped[0]['reason']}.", 409 if duplicate else 422)
    return {"created": created, "skipped": skipped}


def update_vocab(conn: sqlite3.Connection, vocab_id: int, changes: dict) -> dict:
    current = repo.get_vocab(conn, vocab_id)
    if not current:
        raise NotFound(f"Palavra {vocab_id} não encontrada.")
    fields = {k: v for k, v in changes.items() if k != "enabled"}
    if fields:
        merged = VocabIn(**{k: current[k] for k in ("english_text", "translation_pt", "part_of_speech", "notes")}
                         | fields)
        normalized = rules.normalize_vocab(merged.english_text)
        if repo.find_duplicate(conn, normalized, merged.translation_pt, vocab_id):
            raise RuleViolation("duplicate", f"“{merged.english_text}” já está cadastrada com esse sentido.")
        fields = {k: getattr(merged, k) for k in fields} | {"normalized_text": normalized}
    if "enabled" in changes:
        fields["enabled"] = bool(changes["enabled"])
    with transaction(conn):
        repo.update_vocab(conn, vocab_id, fields)
    return repo.get_vocab(conn, vocab_id)


def delete_vocab(conn: sqlite3.Connection, vocab_id: int) -> None:
    if not repo.get_vocab(conn, vocab_id):
        raise NotFound(f"Palavra {vocab_id} não encontrada.")
    with transaction(conn):
        repo.soft_delete_vocab(conn, vocab_id)


def choose_targets(conn: sqlite3.Connection) -> list[dict]:
    """Uma palavra por frase (foco claro e frases naturais), priorizando as menos praticadas
    e evitando as dos últimos exercícios. Devolve lista para manter o contrato da geração."""
    entries = repo.list_vocab(conn, only_enabled=True)
    if not entries:
        return []
    recent = repo.recently_used_vocab(conn)
    fresh = [e for e in entries if e["id"] not in recent] or entries
    fresh.sort(key=lambda e: (e["times_used"], random.random()))
    pool = fresh[: max(2, (len(fresh) + 1) // 2)]
    return [random.choice(pool)]


# ---------- exercícios ----------

def create_new_exercise(conn: sqlite3.Connection, llm: LLMClient) -> dict:
    if quota(conn)["blocked"]:
        raise RuleViolation("daily_limit", LIMIT_MESSAGE, 429)
    pending = repo.pending_exercise(conn, "new")
    if pending:  # recarregar a página não gera outra frase
        return get_state(conn, pending)
    entries = choose_targets(conn)
    if not entries:
        raise RuleViolation("no_vocabulary", "Cadastre algumas palavras em “Minhas palavras” para começar.", 422)
    data = ai.generate_recall_prompt(llm, entries, repo.recent_sentences(conn), frames_repo.topic_ids(conn))
    with transaction(conn):
        exercise_id = repo.insert_exercise(conn, "new", None, data, llm.model, RECALL_PROMPT_VERSION)
    return get_state(conn, exercise_id)


def create_review_exercise(conn: sqlite3.Connection, llm: LLMClient, item_id: int) -> dict:
    item = repo.get_review_item(conn, item_id)
    if not item:
        raise NotFound(f"Revisão {item_id} não encontrada.")
    pending = repo.pending_exercise(conn, "review", item_id)
    if pending:
        return get_state(conn, pending)
    if item["due_at"] > iso(now()):
        raise RuleViolation("not_due", "Esta dificuldade ainda não está agendada para revisão.")
    if item["target_type"] == "sentence":
        # Erro fora das palavras registradas: revisa literalmente a mesma frase, sem IA.
        source = repo.get_exercise(conn, int(item["target_id"]))
        data = {
            "sentence_pt": source["sentence_pt"],
            "reference_en": source["reference_en"],
            "grammar_tags": source["grammar_tags"],
            "targets": repo.get_targets(conn, source["id"]),
        }
        model = source["model"]
    else:
        # Palavra registrada: frase nova para a mesma palavra.
        entry = repo.get_vocab(conn, int(item["target_id"]))
        target_text = entry["english_text"] if entry else item["label_pt"]
        recent = [ex["sentence_pt"] for ex in item["examples"]] + repo.recent_sentences(conn, 10, item_id)
        data = ai.generate_targeted_review(llm, item, target_text, entry, recent, frames_repo.topic_ids(conn))
        model = llm.model
    with transaction(conn):
        exercise_id = repo.insert_exercise(conn, "review", item_id, data, model, RECALL_PROMPT_VERSION)
    return get_state(conn, exercise_id)


def answer(conn: sqlite3.Connection, llm: LLMClient, exercise_id: int, text: str, key: str) -> dict:
    exercise = repo.get_exercise(conn, exercise_id)
    if not exercise:
        raise NotFound(f"Exercício {exercise_id} não encontrado.")
    existing = repo.get_attempt_by_key(conn, key) or repo.get_attempt(conn, exercise_id)
    if existing:  # reenvio (rede, duplo clique): devolve o resultado já registrado
        if existing["exercise_id"] != exercise_id:
            raise RuleViolation("key_reused", "Chave de envio já usada em outro exercício.", 409)
        return get_state(conn, exercise_id)
    clean = " ".join(text.split())
    if not clean or not any(c.isalpha() for c in clean):
        raise RuleViolation("empty_answer", "Escreva sua tradução em inglês.", 422)
    if len(clean) > rules.MAX_ANSWER_CHARS:
        raise RuleViolation("too_long", f"A resposta pode ter no máximo {rules.MAX_ANSWER_CHARS} caracteres.", 422)

    # A resposta é salva antes de chamar a IA: nada se perde se ela falhar.
    with transaction(conn):
        attempt_id = repo.insert_attempt(conn, exercise_id, key, clean, local_today(conn))
        repo.set_exercise_status(conn, exercise_id, "awaiting_evaluation")
    return _evaluate(conn, llm, exercise, repo.get_attempt(conn, exercise_id) | {"id": attempt_id})


def skip(conn: sqlite3.Connection, exercise_id: int) -> dict:
    """Descarta uma frase ainda não respondida (estranha, ambígua). Não conta na cota nem na revisão."""
    exercise = repo.get_exercise(conn, exercise_id)
    if not exercise:
        raise NotFound(f"Exercício {exercise_id} não encontrado.")
    if exercise["status"] != "pending_answer":
        raise RuleViolation("already_answered", "Só dá para pular uma frase antes de responder.")
    with transaction(conn):
        repo.set_exercise_status(conn, exercise_id, "skipped")
    return get_state(conn, exercise_id)


def reevaluate(conn: sqlite3.Connection, llm: LLMClient, exercise_id: int) -> dict:
    exercise = repo.get_exercise(conn, exercise_id)
    attempt = repo.get_attempt(conn, exercise_id) if exercise else None
    if not exercise or not attempt:
        raise NotFound("Exercício sem resposta para avaliar.")
    if exercise["status"] != "awaiting_evaluation":
        return get_state(conn, exercise_id)
    return _evaluate(conn, llm, exercise, attempt)


def _evaluate(conn: sqlite3.Connection, llm: LLMClient, exercise: dict, attempt: dict) -> dict:
    targets = repo.get_targets(conn, exercise["id"])
    topic_ids = frames_repo.topic_ids(conn)
    answer_text = attempt["answer_text"]

    raw_dump, model = None, llm.model
    if rules.same_meaning_form(answer_text, exercise["reference_en"]):
        processed, model = rules.exact_match_result(answer_text, exercise["reference_en"], targets), "exact-match"
    else:
        try:
            raw = ai.evaluate_recall_answer(
                llm, exercise["sentence_pt"], exercise["reference_en"],
                [t["english_text"] for t in targets], answer_text, topic_ids,
            )
        except LLMError as exc:
            # Sem cota consumida, sem revisão concluída: fica pendente para reavaliar.
            with transaction(conn):
                repo.insert_ai_evaluation(conn, attempt["id"], "pending", RECALL_SCHEMA_VERSION, llm.model,
                                          None, None, str(exc))
            return get_state(conn, exercise["id"])
        raw_dump = raw.model_dump()
        processed = rules.process_recall_evaluation(raw, answer_text, exercise["reference_en"], targets, set(topic_ids))

    is_new = exercise["mode"] == "new"
    counts = is_new and processed.verdict == "incorrect"
    current = now()
    today = local_today(conn)
    with transaction(conn):
        repo.set_attempt_verdict(conn, attempt["id"], processed.verdict, counts)
        repo.insert_ai_evaluation(conn, attempt["id"], "completed", RECALL_SCHEMA_VERSION, model,
                                  raw_dump, processed.model_dump(), None)
        repo.insert_target_usage(conn, attempt["id"], [(u.vocabulary_id, u.demonstrated) for u in processed.target_usage])
        _record_observations(conn, exercise, attempt["id"], processed)
        # Só frases novas criam revisões. Errar uma revisão reagenda apenas ela: a fila não cresce.
        if is_new and processed.verdict == "incorrect":
            example = {"sentence_pt": exercise["sentence_pt"], "answer": answer_text}
            for target in _review_targets(processed, exercise, targets):
                _upsert_review(conn, target, example | target["example"], exercise["id"], attempt["id"], current, today)
        if exercise["mode"] == "review":
            _apply_review_outcome(conn, exercise, attempt["id"], processed, targets, current, today)
        repo.set_exercise_status(conn, exercise["id"], "evaluated")
    return get_state(conn, exercise["id"])


def _record_observations(conn: sqlite3.Connection, exercise: dict, attempt_id: int, processed) -> None:
    rows = [
        (e.topic_id, exercise["id"], attempt_id, "error", e.category, e.excerpt, e.correction, e.explanation_pt)
        for e in processed.errors
    ]
    if processed.verdict == "correct":  # acerto só dos tópicos que a frase realmente exercitou
        rows += [
            (t, exercise["id"], attempt_id, "correct", "grammar", None, None, None)
            for t in exercise["grammar_tags"] if t not in IGNORED_TOPICS and t != "other"
        ]
    repo.insert_observations(conn, rows)


def _review_targets(processed, exercise: dict, targets: list[dict]) -> list[dict]:
    """Revisões criadas por uma frase nova errada:
    - erro que envolve uma palavra registrada → revisão da palavra (frases novas com ela);
    - qualquer outro erro → UMA revisão da frase, que volta idêntica até você acertar.
    Uma tradução correta que só não usou a palavra-alvo não gera revisão (não é erro)."""
    found: dict[tuple[str, str], dict] = {}
    for error in processed.errors:
        example = {"excerpt": error.excerpt, "correction": error.correction}
        about_target = False
        for t in targets:  # palavra-alvo usada com sentido/grafia errados, ou trocada por outra errada
            if (rules.target_demonstrated(t["english_text"], error.excerpt)
                    or rules.target_demonstrated(t["english_text"], error.correction)):
                about_target = True
                meaning = f" ({t['intended_meaning']})" if t.get("intended_meaning") else ""
                found.setdefault(("vocabulary_sense", str(t["vocabulary_id"])),
                                 {"type": "vocabulary_sense", "id": str(t["vocabulary_id"]),
                                  "label": f"Uso de “{t['english_text']}”{meaning}", "example": example})
        if not about_target:
            found.setdefault(("sentence", str(exercise["id"])),
                             {"type": "sentence", "id": str(exercise["id"]), "label": exercise["sentence_pt"],
                              "example": example})
    return list(found.values())


def _upsert_review(conn, target: dict, example: dict, exercise_id: int, attempt_id: int, current: datetime, today: str):
    item = repo.get_review_item_by_target(conn, target["type"], target["id"])
    if not item:
        state, due = scheduler.on_created(current)
        item_id = repo.insert_review_item(conn, target["type"], target["id"], target["label"], state.to_dict(),
                                          iso(due), [example], today, target.get("target_text"))
        repo.insert_review_event(conn, item_id, "created", None, iso(due), exercise_id, attempt_id)
        return
    examples = (item["examples"] + [example])[-MAX_EXAMPLES:]
    if item["last_event_local_date"] == today:
        # Mesmo dia: acumula o exemplo sem reagendar (evita revisões infinitas na mesma sessão).
        repo.update_review_item(conn, item["id"], examples=examples)
        return
    state, due = scheduler.on_reinforced(SchedulerState.from_dict(item["scheduler_state"]),
                                         datetime.fromisoformat(item["due_at"]), current)
    repo.update_review_item(conn, item["id"], examples=examples, scheduler_state=state.to_dict(), due_at=iso(due),
                            last_event_local_date=today, status=scheduler.status(state))
    repo.insert_review_event(conn, item["id"], "reinforced", item["due_at"], iso(due), exercise_id, attempt_id)


def _apply_review_outcome(conn, exercise: dict, attempt_id: int, processed, targets, current: datetime, today: str):
    item = repo.get_review_item(conn, exercise["review_item_id"])
    if not item or processed.verdict == "needs_review":
        return  # incerteza da IA não conclui nem penaliza a revisão
    if item["target_type"] == "sentence":
        failed = processed.verdict == "incorrect"  # a mesma frase: precisa sair certa
    else:
        usage = {u.vocabulary_id: u for u in processed.target_usage}
        target_usage = usage.get(int(item["target_id"]))
        failed = processed.verdict == "incorrect" and (target_usage is None or not target_usage.demonstrated
                                                       or any(e.category in ("lexical", "meaning") for e in processed.errors))
    state = SchedulerState.from_dict(item["scheduler_state"])
    if failed:
        state, due = scheduler.on_fail(state, current)
        outcome = "fail"
        examples = (item["examples"] + [{
            "sentence_pt": exercise["sentence_pt"], "answer": repo.get_attempt(conn, exercise["id"])["answer_text"],
            "excerpt": processed.errors[0].excerpt if processed.errors else "",
            "correction": processed.errors[0].correction if processed.errors else "",
        }])[-MAX_EXAMPLES:]
    elif processed.verdict == "correct":
        state, due = scheduler.on_success(state, current, today)
        outcome, examples = "success", item["examples"]
    else:
        return  # palavra usada certo, mas errou outra coisa: a palavra não falhou nem foi confirmada
    repo.update_review_item(conn, item["id"], scheduler_state=state.to_dict(), due_at=iso(due), examples=examples,
                            status=scheduler.status(state), last_event_local_date=today)
    repo.insert_review_event(conn, item["id"], outcome, item["due_at"], iso(due), exercise["id"], attempt_id)


def backfill_reviews(conn: sqlite3.Connection) -> int:
    """Cria revisões que faltam para frases novas erradas (ex.: as de antes da revisão por frase).
    Idempotente: só insere unidades inexistentes; não reagenda nem duplica as que já existem."""
    rows = conn.execute(
        """SELECT e.id AS exercise_id, e.sentence_pt, a.id AS attempt_id, a.answer_text, a.local_date, ev.result
           FROM recall_attempts a
           JOIN recall_exercises e ON e.id = a.exercise_id
           JOIN ai_evaluations ev ON ev.id = (SELECT MAX(id) FROM ai_evaluations WHERE attempt_id = a.id
                                              AND status = 'completed')
           WHERE a.verdict = 'incorrect' AND e.mode = 'new'"""
    ).fetchall()
    created = 0
    current = now()
    with transaction(conn):
        for row in rows:
            processed = rules.ProcessedRecall.model_validate_json(row["result"])
            exercise = {"id": row["exercise_id"], "sentence_pt": row["sentence_pt"]}
            for target in _review_targets(processed, exercise, repo.get_targets(conn, row["exercise_id"])):
                if repo.get_review_item_by_target(conn, target["type"], target["id"]):
                    continue
                state, due = scheduler.on_created(current)
                example = {"sentence_pt": row["sentence_pt"], "answer": row["answer_text"]} | target["example"]
                item_id = repo.insert_review_item(conn, target["type"], target["id"], target["label"],
                                                  state.to_dict(), iso(due), [example], row["local_date"],
                                                  target.get("target_text"))
                repo.insert_review_event(conn, item_id, "created", None, iso(due), row["exercise_id"],
                                         row["attempt_id"])
                created += 1
    return created


# ---------- leitura ----------

def get_state(conn: sqlite3.Connection, exercise_id: int) -> dict:
    exercise = repo.get_exercise(conn, exercise_id)
    if not exercise:
        raise NotFound(f"Exercício {exercise_id} não encontrado.")
    attempt = repo.get_attempt(conn, exercise_id)
    evaluation = repo.latest_ai_evaluation(conn, attempt["id"]) if attempt else None
    evaluated = exercise["status"] == "evaluated"
    review = None
    if exercise["review_item_id"]:
        item = repo.get_review_item(conn, exercise["review_item_id"])
        review = ({"item_id": item["id"], "target_type": item["target_type"],
                   # Revisão de frase: o rótulo é a própria frase (já está na tela).
                   "label_pt": item["label_pt"] if item["target_type"] == "vocabulary_sense" else None}
                  if item else None)
    return {
        "id": exercise["id"],
        "mode": exercise["mode"],
        "sentence_pt": exercise["sentence_pt"],
        "status": exercise["status"],
        "created_at": exercise["created_at"],
        "review": review,
        # Antes da resposta avaliada: nada de referência nem alvos (seriam dicas).
        "reference_en": exercise["reference_en"] if evaluated else None,
        "targets": [{"vocabulary_id": t["vocabulary_id"], "english_text": t["english_text"],
                     "intended_meaning": t["intended_meaning"]} for t in repo.get_targets(conn, exercise_id)]
        if evaluated else [],
        "answer": attempt["answer_text"] if attempt else None,
        "verdict": attempt["verdict"] if attempt else None,
        "score": _score(exercise, attempt, evaluation),
        "result": _result_view(conn, exercise, attempt, evaluation),
        "evaluation_error": evaluation["error_message"] if evaluation and evaluation["status"] == "pending" else None,
        "quota": quota(conn),
        "due_reviews": len(repo.due_review_items(conn, iso(now()))),
    }


def _result_view(conn: sqlite3.Connection, exercise: dict, attempt: dict | None,
                 evaluation: dict | None) -> dict | None:
    """Resultado salvo + sentido de cada palavra-alvo. Aplica também a avaliações antigas a regra de
    mostrar uma tradução válida que use a palavra-alvo quando você não a usou."""
    if not attempt or not evaluation or evaluation["status"] != "completed":
        return None
    result = dict(evaluation["result"] or {})
    meanings = {t["vocabulary_id"]: t["intended_meaning"] for t in repo.get_targets(conn, exercise["id"])}
    usage_list = [rules.TargetUsage(**u) for u in result.get("target_usage", [])]
    result["alternative_en"] = rules.alternative_using_targets(
        result.get("alternative_en"), exercise["reference_en"], attempt["answer_text"], usage_list)
    result["target_usage"] = [u.model_dump() | {"meaning_pt": meanings.get(u.vocabulary_id)} for u in usage_list]
    return result


def _score(exercise: dict, attempt: dict | None, evaluation: dict | None) -> int | None:
    """Calculada a partir do que está salvo: vale também para tentativas antigas."""
    if not attempt or not evaluation or evaluation["status"] != "completed":
        return None
    result = evaluation["result"] or {}
    return recall_score(attempt["verdict"], attempt["answer_text"], result.get("corrected_answer"),
                        result.get("alternative_en"), exercise["reference_en"])


def due_reviews(conn: sqlite3.Connection) -> dict:
    current = iso(now())
    items = repo.due_review_items(conn, current)
    upcoming = repo.upcoming_review_items(conn, current)
    view = lambda i: {"id": i["id"], "label_pt": i["label_pt"], "target_type": i["target_type"],  # noqa: E731
                      "due_at": i["due_at"], "status": i["status"], "mistakes": len(i["examples"])}
    return {"due": [view(i) for i in items], "upcoming": [view(i) for i in upcoming]}


def progress(conn: sqlite3.Connection) -> dict:
    counts = repo.verdict_counts(conn)
    vocab = repo.list_vocab(conn)
    return {
        "quota": quota(conn),
        "due_reviews": len(repo.due_review_items(conn, iso(now()))),
        "new": counts.get("new", {}),
        "review": counts.get("review", {}),
        "words": {"total": len(vocab), "enabled": sum(v["enabled"] for v in vocab),
                  "practiced": sum(1 for v in vocab if v["times_used"]),
                  "demonstrated": sum(1 for v in vocab if v["times_demonstrated"])},
        "topics": repo.topic_errors(conn),
        "history": [_with_score(conn, row) for row in repo.history(conn)],
    }


def _with_score(conn: sqlite3.Connection, row: dict) -> dict:
    exercise = repo.get_exercise(conn, row["id"])
    attempt = repo.get_attempt(conn, row["id"])
    evaluation = repo.latest_ai_evaluation(conn, attempt["id"]) if attempt else None
    return {**row, "score": _score(exercise, attempt, evaluation)}
