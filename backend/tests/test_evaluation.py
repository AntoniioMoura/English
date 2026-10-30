"""Separação entre grammar_error e idea_improvement, deduplicação e proteção contra erros inventados."""

import sqlite3

from conftest import V, complete_versions, make_evaluation, new_exercise

from app.domain.evaluation import process_evaluation
from app.llm.schemas import LLMEvaluation, LLMFinalReview
from app.seed_data import GRAMMAR_TOPICS

TOPICS = {t[0] for t in GRAMMAR_TOPICS}


def process(versions, final_review=None, **raw):
    review = LLMFinalReview.model_validate(final_review) if final_review else None
    return process_evaluation(LLMEvaluation.model_validate(make_evaluation(**raw)), versions, TOPICS, review)


USER_CASE = [
    "i wanted to byu, but i don't have money",
    "i wanted to buy, but i don't have money because my mother died",
    "i wanted to buy a car, but i don't have money because my mother died this month",
    "i wanted to buy a car, but i don't have money because my mother died this month, so i will go to wait",
]


def make_review(**overrides) -> dict:
    base = {
        "phrase_checks": [
            {"phrase": "i wanted to buy a car", "is_correct": True},
            {"phrase": "but i don't have money", "is_correct": True},
            {"phrase": "because my mother died this month", "is_correct": True},
            {"phrase": "so i will go to wait", "is_correct": False, "correction": "so I will wait",
             "topic_id": "verb_forms", "explanation_pt": "Use 'will' + verbo base: 'will wait'."},
        ],
        "enrichment_comment_pt": "Conte por quanto tempo você vai esperar.",
        "enrichment_example_en": "I wanted to buy a car, but I don't have money because my mother died this month, "
                                 "so I will wait until next year.",
        "next_tip_pt": "Use 'although' para contrastar ideias.",
        "next_tip_example_en": "Although I was tired, I went to the gym.",
    }
    base.update(overrides)
    return base


def test_final_review_catches_missed_error_and_blocks_false_positive():
    result = process(
        USER_CASE,
        final_review=make_review(),
        grammar_errors=[  # a passada principal erra: inventa don't→didn't e não vê "go to wait"
            {"topic_id": "verb_tenses", "version_index": 0, "original_excerpt": "don't",
             "suggested_correction": "didn't", "explanation_pt": "Passado."},
        ],
    )
    shown = [(c.excerpt, c.correction) for c in result.feedback.grammar_corrections]
    assert shown == [("so i will go to wait", "so i will wait")]
    assert result.feedback.corrected_final_sentence == (
        "i wanted to buy a car, but i don't have money because my mother died this month, so i will wait"
    )
    assert {"contradicted_by_final_review", "optional_tense_shift"} & {d.reason for d in result.discarded}


def test_enrichment_must_show_the_users_sentence_expanded():
    result = process(USER_CASE, final_review=make_review())
    idea = result.feedback.idea_suggestions[0]
    assert idea.suggestion_en.endswith("so I will wait until next year.")

    # Se o modelo repetir o erro no exemplo, o backend corrige.
    repeated = process(USER_CASE, final_review=make_review(
        enrichment_example_en=USER_CASE[3] + " for a better time."))
    assert repeated.feedback.idea_suggestions[0].suggestion_en.endswith("so i will wait for a better time.")

    vague = process(
        USER_CASE,
        final_review=make_review(enrichment_example_en="You could explain more about your mother."),
        idea_development=[{"version_index": 3, "kind": "clarity", "is_positive": False,
                           "comment_pt": "Explique melhor.", "suggestion_en": "Explain how it affects you."}],
    )
    assert vague.feedback.idea_suggestions == []


def test_next_tip_never_suggests_a_connector_already_used():
    result = process(
        USER_CASE,
        final_review=make_review(next_tip_pt="Use 'because' e 'so' para conectar ideias."),
        next_tip="Revise o uso de 'because' e 'so'.",
    )
    assert "'because'" not in result.feedback.next_tip
    assert "'so'" not in result.feedback.next_tip
    assert result.feedback.next_tip_example


def test_tip_from_review_is_used_when_valid():
    result = process(USER_CASE, final_review=make_review())
    assert result.feedback.next_tip == "Use 'although' para contrastar ideias."
    assert result.feedback.next_tip_example == "Although I was tired, I went to the gym."


