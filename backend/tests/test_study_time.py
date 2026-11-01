from datetime import datetime, timezone

import pytest

from app.services import recall_service

# 23:59:50 de 31/10 em São Paulo (UTC-3).
BEFORE_MIDNIGHT = datetime(2026, 11, 1, 2, 59, 50, tzinfo=timezone.utc)
AFTER_MIDNIGHT = datetime(2026, 11, 1, 3, 0, 5, tzinfo=timezone.utc)


@pytest.fixture
def clock(monkeypatch):
    moment = {"now": BEFORE_MIDNIGHT}
    monkeypatch.setattr(recall_service, "now", lambda: moment["now"])
    return moment


def test_soma_por_dia_e_atividade(client, clock):
    assert client.get("/api/study-time/today").json() == {
        "day": "2026-10-31", "total_seconds": 0, "seconds_until_reset": 10,
    }
    client.post("/api/study-time", json={"seconds": {"builder": 10, "listening": 5}})
    r = client.post("/api/study-time", json={"seconds": {"builder": 20, "anki_review": 0}})
    assert r.json()["total_seconds"] == 35

    month = client.get("/api/study-time/month", params={"month": "2026-10"}).json()
    assert month["total_seconds"] == 35
    assert month["days"] == [
        {"date": "2026-10-31", "total_seconds": 35, "activities": {"builder": 30, "listening": 5}},
    ]


def test_zera_a_meia_noite_e_guarda_o_dia_anterior(client, clock):
    client.post("/api/study-time", json={"seconds": {"builder": 100}})
    clock["now"] = AFTER_MIDNIGHT
    today = client.get("/api/study-time/today").json()
    assert (today["day"], today["total_seconds"]) == ("2026-11-01", 0)
    assert client.get("/api/study-time/month", params={"month": "2026-10"}).json()["total_seconds"] == 100
    assert client.get("/api/study-time/month").json()["month"] == "2026-11"


def test_envio_atrasado_conta_para_o_dia_medido(client, clock):
    clock["now"] = AFTER_MIDNIGHT
    r = client.post("/api/study-time", json={"seconds": {"listening": 8}, "day": "2026-10-31"}).json()
    assert (r["day"], r["total_seconds"]) == ("2026-11-01", 0)
    assert client.get("/api/study-time/month", params={"month": "2026-10"}).json()["total_seconds"] == 8


def test_data_antiga_cai_em_hoje(client, clock):
    client.post("/api/study-time", json={"seconds": {"builder": 8}, "day": "2020-01-01"})
    assert client.get("/api/study-time/today").json()["total_seconds"] == 8


@pytest.mark.parametrize("payload", [
    {"seconds": {"reports": 10}},  # relatórios não contam
    {"seconds": {"builder": -1}},
])
def test_rejeita_atividade_ou_tempo_invalido(client, payload):
    assert client.post("/api/study-time", json=payload).status_code == 422


def test_rejeita_mes_invalido(client):
    assert client.get("/api/study-time/month", params={"month": "2026-13"}).status_code == 422
