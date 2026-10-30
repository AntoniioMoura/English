-- Downloads do YouTube para a pasta videos/ (yt-dlp). O vídeo baixado entra no catálogo como qualquer outro.

CREATE TABLE listening_downloads (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    url            TEXT NOT NULL,
    youtube_id     TEXT NOT NULL,
    category       TEXT NOT NULL DEFAULT '',
    max_height     INTEGER NOT NULL DEFAULT 720,
    status         TEXT NOT NULL DEFAULT 'queued',  -- queued | downloading | done | error
    stage          TEXT,
    progress       REAL,
    title          TEXT,
    rel_path       TEXT,
    video_id       INTEGER REFERENCES listening_videos(id) ON DELETE SET NULL,
    error_message  TEXT,
    dismissed      INTEGER NOT NULL DEFAULT 0,      -- some da lista da tela; o vídeo continua no catálogo
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX idx_listening_downloads_yt ON listening_downloads(youtube_id, status);
