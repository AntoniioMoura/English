# English Builder — Especificação de Desenvolvimento

## 1. Objetivo

Criar uma aplicação **local, offline e extensível** para treinar a construção de frases em inglês (nível A2 → B1). O método central combina **Sentence Frames + Construção Progressiva**: o usuário cria uma frase e a expande em três rodadas. O Ollama fornece dicas opcionais, avalia a tentativa e ajuda a acompanhar a evolução.

**Prioridade:** escrita ativa, autonomia, exercícios rápidos e feedback objetivo. A interface será em inglês (pt-BR); as frases, em inglês.

## 2. Stack e arquitetura

- **Frontend:** React + TypeScript + Vite.
- **Backend:** Python + FastAPI + Pydantic.
- **Banco:** SQLite, com migrações e persistência entre execuções.
- **IA:** Ollama local via API HTTP, com modelo configurável; respostas estruturadas em JSON validadas pelo backend.
- **Organização:** separar interface, regras de exercício, acesso ao banco e integração com Ollama. O backend controla o fluxo; a IA não define regras de negócio.
- **Execução:** interface e API no próprio computador, sem dependência de serviços externos. Prever configuração de endereço do Ollama e mensagens claras quando ele estiver indisponível.

## 3. Menu inicial

- **Sentence Builder:** modo de estudo implementado no MVP.
- **Meu progresso:** resumo dos exercícios e dificuldades (Fase 2).
- **Relatórios:** análise detalhada e exportação (Fase 2).
- **Configurações:** modelo Ollama, conexão e preferências.

Preparar a navegação para adicionar outros modos futuramente; **não** implementar outros modos no MVP.

## 4. Fluxo do Sentence Builder

### 4.1. Escolha da estrutura

O usuário escolhe uma Sentence Frame cadastrada ou o modo **Aleatório**. Em fase posterior, incluir modo **Recomendado**, baseado no histórico.

Cada frame tem: `id`, `text`, `explanation_pt`, `level`, `grammar_tags`, `examples`, `enabled`.

Exemplos iniciais:

- `I wanted to ___, but ___.`
- `I didn't ___ because ___.`
- `I was ___ when ___.`
- `I'm going to ___.`
- `I think ___ because ___.`
- `I've never ___.`
- `I've been ___ for ___.`
- `If I ___, I'll ___.`

Fornecer biblioteca inicial curada. A geração automática de novos frames é opcional e deve passar por validação antes de salvá-los na biblioteca.

### 4.2. Frase inicial + 3 expansões

1. Exibir frame, significado breve e campo para o usuário criar uma **frase completa**.
2. Salvar a versão **V0**.
3. Abrir a expansão **1/3** com V0 em campo editável. Solicitar informação nova ou aprofundamento da ideia; salvar **V1**.
4. Repetir para **2/3 (V2)** e **3/3 (V3)**.
5. Enviar frame e as **quatro versões** ao Ollama para avaliação final.
6. Exibir feedback compacto e botão **Próxima frase**.

Exemplo:

- V0: `I wanted to play, but I was tired.`
- V1: `I wanted to play with my friends, but I was tired.`
- V2: `I wanted to play with my friends last night, but I was tired after work.`
- V3: `I wanted to play with my friends last night, but I was tired after work, so I went to bed early.`

**Regras:**

- O exercício só é concluído após três expansões; não exigir um número mínimo arbitrário de palavras.
- Cada versão pode editar e corrigir trechos anteriores. Preservar V0–V3 integralmente.
- Incentivar **novas informações relevantes**, não apenas frases mais longas.
- O backend controla as quatro etapas; a IA não pode pular ou criar rodadas.
- Não mostrar avaliação gramatical antes da conclusão, para privilegiar a produção autônoma.

### 4.3. Dicas opcionais

Botão **Mostrar ideias / Ocultar ideias** em cada expansão; dicas ocultas por padrão.

Ao solicitar, o Ollama recebe frame, versão atual e número da etapa e devolve **2–3 sugestões curtas em inglês utilizando a frase final da utima etapa**

Registrar se o usuário abriu as dicas naquela etapa, sem tratar isso como erro.

## 5. Avaliação: separar erros de oportunidades de melhoria

**Requisito central:** não confundir **incorreção gramatical** com **frase correta, porém simples**. São dois eixos independentes:

| Eixo | O que analisa | Como registrar |
|---|---|---|
| **Precisão gramatical** | Tempos verbais, auxiliares, preposições, artigos, ordem das palavras etc. | Erros objetivos e evidências de uso correto por tópico. |
| **Desenvolvimento das ideias** | Informação acrescentada, conexão entre ideias, clareza e coerência nas expansões. | Acertos e oportunidades de elaboração; **nunca contabilizar como erro gramatical**. |

Exemplo: `I played Brawl Stars yesterday. It was fun.` está correto. O sistema pode sugerir `I played Brawl Stars yesterday, and I had a lot of fun.` como **alternativa de construção**, mas **não deve registrar erro**.

Avaliar também:

- Uso adequado da Sentence Frame escolhida.
- Progressão de V0 até V3: novas informações relevantes e preservação de sentido.
- Autocorreções feitas pelo usuário entre versões (registrar como avanço).
- Naturalidade apropriada ao nível A2–B1, sem reescrever desnecessariamente frases corretas.

### Feedback visível (curto)

Apresentar **um acerto**, **no máximo dois ajustes prioritários** (se existirem) e **uma orientação para a próxima tentativa**. Se houver erro, incluir versão corrigida da frase final; se não houver, reconhecer a correção. Diferenciar visualmente:

- **Erro:** “Depois de *didn't*, use o verbo na forma base: *didn't go*.”
- **Pode melhorar:** “Sua frase está correta. Você também pode conectar as ideias com *and*.”
- **Acerto:** “Boa utilização de *because* para justificar sua decisão.”

Não inventar erros nem penalizar frases simples e corretas. Correções de estilo e sugestões de expansão **não** alimentam o contador de erros gramaticais.

## 6. Histórico e inteligência de aprendizagem

Salvar **todos** os exercícios, incluindo frame, versões V0–V3, dicas consultadas, horário, feedback e modelo Ollama usado.

Registrar as observações por tópico gramatical em formato estruturado:

- `topic_id`, `exercise_id`, `version_index`, `evidence_type` (`error`, `correct`, `self_correction`, `not_assessed`), `original_excerpt`, `suggested_correction`, `explanation_pt`, `severity`, `confidence`, `review_status`.
- Uma mesma ocorrência de erro propagada por V0–V3 **não** deve contar como quatro erros novos.
- Registrar acerto **somente** quando houver oportunidade real de demonstrar o tópico; não inferir domínio de estruturas não utilizadas.
- Guardar avaliações do modelo como **observações revisáveis**, não como verdades absolutas. Permitir corrigir/descartar classificações equivocadas.
- Manter separado um registro de **desenvolvimento de ideias**: expansão relevante, coesão, clareza, diversidade de conectores e oportunidades de elaboração. Não transformar essa dimensão em erro gramatical.

### Indicadores do painel (Fase 2)

- Sessões concluídas e dias de estudo.
- Evolução da precisão **por tópico**, usando erros em relação às oportunidades avaliadas (e não apenas número bruto de erros).
- Temas com dificuldade persistente, melhoria recente e acertos consistentes em dias diferentes.
- Evolução da elaboração: expansões com informação relevante, conexão/coerência e menor dependência de dicas.
- Visualização por semana/mês e exemplos reais do histórico.

Estados sugeridos por tópico: `precisa_de_atencao`, `em_evolucao`, `consistente`, `revisar`. Não declarar “dominado” com base em poucos acertos; quando houver evidência insuficiente, mostrar **dados insuficientes**.

### Relatório detalhado (Fase 2)

Gerar sob demanda um relatório em português contendo: resumo do período, pontos fortes, erros recorrentes com exemplos, **oportunidades de elaboração separadas dos erros**, autocorreções, evolução temporal e próximos tópicos recomendados. Basear-se apenas nos registros; identificar limitações de amostra e não afirmar nível CEFR formal automaticamente. Permitir consultar relatórios anteriores e exportar em Markdown.

## 7. Integração com Ollama

Implementar três operações independentes:

1. **`suggest_hints`**: retorna lista de 2–3 sugestões curtas.
2. **`evaluate_exercise`**: recebe frame, V0–V3 e devolve JSON validado com `highlights`, `grammar_errors`, `grammar_correct_evidence`, `idea_development`, `self_corrections`, `corrected_final_sentence` e `next_tip`.
3. **`generate_report`** (Fase 2): recebe agregados e evidências selecionadas do banco; devolve análise textual fundamentada, sem recalcular métricas arbitrariamente.

