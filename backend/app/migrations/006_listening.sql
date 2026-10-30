-- Listening com vídeos locais: catálogo, cache do processamento, trechos, sessões e tentativas por palavra.

CREATE TABLE listening_videos (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path              TEXT NOT NULL UNIQUE,      -- relativo a videos/, com "/"
    category              TEXT NOT NULL DEFAULT '',  -- primeira subpasta ('' = raiz)
    title                 TEXT,                      -- editado pelo usuário; NULL = nome do arquivo
    file_size             INTEGER NOT NULL,
    file_mtime            REAL NOT NULL,
    fingerprint           TEXT NOT NULL,             -- tamanho + hash do início e do fim do arquivo
    present               INTEGER NOT NULL DEFAULT 1,-- 0 = arquivo sumiu da pasta; o histórico fica
    -- metadados (ffprobe) e miniatura: preenchidos em segundo plano logo após a varredura
    meta_fingerprint      TEXT,
    duration              REAL,
    width                 INTEGER,
    height                INTEGER,
    video_codec           TEXT,
    audio_codec           TEXT,
    probe_json            TEXT,
    thumbnail_path        TEXT,
    -- preparação para o estudo (legendas + versão compatível): só quando o usuário abre o vídeo
    status                TEXT NOT NULL DEFAULT 'unprocessed', -- unprocessed | processing | ready | error
    stage                 TEXT,
    progress              REAL,
    error_message         TEXT,
    processed_fingerprint TEXT,
    pipeline_version      INTEGER,
    processing_rev        INTEGER NOT NULL DEFAULT 0,  -- muda a cada novo conjunto de trechos
    playback_path         TEXT,                      -- NULL = o original já toca no navegador
    subtitle_source       TEXT,                      -- external | embedded | whisper
    translation_source    TEXT,                      -- external | embedded | NULL
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
CREATE INDEX idx_listening_videos_fp ON listening_videos(fingerprint);

CREATE TABLE listening_segments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER NOT NULL REFERENCES listening_videos(id) ON DELETE CASCADE,
    processing_rev  INTEGER NOT NULL,
    idx             INTEGER NOT NULL,
    start           REAL NOT NULL,
    end             REAL NOT NULL,
    text            TEXT NOT NULL,
    translation_pt  TEXT,
    original_text   TEXT NOT NULL,                -- como veio da legenda/transcrição
    original_start  REAL NOT NULL,
    original_end    REAL NOT NULL,
    edited          INTEGER NOT NULL DEFAULT 0,
    flagged         INTEGER NOT NULL DEFAULT 0,   -- usuário marcou "legenda não corresponde ao áudio"
    active          INTEGER NOT NULL DEFAULT 1,   -- 0 = substituído por um reprocessamento
    updated_at      TEXT NOT NULL
);
CREATE INDEX idx_listening_segments_video ON listening_segments(video_id, active, idx);

CREATE TABLE listening_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER NOT NULL REFERENCES listening_videos(id) ON DELETE CASCADE,
    difficulty      TEXT NOT NULL,                -- beginner | easy | medium | hard
    mode            TEXT NOT NULL DEFAULT 'normal', -- normal | review
    processing_rev  INTEGER NOT NULL,
    seed            INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active', -- active | finished | abandoned
    current_index   INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    finished_at     TEXT
);
CREATE INDEX idx_listening_sessions_video ON listening_sessions(video_id, status);

-- Lacunas escolhidas ao criar a sessão: estáveis ao recarregar, independentes dos dados processados.
CREATE TABLE listening_session_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES listening_sessions(id) ON DELETE CASCADE,
    segment_id     INTEGER NOT NULL REFERENCES listening_segments(id),
    position       INTEGER NOT NULL,
    text_snapshot  TEXT NOT NULL,                 -- texto usado para escolher as lacunas
    blanks         TEXT NOT NULL,                 -- JSON: índices das palavras ocultas
    status         TEXT NOT NULL DEFAULT 'pending', -- pending | done | skipped
    replays        INTEGER NOT NULL DEFAULT 0,
    completed_at   TEXT,
    UNIQUE (session_id, position)
);

CREATE TABLE listening_word_attempts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES listening_sessions(id) ON DELETE CASCADE,
    item_id        INTEGER NOT NULL REFERENCES listening_session_items(id) ON DELETE CASCADE,
    video_id       INTEGER NOT NULL REFERENCES listening_videos(id) ON DELETE CASCADE,
    segment_id     INTEGER NOT NULL REFERENCES listening_segments(id),
    word_index     INTEGER NOT NULL,
    expected       TEXT NOT NULL,
    expected_norm  TEXT NOT NULL,
    typed          TEXT,                          -- NULL quando a palavra foi revelada
    is_correct     INTEGER NOT NULL,
    used_help      INTEGER NOT NULL DEFAULT 0,
    replays        INTEGER NOT NULL DEFAULT 0,    -- repetições do trecho até esta tentativa
    segment_start  REAL NOT NULL,
    segment_text   TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX idx_listening_attempts_word ON listening_word_attempts(expected_norm);
CREATE INDEX idx_listening_attempts_item ON listening_word_attempts(item_id, word_index);