def test_simple_correct_sentence_has_no_errors():
    versions = [
        "I played Brawl Stars yesterday.",
        "I played Brawl Stars yesterday. It was fun.",
        "I played Brawl Stars with my brother yesterday. It was fun.",
        "I played Brawl Stars with my brother yesterday. It was fun, so we played again.",
    ]
    result = process(
        versions,
        final_review=make_review(
            phrase_checks=[{"phrase": "It was fun", "is_correct": True}],
            enrichment_example_en="I played Brawl Stars with my brother yesterday. It was fun, "
                                  "so we played again after dinner.",
        ),
        idea_development=[
            {
                "version_index": 1,
                "kind": "cohesion",
                "is_positive": False,
                "comment_pt": "Sua frase está correta. Você também pode conectar as ideias com 'and'.",
                "suggestion_en": "I played Brawl Stars yesterday, and I had a lot of fun.",
            }
        ],
    )
    assert result.grammar_errors == []
    assert result.final_is_correct is True
    assert result.feedback.corrected_final_sentence is None
    assert result.feedback.grammar_corrections == []
    assert [s.type for s in result.feedback.idea_suggestions] == ["improvement"]


def test_style_item_labelled_as_error_becomes_idea():
    result = process(
        V,
        grammar_errors=[
            {
                "topic_id": "connectors",
                "version_index": 0,
                "original_excerpt": "but I was tired",
                "suggested_correction": "but I felt exhausted",
                "explanation_pt": "Poderia soar mais natural.",
                "category": "style",
            }
        ],
    )
    assert result.grammar_errors == []
    assert result.final_is_correct
    assert result.ideas[0].rerouted_from_grammar
    assert result.ideas[0].is_positive is False


def test_invented_error_not_in_text_is_discarded():
    result = process(
        V,
        grammar_errors=[
            {
                "topic_id": "past_simple",
                "version_index": 3,
                "original_excerpt": "I goed to bed",
                "suggested_correction": "I went to bed",
                "explanation_pt": "Passado irregular.",
            }
        ],
    )
    assert result.grammar_errors == []
    assert result.discarded[0].reason == "excerpt_not_in_text"


def test_correction_equal_to_original_is_discarded():
    result = process(
        V,
        grammar_errors=[
            {
                "topic_id": "capitalization_punctuation",
                "version_index": 3,
                "original_excerpt": "after work so",
                "suggested_correction": "after work, so",
                "explanation_pt": "Vírgula.",
            }
        ],
    )
    assert result.grammar_errors == []


def test_capitalization_is_never_a_correction():
    versions = [
        "i wanted to buy a car, but i don't have money.",
        "i wanted to buy a car, but i don't have money this month.",
        "i wanted to buy a new car, but i don't have money this month.",
        "i wanted to buy a car, but i don't have money because my mother died this month",
    ]
    result = process(
        versions,
        grammar_errors=[
            {"topic_id": "capitalization_punctuation", "version_index": 3, "original_excerpt": "i don't have money",
             "suggested_correction": "I don't have money", "explanation_pt": "A palavra 'i' deve ser maiúscula."},
            {"topic_id": "pronouns", "version_index": 3, "original_excerpt": "i wanted to buy a car",
             "suggested_correction": "I wanted to buy a car", "explanation_pt": "A palavra 'i' deve ser maiúscula."},
        ],
        self_corrections=[
            {"topic_id": "pronouns", "from_version": 0, "to_version": 1, "before": "i wanted",
             "after": "I wanted", "explanation_pt": "x"},
        ],
    )
    assert result.grammar_errors == []
    assert result.self_corrections == []
    assert result.final_is_correct
    assert result.feedback.grammar_corrections == []
    assert result.feedback.corrected_final_sentence is None


def test_real_correction_keeps_user_capitalization():
    versions = ["i goes to school.", "i goes to school every day.", "i goes to school every day by bus.",
                "i goes to school every day by bus with my sister."]
    result = process(versions, grammar_errors=[
        {"topic_id": "subject_verb_agreement", "version_index": 0, "original_excerpt": "i goes",
         "suggested_correction": "I go", "explanation_pt": "Com 'I', use 'go'."}
    ])
    assert result.feedback.grammar_corrections[0].correction == "i go"
    assert result.feedback.corrected_final_sentence == "i go to school every day by bus with my sister."


