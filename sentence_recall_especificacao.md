# English Builder — Extensão: Sentence Recall

## 1. Objetivo e escopo

Adicionar ao **English Builder** um modo de estudo chamado **Sentence Recall**, inspirado em flashcards interativos. O usuário cadastra palavras ou expressões **em inglês**; a IA local (Ollama) cria frases curtas **em português** que utilizam seus significados. O usuário traduz cada frase para inglês sem consultar uma resposta pronta.

**Propósito:** treinar recuperação ativa, vocabulário em contexto e construção de frases simples (A2 → B1). Corrigir tentativas, registrar evidências de acertos/erros e revisar dificuldades com repetição espaçada.

Este arquivo é uma **especificação complementar** ao `english_builder_especificacao.md`. Reaproveitar a stack existente (**React + TypeScript + Vite; FastAPI + Pydantic; SQLite; Ollama local**), autenticação/configurações quando houver e o painel geral de aprendizagem. **Não alterar o fluxo de quatro versões do Sentence Builder.**

## 2. Navegação

Adicionar **Sentence Recall** ao menu inicial, ao lado de Sentence Builder. Dentro dele, disponibilizar:

- **Minhas palavras:** cadastrar, editar, ativar/desativar e excluir palavras ou expressões em inglês; importação em lote por linhas (opcional no MVP).
- **Praticar:** resolver frases novas, enquanto o limite diário permitir.
- **Revisar:** estudar as dificuldades agendadas, mesmo após atingir o limite de frases novas.
- **Histórico e progresso:** ver tentativas, palavras praticadas e tópicos com dificuldade; integrar os dados ao painel geral.

Interface em **pt-BR**. Frases para traduzir em português; respostas digitadas em inglês.

## 3. Cadastro e seleção do vocabulário

Cada entrada do vocabulário deve possuir `id`, `english_text`, `part_of_speech` (opcional), `translation_pt` (opcional), `notes` (opcional), `enabled` e datas.

- Aceitar uma palavra ou expressão curta: `tired`, `because`, `didn't`, `have to`, `look for`.
- Permitir que o usuário informe a tradução/sentido preferido; quando não informar, a IA identifica um significado adequado ao contexto e salva o sentido usado na atividade.
- Não pressupor correspondência única entre palavras nos dois idiomas: `get`, `have`, `since` etc. variam conforme o contexto.
- Evitar duplicações normalizadas; permitir sentidos distintos para a mesma palavra quando necessário.
- Ao gerar exercício novo, escolher uma ou poucas entradas ativas, sem exigir que todas apareçam na mesma frase. Variar vocabulário, estruturas e contextos.
- Registrar as entradas-alvo utilizadas em cada exercício para avaliar seu uso posteriormente.

## 4. Fluxo de um flashcard

1. Usuário seleciona **Praticar** ou **Revisar**.
2. Backend seleciona os alvos adequados. Em **Praticar**, solicita ao Ollama uma frase **simples, natural e sem ambiguidade excessiva**, em português, com tradução de referência em inglês e metadados dos alvos.
3. Exibir **apenas a frase em português** e um campo de resposta. Nunca mostrar a tradução de referência antes da tentativa.
4. Usuário digita sua tradução e envia.
5. Ollama avalia a **equivalência de sentido** e a **correção do inglês**; o backend valida o resultado estruturado.
6. Mostrar feedback curto: acerto reconhecido, no máximo dois pontos de correção e uma tradução válida quando útil. Botão **Próxima frase**.
7. Salvar tentativa, julgamento, alvos e evidências de aprendizagem antes de avançar.

**Exemplo:**

- Alvos cadastrados: `didn't`, `yesterday`, `tired`, `because`.
- Frente: **“Eu não joguei ontem porque estava cansado.”**
- Resposta válida: `I didn't play yesterday because I was tired.`
- Resposta com erro: `I didn't played yesterday because I was tired.`
- Feedback: **“Boa conexão com _because_. Depois de _didn't_, use o verbo base: _play_, não _played_.”**

Não exigir pontuação ou capitalização perfeita. Aceitar **múltiplas traduções corretas**, incluindo alternativas à tradução de referência.

## 5. Critérios de avaliação: separar três dimensões

