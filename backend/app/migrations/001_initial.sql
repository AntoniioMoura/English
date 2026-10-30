-- Esquema inicial do English Builder (Fase 1, já preparado para a Fase 2).

CREATE TABLE sentence_frames (
    id              TEXT PRIMARY KEY,
    text            TEXT NOT NULL,
    explanation_pt  TEXT NOT NULL,
    level           TEXT NOT NULL,
    grammar_tags    TEXT NOT NULL DEFAULT '[]',   -- JSON: lista de topic_id
    examples        TEXT NOT NULL DEFAULT '[]',   -- JSON: lista de frases
    enabled         INTEGER NOT NULL DEFAULT 1,
    source          TEXT NOT NULL DEFAULT 'curated',
    created_at      TEXT NOT NULL
);

CREATE TABLE study_sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT NOT NULL,
    last_activity_at TEXT NOT NULL
);

CREATE TABLE exercises (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES study_sessions(id),
    frame_id        TEXT NOT NULL REFERENCES sentence_frames(id),
    mode            TEXT NOT NULL DEFAULT 'sentence_builder',
    selection_mode  TEXT NOT NULL,                -- manual | random
    status          TEXT NOT NULL,                -- in_progress | awaiting_evaluation | evaluated
    started_at      TEXT NOT NULL,
    completed_at    TEXT
);
CREATE INDEX idx_exercises_status ON exercises(status);

CREATE TABLE sentence_versions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id    INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    version_index  INTEGER NOT NULL CHECK (version_index BETWEEN 0 AND 3),
    text           TEXT NOT NULL,
    hints_opened   INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    UNIQUE (exercise_id, version_index)
);

-- Dicas pedidas por etapa (stage = índice da versão que está sendo escrita).
CREATE TABLE hint_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id  INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    stage        INTEGER NOT NULL CHECK (stage BETWEEN 1 AND 3),
    base_text    TEXT NOT NULL,
    hints        TEXT NOT NULL,                   -- JSON: lista de dicas
    model        TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_hint_requests_exercise ON hint_requests(exercise_id, stage);

CREATE TABLE exercise_evaluations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id     INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,                -- ok | failed
    schema_version  INTEGER NOT NULL,
    model           TEXT NOT NULL,
    raw_result      TEXT,                         -- JSON devolvido pela IA (validado)
    result          TEXT,                         -- JSON pós-processado pelo backend
    error_message   TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_evaluations_exercise ON exercise_evaluations(exercise_id);

CREATE TABLE grammar_topics (
    id              TEXT PRIMARY KEY,
    name_pt         TEXT NOT NULL,
    description_pt  TEXT NOT NULL
);

CREATE TABLE grammar_observations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id              TEXT NOT NULL REFERENCES grammar_topics(id),
    exercise_id           INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    evaluation_id         INTEGER NOT NULL REFERENCES exercise_evaluations(id) ON DELETE CASCADE,
    version_index         INTEGER NOT NULL CHECK (version_index BETWEEN 0 AND 3),
    evidence_type         TEXT NOT NULL,          -- error | correct | self_correction | not_assessed
    original_excerpt      TEXT NOT NULL,
    suggested_correction  TEXT,
    explanation_pt        TEXT NOT NULL,
    severity              TEXT,                   -- low | medium | high (apenas erros)
    confidence            REAL NOT NULL,
    resolved_in_final     INTEGER NOT NULL DEFAULT 0,
    review_status         TEXT NOT NULL,          -- pending | uncertain | confirmed | dismissed | superseded
    created_at            TEXT NOT NULL
);
CREATE INDEX idx_grammar_obs_topic ON grammar_observations(topic_id, evidence_type);
CREATE INDEX idx_grammar_obs_exercise ON grammar_observations(exercise_id);

-- Desenvolvimento de ideias: nunca é contado como erro gramatical.
CREATE TABLE idea_observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id     INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    evaluation_id   INTEGER NOT NULL REFERENCES exercise_evaluations(id) ON DELETE CASCADE,
    version_index   INTEGER,
    kind            TEXT NOT NULL,                -- relevant_expansion | cohesion | clarity | connector_variety | elaboration_opportunity | naturalness
    is_positive     INTEGER NOT NULL,
    comment_pt      TEXT NOT NULL,
    suggestion_en   TEXT,
    review_status   TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_idea_obs_exercise ON idea_observations(exercise_id);

-- Fase 2: relatórios gerados sob demanda.
CREATE TABLE learning_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start  TEXT NOT NULL,
    period_end    TEXT NOT NULL,
    model         TEXT NOT NULL,
    metrics       TEXT NOT NULL,                  -- JSON calculado pelo backend
    content_md    TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE app_settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