def test_error_propagated_across_versions_counts_once():
    versions = [
        "I didn't went to school because I was sick.",
        "I didn't went to school yesterday because I was sick.",
        "I didn't went to school yesterday because I was very sick.",
        "I didn't went to school yesterday because I was very sick, so I stayed home.",
    ]
    error = {
        "topic_id": "auxiliaries_negation",
        "original_excerpt": "didn't went",
        "suggested_correction": "didn't go",
        "explanation_pt": "Depois de didn't, use o verbo na forma base: didn't go.",
        "severity": "high",
        "confidence": 0.95,
    }
    result = process(versions, grammar_errors=[{**error, "version_index": i} for i in range(4)])
    assert len(result.grammar_errors) == 1
    err = result.grammar_errors[0]
    assert err.version_index == 0 and err.persists_in_final
    assert result.final_is_correct is False
    assert result.feedback.corrected_final_sentence == (
        "I didn't go to school yesterday because I was very sick, so I stayed home."
    )
    assert result.feedback.grammar_corrections[0].type == "error"


def test_self_correction_is_recorded_and_not_an_unresolved_error():
    versions = [
        "I didn't went to school because I was sick.",
        "I didn't go to school because I was sick.",
        "I didn't go to school yesterday because I was sick.",
        "I didn't go to school yesterday because I was sick, so I slept.",
    ]
    result = process(
        versions,
        grammar_errors=[
            {
                "topic_id": "auxiliaries_negation",
                "version_index": 0,
                "original_excerpt": "didn't went",
                "suggested_correction": "didn't go",
                "explanation_pt": "Forma base depois de didn't.",
            }
        ],
        self_corrections=[
            {
                "topic_id": "auxiliaries_negation",
                "from_version": 0,
                "to_version": 1,
                "before": "didn't went",
                "after": "didn't go",
                "explanation_pt": "Você corrigiu sozinho!",
            }
        ],
    )
    assert result.final_is_correct
    assert result.grammar_errors[0].persists_in_final is False
    assert len(result.self_corrections) == 1
    assert result.feedback.self_corrections == ["didn't went → didn't go"]


def test_feedback_has_at_most_two_adjustments():
    versions = ["She go to school and he have a car."] + [
        f"She go to school and he have a car{'!' * i} Yes." for i in range(1, 4)
    ]
    errs = [
        {"topic_id": "subject_verb_agreement", "version_index": 0, "original_excerpt": "She go",
         "suggested_correction": "She goes", "explanation_pt": "a", "severity": "high"},
        {"topic_id": "subject_verb_agreement", "version_index": 0, "original_excerpt": "he have",
         "suggested_correction": "he has", "explanation_pt": "b", "severity": "medium"},
    ]
    ideas = [{"version_index": 3, "kind": "clarity", "is_positive": False, "comment_pt": "c"}]
    result = process(versions, grammar_errors=errs, idea_development=ideas)
    fb = result.feedback
    assert len(fb.grammar_corrections) + len(fb.idea_suggestions) <= 2
    assert fb.grammar_corrections[0].excerpt == "She go"


def test_low_confidence_error_is_not_shown():
    result = process(
        V,
        grammar_errors=[
            {"topic_id": "prepositions", "version_index": 2, "original_excerpt": "after work",
             "suggested_correction": "from work", "explanation_pt": "?", "confidence": 0.3}
        ],
    )
    assert result.final_is_correct
    assert result.grammar_errors[0].visible is False


def test_api_stores_errors_and_ideas_in_separate_tables(client, llm, db_path):
    ex = new_exercise(client)
    versions = [
        "I wanted to plays, but I was tired.",
        "I wanted to play with my friends, but I was tired.",
        "I wanted to play with my friends last night, but I was tired after work.",
        "I wanted to play with my friends last night, but I was tired after work, so I went to bed early.",
    ]
    complete_versions(client, ex["id"], versions)
    llm.queue(
        make_evaluation(
            grammar_errors=[
                {"topic_id": "verb_forms", "version_index": 0, "original_excerpt": "to plays",
                 "suggested_correction": "to play", "explanation_pt": "Depois de 'to', verbo base."}
            ],
            grammar_correct_evidence=[
                {"topic_id": "connectors", "version_index": 3, "excerpt": "so I went to bed early",
                 "explanation_pt": "Bom uso de 'so'."}
            ],
            self_corrections=[
                {"topic_id": "verb_forms", "from_version": 0, "to_version": 1, "before": "to plays",
                 "after": "to play", "explanation_pt": "Corrigiu."}
            ],
            idea_development=[
                {"version_index": 2, "kind": "relevant_expansion", "is_positive": True,
                 "comment_pt": "Acrescentou quando e por quê."},
                {"version_index": 3, "kind": "elaboration_opportunity", "is_positive": False,
                 "comment_pt": "Poderia dizer o que iam jogar.", "suggestion_en": "play football"},
            ],
        )
    )
    llm.queue_review(make_review(
        phrase_checks=[{"phrase": "so I went to bed early", "is_correct": True}],
        enrichment_example_en=versions[3].rstrip(".") + " and slept for ten hours.",
    ))
    state = client.post(f"/api/exercises/{ex['id']}/evaluate").json()
    assert state["status"] == "evaluated"
    fb = state["evaluation"]["feedback"]
    assert fb["final_is_correct"] is True
    assert fb["grammar_corrections"] == []
    assert fb["idea_suggestions"][0]["type"] == "improvement"

    conn = sqlite3.connect(db_path)
    kinds = dict(
        conn.execute(
            "SELECT evidence_type, COUNT(*) FROM grammar_observations WHERE exercise_id = ? GROUP BY evidence_type",
            (ex["id"],),
        ).fetchall()
    )
    assert kinds == {"error": 1, "correct": 1, "self_correction": 1}
    resolved = conn.execute(
        "SELECT resolved_in_final FROM grammar_observations WHERE evidence_type='error'"
    ).fetchone()[0]
    assert resolved == 1
    assert conn.execute("SELECT COUNT(*) FROM idea_observations").fetchone()[0] == 3  # 2 da passada principal + 1 da revisão focada
    # Nenhuma sugestão de ideia aparece como erro gramatical.
    assert conn.execute(
        "SELECT COUNT(*) FROM grammar_observations WHERE original_excerpt LIKE '%football%'"
    ).fetchone()[0] == 0
    model = conn.execute("SELECT model, schema_version FROM exercise_evaluations").fetchone()
    assert model == ("fake-model:1", 2)


