"""Relatório: métricas calculadas no backend com os mesmos critérios de erro da avaliação."""

from conftest import V, complete_versions, make_evaluation, new_exercise

from app.domain.report_metrics import compute_report, topic_state
from app.llm.client import LLMError

PERIOD = {"key": "all", "label": "Todo o histórico", "start": None, "end": "2026-12-31T00:00:00+00:00"}
FINAL = "I wanted to buy a car, but I don't have money, so I will wait."


def exercise(id, day="2026-10-20", session=1):
    return {"id": id, "session_id": session, "started_at": f"{day}T15:00:00+00:00",
            "completed_at": f"{day}T15:10:00+00:00"}


def versions(ex_id, final=FINAL, hints=(False, True, False)):
    texts = ["I wanted to buy.", "I wanted to buy a car.", "I wanted to buy a car, but I don't have money.", final]
    return [{"exercise_id": ex_id, "version_index": i, "text": t, "hints_opened": i > 0 and hints[i - 1]}
            for i, t in enumerate(texts)]


_ids = iter(range(1, 10_000))


def obs(ex_id, topic, kind, excerpt="x", correction=None, review="pending", version=3, resolved=0):
    return {"id": next(_ids), "exercise_id": ex_id, "topic_id": topic, "version_index": version,
            "evidence_type": kind, "original_excerpt": excerpt, "suggested_correction": correction,
            "explanation_pt": "explicação", "review_status": review, "resolved_in_final": resolved}


def report(exercises, grammar=(), ideas=(), vers=None):
    vers = vers if vers is not None else [v for e in exercises for v in versions(e["id"])]
    return compute_report(PERIOD, list(exercises), vers, list(grammar), list(ideas), {"verb_forms": "Formas verbais"})


def test_report_applies_current_error_rules_to_old_observations():
    data = report(
        [exercise(1)],
        grammar=[
            obs(1, "capitalization_punctuation", "error", "i wanted", "I wanted"),
            obs(1, "pronouns", "error", "i don't", "I don't"),                       # só maiúscula
            obs(1, "past_simple", "error", "I don't have", "I didn't have"),          # tempo opcional
            obs(1, "prepositions", "error", "in monday", "on monday", review="dismissed"),
            obs(1, "articles", "error", "a apple", "an apple", review="uncertain"),
            obs(1, "verb_forms", "error", "will go to wait", "will wait"),            # erro real
        ],
    )
    assert [(t["topic_id"], t["errors"]) for t in data["topics"]] == [("verb_forms", 1)]
    assert data["totals"]["grammar_errors"] == 1
    assert data["totals"]["dismissed_by_you"] == 1


def test_ideas_never_count_as_grammar_errors():
    data = report(
        [exercise(1)],
        ideas=[
            {"id": 1, "exercise_id": 1, "version_index": 3, "kind": "elaboration_opportunity", "is_positive": False,
             "comment_pt": "Diga por quanto tempo.", "suggestion_en": FINAL[:-1] + " until next year."},
            {"id": 2, "exercise_id": 1, "version_index": 3, "kind": "clarity", "is_positive": False,
             "comment_pt": "Explique melhor.", "suggestion_en": "Explain how you feel."},  # vago: não entra
            {"id": 3, "exercise_id": 1, "version_index": 2, "kind": "relevant_expansion", "is_positive": True,
             "comment_pt": "Boa.", "suggestion_en": None},
        ],
    )
    assert data["totals"]["grammar_errors"] == 0 and data["topics"] == []
    assert [e["suggestion_en"] for e in data["elaboration_examples"]] == [FINAL[:-1] + " until next year."]
    assert data["totals"]["relevant_expansion_rate"] == 0.5  # 1 relevante entre 2 expansões avaliadas
    assert data["totals"]["hint_rate"] == round(1 / 3, 3)
    assert data["totals"]["distinct_connectors"] == ["but", "so"]


def test_topic_states():
    assert topic_state([True, False], correct_days=1) == "dados_insuficientes"
    assert topic_state([True, True, False], correct_days=1) == "precisa_de_atencao"
    assert topic_state([True, True, False, False], correct_days=1) == "em_evolucao"
    assert topic_state([False, False, True, False, False], correct_days=2) == "consistente"
    # poucos acertos num único dia não bastam para "consistente"
    assert topic_state([False, False, False, False], correct_days=1) == "revisar"


def test_consistent_requires_correct_uses_on_different_days():
    exercises = [exercise(i, day=f"2026-10-{20 + i}") for i in range(1, 5)]
    grammar = [obs(i, "verb_forms", "correct", "wanted to buy") for i in range(1, 5)]
    data = report(exercises, grammar=grammar)
    assert data["topics"][0]["state"] == "consistente"
    assert data["totals"]["study_days"] == 4
    assert len(data["weekly"]) >= 1