| Dimensão | Pergunta | Efeito |
|---|---|---|
| **Correção linguística** | A frase em inglês está correta e expressa o sentido pedido? | Determina `correct` / `incorrect` / `needs_review`. |
| **Uso do vocabulário-alvo** | O usuário demonstrou o uso da palavra/expressão selecionada? | Registra `demonstrated` / `not_demonstrated`; não confundir sinônimo válido com erro. |
| **Oportunidade de elaboração** | Haveria outra forma interessante de formular a frase? | Sugestão opcional; **nunca** constitui erro nem conta no limite diário. |

Exemplo: para **“Eu preciso terminar meu trabalho hoje”**, `I need to finish my work today` e `I have to finish my work today` podem ser traduções corretas. Se o alvo era `need`, a segunda é **correta**, mas **não demonstra esse alvo**. Não marcar como erro nem falsamente como acerto de `need`.

- Distinguir erro de gramática, de escolha lexical, de sentido e de simples diferença estilística.
- Não penalizar contrações e variantes corretas (`did not` / `didn't`), a menos que a meta explícita do exercício exija uma forma específica; nesse caso registrar **meta não demonstrada**, não erro de tradução.
- Em frase ambígua ou avaliação incerta, usar `needs_review`: não cobrar como erro e permitir nova avaliação.
- Quando a tradução está gramaticalmente correta, porém não transmite a ideia pedida, classificar como incorreta **por sentido**, explicando objetivamente.
- Registrar evidências positivas apenas dos tópicos efetivamente utilizados, sem supor domínio de estruturas ausentes.
- Reaproveitar o catálogo compartilhado de tópicos gramaticais do English Builder, mantendo o tipo de exercício identificado.

## 6. Repetição espaçada: revisar a dificuldade, não decorar a frase

**Regra central para exercícios novos:**

- **Acertou:** registrar acerto; **não adicionar a frase à fila principal de repetição espaçada**.
- **Errou:** criar/atualizar uma ou mais **unidades de revisão** relacionadas às dificuldades identificadas (ex.: `didnt_base_verb`, `word_order`, sentido de `since`).
- Revisões devem usar **frases novas em português que testem a mesma dificuldade**, não repetir obrigatoriamente o enunciado original.

Cada unidade de revisão deve ter `target_type` (`grammar_topic` ou `vocabulary_sense`), `target_id`, status, histórico de tentativas, `due_at`, estado do algoritmo e exemplos de erros relacionados. Evitar duplicar unidades ativas para o mesmo alvo; acumular evidências e atualizar seu agendamento.

- Ao acertar uma **revisão**, aumentar o intervalo gradualmente; ao errar, reduzir o intervalo e priorizar revisão futura.
- Não retirar uma dificuldade da revisão após **um único acerto**; ela pode alcançar um estado de retenção estável após sucessos distribuídos no tempo.
- Preferir um algoritmo consolidado de repetição espaçada, como **FSRS**, por meio de biblioteca adequada. **O Ollama identifica o erro; o backend executa o algoritmo e calcula datas.** Para o MVP, intervalos determinísticos simples são aceitáveis se o agendador for substituível.
- Evitar agendar infinitas revisões de uma única dificuldade por erros repetidos na mesma sessão.
- Ao abrir o modo de revisão, priorizar unidades vencidas (`due_at <= agora`) e informar quando não houver pendências.
- Nunca gerar afirmações de domínio definitivo apenas pelo agendamento ou por poucos acertos.

**Distinção:** frases novas acertadas ficam fora do agendamento principal, conforme a regra desejada. O banco ainda poderá usar seus acertos como evidência no relatório e para variar exercícios futuros. Isso **não** implica apagar as frases nem proibir que habilidades previamente corretas voltem a aparecer em outros contextos.

## 7. Limite diário: 10 frases novas erradas

