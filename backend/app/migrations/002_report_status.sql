-- Relatórios: rótulo do período e se a análise em texto da IA foi gerada.
ALTER TABLE learning_reports ADD COLUMN period_label TEXT NOT NULL DEFAULT '';
ALTER TABLE learning_reports ADD COLUMN status TEXT NOT NULL DEFAULT 'complete';  -- complete | numbers_only
ALTER TABLE learning_reports ADD COLUMN narrative_error TEXT;
