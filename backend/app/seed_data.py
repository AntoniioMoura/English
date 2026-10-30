"""Biblioteca curada inicial: tópicos gramaticais e Sentence Frames.

O seed é idempotente (INSERT OR IGNORE): adiciona itens novos sem sobrescrever
alterações feitas pelo usuário (por exemplo, frames desativadas).
"""

import json
import sqlite3

from .db import utcnow

GRAMMAR_TOPICS: list[tuple[str, str, str]] = [
    ("past_simple", "Passado simples", "Verbos regulares e irregulares no passado (went, played)."),
    ("past_continuous", "Passado contínuo", "was/were + verbo com -ing para ações em andamento no passado."),
    ("present_simple", "Presente simples", "Hábitos e fatos; -s na terceira pessoa (he works)."),
    ("present_continuous", "Presente contínuo", "am/is/are + verbo com -ing."),
    ("present_perfect", "Present perfect", "have/has + particípio (I've never been...)."),
    ("present_perfect_continuous", "Present perfect contínuo", "have/has been + verbo com -ing; for/since."),
    ("future_going_to", "Futuro com going to", "am/is/are going to + verbo base."),
    ("future_will", "Futuro com will", "will + verbo base."),
    ("first_conditional", "Primeira condicional", "If + presente, will + verbo base."),
    ("auxiliaries_negation", "Auxiliares e negação", "do/does/did + not + verbo base (didn't go)."),
    ("questions", "Perguntas", "Ordem e auxiliares em perguntas."),
    ("subject_verb_agreement", "Concordância sujeito-verbo", "Verbo concorda com o sujeito (she has, they have)."),
    ("verb_forms", "Formas verbais", "Infinitivo, gerúndio e particípio (want to go, enjoy playing)."),
    ("articles", "Artigos", "Uso de a/an/the ou ausência de artigo."),
    ("prepositions", "Preposições", "in/on/at/to/for/with etc."),
    ("pronouns", "Pronomes", "Pronomes pessoais, possessivos e objeto."),
    ("plurals_nouns", "Plural e substantivos", "Plural regular/irregular e contáveis/incontáveis."),
    ("adjectives_adverbs", "Adjetivos e advérbios", "Posição e forma (good/well, a big house)."),
    ("comparatives", "Comparativos e superlativos", "bigger than, the best."),
    ("word_order", "Ordem das palavras", "Posição de sujeito, verbo, objeto, advérbios."),
    ("connectors", "Conectores", "because, but, so, when, and, although..."),
    ("modals", "Verbos modais", "can, could, should, must + verbo base."),
    ("spelling", "Ortografia", "Grafia das palavras."),
    ("capitalization_punctuation", "Maiúsculas e pontuação", "I maiúsculo, início de frase, vírgulas e ponto."),
    ("other", "Outro", "Tópicos fora do catálogo padrão."),
]

SENTENCE_FRAMES: list[dict] = [
    {
        "id": "wanted_but",
        "text": "I wanted to ___, but ___.",
        "explanation_pt": "Algo que você queria fazer e o que impediu. Depois de 'wanted to' use o verbo base.",
        "level": "A2",
        "grammar_tags": ["past_simple", "verb_forms", "connectors"],
        "examples": ["I wanted to go out, but it was raining."],
    },
    {
        "id": "didnt_because",
        "text": "I didn't ___ because ___.",
        "explanation_pt": "Algo que você não fez e o motivo. Depois de 'didn't' use o verbo base.",
        "level": "A2",
        "grammar_tags": ["auxiliaries_negation", "past_simple", "connectors"],
        "examples": ["I didn't call you because my phone was dead."],
    },
    {
        "id": "was_when",
        "text": "I was ___ when ___.",
        "explanation_pt": "Uma ação em andamento no passado interrompida por outra (passado contínuo + passado simples).",
        "level": "A2",
        "grammar_tags": ["past_continuous", "past_simple", "connectors"],
        "examples": ["I was cooking dinner when the lights went out."],
    },
    {
        "id": "going_to",
        "text": "I'm going to ___.",
        "explanation_pt": "Um plano ou intenção para o futuro. Use 'going to' + verbo base.",
        "level": "A2",
        "grammar_tags": ["future_going_to", "verb_forms"],
        "examples": ["I'm going to visit my grandparents this weekend."],
    },
    {
        "id": "think_because",
        "text": "I think ___ because ___.",
        "explanation_pt": "Dar uma opinião e justificá-la.",
        "level": "A2",
        "grammar_tags": ["present_simple", "connectors"],
        "examples": ["I think this game is great because it's very creative."],
    },
    {
        "id": "never_done",
        "text": "I've never ___.",
        "explanation_pt": "Uma experiência que você nunca teve. Use 'have never' + particípio.",
        "level": "B1",
        "grammar_tags": ["present_perfect"],
        "examples": ["I've never been to the beach in winter."],
    },
    {
        "id": "been_for",
        "text": "I've been ___ for ___.",
        "explanation_pt": "Algo que começou no passado e continua até agora, com a duração (for + período).",
        "level": "B1",
        "grammar_tags": ["present_perfect_continuous", "prepositions"],
        "examples": ["I've been studying English for two years."],
    },
    {
        "id": "if_will",
        "text": "If I ___, I'll ___.",
        "explanation_pt": "Uma condição possível e a consequência (If + presente, will + verbo base).",
        "level": "B1",
        "grammar_tags": ["first_conditional", "present_simple", "future_will"],
        "examples": ["If I finish my homework early, I'll play video games."],
    },
]


def seed(conn: sqlite3.Connection) -> None:
    now = utcnow()
    conn.executemany(
        "INSERT OR IGNORE INTO grammar_topics (id, name_pt, description_pt) VALUES (?, ?, ?)",
        GRAMMAR_TOPICS,
    )
    conn.executemany(
        """INSERT OR IGNORE INTO sentence_frames
           (id, text, explanation_pt, level, grammar_tags, examples, enabled, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 1, 'curated', ?)""",
        [
            (
                f["id"],
                f["text"],
                f["explanation_pt"],
                f["level"],
                json.dumps(f["grammar_tags"]),
                json.dumps(f["examples"]),
                now,
            )
            for f in SENTENCE_FRAMES
        ],
    )
    conn.commit()