def test_reevaluation_supersedes_previous_observations(client, llm, db_path):
    ex = new_exercise(client)
    complete_versions(client, ex["id"])
    err = {"topic_id": "prepositions", "version_index": 3, "original_excerpt": "after work",
           "suggested_correction": "from work", "explanation_pt": "x"}
    llm.queue(make_evaluation(grammar_errors=[err]), make_evaluation())
    client.post(f"/api/exercises/{ex['id']}/evaluate")
    state = client.post(f"/api/exercises/{ex['id']}/evaluate").json()
    assert state["evaluation"]["grammar_observations"] == []
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT review_status FROM grammar_observations").fetchall() == [("superseded",)]


def test_user_can_dismiss_an_observation(client, llm):
    ex = new_exercise(client)
    complete_versions(client, ex["id"])
    llm.queue(make_evaluation(grammar_errors=[
        {"topic_id": "prepositions", "version_index": 3, "original_excerpt": "after work",
         "suggested_correction": "from work", "explanation_pt": "x"}
    ]))
    state = client.post(f"/api/exercises/{ex['id']}/evaluate").json()
    obs_id = state["evaluation"]["grammar_observations"][0]["id"]
    r = client.patch(f"/api/observations/{obs_id}", json={"review_status": "dismissed"})
    assert r.status_code == 200 and r.json()["review_status"] == "dismissed"


def test_present_to_past_without_time_marker_is_not_an_error():
    """'but i don't have money' (ainda não tenho) é tão correto quanto 'didn't have' (não tinha)."""
    result = process(USER_CASE, grammar_errors=[
        {"topic_id": "past_simple", "version_index": 0, "original_excerpt": "i don't have money",
         "suggested_correction": "I didn't have money",
         "explanation_pt": "O verbo 'have' deve estar no passado para manter a consistência do tempo verbal."},
    ])
    assert result.grammar_errors == []
    assert result.feedback.grammar_corrections == []
    assert result.discarded[0].reason == "optional_tense_shift"


def test_present_with_past_time_marker_is_still_an_error():
    versions = ["Yesterday I don't go to school.", "Yesterday I don't go to school because I was sick.",
                "Yesterday I don't go to school because I was very sick.",
                "Yesterday I don't go to school because I was very sick, so I slept all day."]
    result = process(versions, grammar_errors=[
        {"topic_id": "past_simple", "version_index": 0, "original_excerpt": "I don't go",
         "suggested_correction": "I didn't go", "explanation_pt": "'Yesterday' pede passado."},
    ])
    assert [(c.excerpt, c.correction) for c in result.feedback.grammar_corrections] == [("I don't go", "I didn't go")]


def test_builder_feedback_has_score(client, llm):
    ex = new_exercise(client)
    complete_versions(client, ex["id"])
    llm.queue(make_evaluation(grammar_errors=[
        {"topic_id": "prepositions", "version_index": 3, "original_excerpt": "after work",
         "suggested_correction": "from work", "explanation_pt": "x"}]))
    state = client.post(f"/api/exercises/{ex['id']}/evaluate").json()
    assert 0 < state["evaluation"]["score"] < 100
