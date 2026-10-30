-- Ritmo da sessão: uma frase-exercício a cada ~N segundos; o resto do vídeo corre com a legenda completa.
-- 0 = todas as frases (comportamento das sessões criadas antes desta migração).
ALTER TABLE listening_sessions ADD COLUMN interval_seconds INTEGER NOT NULL DEFAULT 0;
