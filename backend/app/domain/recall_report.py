"""Seção do Anki Premium no relatório: métricas de tradução, calculadas só a partir dos registros.

Fica separada do Criador de frases: traduzir certo não mede a capacidade de criar e desenvolver
ideias livremente (especificação do Sentence Recall, seção 8).
"""

import json
from collections import Counter
from datetime import datetime

from .recall import canonical_tokens
from .score import recall_score

SMALL_SAMPLE = 10


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def compute_recall_section(data: dict, now_iso: str) -> dict | None:
    attempts = data["attempts"]
    if not attempts:
        return None

    by_mode: dict[str, Counter] = {"new": Counter(), "review": Counter()}
    scores: list[int] = []
    errors: Counter = Counter()
    error_examples: dict[tuple[str, str], dict] = {}
    for a in attempts:
        by_mode[a["mode"]][a["verdict"]] += 1
        result = json.loads(a["result"]) if a["result"] else {}
        score = recall_score(a["verdict"], a["answer_text"], result.get("corrected_answer"),
                             result.get("alternative_en"), a["reference_en"])
        if score is not None:
            scores.append(score)
        for e in result.get("errors", []) if a["verdict"] == "incorrect" else []:
            if not e.get("excerpt") or not e.get("correction"):
                continue
            key = (" ".join(canonical_tokens(e["excerpt"])), " ".join(canonical_tokens(e["correction"])))
            errors[key] += 1
            error_examples.setdefault(key, {
                "excerpt": e["excerpt"], "correction": e["correction"],
                "rule_pt": e.get("rule_pt") or "", "sentence_pt": a["sentence_pt"],
            })

    recurring = [error_examples[k] | {"count": n} for k, n in errors.most_common(5)]

    topics: dict[str, dict] = {}
    for o in data["observations"]:
        if o["topic_id"] == "other":
            continue
        t = topics.setdefault(o["topic_id"], {"topic_id": o["topic_id"], "name_pt": o["name_pt"],
                                             "errors": 0, "correct": 0})
        t["errors" if o["evidence_type"] == "error" else "correct"] += 1
    topic_list = sorted(topics.values(), key=lambda t: (-t["errors"], -t["correct"]))[:8]

    words_seen = {u["vocabulary_id"]: u["english_text"] for u in data["usage"]}
    words_used = {u["vocabulary_id"] for u in data["usage"] if u["demonstrated"]}
    not_used = sorted({words_seen[v] for v in words_seen if v not in words_used})

    reviews = data["reviews"]
    review_outcomes = by_mode["review"]
    new = by_mode["new"]

    days = {datetime.fromisoformat(a["created_at"]).astimezone().date() for a in attempts}
    limitations = []
    if len(attempts) < SMALL_SAMPLE:
        limitations.append(f"Amostra pequena no Anki Premium: {len(attempts)} tradução(ões) avaliada(s).")
    limitations.append("Traduzir certo mede reconhecimento e uso das estruturas, não a produção livre de ideias.")

    return {
        "attempts": len(attempts),
        "study_days": len(days),
        "new": dict(new),
        "review": dict(review_outcomes),
        "new_accuracy": _ratio(new["correct"], new["correct"] + new["incorrect"]),
        "review_accuracy": _ratio(review_outcomes["correct"], review_outcomes["correct"] + review_outcomes["incorrect"]),
        "avg_score": round(sum(scores) / len(scores)) if scores else None,
        "words": {
            "practiced": len(words_seen),
            "used": len(words_used),
            "not_used_examples": not_used[:8],
        },
        "topics": topic_list,
        "recurring_errors": recurring,
        "reviews": {
            "pending_now": sum(1 for r in reviews if r["due_at"] <= now_iso),
            "learning": sum(1 for r in reviews if r["status"] == "learning"),
            "stable": sum(1 for r in reviews if r["status"] == "stable"),
        },
        "limitations": limitations,
    }