- Valor padrão configurável: **10 exercícios novos distintos respondidos incorretamente por dia**.
- Ao atingir **10 erros**, **bloquear a geração de novos exercícios** em **Praticar** até a virada do dia.
- Continuar permitindo **Revisar**, consultar histórico, cadastrar palavras e ver relatórios.
- Erros em **revisões** não aumentam a contagem de bloqueio.
- Uma frase respondida incorretamente conta **uma vez**, mesmo que tenha vários erros gramaticais. Reavaliações, edição de resposta, múltiplas categorias do mesmo exercício e tentativas de rede duplicadas não aumentam a contagem.
- Respostas classificadas `needs_review`, problemas de IA e **traduções válidas que não utilizaram a palavra-alvo** não contam como erros.
- Recalcular o total a partir das tentativas persistidas (ou contador transacional idempotente); não confiar no estado do navegador.
- Virada do dia às **00:00 no fuso horário configurado do usuário** (padrão `America/Sao_Paulo`). Armazenar horários em UTC e usar a data local apenas para a cota. Histórico e revisões **não** são apagados no reset.
- A API deve recusar novas solicitações de `Praticar` quando a cota acabar, inclusive após atualização da página. Exibir: **“Limite diário atingido. Você ainda pode revisar seus erros.”**

A atividade de revisão pode apresentar **um novo enunciado para o mesmo tópico** mesmo com o bloqueio: isso é **revisão de unidade existente**, não criação de exercício livre.

## 8. Dados e integração com o English Builder

Adicionar entidades (ou equivalentes), aproveitando tabelas de sessões, tópicos e observações já existentes:

- `vocabulary_entries`: palavras, expressões e sentidos cadastrados.
- `recall_exercises`: enunciado pt-BR, tradução de referência, modo (`new`/`review`), data, status, modelo IA e IDs dos alvos.
- `recall_attempts`: resposta original, classificação, feedback e evidências, com chave de idempotência.
- `review_items`: habilidade/sentido revisado, estado de agendamento e próxima revisão.
- `review_events`: histórico de acertos/erros e datas das revisões.
- `ai_evaluations`: JSON estruturado, versão do schema, modelo e situação (`completed`/`pending`/`rejected`).

**Integração:**

- Registrar erros e acertos por tópico no **mesmo catálogo gramatical** do Sentence Builder, identificando `source_mode = sentence_recall`.
- Preservar separadamente métricas de cada modo: **tradução correta** não mede automaticamente a capacidade de desenvolver ideias livremente.
- Exibir, no painel geral: quantidade de exercícios, acertos/erros por oportunidade avaliada, evolução por tópico, dependência de revisão, palavras praticadas, revisões vencidas e evolução temporal.
- Gerar relatório combinado que diferencie **correção linguística**, **uso das palavras-alvo** e **elaboração de ideias no Sentence Builder**. Não confundir tradução literal com produção espontânea.
- Manter enunciados, respostas originais e julgamentos anteriores para auditoria/reavaliação. Permitir revisar/descartar correções incorretas da IA sem destruir o histórico.

## 9. Ollama: operações e contratos

Implementar funções independentes no backend, com **JSON estruturado + validação Pydantic**:

1. **`generate_recall_prompt`**: recebe nível, entradas escolhidas e exemplos recentes; retorna `sentence_pt`, `reference_en`, `targets`, `intended_meanings`, `grammar_tags`. Verificar se a frase é curta, natural, adequada ao nível e se o sentido-alvo realmente cabe nela. Evitar enunciados idênticos recentes.
2. **`evaluate_recall_answer`**: recebe enunciado, objetivos e resposta; retorna `verdict`, `meaning_match`, `grammar_valid`, `target_usage`, `error_events` (categoria, trecho, correção e explicação), `strengths`, `short_feedback`, `valid_example_en`, `confidence`.
3. **`generate_targeted_review`**: recebe uma unidade de revisão e seu histórico; gera **outra** frase pt-BR para verificar a mesma dificuldade, sem antecipar a resposta.
4. **`summarize_recall_progress`** (fase posterior): explica tendências usando agregados calculados no backend e exemplos reais, sem inventar estatísticas.

**Regras de robustez:**

- O backend controla a cota, os modos, as tentativas e a repetição espaçada; a IA **não decide** quando bloquear nem define datas de revisão.
- O backend valida campos, categorias permitidas, tamanho das frases, integridade dos alvos e consistência do julgamento.
- Se geração/avaliação falhar, tentar novamente de forma limitada; preservar resposta e marcar avaliação como pendente, **sem consumir cota nem marcar revisão como concluída**.
- Persistir modelo, versão do prompt/schema e horário para permitir auditoria.
- Evitar exigir uma tradução exata da resposta de referência. Se a IA estiver insegura, não penalizar automaticamente o usuário.

