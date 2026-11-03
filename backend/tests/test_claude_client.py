import pytest
from pydantic import BaseModel

from app import config
from app.api import deps
from app.llm.claude_client import ClaudeClient, FallbackClient
from app.llm.client import LLMError, LLMUnavailable, OllamaClient


class Answer(BaseModel):
    text: str


class Stub:
    def __init__(self, model, result):
        self.model, self.result, self.calls = model, result, 0

    def generate(self, system, user, schema, temperature=None):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return schema(text=self.result)


def test_fallback_uses_claude_when_it_answers():
    claude, ollama = Stub("claude-sonnet-5-5", "do"), Stub("qwen3:14b", "x")
    llm = FallbackClient(claude, ollama)
    assert llm.generate("s", "u", Answer).text == "do"
    assert llm.model == "claude-sonnet-5-5" and ollama.calls == 0


@pytest.mark.parametrize("error", [LLMError("sem saldo"), LLMUnavailable("sem internet")])
def test_fallback_goes_to_ollama_when_claude_fails(error):
    claude, ollama = Stub("claude-sonnet-5-5", error), Stub("qwen3:14b", "ok")
    llm = FallbackClient(claude, ollama)
    assert llm.generate("s", "u", Answer).text == "ok"
    assert llm.model == "qwen3:14b"  # fica registrado quem corrigiu


def test_corrector_is_ollama_without_key(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    from app import db
    conn = db.init_db(tmp_path / "t.db")
    assert isinstance(deps.get_corrector(conn), OllamaClient)


def test_corrector_stays_on_ollama_when_claude_is_switched_off(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")
    from app import db
    conn = db.init_db(tmp_path / "t.db")
    assert isinstance(deps.get_corrector(conn), OllamaClient)  # desligado por padrão: não gasta créditos


def test_corrector_is_claude_with_ollama_backup_when_switched_on(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")
    from app import db
    from app.services import settings_service
    conn = db.init_db(tmp_path / "t.db")
    settings_service.save_claude_settings(conn, settings_service.ClaudeSettings(enabled=True))
    llm = deps.get_corrector(conn)
    assert isinstance(llm, FallbackClient)
    assert isinstance(llm.primary, ClaudeClient) and llm.primary.model == config.CLAUDE_MODEL
    assert isinstance(llm.backup, OllamaClient)


def test_env_file_is_read_without_overriding_real_variables(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comentário\nEB_TEST_KEY="abc"\nEB_TEST_SET=arquivo\n', encoding="utf-8")
    monkeypatch.delenv("EB_TEST_KEY", raising=False)
    monkeypatch.setenv("EB_TEST_SET", "variavel")
    config._load_env_file(env)
    import os
    assert os.environ["EB_TEST_KEY"] == "abc"
    assert os.environ["EB_TEST_SET"] == "variavel"
    monkeypatch.delenv("EB_TEST_KEY")


def test_claude_switch_api(client, monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    r = client.get("/api/settings/claude").json()
    assert r["enabled"] is False and r["key_configured"] is False and r["active"] is False
    r = client.put("/api/settings/claude", json={"enabled": True})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_api_key"

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")
    r = client.put("/api/settings/claude", json={"enabled": True}).json()
    assert r["enabled"] is True and r["active"] is True and r["model"] == config.CLAUDE_MODEL
    assert client.get("/api/settings/claude").json()["active"] is True  # fica salvo
    r = client.put("/api/settings/claude", json={"enabled": False}).json()
    assert r["active"] is False
    assert "sk-ant" not in str(r)  # a chave nunca sai pela API
