# Funcionalidade: Listening com Vídeos Locais

## Objetivo
Implementar no sistema existente uma ferramenta de listening inspirada em https://video.vocatype.app/pt/: o usuário assiste a vídeos em inglês e completa palavras ocultas nas legendas. Os vídeos são adicionados manualmente à pasta `videos/` na raiz do projeto. Interface de catálogo semelhante à de um serviço de streaming. Todo processamento é local e reutilizável.

## Diretrizes
- **Integrar à arquitetura e ao visual existentes**; não recriar o projeto nem alterar funcionalidades atuais.
- Priorizar interface simples, responsiva e navegação rápida.
- Operar localmente, sem serviços pagos nem dependência de nuvem.
- **Não implementar download de vídeos**: usar apenas arquivos disponibilizados pelo usuário em `videos/`.

## 1. Biblioteca de vídeos
- Ao abrir a funcionalidade, varrer `videos/` e subpastas.
- Aceitar inicialmente `.mp4`, `.mkv`, `.mov` e `.webm`.
- Exibir cartões com miniatura, título (nome do arquivo, editável), duração, categoria (subpasta), status e progresso de estudo.
- Oferecer pesquisa, filtros por categoria e status, seção "Continuar assistindo" e ordenação simples.
- Gerar miniatura e metadados com FFmpeg/FFprobe.
- Status: **não processado**, **processando**, **pronto**, **erro**.
- Ao adicionar/remover arquivos da pasta, refletir as mudanças por atualização do catálogo; arquivos ausentes não devem apagar automaticamente histórico do usuário.

## 2. Processamento e cache
Ao selecionar um vídeo:
1. Consultar o banco para verificar se existe processamento válido para o arquivo.
2. Se estiver pronto, abrir imediatamente o player, **sem reprocessar**.
3. Se não estiver processado, iniciar preparação com progresso visível; permitir navegar pelo catálogo durante o processamento.
4. Persistir resultados, status e eventuais mensagens de erro; disponibilizar ação "Tentar novamente".

Identificar cada vídeo de forma persistente, usando caminho relativo + fingerprint do arquivo (tamanho, data de modificação e/ou hash). Invalidar o cache somente se o conteúdo ou a versão relevante do pipeline de processamento mudar. Alterar dificuldade ou repetir sessão **nunca** deve gerar nova transcrição.

## 3. Preparação de legendas
Prioridade de obtenção do texto **em inglês**:
1. Arquivo externo `.srt`/`.vtt` em inglês com o mesmo nome-base do vídeo (ex.: `episodio_01.en.srt`).
2. Faixa de legenda em inglês embutida no vídeo, extraída com FFmpeg.
3. Transcrição automática local do áudio em inglês com **WhisperX** (ou equivalente, se tecnicamente necessário).

Requisitos:
- Gerar uma lista estruturada de trechos com `start`, `end`, `text` e palavras para os exercícios.
- Preservar contrações, pontuação e texto original; não usar tradução como resposta correta.
- Evitar depender de timing individual de palavras no MVP: início/fim de cada trecho é suficiente.
- Oferecer uma tela simples para corrigir texto e horários de trechos imprecisos, salvando as correções sem transcrever tudo novamente.
- Se houver legenda em português externa/embutida, disponibilizá-la como tradução opcional. Caso não haja, a tradução por IA local poderá ser adicionada depois; **não bloquear o estudo por falta de tradução**.

## 4. Compatibilidade de reprodução
- Reproduzir vídeos pelo player HTML5 no navegador.
- Preferir MP4 com H.264 + AAC, mas aceitar formatos de entrada listados acima.
- Se o contêiner/codec não funcionar no navegador, gerar **uma versão compatível para reprodução** e armazená-la em cache, preservando o original.
- Usar FFmpeg/FFprobe para inspeção e conversão apenas quando necessária.

## 5. Player e exercício
Interface inspirada no VocaType: vídeo, legenda da fala atual com lacunas, área de digitação, comandos de reprodução e progresso.

Fluxo:
1. Usuário escolhe vídeo e dificuldade.
2. Reproduzir um trecho da fala; exibir a frase com algumas palavras ocultas.
3. Usuário digita as palavras faltantes, na ordem, e confirma.
4. Conferir respostas; destacar erros e permitir ouvir novamente.
5. Ao concluir a fala, avançar para a próxima.

