"""Sentence Recall: critérios de aceite do MVP."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_corrector, get_llm
from app.domain.recall import canonical_tokens, target_demonstrated
from app.domain.scheduler import SchedulerState, scheduler
from app.llm.client import LLMError
from app.main import create_app
from app.services import recall_service

T0 = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)  # 12:00 em São Paulo


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    state = {"now": T0}
    monkeypatch.setattr(recall_service, "now", lambda: state["now"])
    return state


def add_words(client, *words):
    r = client.post("/api/recall/vocabulary", json={"entries": [
        w if isinstance(w, dict) else {"english_text": w} for w in words
    ]})
    assert r.status_code == 201, r.text
    return r.json()["created"]


def prompt(sentence, reference, targets=(), tags=("past_simple",)):
    return {"sentence_pt": sentence, "reference_en": reference,
            "targets": [{"english_text": t, "meaning_pt": "x"} for t in targets], "grammar_tags": list(tags)}


def evaluation(verdict="correct", errors=(), meaning=True, grammar=True, confidence=0.9, example="", natural=""):
    return {"natural_en": natural, "error_events": list(errors), "meaning_match": meaning, "grammar_valid": grammar,
            "verdict": verdict, "strengths": ["Boa conexão com because."], "valid_example_en": example,
            "confidence": confidence}


DIDNT_ERROR = {"category": "grammar", "topic_id": "auxiliaries_negation", "excerpt": "didn't played",
               "correction": "didn't play", "explanation_pt": "Depois de didn't, use o verbo base: play."}


def new_ex(client, llm, sentence="Eu não joguei ontem porque estava cansado.",
           reference="I didn't play yesterday because I was tired.", targets=("tired",)):
    llm.queue(prompt(sentence, reference, targets))
    r = client.post("/api/recall/exercises")
    assert r.status_code == 201, r.text
    return r.json()


def answer(client, ex_id, text, key=None):
    r = client.post(f"/api/recall/exercises/{ex_id}/answer",
                    json={"answer": text, "idempotency_key": key or f"key-{ex_id}-{len(text)}"})
    assert r.status_code == 200, r.text
    return r.json()


def wrong_answer(client, llm, n):
    ex = new_ex(client, llm, sentence=f"Frase {n} sobre ontem.", reference=f"I didn't play yesterday {n} tired.")
    llm.queue(evaluation("incorrect", [DIDNT_ERROR], grammar=False))
    return answer(client, ex["id"], f"I didn't played yesterday {n} tired")


# ---------- vocabulário ----------

def test_vocabulary_crud_and_duplicates(client):
    tired = add_words(client, "tired")[0]
    r = client.post("/api/recall/vocabulary", json={"entries": [{"english_text": "  Tired "}]})
    assert r.status_code == 409
    # mesmo termo com outro sentido é permitido
    add_words(client, {"english_text": "get", "translation_pt": "conseguir"}, {"english_text": "get", "translation_pt": "chegar"})
    r = client.patch(f"/api/recall/vocabulary/{tired['id']}", json={"enabled": False})
    assert r.json()["enabled"] is False
    assert client.delete(f"/api/recall/vocabulary/{tired['id']}").status_code == 204
    assert [v["english_text"] for v in client.get("/api/recall/vocabulary").json()] == ["get", "get"]


def test_practice_requires_vocabulary(client):
    r = client.post("/api/recall/exercises")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_vocabulary"


# ---------- geração ----------

def test_reference_and_targets_hidden_until_answered(client, llm):
    add_words(client, "tired")
    ex = new_ex(client, llm)
    assert ex["reference_en"] is None and ex["targets"] == []
    assert client.get(f"/api/recall/exercises/{ex['id']}").json()["reference_en"] is None
    # recarregar não gera outra frase nem chama a IA de novo
    calls = len(llm.calls)
    assert client.post("/api/recall/exercises").json()["id"] == ex["id"]
    assert len(llm.calls) == calls

    llm.queue(evaluation())
    done = answer(client, ex["id"], "I didn't play yesterday because I was exhausted")
    assert done["reference_en"] == "I didn't play yesterday because I was tired."
    assert done["targets"][0]["english_text"] == "tired"


def test_generation_must_use_the_target_word(client, llm):
    add_words(client, "tired")
    llm.queue(prompt("Eu estou feliz.", "I am happy."), prompt("Eu estava cansado.", "I was tired."))
    ex = client.post("/api/recall/exercises").json()
    assert ex["sentence_pt"] == "Eu estava cansado."

    llm.queue(prompt("Eu estou feliz.", "I am happy."), prompt("Eu estou triste.", "I am sad."),
              prompt("Eu estou bem.", "I am fine."))  # 3 tentativas, nenhuma usa o alvo
    llm.queue(evaluation())
    answer(client, ex["id"], "I was tired")
    r = client.post("/api/recall/exercises")
    assert r.status_code == 503
    assert "palavra-alvo" in r.json()["detail"]["message"]


# ---------- avaliação ----------

def test_two_equivalent_translations_are_both_correct(client, llm):
    add_words(client, "need")
    ex1 = new_ex(client, llm, "Eu preciso terminar meu trabalho hoje.", "I need to finish my work today.", ("need",))
    r1 = answer(client, ex1["id"], "i need to finish my work today")  # igual à referência: sem IA
    assert r1["verdict"] == "correct"
    assert r1["result"]["target_usage"][0]["demonstrated"] is True

    ex2 = new_ex(client, llm, "Eu preciso terminar meu trabalho amanhã.", "I need to finish my work tomorrow.", ("need",))
    llm.queue(evaluation(example="I need to finish my work tomorrow."))
    r2 = answer(client, ex2["id"], "I have to finish my work tomorrow")
    assert r2["verdict"] == "correct"
    # correta, mas não demonstra o alvo: não é erro, não conta na cota, não gera revisão
    assert r2["result"]["target_usage"][0]["demonstrated"] is False
    assert r2["quota"]["errors_today"] == 0
    assert client.get("/api/recall/reviews/due").json()["due"] == []


def test_capitalization_and_contractions_are_never_errors(client, llm):
    add_words(client, "tired")
    ex = new_ex(client, llm)
    llm.queue(evaluation("incorrect", [
        {"category": "grammar", "topic_id": "pronouns", "excerpt": "i did not", "correction": "I didn't",
         "explanation_pt": "Use a contração."},
        {"category": "spelling", "topic_id": "capitalization_punctuation", "excerpt": "i", "correction": "I",
         "explanation_pt": "Maiúscula."},
    ]))
    r = answer(client, ex["id"], "i did not play yesterday because i was so tired")
    assert r["verdict"] == "correct" and r["quota"]["errors_today"] == 0


def test_style_suggestion_is_not_an_error(client, llm):
    add_words(client, "tired")
    ex = new_ex(client, llm)
    llm.queue(evaluation("correct", [{"category": "style", "topic_id": "other", "excerpt": "very tired",
                                      "correction": "exhausted", "explanation_pt": "Mais natural."}]))
    r = answer(client, ex["id"], "I didn't play yesterday because I was very tired")
    assert r["verdict"] == "correct" and r["result"]["errors"] == []
    assert r["result"]["suggestion"]["example_en"] == "exhausted"


def test_uncertain_and_failed_evaluations_do_not_punish(client, llm):
    add_words(client, "tired")
    ex = new_ex(client, llm)
    llm.queue(evaluation("incorrect", [DIDNT_ERROR], confidence=0.3))
    r = answer(client, ex["id"], "I didn't played yesterday because I was tired")
    assert r["verdict"] == "needs_review" and r["quota"]["errors_today"] == 0

    ex2 = new_ex(client, llm, "Ela não veio ontem porque estava cansada.", "She didn't come yesterday because she was tired.")
    llm.queue(LLMError("x"), LLMError("y"))
    r = answer(client, ex2["id"], "She didn't came yesterday because she was tired")
    assert r["status"] == "awaiting_evaluation" and r["verdict"] is None
    assert r["evaluation_error"] == "y" and r["answer"] == "She didn't came yesterday because she was tired"
    assert r["quota"]["errors_today"] == 0
    llm.queue(evaluation("incorrect", [{**DIDNT_ERROR, "excerpt": "didn't came", "correction": "didn't come"}]))
    r = client.post(f"/api/recall/exercises/{ex2['id']}/evaluate").json()
    assert r["verdict"] == "incorrect" and r["quota"]["errors_today"] == 1


# ---------- cota diária ----------

def test_quota_uses_local_day_not_utc(client, llm, clock):
    add_words(client, "tired")
    clock["now"] = datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)  # ainda dia 27 em São Paulo
    wrong_answer(client, llm, 1)
    clock["now"] = datetime(2026, 10, 28, 2, 59, tzinfo=timezone.utc)
    assert client.get("/api/recall/progress").json()["quota"]["errors_today"] == 1
    clock["now"] = datetime(2026, 10, 28, 3, 0, tzinfo=timezone.utc)
    assert client.get("/api/recall/progress").json()["quota"]["errors_today"] == 0


# ---------- revisão espaçada ----------

def test_scheduler_needs_distributed_successes_for_stable():
    state, due = scheduler.on_created(T0)
    for day in range(3):
        state, due = scheduler.on_success(state, T0 + timedelta(days=day), f"2026-10-{27 + day}")
    assert scheduler.status(state) == "stable"
    same_day, _ = scheduler.on_created(T0)
    for _ in range(3):
        same_day, _ = scheduler.on_success(same_day, T0, "2026-10-27")
    assert scheduler.status(same_day) == "learning"
    failed, due = scheduler.on_fail(SchedulerState(step=3, successes=3), T0)
    assert failed.step == -1 and due == T0  # volta na hora para a fila de hoje


# ---------- texto e persistência ----------

def test_target_detection_accepts_inflections_and_contractions():
    assert target_demonstrated("have to", "I had to leave early")
    assert target_demonstrated("look for", "She was looking for her keys")
    assert target_demonstrated("didn't", "I did not see it")
    assert not target_demonstrated("need", "I have to go")
    assert canonical_tokens("I CAN'T go!") == ["i", "cannot", "go"]


def test_wrong_reference_is_corrected_before_use(client, llm):
    add_words(client, "since")
    llm.queue(prompt("Eu tenho um trabalho novo desde ontem.", "I have a new job since yesterday.", ("since",)))
    llm.reference_checks.append({"is_correct": False, "corrected_en": "I have had a new job since yesterday."})
    ex = client.post("/api/recall/exercises").json()
    llm.queue(evaluation())
    done = answer(client, ex["id"], "I've had a new job since yesterday")
    assert done["reference_en"] == "I have had a new job since yesterday."


def test_topic_is_inferred_when_ai_says_other():
    from app.domain.recall import infer_topic
    assert infer_topic("didn't played", "didn't play") == "auxiliaries_negation"
    assert infer_topic("lives here since", "has lived here since") == "present_perfect"
    assert infer_topic("I need finish", "I need to finish") == "verb_forms"
    assert infer_topic("in monday", "on monday") == "prepositions"
    assert infer_topic("a apple", "an apple") == "articles"
    assert infer_topic("she go", "she goes") == "verb_forms"


def test_portuguese_sentence_cannot_contain_the_english_target(client, llm):
    add_words(client, "tired")
    llm.queue(prompt("Eu fiquei muito tired hoje.", "I was very tired today.", ("tired",)),
              prompt("Eu fiquei muito cansado hoje.", "I was very tired today.", ("tired",)))
    assert client.post("/api/recall/exercises").json()["sentence_pt"] == "Eu fiquei muito cansado hoje."


def test_batch_adds_valid_words_and_skips_the_rest(client):
    add_words(client, "tired")
    r = client.post("/api/recall/vocabulary", json={"entries": [
        {"english_text": "because"}, {"english_text": "Tired"}, {"english_text": "look for"},
        {"english_text": "because"}, {"english_text": "one two three four five six"}, {"english_text": "123"},
    ]})
    assert r.status_code == 201
    body = r.json()
    assert [w["english_text"] for w in body["created"]] == ["because", "look for"]
    assert [(s["english_text"], s["reason"]) for s in body["skipped"][:2]] == [
        ("Tired", "já cadastrada"), ("because", "repetida na lista")]
    assert len(body["skipped"]) == 4


def test_score_is_returned_with_the_feedback(client, llm):
    add_words(client, "tired")
    ex = new_ex(client, llm)
    assert ex["score"] is None  # sem resposta, sem nota
    llm.queue(evaluation("incorrect", [DIDNT_ERROR], grammar=False))
    r = answer(client, ex["id"], "I didn't played yesterday because I was tired")
    assert 0 < r["score"] < 100
    ex2 = new_ex(client, llm, "Ela estava cansada.", "She was tired.")
    assert answer(client, ex2["id"], "she was tired")["score"] == 100
    history = client.get("/api/recall/progress").json()["history"]
    assert [h["score"] for h in history] == [100, r["score"]]


def test_nonsense_portuguese_sentence_is_regenerated(client, llm):
    add_words(client, "have", "on")
    llm.queue(prompt("Eu tenho um livro na mesa e ele está em cima do livro.",
                     "I have a book on the table and it is on top of the book.", ("have", "on")),
              prompt("Eu tenho uma reunião na segunda.", "I have a meeting on Monday.", ("have", "on")))
    llm.reference_checks.append({"portuguese_makes_sense": False, "problem_pt": "circular",
                                 "is_correct": True, "corrected_en": ""})
    assert client.post("/api/recall/exercises").json()["sentence_pt"] == "Eu tenho uma reunião na segunda."


def test_skip_discards_without_counting(client, llm):
    add_words(client, "tired")
    ex = new_ex(client, llm)
    r = client.post(f"/api/recall/exercises/{ex['id']}/skip")
    assert r.status_code == 200 and r.json()["status"] == "skipped"
    assert r.json()["quota"]["errors_today"] == 0
    # a próxima chamada gera uma frase nova em vez de devolver a pulada
    ex2 = new_ex(client, llm, "Ela estava cansada.", "She was tired.")
    assert ex2["id"] != ex["id"]
    # resposta depois de pular, ou pular depois de responder, não é permitido
    assert client.post(f"/api/recall/exercises/{ex2['id']}/answer",
                       json={"answer": "She was tired", "idempotency_key": "k-abcdefgh"}).status_code == 200
    assert client.post(f"/api/recall/exercises/{ex2['id']}/skip").status_code == 409


def test_sentence_that_repeats_itself_is_rejected(client, llm):
    from app.domain.recall import repeats_itself
    assert repeats_itself("O livro é dos meus irmãos e é dos meus irmãos.")
    assert not repeats_itself("O livro é dos meus irmãos.")
    add_words(client, "theirs")
    llm.queue(prompt("O livro é dos meus irmãos e é dos meus irmãos.", "The book is theirs and it is theirs.", ("theirs",)),
              prompt("Esse carro não é nosso, é deles.", "That car isn't ours, it's theirs.", ("theirs",)))
    assert client.post("/api/recall/exercises").json()["sentence_pt"] == "Esse carro não é nosso, é deles."


def test_each_new_sentence_targets_exactly_one_word(client, llm, db_path):
    add_words(client, "tired", "because", "look for", "have to", "then", "whatever")
    for n in range(6):
        # a referência contém todas as palavras: só a escolhida deve virar alvo
        ex = new_ex(client, llm, f"Frase {n}.", f"I was tired then because I have to look for whatever {n}.",
                    ("tired", "because", "then", "whatever", "have to", "look for"))
        client.post(f"/api/recall/exercises/{ex['id']}/skip")
    import sqlite3
    counts = sqlite3.connect(db_path).execute(
        "SELECT COUNT(*) FROM recall_exercise_targets GROUP BY exercise_id").fetchall()
    assert counts and all(c == (1,) for c in counts)


def test_natural_parallel_sentence_is_not_flagged_as_repetition():
    from app.domain.recall import repeats_itself
    assert not repeats_itself("Eu não quero ir, mas eu não quero ficar sozinho.")


# ---------- revisão por frase (o seu caso) ----------

WENT = {"category": "lexical", "topic_id": "other", "excerpt": "went", "correction": "came",
        "explanation_pt": "Para 'veio', use 'came'."}
STAY = {"category": "grammar", "topic_id": "past_simple", "excerpt": "stay", "correction": "stayed",
        "explanation_pt": "Use o passado."}


def user_case(client, llm):
    add_words(client, "from")
    ex = new_ex(client, llm, "Ela veio de São Paulo e ficou aqui todo dia.",
                "She came from São Paulo and stayed here every day.", ("from",))
    llm.queue(evaluation("incorrect", [STAY, WENT], grammar=False))
    return answer(client, ex["id"], "she went from São Paulo and stay here every day")


# ---------- regras e formas informais ----------

def test_gonna_without_be_is_corrected_with_a_rule_not_replaced_by_will(client, llm):
    add_words(client, "gonna")
    ex = new_ex(client, llm, "Eles vão fazer a festa só se eu ajudar.",
                "They're gonna throw the party only if I help.", ("gonna",))
    # a IA sugere trocar gonna por will "por ser formal": não é erro
    llm.queue(evaluation("incorrect", [{"category": "grammar", "topic_id": "future_will", "excerpt": "they gonna do",
                                        "correction": "they will do",
                                        "explanation_pt": "Use will em vez de gonna em inglês formal."}]))
    r = answer(client, ex["id"], "they gonna do the party only if i help")
    assert r["verdict"] == "incorrect"
    err = r["result"]["errors"][0]
    assert (err["excerpt"], err["correction"]) == ("they gonna", "they're gonna")
    assert "am/is/are" in err["rule_pt"]
    assert r["result"]["corrected_answer"] == "they're gonna do the party only if i help"
    assert r["result"]["suggestion"]["example_en"] == "they will do"


def test_correct_gonna_is_not_an_error(client, llm):
    add_words(client, "gonna")
    ex = new_ex(client, llm, "Eu vou viajar amanhã.", "I'm gonna travel tomorrow soon.", ("gonna",))
    llm.queue(evaluation("incorrect", [{"category": "grammar", "topic_id": "future_will", "excerpt": "I'm gonna",
                                        "correction": "I will", "explanation_pt": "Mais formal."}]))
    r = answer(client, ex["id"], "I'm gonna travel tomorrow")
    assert r["verdict"] == "correct" and r["quota"]["errors_today"] == 0


def test_error_rule_is_kept(client, llm):
    add_words(client, "tired")
    ex = new_ex(client, llm)
    llm.queue(evaluation("incorrect", [{**DIDNT_ERROR, "rule_pt": "Depois de didn't, verbo na forma base (didn't go)."}]))
    r = answer(client, ex["id"], "I didn't played yesterday because I was tired")
    assert r["result"]["errors"][0]["rule_pt"].startswith("Depois de didn't")


def due_ids(client):
    return [d["id"] for d in client.get("/api/recall/reviews/due").json()["due"]]


def test_one_wrong_sentence_becomes_one_review_of_the_same_sentence(client, llm):
    r = user_case(client, llm)  # dois erros (went, stay), nenhum envolve "from"
    assert r["quota"]["errors_today"] == 1
    due = client.get("/api/recall/reviews/due").json()["due"]
    assert [(d["target_type"], d["label_pt"]) for d in due] == [
        ("sentence", "Ela veio de São Paulo e ficou aqui todo dia.")]
    calls = len(llm.calls)
    rev = client.post(f"/api/recall/reviews/{due[0]['id']}/exercise").json()
    assert rev["sentence_pt"] == "Ela veio de São Paulo e ficou aqui todo dia."  # literalmente a mesma
    assert len(llm.calls) == calls  # sem IA para gerar
    assert rev["review"]["target_type"] == "sentence" and rev["review"]["label_pt"] is None


def test_failing_a_review_keeps_the_queue_size_and_returns_identical(client, llm, clock):
    user_case(client, llm)
    add_words(client, "tired")
    wrong_answer(client, llm, 1)
    queue = due_ids(client)
    assert len(queue) == 2

    first = client.post(f"/api/recall/reviews/{queue[0]}/exercise").json()
    llm.queue(evaluation("incorrect", [WENT, {"category": "grammar", "topic_id": "articles", "excerpt": "the",
                                              "correction": "a", "explanation_pt": "x"}]))
    r = answer(client, first["id"], "she went from the São Paulo and stayed here every day")
    assert r["verdict"] == "incorrect" and r["quota"]["errors_today"] == 2  # revisão não conta na cota
    clock["now"] = T0 + timedelta(minutes=2)
    after = due_ids(client)
    assert sorted(after) == sorted(queue)          # errou 1 revisão: continuam as mesmas 2
    assert after[-1] == queue[0]                   # a errada volta depois das outras
    again = client.post(f"/api/recall/reviews/{queue[0]}/exercise").json()
    assert again["sentence_pt"] == first["sentence_pt"]  # igual de novo


def test_can_review_same_sentence_many_times_in_a_day(client, llm, clock):
    user_case(client, llm)
    item = due_ids(client)[0]
    for i in range(10):
        clock["now"] = T0 + timedelta(minutes=2 * (i + 1))
        rev = client.post(f"/api/recall/reviews/{item}/exercise").json()
        llm.queue(evaluation("incorrect", [WENT]))
        answer(client, rev["id"], f"she went from São Paulo and stayed here every day {i}")
    assert due_ids(client) == [] or due_ids(client) == [item]
    clock["now"] += timedelta(minutes=2)
    rev = client.post(f"/api/recall/reviews/{item}/exercise").json()
    r = answer(client, rev["id"], "she came from São Paulo and stayed here every day")
    assert r["verdict"] == "correct"
    upcoming = client.get("/api/recall/reviews/due").json()["upcoming"][0]
    assert upcoming["due_at"] == (clock["now"] + timedelta(days=1)).isoformat()


def test_more_mistakes_make_the_sentence_come_back_more_often():
    easy, hard = SchedulerState(), SchedulerState(lapses=4)
    for day in range(4):
        easy, _ = scheduler.on_success(easy, T0, f"d{day}")
        hard, _ = scheduler.on_success(hard, T0, f"d{day}")
    assert scheduler.interval_days(easy) == 14
    assert scheduler.interval_days(hard) == 6   # 14 × 0,4
    very_hard = SchedulerState(step=4, lapses=10)
    assert scheduler.interval_days(very_hard) == 9  # piso: 30 × 0,3


def test_vocabulary_error_reviews_the_word_with_new_sentences(client, llm):
    add_words(client, "look for")
    ex = new_ex(client, llm, "Eu estou procurando minhas chaves.", "I am looking for my keys.", ("look for",))
    llm.queue(evaluation("incorrect", [{"category": "lexical", "topic_id": "other", "excerpt": "looking at",
                                        "correction": "looking for", "explanation_pt": "x"}]))
    answer(client, ex["id"], "I am looking at my keys")
    due = client.get("/api/recall/reviews/due").json()["due"]
    assert [(d["target_type"], d["label_pt"]) for d in due] == [("vocabulary_sense", "Uso de “look for” (x)")]
    llm.queue(prompt("Ela está procurando o celular.", "She is looking for her phone.", ("look for",)))
    rev = client.post(f"/api/recall/reviews/{due[0]['id']}/exercise").json()
    assert rev["sentence_pt"] == "Ela está procurando o celular."  # frase nova para a mesma palavra
    # errar a revisão da palavra não cria revisões novas
    llm.queue(evaluation("incorrect", [{"category": "lexical", "topic_id": "other", "excerpt": "looking at",
                                        "correction": "looking for", "explanation_pt": "x"},
                                       {"category": "grammar", "topic_id": "articles", "excerpt": "the phone",
                                        "correction": "her phone", "explanation_pt": "x"}]))
    answer(client, rev["id"], "She is looking at the phone")
    reviews = client.get("/api/recall/reviews/due").json()
    assert len(reviews["due"]) + len(reviews["upcoming"]) == 1


def test_error_with_word_and_other_errors_creates_word_and_sentence_reviews(client, llm):
    add_words(client, "look for")
    ex = new_ex(client, llm, "Ela estava procurando as chaves ontem.", "She was looking for the keys yesterday.",
                ("look for",))
    llm.queue(evaluation("incorrect", [
        {"category": "lexical", "topic_id": "other", "excerpt": "looking at", "correction": "looking for",
         "explanation_pt": "x"},
        {"category": "grammar", "topic_id": "past_continuous", "excerpt": "is looking", "correction": "was looking",
         "explanation_pt": "x"}]))
    answer(client, ex["id"], "She is looking at the keys yesterday")
    types = sorted(d["target_type"] for d in client.get("/api/recall/reviews/due").json()["due"])
    assert types == ["sentence", "vocabulary_sense"]


def test_daily_limit_still_allows_sentence_reviews(client, llm):
    client.patch("/api/recall/settings", json={"daily_error_limit": 2})
    add_words(client, "tired")
    wrong_answer(client, llm, 1)
    wrong_answer(client, llm, 2)
    assert client.post("/api/recall/exercises").status_code == 429
    queue = due_ids(client)
    assert len(queue) == 2
    rev = client.post(f"/api/recall/reviews/{queue[0]}/exercise").json()
    assert rev["sentence_pt"] == "Frase 1 sobre ontem."


def test_backfill_and_restart_keep_sentence_reviews(db_path, llm):
    import sqlite3
    app = create_app(db_path)
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_corrector] = lambda: llm
    with TestClient(app) as c:
        user_case(c, llm)
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM review_events")
    conn.execute("DELETE FROM review_items")
    conn.commit()
    with TestClient(create_app(db_path)) as c2:  # o backfill recria na inicialização
        due = c2.get("/api/recall/reviews/due").json()["due"]
        assert [d["target_type"] for d in due] == ["sentence"]
        assert c2.get("/api/recall/progress").json()["history"][0]["verdict"] == "incorrect"


def test_failed_review_is_counted_as_pending_immediately(client, llm):
    user_case(client, llm)
    add_words(client, "tired")
    wrong_answer(client, llm, 1)
    queue = due_ids(client)
    rev = client.post(f"/api/recall/reviews/{queue[0]}/exercise").json()
    llm.queue(evaluation("incorrect", [WENT]))
    r = answer(client, rev["id"], "she went from São Paulo and stayed here every day")
    assert r["due_reviews"] == 2           # sem "sumir" da contagem
    assert due_ids(client) == [queue[1], queue[0]]  # volta para o fim da fila


def test_valid_translation_shows_the_target_when_answer_did_not_use_it(client, llm):
    add_words(client, "whatever")
    ex = new_ex(client, llm, "Eles vão fazer o que quiserem.", "They're gonna do whatever they want.", ("whatever",))
    # a IA sugere uma alternativa sem a palavra-alvo
    llm.queue(evaluation("correct", example="They're gonna do what they want."))
    r = answer(client, ex["id"], "they're gonna do what they want")
    usage = r["result"]["target_usage"][0]
    assert usage["demonstrated"] is False and usage["meaning_pt"] == "x"
    shown = r["result"]["alternative_en"] or r["result"]["natural_en"]  # a mesma frase aparece uma vez só
    assert shown == "They're gonna do whatever they want."


def test_valid_translation_unchanged_when_target_was_used(client, llm):
    add_words(client, "whatever")
    ex = new_ex(client, llm, "Eles vão fazer o que quiserem.", "They're gonna do whatever they want.", ("whatever",))
    llm.queue(evaluation("correct", example="They will do whatever they want."))
    r = answer(client, ex["id"], "they're gonna do whatever they like")
    assert r["result"]["alternative_en"] == "They will do whatever they want."


def test_natural_version_comes_from_the_portuguese_not_from_the_answer(client, llm):
    add_words(client, "tired")
    ex = new_ex(client, llm)
    llm.queue(evaluation("incorrect", [DIDNT_ERROR], example="I didn't play yesterday because I was tired.",
                         natural="I didn't play yesterday 'cause I was really tired."))
    r = answer(client, ex["id"], "I didn't played yesterday because I was tired")
    assert r["result"]["corrected_answer"] == "I didn't play yesterday because I was tired"
    assert r["result"]["natural_en"] == "I didn't play yesterday 'cause I was really tired."


def test_natural_version_hidden_when_it_repeats_what_is_shown(client, llm):
    add_words(client, "tired")
    ex = new_ex(client, llm)
    llm.queue(evaluation("incorrect", [DIDNT_ERROR], natural="I didn't play yesterday because I was tired."))
    r = answer(client, ex["id"], "I didn't played yesterday because I was tired")
    assert r["result"]["natural_en"] is None


def test_natural_version_falls_back_to_the_reference(client, llm):
    add_words(client, "tired")
    ex = new_ex(client, llm)
    llm.queue(evaluation("correct", example="I didn't play yesterday as I was tired."))
    r = answer(client, ex["id"], "I didn't play yesterday since I was tired")
    assert r["result"]["natural_en"] == "I didn't play yesterday because I was tired."


def test_natural_version_replaces_an_equal_valid_translation(client, llm):
    add_words(client, "tired")
    ex = new_ex(client, llm)
    llm.queue(evaluation("incorrect", [DIDNT_ERROR], example="I didn't play yesterday 'cause I was so tired.",
                         natural="I didn't play yesterday 'cause I was so tired."))
    r = answer(client, ex["id"], "I didn't played yesterday because I was tired")
    assert r["result"]["alternative_en"] is None
    assert r["result"]["natural_en"] == "I didn't play yesterday 'cause I was so tired."


def test_overlapping_corrections_are_applied_once(client, llm):
    add_words(client, "old")
    ex = new_ex(client, llm, "Ela tem 25 anos.", "She is 25 years old.", ("old",))
    llm.queue(evaluation("incorrect", [
        {"category": "grammar", "topic_id": "other", "excerpt": "has 25 years", "correction": "is 25 years old",
         "explanation_pt": "Idade usa be."},
        {"category": "lexical", "topic_id": "other", "excerpt": "25 years", "correction": "25 years old",
         "explanation_pt": "Falta old."},
    ]))
    r = answer(client, ex["id"], "She has 25 years")
    assert r["result"]["corrected_answer"] == "She is 25 years old"


def test_possessive_pronouns_are_not_plurals():
    assert not target_demonstrated("theirs", "They ate their parents' bread.")
    assert target_demonstrated("theirs", "The house is theirs.")
    assert not target_demonstrated("its", "It is late.")
    assert not target_demonstrated("yours", "Is this your bag?")
    assert target_demonstrated("play", "She plays every day.")  # verbos continuam aceitando flexões


def _word_and_sentence_reviews(client, llm):
    """Fila com uma revisão de palavra (look for) e, depois dela, uma de frase."""
    add_words(client, "look for")
    ex = new_ex(client, llm, "Eu estou procurando minhas chaves.", "I am looking for my keys.", ("look for",))
    llm.queue(evaluation("incorrect", [{"category": "lexical", "topic_id": "other", "excerpt": "looking at",
                                        "correction": "looking for", "explanation_pt": "x"}]))
    answer(client, ex["id"], "I am looking at my keys")
    ex = new_ex(client, llm, "Ela procurou o gato ontem.", "She looked for the cat yesterday.", ("look for",))
    llm.queue(evaluation("incorrect", [{"category": "grammar", "topic_id": "past_simple", "excerpt": "the cat today",
                                        "correction": "the cat yesterday", "explanation_pt": "x"}]))
    answer(client, ex["id"], "She looked for the cat today")  # erro fora da palavra: revisão da frase
    queue = due_ids(client)
    assert len(queue) == 2
    llm.queue(prompt("Ela está procurando o celular.", "She is looking for her phone.", ("look for",)))
    rev = client.post(f"/api/recall/reviews/{queue[0]}/exercise").json()
    return queue, rev


def test_word_review_wrong_elsewhere_goes_to_the_back_of_the_queue(client, llm):
    queue, rev = _word_and_sentence_reviews(client, llm)
    # usou "looking for" certo, errou outra coisa: a palavra não falhou, mas dá a vez à outra revisão
    llm.queue(evaluation("incorrect", [{"category": "grammar", "topic_id": "articles", "excerpt": "the phone",
                                        "correction": "her phone", "explanation_pt": "x"}]))
    answer(client, rev["id"], "She is looking for the phone")
    assert due_ids(client) == [queue[1], queue[0]]
    word = next(d for d in client.get("/api/recall/reviews/due").json()["due"] if d["id"] == queue[0])
    assert word["mistakes"] == 1  # não contou como erro da palavra


def test_uncertain_review_goes_to_the_back_of_the_queue(client, llm):
    queue, rev = _word_and_sentence_reviews(client, llm)
    llm.queue(evaluation("correct", confidence=0.2))
    answer(client, rev["id"], "She is looking for her cellphone")
    assert due_ids(client) == [queue[1], queue[0]]


def test_grammar_error_on_the_word_itself_fails_the_word_review(client, llm):
    queue, rev = _word_and_sentence_reviews(client, llm)
    llm.queue(evaluation("incorrect", [{"category": "grammar", "topic_id": "other", "excerpt": "looking for of",
                                        "correction": "looking for", "explanation_pt": "x"}]))
    answer(client, rev["id"], "She is looking for of her phone")
    assert due_ids(client) == [queue[1], queue[0]]
    word = next(d for d in client.get("/api/recall/reviews/due").json()["due"] if d["id"] == queue[0])
    assert word["mistakes"] == 2  # o erro estava na própria palavra


def test_word_review_does_not_reveal_the_word_before_the_answer(client, llm):
    add_words(client, "look for")
    ex = new_ex(client, llm, "Eu estou procurando minhas chaves.", "I am looking for my keys.", ("look for",))
    llm.queue(evaluation("incorrect", [{"category": "lexical", "topic_id": "other", "excerpt": "looking at",
                                        "correction": "looking for", "explanation_pt": "x"}]))
    answer(client, ex["id"], "I am looking at my keys")
    item_id = due_ids(client)[0]
    llm.queue(prompt("Ela está procurando o celular.", "She is looking for her phone.", ("look for",)))
    rev = client.post(f"/api/recall/reviews/{item_id}/exercise").json()
    assert rev["review"]["label_pt"] is None and "look for" not in str(rev)  # sem spoiler
    llm.queue(evaluation("correct"))
    r = answer(client, rev["id"], "She's looking for her cellphone")
    assert r["review"]["label_pt"] == "Uso de “look for” (x)"  # depois da resposta, mostra o que foi revisado
