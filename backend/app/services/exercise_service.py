"""Orquestra o fluxo do Sentence Builder: criação, versões, dicas e avaliação."""

import sqlite3

from ..db import transaction
from ..domain import rules
from ..domain.evaluation import process_evaluation, used_connectors
from ..domain.rules import ExerciseStatus, RuleViolation
from ..domain.score import builder_score
from ..llm import operations
from ..llm.client import LLMClient, LLMError
from ..llm.schemas import EVALUATION_SCHEMA_VERSION
from ..repositories import evaluations as eval_repo
from ..repositories import exercises as ex_repo
from ..repositories import frames as frames_repo


class NotFound(Exception):
    pass


def _require_exercise(conn: sqlite3.Connection, exercise_id: int) -> dict:
    exercise = ex_repo.get_exercise(conn, exercise_id)
    if not exercise:
        raise NotFound(f"Exercício {exercise_id} não encontrado.")
    return exercise


def create_exercise(conn: sqlite3.Connection, selection_mode: str, frame_id: str | None) -> dict:
    if selection_mode == "random":
        frame = frames_repo.random_frame(conn)
        if not frame:
            raise RuleViolation("no_frames", "Não há frames ativas na biblioteca.")
    else:
        if not frame_id:
            raise RuleViolation("frame_required", "Escolha uma frame ou use o modo aleatório.", 422)
        frame = frames_repo.get_frame(conn, frame_id)
        if not frame or not frame["enabled"]:
            raise NotFound(f"Frame '{frame_id}' não encontrada.")
    with transaction(conn):
        # Só fica salvo o que chega ao feedback: um exercício abandonado some ao começar outro.
        ex_repo.delete_unfinished(conn)
        session_id = ex_repo.get_or_create_session(conn)
        exercise_id = ex_repo.create_exercise(
            conn, session_id, frame["id"], selection_mode, ExerciseStatus.IN_PROGRESS.value
        )
    return get_state(conn, exercise_id)


def save_version(conn: sqlite3.Connection, exercise_id: int, version_index: int, text: str) -> dict:
    exercise = _require_exercise(conn, exercise_id)
    versions = ex_repo.list_versions(conn, exercise_id)
    clean = rules.validate_version_submission(
        exercise["status"], [v["text"] for v in versions], version_index, text
    )
    hints_opened = version_index > 0 and ex_repo.latest_hints(conn, exercise_id, version_index) is not None
    with transaction(conn):
        ex_repo.insert_version(conn, exercise_id, version_index, clean, hints_opened)
        new_status = rules.status_after_versions(len(versions) + 1)
        ex_repo.set_status(
            conn, exercise_id, new_status.value, completed=new_status != ExerciseStatus.IN_PROGRESS
        )
        ex_repo.touch_session(conn, exercise["session_id"])
    return get_state(conn, exercise_id)


def request_hints(conn: sqlite3.Connection, llm: LLMClient, exercise_id: int, refresh: bool = False) -> dict:
    exercise = _require_exercise(conn, exercise_id)
    versions = ex_repo.list_versions(conn, exercise_id)
    stage = rules.validate_hint_request(exercise["status"], len(versions))
    if not refresh:
        cached = ex_repo.latest_hints(conn, exercise_id, stage)
        if cached:
            return {"stage": stage, "hints": cached}
    frame = frames_repo.get_frame(conn, exercise["frame_id"])
    base_text = versions[-1]["text"]
    hints = operations.suggest_hints(llm, frame["text"], base_text, stage)
    with transaction(conn):
        ex_repo.insert_hints(conn, exercise_id, stage, base_text, hints, llm.model)
    return {"stage": stage, "hints": hints}


