"""Regras de progressão: V0 + exatamente três expansões, controladas pelo backend."""

from conftest import V, complete_versions, make_evaluation, new_exercise


def test_random_mode_picks_an_enabled_frame(client):
    r = client.post("/api/exercises", json={"selection_mode": "random"})
    assert r.status_code == 201
    assert r.json()["frame"]["enabled"] is True


def test_manual_mode_requires_frame(client):
    r = client.post("/api/exercises", json={"selection_mode": "manual"})
    assert r.status_code == 422


def test_stages_advance_in_order(client):
    ex = new_exercise(client)
    assert ex["next_version_index"] == 0
    assert ex["stage_label"] == "Frase inicial"
    for i, text in enumerate(V):
        r = client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": i, "text": text})
        state = r.json()
        if i < 3:
            assert state["status"] == "in_progress"
            assert state["next_version_index"] == i + 1
            assert state["stage_label"] == f"Expansão {i + 1}/3"
    assert state["status"] == "awaiting_evaluation"
    assert state["next_version_index"] is None
    assert state["can_evaluate"] is True
    assert [v["text"] for v in state["versions"]] == V


def test_cannot_skip_a_stage(client):
    ex = new_exercise(client)
    r = client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 1, "text": V[1]})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "wrong_stage"


def test_cannot_resubmit_a_saved_version(client):
    ex = new_exercise(client)
    client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": V[0]})
    r = client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": "Other text."})
    assert r.status_code == 409
    state = client.get(f"/api/exercises/{ex['id']}").json()
    assert state["versions"][0]["text"] == V[0]


def test_no_fifth_version(client):
    ex = new_exercise(client)
    complete_versions(client, ex["id"])
    r = client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 3, "text": "More text here."})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "exercise_closed"


def test_expansion_must_change_previous_version(client):
    ex = new_exercise(client)
    client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": V[0]})
    r = client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 1, "text": "  " + V[0].upper()})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "unchanged"


def test_expansion_may_edit_earlier_parts(client):
    """Cada versão pode corrigir trechos anteriores; não há mínimo de palavras."""
    ex = new_exercise(client)
    client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": "I wanted to plays, but I tired."})
    r = client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 1, "text": "I wanted to play, but I was tired."})
    assert r.status_code == 200


def test_empty_and_too_long_text_rejected(client):
    ex = new_exercise(client)
    assert client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": "   "}).status_code == 422
    long_text = "word " * 100
    assert client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": long_text}).status_code == 422


def test_cannot_evaluate_before_v3(client, llm):
    ex = new_exercise(client)
    client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": V[0]})
    r = client.post(f"/api/exercises/{ex['id']}/evaluate")
    assert r.status_code == 409
    assert llm.calls == []


def test_hints_only_during_expansions_and_are_recorded(client, llm):
    ex = new_exercise(client)
    r = client.post(f"/api/exercises/{ex['id']}/hints")
    assert r.status_code == 409  # V0 é produção autônoma

    client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": V[0]})
    llm.queue({"hints": ["Who did you want to play with?", "Add when it happened."]})
    r = client.post(f"/api/exercises/{ex['id']}/hints")
    assert r.status_code == 200
    assert r.json()["stage"] == 1
    assert "Learner's current sentence: " + V[0] in llm.calls[0][1]

    # Reabrir as dicas na mesma etapa não chama a IA de novo.
    assert client.post(f"/api/exercises/{ex['id']}/hints").json()["hints"] == r.json()["hints"]
    assert len(llm.calls) == 1

    state = client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 1, "text": V[1]}).json()
    assert state["versions"][1]["hints_opened"] is True
    state = client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 2, "text": V[2]}).json()
    assert state["versions"][2]["hints_opened"] is False
    assert state["versions"][0]["hints_opened"] is False


def test_hints_that_rewrite_the_sentence_are_dropped(client, llm):
    ex = new_exercise(client)
    client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": V[0]})
    llm.queue({"hints": ["I wanted to play football, but I was very tired.", "Say who you were with."]})
    r = client.post(f"/api/exercises/{ex['id']}/hints")
    assert r.json()["hints"] == ["Say who you were with."]


def test_evaluation_cannot_be_triggered_twice_before_finishing(client, llm):
    ex = new_exercise(client)
    complete_versions(client, ex["id"])
    llm.queue(make_evaluation())
    state = client.post(f"/api/exercises/{ex['id']}/evaluate").json()
    assert state["status"] == "evaluated"
    assert state["completed_at"] is not None
