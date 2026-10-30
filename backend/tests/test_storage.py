"""Persistência: nada se perde quando a IA falha e o histórico sobrevive a reinícios."""

from fastapi.testclient import TestClient

from conftest import V, complete_versions, make_evaluation, new_exercise

from app.api.deps import get_llm
from app.db import connect, init_db, migrate
from app.llm.client import LLMError, LLMUnavailable
from app.main import create_app


def test_migrations_are_idempotent(db_path):
    conn = init_db(db_path)
    assert migrate(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM sentence_frames").fetchone()[0] == 8
    conn.close()
    init_db(db_path).close()  # seed não duplica
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM sentence_frames").fetchone()[0] == 8


def test_retry_once_then_success(client, llm):
    ex = new_exercise(client)
    complete_versions(client, ex["id"])
    llm.queue(LLMError("json inválido"), make_evaluation())
    state = client.post(f"/api/exercises/{ex['id']}/evaluate").json()
    assert state["status"] == "evaluated"
    assert len(llm.calls) == 2


def test_two_failures_keep_exercise_awaiting_and_allow_reevaluation(client, llm):
    ex = new_exercise(client)
    complete_versions(client, ex["id"])
    llm.queue(LLMError("falha 1"), LLMError("falha 2"))
    state = client.post(f"/api/exercises/{ex['id']}/evaluate").json()
    assert state["status"] == "awaiting_evaluation"
    assert state["can_evaluate"] is True
    assert state["evaluation"]["status"] == "failed"
    assert state["evaluation"]["error_message"] == "falha 2"
    assert [v["text"] for v in state["versions"]] == V

    llm.queue(make_evaluation())
    state = client.post(f"/api/exercises/{ex['id']}/evaluate").json()
    assert state["status"] == "evaluated"
    assert state["evaluation"]["error_message"] is None


def test_ollama_offline_is_not_retried(client, llm):
    ex = new_exercise(client)
    complete_versions(client, ex["id"])
    llm.queue(LLMUnavailable("Ollama fora do ar"))
    state = client.post(f"/api/exercises/{ex['id']}/evaluate").json()
    assert state["status"] == "awaiting_evaluation"
    assert len(llm.calls) == 1


def test_failed_reevaluation_keeps_previous_feedback(client, llm):
    ex = new_exercise(client)
    complete_versions(client, ex["id"])
    llm.queue(make_evaluation(), LLMError("a"), LLMError("b"))
    client.post(f"/api/exercises/{ex['id']}/evaluate")
    state = client.post(f"/api/exercises/{ex['id']}/evaluate").json()
    assert state["status"] == "evaluated"
    assert state["evaluation"]["feedback"] is not None
    assert state["evaluation"]["error_message"] == "b"


def test_hint_failure_returns_503_and_keeps_exercise(client, llm):
    ex = new_exercise(client)
    client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": V[0]})
    llm.queue(LLMError("x"), LLMError("y"))
    r = client.post(f"/api/exercises/{ex['id']}/hints")
    assert r.status_code == 503
    assert client.get(f"/api/exercises/{ex['id']}").json()["versions"][0]["text"] == V[0]


def test_history_survives_app_restart(db_path, llm):
    app = create_app(db_path)
    app.dependency_overrides[get_llm] = lambda: llm
    with TestClient(app) as c:
        ex = new_exercise(c)
        complete_versions(c, ex["id"])
        llm.queue(make_evaluation())
        c.post(f"/api/exercises/{ex['id']}/evaluate")

    with TestClient(create_app(db_path)) as c2:
        history = c2.get("/api/exercises").json()
        assert history[0]["id"] == ex["id"] and history[0]["status"] == "evaluated"
        state = c2.get(f"/api/exercises/{ex['id']}").json()
        assert [v["text"] for v in state["versions"]] == V
        assert state["evaluation"]["feedback"]["final_is_correct"] is True


def test_settings_roundtrip_and_validation(client):
    r = client.put("/api/settings/ollama", json={"base_url": "http://localhost:9999/", "model": "llama3.1", "timeout_seconds": 60})
    assert r.status_code == 200
    assert client.get("/api/settings/ollama").json() == {
        "base_url": "http://localhost:9999", "model": "llama3.1", "timeout_seconds": 60.0
    }
    assert client.put("/api/settings/ollama", json={"base_url": "localhost", "model": "x"}).status_code == 422


def test_abandoned_exercise_is_discarded_when_a_new_one_starts(client, llm):
    abandoned = new_exercise(client)
    client.post(f"/api/exercises/{abandoned['id']}/versions", json={"version_index": 0, "text": V[0]})
    finished_but_ai_failed = new_exercise(client)
    complete_versions(client, finished_but_ai_failed["id"])  # chegou à fase de feedback

    new_exercise(client)

    assert client.get(f"/api/exercises/{abandoned['id']}").status_code == 404
    assert client.get(f"/api/exercises/{finished_but_ai_failed['id']}").status_code == 200


def test_history_lists_only_exercises_that_reached_feedback(client, llm):
    done = new_exercise(client)
    complete_versions(client, done["id"])
    llm.queue(make_evaluation())
    client.post(f"/api/exercises/{done['id']}/evaluate")
    new_exercise(client)  # em andamento

    history = client.get("/api/exercises?finished_only=true").json()
    assert [h["id"] for h in history] == [done["id"]]


def test_delete_exercise_removes_everything(client, llm, db_path):
    ex = new_exercise(client)
    client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": V[0]})
    llm.queue({"hints": ["Who was with you?"]})
    client.post(f"/api/exercises/{ex['id']}/hints")
    for i in range(1, 4):
        client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": i, "text": V[i]})
    llm.queue(make_evaluation(grammar_errors=[
        {"topic_id": "prepositions", "version_index": 3, "original_excerpt": "after work",
         "suggested_correction": "from work", "explanation_pt": "x"}
    ], idea_development=[{"version_index": 1, "kind": "clarity", "is_positive": True, "comment_pt": "ok"}]))
    client.post(f"/api/exercises/{ex['id']}/evaluate")

    assert client.delete(f"/api/exercises/{ex['id']}").status_code == 204
    assert client.get(f"/api/exercises/{ex['id']}").status_code == 404
    assert client.delete(f"/api/exercises/{ex['id']}").status_code == 404

    conn = connect(db_path)
    for table in ["sentence_versions", "hint_requests", "exercise_evaluations",
                  "grammar_observations", "idea_observations", "exercises"]:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