def evaluate(conn: sqlite3.Connection, llm: LLMClient, exercise_id: int) -> dict:
    """Avalia após V3. Se a IA falhar, o exercício fica 'aguardando avaliação' e nada é perdido."""
    exercise = _require_exercise(conn, exercise_id)
    versions = [v["text"] for v in ex_repo.list_versions(conn, exercise_id)]
    rules.validate_can_evaluate(exercise["status"], len(versions))
    frame = frames_repo.get_frame(conn, exercise["frame_id"])
    topic_ids = frames_repo.topic_ids(conn)

    try:
        raw = operations.evaluate_exercise(llm, frame["text"], frame["explanation_pt"], versions, topic_ids)
    except LLMError as exc:
        with transaction(conn):
            eval_repo.insert_failed(conn, exercise_id, EVALUATION_SCHEMA_VERSION, llm.model, str(exc))
            # Numa reavaliação que falha, a avaliação anterior continua válida.
            if exercise["status"] != ExerciseStatus.EVALUATED.value:
                ex_repo.set_status(conn, exercise_id, ExerciseStatus.AWAITING_EVALUATION.value)
        return get_state(conn, exercise_id)

    # Segunda passada, focada na frase final. Se falhar, a avaliação principal basta.
    try:
        final_review = operations.review_final_sentence(
            llm, frame["text"], versions[-1], used_connectors(" ".join(versions)), topic_ids
        )
    except LLMError:
        final_review = None

    processed = process_evaluation(raw, versions, set(topic_ids), final_review)
    with transaction(conn):
        raw_result = {**raw.model_dump(), "final_review": final_review.model_dump() if final_review else None}
        eval_repo.insert_success(conn, exercise_id, EVALUATION_SCHEMA_VERSION, llm.model, raw_result, processed)
        ex_repo.set_status(conn, exercise_id, ExerciseStatus.EVALUATED.value, completed=True)
    return get_state(conn, exercise_id)


def get_state(conn: sqlite3.Connection, exercise_id: int) -> dict:
    exercise = _require_exercise(conn, exercise_id)
    versions = ex_repo.list_versions(conn, exercise_id)
    frame = frames_repo.get_frame(conn, exercise["frame_id"])
    saved = len(versions)
    status = exercise["status"]
    in_progress = status == ExerciseStatus.IN_PROGRESS.value

    last_attempt = eval_repo.latest_evaluation(conn, exercise_id)
    evaluation = eval_repo.latest_evaluation(conn, exercise_id, status="ok") or last_attempt
    evaluation_view = None
    if evaluation:
        result = evaluation["result"] or {}
        evaluation_view = {
            "id": evaluation["id"],
            "status": evaluation["status"],
            "model": evaluation["model"],
            "created_at": evaluation["created_at"],
            "error_message": last_attempt["error_message"] if last_attempt["status"] == "failed" else None,
            "feedback": result.get("feedback"),
            "score": builder_score(
                versions[-1]["text"],
                result["feedback"].get("corrected_final_sentence"),
                result["feedback"].get("final_is_correct", True),
            ) if result.get("feedback") and versions else None,
            "grammar_observations": eval_repo.list_observations(conn, exercise_id) if result else [],
            "idea_observations": eval_repo.list_idea_observations(conn, exercise_id) if result else [],
        }

    return {
        "id": exercise["id"],
        "status": status,
        "selection_mode": exercise["selection_mode"],
        "started_at": exercise["started_at"],
        "completed_at": exercise["completed_at"],
        "frame": frame,
        "versions": versions,
        "next_version_index": saved if in_progress else None,
        "stage_label": rules.stage_label(saved if in_progress else rules.VERSION_COUNT),
        "total_versions": rules.VERSION_COUNT,
        "can_request_hints": in_progress and saved > 0,
        "can_evaluate": not in_progress and saved == rules.VERSION_COUNT,
        "hints": {str(k): v for k, v in ex_repo.hints_by_stage(conn, exercise_id).items()},
        "evaluation": evaluation_view,
    }


def delete_exercise(conn: sqlite3.Connection, exercise_id: int) -> None:
    _require_exercise(conn, exercise_id)
    with transaction(conn):
        ex_repo.delete_exercise(conn, exercise_id)


def review_observation(conn: sqlite3.Connection, observation_id: int, review_status: str) -> dict:
    if review_status not in eval_repo.REVIEW_STATUSES:
        raise RuleViolation("invalid_review_status", "Status de revisão inválido.", 422)
    observation = eval_repo.get_observation(conn, observation_id)
    if not observation:
        raise NotFound(f"Observação {observation_id} não encontrada.")
    if observation["review_status"] == "superseded":
        raise RuleViolation("superseded", "Esta observação pertence a uma avaliação antiga.")
    with transaction(conn):
        eval_repo.set_observation_review(conn, observation_id, review_status)
    return eval_repo.get_observation(conn, observation_id)
