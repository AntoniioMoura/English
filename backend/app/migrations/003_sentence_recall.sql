-- Sentence Recall: vocabulário, flashcards de tradução, tentativas, revisão espaçada.

CREATE TABLE vocabulary_entries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    english_text     TEXT NOT NULL,
    normalized_text  TEXT NOT NULL,
    part_of_speech   TEXT,
    translation_pt   TEXT,
    notes            TEXT,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT                          -- exclusão lógica: o histórico continua íntegro
);
CREATE INDEX idx_vocab_normalized ON vocabulary_entries(normalized_text);

CREATE TABLE recall_exercises (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mode            TEXT NOT NULL,                 -- new | review
    review_item_id  INTEGER REFERENCES review_items(id),
    sentence_pt     TEXT NOT NULL,
    reference_en    TEXT NOT NULL,                 -- nunca exibida antes da resposta
    grammar_tags    TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL,                 -- pending_answer | awaiting_evaluation | evaluated
    model           TEXT NOT NULL,
    prompt_version  INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_recall_ex_status ON recall_exercises(mode, status);

CREATE TABLE recall_exercise_targets (
    exercise_id       INTEGER NOT NULL REFERENCES recall_exercises(id) ON DELETE CASCADE,
    vocabulary_id     INTEGER NOT NULL REFERENCES vocabulary_entries(id),
    english_text      TEXT NOT NULL,               -- cópia: sobrevive à edição da palavra
    intended_meaning  TEXT,                        -- sentido usado nesta frase
    PRIMARY KEY (exercise_id, vocabulary_id)
);

CREATE TABLE recall_attempts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id         INTEGER NOT NULL UNIQUE REFERENCES recall_exercises(id) ON DELETE CASCADE,
    idempotency_key     TEXT NOT NULL UNIQUE,
    answer_text         TEXT NOT NULL,
    verdict             TEXT,                      -- correct | incorrect | needs_review | NULL (avaliação pendente)
    counts_toward_quota INTEGER NOT NULL DEFAULT 0,
    local_date          TEXT NOT NULL,             -- dia no fuso do usuário (só para a cota)
    created_at          TEXT NOT NULL,
    evaluated_at        TEXT
);
CREATE INDEX idx_recall_attempts_quota ON recall_attempts(local_date, counts_toward_quota);

CREATE TABLE ai_evaluations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_mode     TEXT NOT NULL,                 -- sentence_recall
    attempt_id      INTEGER NOT NULL REFERENCES recall_attempts(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,                 -- completed | pending | rejected
    schema_version  INTEGER NOT NULL,
    model           TEXT NOT NULL,
    raw_result      TEXT,
    result          TEXT,
    error_message   TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_ai_eval_attempt ON ai_evaluations(attempt_id);

-- Mesmo catálogo de tópicos do Sentence Builder, com o modo identificado.
CREATE TABLE recall_observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_mode     TEXT NOT NULL DEFAULT 'sentence_recall',
    topic_id        TEXT NOT NULL REFERENCES grammar_topics(id),
    exercise_id     INTEGER NOT NULL REFERENCES recall_exercises(id) ON DELETE CASCADE,
    attempt_id      INTEGER NOT NULL REFERENCES recall_attempts(id) ON DELETE CASCADE,
    evidence_type   TEXT NOT NULL,                 -- error | correct
    category        TEXT,                          -- grammar | lexical | meaning | spelling
    excerpt         TEXT,
    correction      TEXT,
    explanation_pt  TEXT,
    review_status   TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_recall_obs_topic ON recall_observations(topic_id, evidence_type);

CREATE TABLE recall_target_usage (
    attempt_id     INTEGER NOT NULL REFERENCES recall_attempts(id) ON DELETE CASCADE,
    vocabulary_id  INTEGER NOT NULL REFERENCES vocabulary_entries(id),
    demonstrated   INTEGER NOT NULL,
    PRIMARY KEY (attempt_id, vocabulary_id)
);

CREATE TABLE review_items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type       TEXT NOT NULL,               -- grammar_topic | vocabulary_sense
    target_id         TEXT NOT NULL,
    label_pt          TEXT NOT NULL,
    status            TEXT NOT NULL,               -- learning | stable
    scheduler_state   TEXT NOT NULL,               -- JSON do agendador (substituível, ex.: FSRS)
    due_at            TEXT NOT NULL,
    examples          TEXT NOT NULL DEFAULT '[]',  -- erros reais relacionados
    last_event_local_date TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (target_type, target_id)
);
CREATE INDEX idx_review_due ON review_items(due_at);

CREATE TABLE review_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    review_item_id  INTEGER NOT NULL REFERENCES review_items(id) ON DELETE CASCADE,
    exercise_id     INTEGER REFERENCES recall_exercises(id) ON DELETE SET NULL,
    attempt_id      INTEGER REFERENCES recall_attempts(id) ON DELETE SET NULL,
    outcome         TEXT NOT NULL,                 -- created | reinforced | success | fail
    due_before      TEXT,
    due_after       TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_review_events_item ON review_events(review_item_id);
