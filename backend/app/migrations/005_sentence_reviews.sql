-- Revisão por frase: erros fora das palavras registradas passam a ser revisados com a MESMA frase.
-- As unidades antigas por tópico gramatical e por erro específico são substituídas; o backfill da
-- inicialização recria uma revisão por frase errada. Frases, respostas e avaliações não são tocadas.

UPDATE recall_exercises SET status = 'skipped'
 WHERE status = 'pending_answer'
   AND review_item_id IN (SELECT id FROM review_items WHERE target_type IN ('grammar_topic', 'mistake'));

UPDATE recall_exercises SET review_item_id = NULL
 WHERE review_item_id IN (SELECT id FROM review_items WHERE target_type IN ('grammar_topic', 'mistake'));

DELETE FROM review_events
 WHERE review_item_id IN (SELECT id FROM review_items WHERE target_type IN ('grammar_topic', 'mistake'));

DELETE FROM review_items WHERE target_type IN ('grammar_topic', 'mistake');
