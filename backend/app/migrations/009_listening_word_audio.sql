-- Por palavra da fala, o que o Whisper ouviu no áudio: "heard" | "misheard" | "unheard" | "filler" | null.
-- NULL na coluna = não verificado (transcrição do próprio Whisper ou texto corrigido à mão: tudo vale).
-- Só palavras ouvidas viram lacuna; "unheard" aparece riscada (a legenda tem, a fala não).
ALTER TABLE listening_segments ADD COLUMN word_audio TEXT;