## 10. API sugerida

- `GET /api/recall/vocabulary` — listar entradas.
- `POST /api/recall/vocabulary` — cadastrar entrada(s).
- `PATCH /api/recall/vocabulary/{id}` — editar/ativar/desativar.
- `DELETE /api/recall/vocabulary/{id}` — excluir entrada, preservando integridade do histórico.
- `POST /api/recall/exercises` — gerar exercício novo (validar cota).
- `GET /api/recall/exercises/{id}` — recuperar atividade e status.
- `POST /api/recall/exercises/{id}/answer` — avaliar e registrar tentativa de modo idempotente.
- `GET /api/recall/reviews/due` — listar revisões vencidas.
- `POST /api/recall/reviews/{id}/exercise` — gerar enunciado de revisão para alvo existente.
- `GET /api/recall/progress` — estatísticas e cota do dia.
- `GET /api/recall/settings` e `PATCH /api/recall/settings` — limite diário e preferências.

As rotas são orientativas: manter convenções do projeto principal. Proteger todas as mutações com validação no backend.

## 11. Interface e feedback

- Tela de estudo limpa: **enunciado em português**, campo amplo para inglês e botão **Verificar**.
- Após correção, destacar **um acerto** e **até dois ajustes objetivos**; oferecer um exemplo correto sem transformar sugestões de estilo em erro.
- Mostrar discretamente **“Erros de hoje: 3/10”**, pendências de revisão e botão **Próxima frase**.
- Ao atingir o limite, desabilitar apenas a opção **Nova frase** e destacar **Revisar erros**.
- No modo revisão, indicar que a atividade testa uma dificuldade anterior, **sem exibir sua solução antes da resposta**.
- Sem gamificação punitiva, excesso de explicações ou correções avançadas desnecessárias para A2–B1.

## 12. Implementação por fases

**Fase 1 — MVP:** menu Sentence Recall, cadastro de palavras, geração contextualizada por Ollama, tradução digitada, correção que aceite respostas equivalentes, histórico em SQLite, **limite de 10 erros novos/dia** e fila simples de revisão com novas frases para dificuldades registradas.

**Fase 2 — Aprimoramento:** agendamento FSRS, painel compartilhado por tópico, relatório combinado, edição/revisão de avaliações equivocadas e métricas de domínio por evidências acumuladas.

**Fase 3 — Opcional:** importação em lote, filtros por tema/dificuldade, prática oral e seleção adaptativa de alvos.

## 13. Critérios de aceite do MVP

- [ ] Cadastrar palavras em inglês e praticar frases geradas em português com seus sentidos.
- [ ] Receber tradução de referência e correção **somente depois** de enviar a resposta.
- [ ] Aceitar duas traduções equivalentes corretas sem obrigar cópia literal da referência.
- [ ] Distinguir resposta correta, demonstração da palavra-alvo e sugestão estilística.
- [ ] Após uma frase nova correta, registrar acerto **sem** criar revisão principal; após erro, criar/atualizar dificuldade revisável.
- [ ] Revisar a dificuldade usando **outra frase** e manter histórico/agendamento independente do enunciado original.
- [ ] Bloquear apenas exercícios novos ao chegar a **10 exercícios novos errados** no dia; revisões continuam disponíveis.
- [ ] Zerar a cota à meia-noite local sem apagar histórico ou agendamentos.
- [ ] Persistir todos os dados após fechar/reabrir o aplicativo; não contar respostas duplicadas duas vezes.
- [ ] Falhas e incertezas da IA não geram punição nem perda da resposta.
- [ ] Separar métricas de Sentence Recall e Sentence Builder, com tópicos compartilhados para relatórios futuros.

**Instrução para o Claude:** implementar primeiro o caminho completo **palavras → frase pt-BR → tradução do usuário → avaliação → registro → próxima/revisão**, com testes para limite diário, equivalência de traduções, erros repetidos e persistência. Não adicionar funcionalidades fora do MVP até esse fluxo estar estável.
