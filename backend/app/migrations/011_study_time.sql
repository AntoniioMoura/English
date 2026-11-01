-- Tempo de estudo por dia (no fuso das configurações) e por tipo de exercício.
CREATE TABLE study_time (
    local_date TEXT NOT NULL,
    activity TEXT NOT NULL,
    seconds INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (local_date, activity)
);