Controles: reproduzir/pausar, repetir trecho, avançar/voltar trecho, revelar resposta, mostrar/ocultar tradução e retomar sessão.

Regras de avaliação:
- Comparar palavras ignorando apenas diferenças irrelevantes como maiúsculas/minúsculas e pontuação final; **não tratar palavras gramaticalmente diferentes como iguais** (ex.: `was` ≠ `were`, `dont` ≠ `don't`).
- Contabilizar erro na verificação da resposta, **não a cada tecla pressionada**.
- Repetições do áudio devem ser permitidas sem punição, mas sua quantidade será registrada.
- Ao revelar a resposta, registrar que a palavra precisou de ajuda; não contar como acerto independente.
- Se a legenda não corresponder ao áudio, permitir sinalizar/corrigir ou pular a fala.

## 6. Dificuldades
Definir percentual aproximado de palavras ocultas por fala:
- **Iniciante:** 10–15%.
- **Fácil:** 25–30%.
- **Médio:** 40–45%.
- **Difícil:** 60%.

Garantir pelo menos uma lacuna quando a frase for adequada. Não esconder pontuação isolada. Selecionar as lacunas dinamicamente por sessão, sem alterar os dados processados. Manter a seleção estável enquanto a sessão estiver em andamento, inclusive ao recarregar a página.

## 7. Histórico de erros e progresso
Persistir em SQLite:
- Vídeos, fingerprints, arquivos de cache e estado do processamento.
- Trechos/legendas processados e correções manuais.
- Sessões de estudo: vídeo, dificuldade, posição, data, acertos e tentativas.
- Tentativas por palavra: palavra esperada, resposta digitada, acerto/erro, quantidade de repetições, uso de ajuda e contexto (vídeo, trecho e horário).

Exibir no painel:
- Percentual de acerto por vídeo e dificuldade.
- Quantidade de frases concluídas e ponto em que o estudo parou.
- Palavras mais erradas com **erros/tentativas**, não apenas total absoluto.
- Histórico de evolução por sessão.

Permitir uma revisão dos trechos errados, reutilizando o áudio e as legendas já processados. Na seleção de lacunas, o sistema poderá priorizar palavras com histórico de dificuldades, sem ocultar sempre as mesmas.

## 8. Organização sugerida
```text
projeto/
├── videos/                 # Vídeos fornecidos pelo usuário; aceita subpastas
├── data/
│   ├── listening.db         # Metadados, sessões e estatísticas
│   └── processed/           # Miniaturas, legendas, JSON e vídeos convertidos
├── backend/                 # Rotas, catalogação e processamento
└── frontend/                # Catálogo, player e histórico
```

Adequar essa estrutura à organização real do projeto; não duplicar infraestrutura existente.

## 9. Stack sugerida
- Frontend: **React**, aproveitando componentes e estilos existentes.
- Backend: **Python + FastAPI**, se compatível com o projeto atual.
- Banco: **SQLite**.
- Mídia: **FFmpeg/FFprobe**.
- Legendas/transcrição: **SRT/VTT + WhisperX local**.
- IA adicional: **Ollama apenas se for útil** para tradução/análise posterior; não necessário para o núcleo.

## 10. Critérios de aceite
- Novo vídeo colocado em `videos/` aparece no catálogo após atualização.
- Primeiro acesso prepara legenda, miniatura e metadados e salva o resultado.
- Reabrir vídeo pronto não inicia nova transcrição.
- Alterar dificuldade gera outras lacunas sem reprocessar a mídia.
- Exercícios funcionam com trechos sincronizados e permitem repetir áudio.
- Erros, acertos, ajudas, repetições e progresso persistem após fechar e reabrir o sistema.
- Arquivo sem legenda pode ser transcrito localmente; falha de processamento é recuperável.
- Player funciona com vídeos compatíveis e converte somente quando necessário.

## Ordem de implementação
1. Leitura da pasta `videos/`, catálogo e miniaturas.
2. Banco de dados, identificação de arquivos e cache.
3. Importação de legendas, transcrição local e edição de trechos.
4. Player com lacunas, dificuldades e controles.
5. Histórico de erros, progresso e revisão.
6. Ajustes de UX, tratamento de erros e testes.
