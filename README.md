# English Builder

Aplicação **local e offline** para quem está aprendendo inglês do nível **A2 ao B1** praticar a
construção de frases com autonomia. Uma IA rodando no próprio computador ([Ollama](https://ollama.com))
gera exercícios e corrige as respostas, mas quem decide as regras, as notas e o agendamento das
revisões é o sistema, nunca a IA.

## Resumo

O sistema tem dois modos de estudo e um relatório que junta os dois:

- **Criador de frases** — você escolhe uma estrutura (*Sentence Frame*, como `I wanted to ___, but ___.`),
  escreve uma frase e a expande em três rodadas. A avaliação vem só no final e separa **erros gramaticais**
  de **ideias para enriquecer a frase** (que nunca contam como erro). Mostra a versão corrigida com as
  diferenças destacadas e uma nota de 0 a 100%.
- **Anki Premium** — você cadastra palavras ou expressões em inglês; a IA cria frases curtas em português
  que usam essas palavras, e você traduz. Cada erro vem com a **regra** para lembrar na próxima vez.
  Frases erradas entram numa **revisão espaçada**: a mesma frase volta até você acertar e, quanto mais
  você erra, mais ela reaparece nos dias seguintes. Limite de 10 frases novas erradas por dia.
- **Relatórios** — análise do período com métricas calculadas pelo sistema (precisão por tópico,
  erros mais frequentes, autocorreções, evolução semanal, palavras usadas e revisões), comentada pela IA
  e exportável em Markdown.

Princípios que guiam a correção: maiúscula, pontuação, contrações e formas informais (`gonna`) não são
erro; frase simples e correta não é penalizada; trechos que a IA "corrige" mas que não existem na sua
resposta são descartados; avaliação incerta nunca pune.

**Stack:** React + TypeScript + Vite · Python + FastAPI + Pydantic · SQLite · Ollama (padrão `qwen3:8b`).
Especificações: [english_builder_especificacao.md](english_builder_especificacao.md) e
[sentence_recall_especificacao.md](sentence_recall_especificacao.md) (o *Sentence Recall* virou o Anki Premium).

## Como usar

Requisitos: Python 3.11+, Node 18+ e [Ollama](https://ollama.com) com um modelo instalado
(padrão: `qwen3:8b`, ajustável pela API `PUT /api/settings/ollama`). O Listening com vídeos usa também o
[FFmpeg](https://ffmpeg.org) (`winget install Gyan.FFmpeg`).

No Windows, dê duplo clique em **`Iniciar English Builder.bat`** (ou rode `.\start.ps1`).

Abre `http://localhost:8000`. Na primeira vez, cria o ambiente Python e gera a interface.
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
  llm/                   cliente Ollama, schemas Pydantic, prompts e operações (suggest_hints, evaluate_exercise)
  repositories/          acesso SQLite (frames, exercícios, avaliações, configurações)
  services/              orquestra o fluxo (cria exercício, salva versões, dicas, avaliação)
  api/routes.py          endpoints HTTP finos
  migrations/            SQL numerado, aplicado automaticamente na inicialização
frontend/src/
  pages/                 Home, FramePicker, ExercisePage, Progress, Reports, Settings
  components/            Stepper, HintsBox, FeedbackPanel...
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

Especificação em [especificacao_listening_videos.md](especificacao_listening_videos.md). Rotas em `/api/listening/*`
([listening_routes.py](backend/app/api/listening_routes.py)); regras de lacunas e comparação em
[domain/listening.py](backend/app/domain/listening.py); catálogo e preparação em
[services/listening_media.py](backend/app/services/listening_media.py).

- **Vídeos:** coloque `.mp4`, `.mkv`, `.mov` ou `.webm` em `videos/` (subpastas viram categorias) e clique em
  *Atualizar catálogo*. Miniatura e duração vêm do FFmpeg em segundo plano. Arquivo movido/renomeado é reconhecido
  pelo conteúdo; arquivo removido fica como "ausente" e o histórico é mantido.
- **Baixar do YouTube:** botão no catálogo; cole o link, escolha a categoria (subpasta, padrão `YouTube`) e a qualidade.
  Usa [yt-dlp](https://github.com/yt-dlp/yt-dlp) (no `requirements.txt`) com o Node ou Deno instalado como runtime
  JavaScript. Prefere H.264 + AAC (sem conversão), baixa só legendas feitas pelo autor em inglês/português (as
  automáticas do YouTube repetem linhas; sem legenda, o Whisper transcreve) e já deixa o vídeo preparado. O download
  acontece numa pasta temporária, então o catálogo nunca vê arquivos parciais. Se o YouTube mudar algo e o download
  falhar, atualize: `backend\.venv\Scripts\pip install -U yt-dlp`.
- **Requisitos extras:** FFmpeg (`winget install Gyan.FFmpeg`) e, para vídeos sem legenda,
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (já no `requirements.txt`; modelo padrão `large-v3`,
  ajustável em `PATCH /api/listening/settings`). Para usar a GPU NVIDIA no Windows:
  `backend\.venv\Scripts\pip install -r backend\requirements-gpu.txt`. Sem GPU, a transcrição roda na CPU.
- **Legendas, por prioridade:** `nome.en.srt`/`.vtt` ao lado do vídeo (`nome.srt` sem idioma vale se o texto for
  inglês) → faixa de legenda em inglês embutida → transcrição local com Whisper. Legenda em português
  (`nome.pt-BR.srt` ou embutida) vira a tradução opcional.
- **Cache:** a preparação acontece só na primeira abertura e fica em `backend/data/listening/<id>/` + banco. Só é refeita
  se o conteúdo do arquivo (fingerprint: tamanho + hash do início/fim) ou a `PIPELINE_VERSION` mudarem. Vídeo que o
  navegador não toca (MKV, HEVC, áudio AC3…) ganha uma cópia MP4 H.264/AAC; o original nunca é alterado.
- **Ritmo:** o vídeo corre com a legenda completa e para só numa frase-exercício a cada ~15 s, ~30 s (padrão) ou
  ~1 min — ou em todas as frases. Em cada janela entra a frase mais adequada (tamanho médio, palavras de verdade).
- **Exercício:** cada lacuna aceita exatamente o número de letras da palavra e é conferida a cada tecla (verde certo,
  vermelho errado); palavra certa trava e o cursor pula para a próxima; palavra completa e errada conta um erro.
  *Revelar palavra em foco* (Ctrl+Enter) registra dificuldade. Com tudo preenchido aparece *Continuar*.
- **Lacunas:** lacunas por dificuldade (Iniciante 10–15%, Fácil 25–30%, Médio 40–45%, Difícil 60%), sorteadas na
  primeira vez com peso maior para palavras que você já errou e **fixas** depois disso (recomeçar repete as mesmas);
  cada dificuldade tem as suas. *Mostrar resposta* revela a frase inteira e toca de novo (conta como ajuda).
- **Fiel ao áudio:** a legenda é comparada palavra a palavra com o que o Whisper ouve. Só viram lacuna palavras
  realmente ditas; as que a legenda tem e a fala não (legendas "arrumadas" por quem as escreveu) aparecem riscadas, e
  frases com muitas delas não viram exercício. Nomes e termos de nicho (maiúscula no meio da frase e nunca em
  minúscula no vídeo, ou maiúsculas misturadas: Lilies, BLINKs) nunca viram lacuna nem entram no histórico de erros. Comparação ignora só
  maiúsculas, apóstrofo tipográfico e pontuação das pontas (`dont` ≠ `don't`). Erro conta ao conferir, não por tecla;
  revelar registra ajuda (não é acerto); repetições são contadas sem punir.
- **Tradução da frase (PT):** ajuda pontual para tirar uma dúvida: traduz só a frase atual (Ollama local, com as
  falas anteriores de contexto; ~3 s) e some ao passar para a próxima. Usa a legenda em português do vídeo quando
  existe e guarda o resultado, então pedir de novo é instantâneo. Não conta como ajuda.
- **Correções:** *Corrigir legendas* edita texto, horários e tradução de cada fala sem transcrever de novo. No player,
  "A legenda não corresponde ao áudio" pula a fala e a sinaliza para correção.
- **Painel:** acerto por vídeo e dificuldade, onde você parou, palavras mais erradas (erros/tentativas), evolução por
  sessão e revisão dos trechos errados (reaproveita os trechos e foca nas palavras erradas).

## Próximos passos

Painel "Meu progresso" com gráficos (`GET /api/progress` reaproveitando `report_metrics`), tela de revisão
de avaliações e modo **Recomendado** de frames.
