-- Tradução gerada pelo Ollama local para vídeos sem legenda em português.
-- translation_source passa a aceitar 'ai'; o andamento fica aqui (NULL = nenhuma tradução em curso).
ALTER TABLE listening_videos ADD COLUMN translation_status TEXT;     -- running | error | NULL
ALTER TABLE listening_videos ADD COLUMN translation_progress REAL;
ALTER TABLE listening_videos ADD COLUMN translation_error TEXT;