def test_small_sample_is_flagged():
    data = report([exercise(1)], grammar=[obs(1, "verb_forms", "error", "will go to wait", "will wait")])
    assert data["topics"][0]["state"] == "dados_insuficientes"
    assert any("Amostra pequena" in item for item in data["limitations"])
    assert any("CEFR" in item for item in data["limitations"])


# ---------- API ----------

NARRATIVE = {
    "summary_pt": "Você praticou bem.",
    "strengths_pt": ["Boas expansões."],
    "errors_comment_pt": "Atenção a 'after work'.",
    "elaboration_comment_pt": "Use mais detalhes.",
    "evolution_comment_pt": "Ainda é cedo.",
    "next_topics": [{"topic_id": "prepositions", "reason_pt": "Pratique."},
                    {"topic_id": "inventado", "reason_pt": "x"}],
}


def finish_evaluated(client, llm, errors=()):
    ex = new_exercise(client)
    complete_versions(client, ex["id"])
    llm.queue(make_evaluation(grammar_errors=list(errors)))
    client.post(f"/api/exercises/{ex['id']}/evaluate")
    return ex


def test_report_requires_finished_studies(client, llm):
    ex = new_exercise(client)
    client.post(f"/api/exercises/{ex['id']}/versions", json={"version_index": 0, "text": V[0]})
    r = client.post("/api/reports", json={"period": "all"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_data"


def test_generate_list_export_and_delete_report(client, llm):
    finish_evaluated(client, llm, errors=[
        {"topic_id": "prepositions", "version_index": 3, "original_excerpt": "after work",
         "suggested_correction": "from work", "explanation_pt": "Preposição."}
    ])
    llm.queue(NARRATIVE)
    r = client.post("/api/reports", json={"period": "30d"})
    assert r.status_code == 201, r.text
    report = r.json()
    assert report["status"] == "complete"
    data = report["data"]
    assert data["totals"]["exercises"] == 1 and data["totals"]["grammar_errors"] == 1
    assert [n["topic_id"] for n in data["narrative"]["next_topics"]] == ["prepositions"]  # inventado descartado

    # A IA recebe os números prontos; não os produz.
    assert '"grammar_errors": 1' in llm.calls[-1][1]

    assert [x["id"] for x in client.get("/api/reports").json()] == [report["id"]]
    md = client.get(f"/api/reports/{report['id']}/markdown")
    assert md.status_code == 200 and "attachment" in md.headers["content-disposition"]
    assert "## Oportunidades de elaboração" in md.text and "~~after work~~ → **from work**" in md.text

    assert client.delete(f"/api/reports/{report['id']}").status_code == 204
    assert client.get(f"/api/reports/{report['id']}").status_code == 404


def test_report_is_saved_with_numbers_when_ai_fails(client, llm):
    finish_evaluated(client, llm)
    llm.queue(LLMError("a"), LLMError("b"))
    report = client.post("/api/reports", json={"period": "all"}).json()
    assert report["status"] == "numbers_only"
    assert report["narrative_error"] == "b"
    assert report["data"]["narrative"] is None
    assert "Estudos concluídos | 1" in report["content_md"]


def test_error_fixed_before_the_final_sentence_counts_as_self_correction():
    data = report([exercise(1)], grammar=[
        obs(1, "spelling", "error", "i wanted to byu", "i wanted to buy", version=0, resolved=1),
        obs(1, "spelling", "self_correction", "byu", "buy", version=1, resolved=1),
        obs(1, "verb_forms", "error", "will go to wait", "will wait"),
    ])
    assert [(t["topic_id"], t["errors"]) for t in data["topics"]] == [("verb_forms", 1)]
    assert data["totals"]["self_corrections"] == 1


def test_expansion_rate_is_empty_when_ai_did_not_assess_expansions():
    assert report([exercise(1)])["totals"]["relevant_expansion_rate"] is None


def test_elaboration_example_does_not_repeat_the_error():
    final = "so I will go to wait, but I don't have money now."
    data = report(
        [exercise(1)],
        vers=versions(1, final=final),
        grammar=[obs(1, "verb_forms", "error", "will go to wait", "will wait")],
        ideas=[{"id": 9, "exercise_id": 1, "version_index": 3, "kind": "elaboration_opportunity",
                "is_positive": False, "comment_pt": "Diga até quando.",
                "suggestion_en": "so I will go to wait, but I don't have money now, until next year."}],
    )
    assert data["elaboration_examples"][0]["suggestion_en"] == (
        "so I will wait, but I don't have money now, until next year."
    )


def test_narrative_sentences_with_numbers_are_removed():
    from app.domain.report_markdown import without_numbers
    text = "Você fez 1 estudo em 1 dia. Seu uso de conectores foi bom. Taxa de 100%."
    assert without_numbers(text) == "Seu uso de conectores foi bom."
    assert without_numbers("Foram 3 estudos.", "padrão") == "padrão"


def test_errors_comment_cannot_present_a_self_correction_as_error():
    from app.domain.report_markdown import grounded_errors_comment
    data = report([exercise(1)], grammar=[
        obs(1, "spelling", "error", "byu", "buy", version=0, resolved=1),
        obs(1, "verb_forms", "error", "will go to wait", "will wait"),
    ])
    text = ("Ainda aparece o erro de usar 'byu' em vez de 'buy'. Esse erro é recorrente. "
            "Atenção a 'will go to wait', o certo é 'will wait'.")
    assert grounded_errors_comment(text, data) == "Atenção a 'will go to wait', o certo é 'will wait'."


def test_errors_comment_without_real_citation_falls_back_to_data():
    from app.domain.report_markdown import grounded_errors_comment
    data = report([exercise(1)], grammar=[obs(1, "verb_forms", "error", "will go to wait", "will wait")])
    assert grounded_errors_comment("Isso mostra que você está aprendendo.", data) == (
        "Na frase final ainda apareceram: “will go to wait” → “will wait”."
    )


# ---------- relatório combinado: Criador de frases + Anki Premium ----------

def recall_wrong(client, llm):
    r = client.post("/api/recall/vocabulary", json={"entries": [{"english_text": "from"}]})
    assert r.status_code == 201
    llm.queue({"targets": [{"english_text": "from", "meaning_pt": "de"}],
               "sentence_pt": "Ela veio de São Paulo.", "reference_en": "She came from São Paulo.",
               "grammar_tags": ["past_simple"]})
    ex = client.post("/api/recall/exercises").json()
    llm.queue({"error_events": [{"category": "lexical", "topic_id": "past_simple", "excerpt": "went",
                                 "correction": "came", "explanation_pt": "x", "rule_pt": "vir = come/came"}],
               "meaning_match": False, "grammar_valid": True, "verdict": "incorrect", "confidence": 0.9})
    client.post(f"/api/recall/exercises/{ex['id']}/answer",
                json={"answer": "She went from São Paulo", "idempotency_key": "rep-key-1"})


def test_report_with_only_anki_premium_data(client, llm):
    recall_wrong(client, llm)
    llm.queue({**NARRATIVE, "recall_comment_pt": "Atenção a 'went' para 'veio'. Você sempre erra 'xyz'."})
    report = client.post("/api/reports", json={"period": "all"}).json()
    data = report["data"]
    assert data["has_builder"] is False
    r = data["recall"]
    assert r["attempts"] == 1 and r["new"] == {"incorrect": 1}
    assert r["recurring_errors"][0]["excerpt"] == "went" and r["recurring_errors"][0]["count"] == 1
    assert r["avg_score"] is not None and r["avg_score"] < 100
    # o comentário só pode citar erros reais; seção do Criador de frases diz que não houve estudos
    assert data["narrative"]["recall_comment_pt"] == "Atenção a 'went' para 'veio'."
    assert data["narrative"]["errors_comment_pt"] == "Nenhum estudo do Criador de frases no período."
    assert "## Anki Premium" in report["content_md"] and "~~went~~ → **came** (1x)" in report["content_md"]


def test_report_combines_both_modes_without_mixing_metrics(client, llm):
    finish_evaluated(client, llm)
    recall_wrong(client, llm)
    llm.queue(NARRATIVE)
    data = client.post("/api/reports", json={"period": "all"}).json()["data"]
    assert data["has_builder"] and data["totals"]["exercises"] == 1
    assert data["recall"]["attempts"] == 1
    # erros do Anki Premium não entram na precisão do Criador de frases
    assert data["totals"]["grammar_errors"] == 0
    assert '"anki_premium"' in llm.calls[-1][1]


def test_generic_recall_comment_falls_back_to_real_errors():
    from app.domain.report_markdown import grounded_recall_comment
    recall = {"recurring_errors": [{"excerpt": "went", "correction": "came", "sentence_pt": "Ela veio.",
                                    "rule_pt": "", "count": 2}],
              "words": {"not_used_examples": []}}
    out = grounded_recall_comment("A tradução é diferente da criação de frases livremente.", recall)
    assert "“went” → “came”" in out