O backend deve definir schemas Pydantic, pedir resposta estruturada ao Ollama, validar os tipos e limitar o tamanho dos textos. Em erro de geração/JSON, tentar novamente uma vez; se falhar, preservar o exercício como **aguardando avaliação** e oferecer **Reavaliar**. Nunca perder as versões digitadas.

Calcular métricas e estados no backend a partir dos registros; **não** confiar números ou estatísticas inventados pela IA. Salvar nome/versão do modelo e data da avaliação para rastreabilidade.

## 8. Persistência mínima

Tabelas sugeridas:

- `sentence_frames`: biblioteca e metadados das estruturas.
- `study_sessions`: identificação e datas das sessões.
- `exercises`: frame, status, início/fim e configuração da tentativa.
- `sentence_versions`: V0–V3 e indicação de dicas abertas em cada etapa.
- `exercise_evaluations`: JSON estruturado, versão do schema, modelo e status.
- `grammar_topics`: catálogo padronizado de tópicos.
- `grammar_observations`: erros, acertos e autocorreções com referência ao exercício.
- `idea_observations`: qualidade da expansão e sugestões sem caráter de erro.
- `learning_reports`: relatórios gerados e período analisado (Fase 2).

Usar identificadores e chaves estrangeiras. Os dados sobrevivem ao fechamento do aplicativo. Não armazenar apenas textos resumidos: conservar as frases originais para reavaliações futuras.

## 9. API mínima sugerida

- `GET /api/frames` — listar/filtrar frames.
- `POST /api/exercises` — criar exercício com frame selecionada/aleatória.
- `GET /api/exercises/{id}` — obter estado e versões.
- `POST /api/exercises/{id}/versions` — salvar V0–V3 com validação da sequência.
- `POST /api/exercises/{id}/hints` — dicas da expansão atual.
- `POST /api/exercises/{id}/evaluate` — avaliar após V3; permitir reavaliação.
- `GET /api/progress` — indicadores calculados (Fase 2).
- `POST /api/reports` e `GET /api/reports/{id}` — geração/consulta de relatórios (Fase 2).
- `GET /api/settings/ollama` e `PUT /api/settings/ollama` — configuração da IA.

Escolher contratos consistentes e validar entradas, tamanho máximo e etapas no backend. Não duplicar regras de negócio no frontend.

## 10. UX

- Interface moderna e limpa, com tema claro e foco na área de escrita.
- Exibir **Frase inicial**, depois **Expansão 1/3, 2/3, 3/3**, com indicação clara do progresso.
- Campo de texto editável, dicas ocultáveis e navegação simples.
- Após V3, exibir feedback breve e botão principal **Próxima frase**.
- Mostrar separadamente **Correções gramaticais** e **Ideias para enriquecer sua frase**, sem forçar ambos quando não houver conteúdo.
- Não transformar tudo em nota/competição; valorizar acertos, autonomia e consistência.

## 11. Entrega por fases

**Fase 1 — MVP obrigatório:** menu, frames iniciais, seleção manual/aleatória, V0 + três expansões, dicas ocultáveis, avaliação com dois eixos separados, feedback curto, persistência SQLite e configuração Ollama.

**Fase 2 — Acompanhamento:** classificação de erros/acertos, revisão de avaliações, gráficos por tópico e desenvolvimento de ideias, relatório detalhado e escolha de frames recomendadas.

**Fase 3 — Expansões futuras:** modos adicionais, prática oral, atividades espontâneas e revisões adaptativas. Não implementar agora.

## 12. Critérios de aceite do MVP

- [ ] Iniciar o aplicativo localmente e selecionar uma frame ou modo aleatório.
- [ ] Criar V0 e realizar **exatamente três expansões** editáveis, com histórico preservado.
- [ ] Mostrar/ocultar dicas contextuais sem revelar frases prontas.
- [ ] Concluir V3 e receber um feedback breve com acertos, eventuais erros e sugestões de elaboração **em categorias separadas**.
- [ ] Frases gramaticalmente corretas, mesmo simples, **não** serem marcadas como erradas.
- [ ] Nenhum exercício ou versão ser perdido se a IA falhar; permitir reavaliação.
- [ ] Reabrir o aplicativo e encontrar o histórico salvo.
- [ ] Código modular e preparado para o painel/relatórios da Fase 2.

**Instrução para implementação:** entregar primeiro um MVP utilizável de ponta a ponta, com testes das regras de progressão, armazenamento e distinção entre `grammar_error` e `idea_improvement`. Não expandir o escopo antes de validar esse fluxo.
