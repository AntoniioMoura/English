import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ENGLISH_BUILDER_NO_ENV_FILE"] = "1"  # nunca chamar o Claude de verdade nos testes

from app.api.deps import get_corrector, get_llm  # noqa: E402
from app.llm.client import LLMError, LLMUnavailable  # noqa: E402
from app.llm.schemas import LLMFinalReview, LLMReferenceCheck  # noqa: E402
from app.main import create_app  # noqa: E402


class FakeLLM:
    """Devolve respostas pré-programadas (dict ou exceção), na ordem.

    A revisão focada da frase final tem fila própria; sem resposta, ela "falha"
    e a avaliação segue só com a passada principal.
    """

    model = "fake-model:1"

    def __init__(self):
        self.responses: list = []
        self.reviews: list = []
        self.reference_checks: list = []
        self.calls: list[tuple[str, str]] = []

    def queue(self, *responses):
        self.responses.extend(responses)

    def queue_review(self, *responses):
        self.reviews.extend(responses)

    def generate(self, system, user, schema, temperature=None):
        if schema is LLMReferenceCheck:  # checagem da referência: aprova, salvo se programada
            response = self.reference_checks.pop(0) if self.reference_checks else {"is_correct": True, "corrected_en": ""}
            return schema.model_validate(response)
        if schema is LLMFinalReview:
            if not self.reviews:
                raise LLMUnavailable("sem revisão programada")
            return schema.model_validate(self.reviews.pop(0))
        self.calls.append((system, user))
        if not self.responses:
            raise LLMError("sem resposta programada")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return schema.model_validate(response)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def client(db_path, llm):
    app = create_app(db_path)
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_corrector] = lambda: llm
    with TestClient(app) as c:
        yield c


V = [
    "I wanted to play, but I was tired.",
    "I wanted to play with my friends, but I was tired.",
    "I wanted to play with my friends last night, but I was tired after work.",
    "I wanted to play with my friends last night, but I was tired after work, so I went to bed early.",
]


def make_evaluation(**overrides) -> dict:
    base = {
        "highlights": ["Boa utilização de 'but' para mostrar contraste."],
        "frame_usage": {"used_correctly": True, "comment_pt": "Frame usada corretamente."},
        "grammar_errors": [],
        "grammar_correct_evidence": [],
        "idea_development": [],
        "self_corrections": [],
        "corrected_final_sentence": None,
        "next_tip": "Experimente usar 'because' na próxima.",
    }
    base.update(overrides)
    return base


def complete_versions(client, exercise_id, versions=V):
    for i, text in enumerate(versions):
        r = client.post(f"/api/exercises/{exercise_id}/versions", json={"version_index": i, "text": text})
        assert r.status_code == 200, r.text
    return r.json()


def new_exercise(client, frame_id="wanted_but"):
    r = client.post("/api/exercises", json={"selection_mode": "manual", "frame_id": frame_id})
    assert r.status_code == 201, r.text
    return r.json()
