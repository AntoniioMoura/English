# English Builder

Aplicação **local e offline** para quem está aprendendo inglês do nível **A2 ao B1** praticar a
construção de frases com autonomia. Uma IA rodando no próprio computador ([Ollama](https://ollama.com))
gera exercícios e corrige as respostas, mas quem decide as regras, as notas e o agendamento das
revisões é o sistema, nunca a IA.

## Resumo

O sistema tem três modos de estudo e um relatório:

- **Criador de frases** — você escolhe uma estrutura (*Sentence Frame*, como `I wanted to ___, but ___.`),
  escreve uma frase e a expande em três rodadas. A avaliação vem só no final e separa **erros gramaticais**
  de **ideias para enriquecer a frase** (que nunca contam como erro). Mostra a versão corrigida com as
  diferenças destacadas e uma nota de 0 a 100%.
- **Anki Premium** — você cadastra palavras ou expressões em inglês; a IA cria frases curtas em português
  que usam essas palavras, e você traduz. Cada erro vem com a **regra** para lembrar na próxima vez.
  Frases erradas entram numa **revisão espaçada**: a mesma frase volta até você acertar e, quanto mais
  você erra, mais ela reaparece nos dias seguintes. Limite de 10 frases novas erradas por dia.
- **Listening com vídeos** — você assiste aos seus vídeos em inglês (da pasta `videos/` ou baixados do YouTube)
  e completa as palavras que faltam nas legendas, conferidas letra a letra. O vídeo corre com a legenda completa e
  para em algumas frases; as lacunas só caem em palavras realmente ditas no áudio. Erros, ajudas e progresso ficam
  salvos, com painel e revisão dos trechos errados.
- **Tempo de estudo** — relógio no canto superior direito com as horas estudadas hoje, zerado à meia-noite. Clicar
  nele abre o calendário com os dias estudados e o tempo de cada tipo de exercício.
- **Relatórios** — análise do Criador de frases e do Anki Premium no período, com métricas calculadas pelo
  sistema (precisão por tópico, erros mais frequentes, autocorreções, evolução semanal, palavras usadas e
  revisões), comentada pela IA e exportável em Markdown.

Princípios que guiam a correção: maiúscula, pontuação, contrações e formas informais (`gonna`) não são
erro; frase simples e correta não é penalizada; trechos que a IA "corrige" mas que não existem na sua
resposta são descartados; avaliação incerta nunca pune.

**Stack:** React + TypeScript + Vite · Python + FastAPI + Pydantic · SQLite · Ollama (padrão `qwen3:8b`) ·
FFmpeg + faster-whisper + yt-dlp (Listening).
Especificações: [english_builder_especificacao.md](english_builder_especificacao.md),
[sentence_recall_especificacao.md](sentence_recall_especificacao.md) (o *Sentence Recall* virou o Anki Premium) e
[especificacao_listening_videos.md](especificacao_listening_videos.md).

## Como usar

Requisitos: Python 3.11+, Node 18+ e [Ollama](https://ollama.com) com um modelo instalado
(padrão: `qwen3:8b`, ajustável pela API `PUT /api/settings/ollama`). O Listening com vídeos usa também o
[FFmpeg](https://ffmpeg.org) (`winget install Gyan.FFmpeg`); detalhes na seção [Listening com vídeos](#listening-com-vídeos).

No Windows, dê duplo clique em **`Iniciar English Builder.bat`** (ou rode `.\start.ps1`).

Abre `http://localhost:8000`. Na primeira vez, cria o ambiente Python e gera a interface; depois, a interface é
gerada de novo sempre que o código do frontend muda.
Os dados ficam em `backend/data/english_builder.db` (SQLite) e sobrevivem entre execuções.

### Modo desenvolvimento

```powershell
cd backend; .venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
cd frontend; npm run dev        # http://localhost:5173 (proxy de /api para a porta 8000)
```

### Testes

```powershell
cd backend; .venv\Scripts\python -m pytest
cd frontend; npm run typecheck
```

## Arquitetura

```
backend/app/
  domain/rules.py        regras de progressão V0–V3 (fonte única da verdade)
  domain/evaluation.py   separa erro gramatical de ideia de melhoria; deduplica; monta o feedback curto
  domain/listening.py    Listening: palavras, lacunas por dificuldade, nomes, frases-exercício, comparação
  media/                 FFmpeg, legendas (leitura, sincronia e conferência com o áudio), Whisper, YouTube
  llm/                   cliente Ollama, schemas Pydantic, prompts e operações (suggest_hints, evaluate_exercise)
  repositories/          acesso SQLite (frames, exercícios, avaliações, configurações)
  services/              orquestra o fluxo (cria exercício, salva versões, dicas, avaliação; catálogo, preparação,
                         downloads e sessões do Listening, com fila em segundo plano)
  api/routes.py          endpoints HTTP finos
  migrations/            SQL numerado, aplicado automaticamente na inicialização
frontend/src/
  pages/                 Home, FramePicker, ExercisePage, Progress, Reports, StudyCalendar, recall/*, listening/*
  components/            Stepper, HintsBox, FeedbackPanel...
  sounds.ts              sons de digitação do Listening (Web Audio, sem arquivos)
  studyTimer.ts          relógio de estudo: conta o tempo da tela ativa e envia ao backend
  modes.ts               registro do menu — novos modos de estudo entram aqui
```

### Decisões importantes

- **O backend controla as etapas.** Só aceita a versão `V{n}` esperada; não existe V4; não avalia antes de V3;
  dicas só nas expansões (V0 é produção autônoma). Uma expansão precisa mudar algo em relação à anterior,
  mas não há mínimo de palavras.
- **A IA não é tratada como verdade.** Depois da resposta do Ollama, o backend:
  - descarta erros cujo trecho não existe no texto do usuário (erro inventado) ou cuja correção só mexe em pontuação;
  - move itens marcados como `style` para "Ideias para enriquecer" — nunca contam como erro;
  - conta uma vez o mesmo erro repetido em V0–V3 (fica registrado na primeira versão em que apareceu);
  - só aceita autocorreção se o trecho antigo realmente sumiu da versão final;
  - gera a versão corrigida trocando apenas os trechos errados, sem reescrever frases corretas;
  - esconde erros com confiança < 0,5 (ficam salvos como `uncertain`).
- **Nada se perde.** As versões são salvas antes de chamar a IA. Se a avaliação falhar duas vezes, o exercício
  fica `awaiting_evaluation` com o botão **Reavaliar**. Ollama desligado não gera retentativa inútil.
- **Observações revisáveis.** `grammar_observations` e `idea_observations` ficam em tabelas separadas, com
  `review_status`; o botão "Discordo desta correção" marca a observação como `dismissed`. Reavaliações marcam
  as observações antigas como `superseded`.

## API

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/frames` | Lista frames ativas (`?level=A2`) |
| POST | `/api/exercises` | `{selection_mode: "manual"\|"random", frame_id?}` |
| GET | `/api/exercises` | Histórico (`?status=`) |
| GET | `/api/exercises/{id}` | Estado, versões, dicas e avaliação |
| POST | `/api/exercises/{id}/versions` | `{version_index, text}` — valida a sequência |
| POST | `/api/exercises/{id}/hints` | Dicas da expansão atual (com cache por etapa) |
| POST | `/api/exercises/{id}/evaluate` | Avalia após V3; também reavalia |
| PATCH | `/api/observations/{id}` | Revisa uma observação (`confirmed`/`dismissed`) |
| GET/PUT | `/api/settings/ollama` | Endereço, modelo e timeout |
| GET | `/api/settings/ollama/status` | Testa a conexão e lista modelos |
| GET/POST | `/api/listening/library`, `/library/scan` | Catálogo; `scan` relê a pasta `videos/` |
| POST | `/api/listening/videos/{id}/prepare` | Prepara (ou não faz nada se o cache vale); `{force}` refaz |
| GET | `/api/listening/videos/{id}/stream`, `/thumbnail` | Vídeo (com Range) e miniatura |
| GET/PATCH | `/api/listening/videos/{id}/segments`, `/segments/{id}` | Falas e correção manual |
| POST | `/api/listening/videos/{id}/sessions` | `{difficulty, interval, mode, restart}` — retoma ou cria |
| POST | `/api/listening/sessions/{id}/items/{item}/check` · `reveal` · `replay` · `skip` · `translate` | Exercício |
| GET | `/api/listening/stats` | Painel |
| GET/POST/DELETE | `/api/listening/downloads` | Downloads do YouTube |
| GET | `/api/study-time/today` | Total de hoje e segundos até a meia-noite |
| POST | `/api/study-time` | `{seconds: {atividade: n}, day?}` — soma o tempo medido |
| GET | `/api/study-time/month` | Dias estudados no mês (`?month=2026-10`), por atividade |

## Relatórios (Fase 2)

`POST /api/reports {period: "7d"|"30d"|"90d"|"all"}`, `GET /api/reports`, `GET /api/reports/{id}`,
`GET /api/reports/{id}/markdown`, `DELETE /api/reports/{id}`.

- Só entram estudos que chegaram ao feedback. **Números vêm do backend** ([report_metrics.py](backend/app/domain/report_metrics.py));
  a IA só escreve o texto, e frases dela com números são descartadas.
- Observações antigas passam pelos critérios atuais: maiúscula/pontuação, troca de tempo verbal sem marcador
  de passado, observações descartadas ("Discordo") ou de baixa confiança não contam como erro.
- Erro que não chegou à frase final conta como **autocorreção**, não como erro.
- Precisão por tópico = erros ÷ oportunidades. Estados: *precisa de atenção* (≥ 50% de erro), *em evolução*
  (queda ≥ 25 p.p. entre a 1ª e a 2ª metade), *consistente* (≤ 25%, ≥ 4 oportunidades, acertos em ≥ 2 dias),
  *revisar*, ou *dados insuficientes* (< 3 oportunidades). Nunca afirma nível CEFR.
- O comentário de erros da IA só é mantido se citar um erro real da frase final; senão, usa os dados.
- Se a IA falhar, o relatório é salvo só com os números (`status = numbers_only`).

## Sentence Recall (MVP)

Especificação em [sentence_recall_especificacao.md](sentence_recall_especificacao.md). Rotas em `/api/recall/*`
([recall_routes.py](backend/app/api/recall_routes.py)); regras em [domain/recall.py](backend/app/domain/recall.py);
agendador substituível em [domain/scheduler.py](backend/app/domain/scheduler.py).

- **Geração:** a IA cria a frase pt-BR + referência; o backend exige que a referência use a palavra-alvo, que a
  frase em português não contenha a palavra em inglês e que não repita frases recentes. Uma segunda chamada
  confere se a referência está correta (ela aparece depois como "tradução válida").
- **Avaliação:** resposta igual à referência (ignorando maiúscula, pontuação e contrações) é correta sem IA.
  Maiúscula, pontuação, contrações e estilo nunca são erro; trecho que não está na resposta é descartado;
  confiança baixa → `needs_review` (não pune). Tradução correta que não usou o alvo = correta, alvo "não usado".
- **Cota:** 10 frases novas erradas por dia (configurável em `PATCH /api/recall/settings`), contadas a partir das
  tentativas salvas, no fuso `America/Sao_Paulo`. Idempotência por `idempotency_key` + uma tentativa por frase.
- **Revisão:** só frases novas erradas criam revisões; errar uma revisão nunca cria outra (a fila não cresce).
  - Erro que envolve uma palavra registrada → revisão da palavra, com **frases novas** para ela.
  - Qualquer outro erro → **uma revisão da mesma frase**, que volta idêntica (sem IA) até você acertar.
  - Errou a revisão: volta na hora para o fim da fila de hoje. Acertou: 1-3-7-14-30 dias, encurtados 15% por
    erro acumulado (mínimo 30%). "Estável" só após 3 acertos em 3 dias diferentes.

## Listening com vídeos

Especificação original em [especificacao_listening_videos.md](especificacao_listening_videos.md) (algumas decisões
mudaram durante o desenvolvimento; o que vale é o descrito aqui). Rotas em `/api/listening/*`
([listening_routes.py](backend/app/api/listening_routes.py)); regras de lacunas, nomes e comparação em
[domain/listening.py](backend/app/domain/listening.py); catálogo e preparação em
[services/listening_media.py](backend/app/services/listening_media.py); sessões e painel em
[services/listening_service.py](backend/app/services/listening_service.py).

### Requisitos e instalação

- **FFmpeg** (`winget install Gyan.FFmpeg`): miniaturas, leitura de legendas embutidas, extração de áudio e conversão.
- **faster-whisper** (no `requirements.txt`; modelo padrão `large-v3`, ajustável em `PATCH /api/listening/settings`):
  transcreve vídeos sem legenda e confere/ressincroniza as legendas existentes. Para usar a GPU NVIDIA no Windows:
  `backend\.venv\Scripts\pip install -r backend\requirements-gpu.txt`. Sem GPU (ou se ela falhar), roda na CPU, mais devagar.
- **yt-dlp** (no `requirements.txt`) + **Node** ou **Deno** instalado: download do YouTube.
- **Ollama**: só para a tradução pontual da frase (botão PT).

### Vídeos e catálogo

- Coloque `.mp4`, `.mkv`, `.mov` ou `.webm` em `videos/` (subpastas viram categorias; a pasta não vai para o git) e clique
  em *Atualizar catálogo*. Miniatura e duração vêm do FFmpeg em segundo plano.
- Cada vídeo é identificado pelo conteúdo (tamanho + hash do início/fim): arquivo movido ou renomeado mantém o histórico;
  arquivo removido fica como "ausente", sem apagar nada.
- **Baixar do YouTube:** botão no catálogo; cole o link, escolha a categoria (padrão `YouTube`) e a qualidade máxima.
  Prefere H.264 + AAC (toca sem conversão) e baixa só legendas feitas pelo autor em inglês/português (as automáticas do
  YouTube repetem linhas). O download acontece numa pasta temporária e o vídeo já entra preparado. Se o YouTube mudar algo
  e o download falhar: `backend\.venv\Scripts\pip install -U yt-dlp`.

### Preparação (uma vez por vídeo)

- **Texto em inglês, por prioridade:** `nome.en.srt`/`.vtt` ao lado do vídeo (`nome.srt` sem idioma vale se o texto for
  inglês) → faixa de legenda em inglês embutida → transcrição local com o Whisper. A IA do Ollama nunca escreve a legenda.
- **Sincronia pelo áudio:** legendas (sobretudo as do YouTube) entram atrasadas e com atraso variável. O Whisper mede o
  tempo de cada palavra falada e cada fala da legenda é reposicionada, sem mudar o texto. Fala sobreposta nunca faz uma
  fala cortar palavras ouvidas da anterior.
- **Fidelidade:** cada palavra da legenda é comparada com o que foi dito. Palavras que a legenda tem e a fala não
  (legenda "arrumada" por quem a escreveu) aparecem riscadas e nunca viram lacuna; frases com muitas delas não viram
  exercício. Hesitações (uh, um) não são marcadas.
- **Reprodução:** vídeo que o navegador não toca (MKV, HEVC, áudio AC3…) ganha uma cópia MP4 H.264/AAC; o original nunca
  é alterado.
- **Cache:** tudo fica em `backend/data/listening/<id>/` + banco e só é refeito se o conteúdo do arquivo ou a
  `PIPELINE_VERSION` mudarem. Trocar dificuldade ou repetir sessão nunca reprocessa.

### Estudo

- **Ritmo:** o vídeo corre com a legenda completa e para só numa frase-exercício a cada ~15 s, ~30 s (padrão) ou ~1 min,
  ou em todas as frases. Em cada janela entra a frase mais adequada (tamanho médio, palavras de verdade, fiel ao áudio).
- **Lacunas:** Iniciante 10–15%, Fácil 25–30%, Médio 40–45%, Difícil 60% das palavras. Sorteadas na primeira vez (com peso
  maior para palavras que você já errou) e **fixas** depois disso; cada dificuldade tem as suas. Nunca escondem números,
  descrições sonoras, nomes e termos de nicho (Lilies, BLINKs, títulos) nem palavras que não foram ditas.
- **Digitação em tempo real:** cada lacuna aceita exatamente o número de letras da palavra e é conferida a cada tecla
  (verde certo, vermelho errado). Palavra certa trava e o cursor pula para a próxima; palavra completa e errada conta um
  erro (uma vez por resposta). Só maiúsculas e o tipo de apóstrofo são ignorados (`dont` ≠ `don't`).
- **Ajuda:** 💡 / Ctrl+Enter revela a palavra em foco; *Mostrar resposta* revela a frase inteira e toca de novo. Os dois
  contam como dificuldade (não como acerto). ↻ / Ctrl+Espaço repete a frase; repetições são registradas sem punir.
- **Tradução (PT):** traduz só a frase atual, para tirar uma dúvida (Ollama local, com as 3 falas anteriores de
  contexto; ~3 s). Some ao passar para a próxima frase; usa a legenda em português do vídeo quando existe e guarda o
  resultado. Não conta como ajuda.
- **Recompensa:** sons suaves de digitação (🔊/🔇 nos controles), selo "Perfeito!" com confete e sequência de frases
  perfeitas; com erro ou ajuda, "Frase concluída · 1 erro". *Continuar* leva à próxima frase; ‹ › navegam só entre as
  frases já concluídas.
- **Correções:** *Corrigir legendas* edita texto, horários e tradução de cada fala sem transcrever de novo. No player,
  "A legenda não corresponde ao áudio" pula a fala e a sinaliza para correção.

### Painel

Acerto por vídeo e dificuldade, onde você parou, palavras mais erradas (erros ÷ tentativas, sem nomes e termos de nicho),
evolução por sessão e revisão dos trechos errados (reaproveita os trechos e foca nas palavras erradas).

## Tempo de estudo

Medido em [studyTimer.ts](frontend/src/studyTimer.ts) e enviado a cada 10 s; o dia segue o fuso das configurações
(padrão `America/Sao_Paulo`) e o histórico fica na tabela `study_time`.

- **Criador de frases:** conta enquanto você escreve as versões, depois de escolher a estrutura.
- **Anki Premium:** conta em Praticar e Revisar, separados. Não conta sem frase para fazer (limite do dia, nada a revisar).
- **Listening:** conta do primeiro play em diante, inclusive parado numa frase para digitar. Para se você pausar o vídeo
  ou a sessão terminar.
- **Telas de resultado:** não contam. Feedback do Criador, resultado da frase no Anki e no Listening só informam; o
  relógio volta quando há algo para fazer de novo.
- **Não contam:** relatórios, menus, catálogo, preparação de vídeos, Minhas palavras e o calendário. A aba escondida ou
  minimizada também pausa.
- **IA processando:** o relógio pausa enquanto você só aguarda a IA: avaliação e ideias do Criador de frases, criação e
  correção de frases do Anki e tradução PT do Listening.

## Próximos passos

Painel "Meu progresso" com gráficos (`GET /api/progress` reaproveitando `report_metrics`), tela de revisão
de avaliações e modo **Recomendado** de frames.
