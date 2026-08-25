from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento
from fluxo.servico.api import app


@pytest.fixture
def cliente(banco):
    """TestClient apontando para o banco temporário da fixture `banco`.

    A fixture monkeypatcha config.CAMINHO_BANCO, e a dependência do serviço
    abre a conexão no momento da requisição — então o serviço enxerga o banco
    de teste sem precisar de override explícito.
    """
    return TestClient(app)


def corpo(camera="entrada_a", h=8, direcao=Direcao.ENTRADA, track=1):
    evento = EventoCruzamento.criar(
        camera,
        datetime(2026, 8, 25, h, 0, 0, tzinfo=FUSO_LOCAL),
        direcao,
        track_id_local=track,
        confianca=0.9,
    )
    return evento.model_dump(mode="json")


class TestSaude:
    def test_responde_ok(self, cliente):
        r = cliente.get("/saude")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestIngestao:
    def test_evento_valido_e_registrado(self, cliente):
        r = cliente.post("/eventos", json=corpo())
        assert r.status_code == 200
        assert r.json()["registrado"] is True

    def test_reenvio_devolve_200_sem_duplicar(self, cliente):
        c = corpo()
        assert cliente.post("/eventos", json=c).json()["registrado"] is True
        segunda = cliente.post("/eventos", json=c)
        assert segunda.status_code == 200
        assert segunda.json()["registrado"] is False
        assert len(cliente.get("/eventos").json()) == 1

    def test_direcao_invalida_devolve_422(self, cliente):
        c = corpo()
        c["direcao"] = "ENTRDA"
        assert cliente.post("/eventos", json=c).status_code == 422

    def test_confianca_fora_da_faixa_devolve_422(self, cliente):
        c = corpo()
        c["confianca"] = 1.7
        assert cliente.post("/eventos", json=c).status_code == 422

    def test_camera_desconhecida_devolve_404(self, cliente):
        r = cliente.post("/eventos", json=corpo(camera="porta_dos_fundos"))
        assert r.status_code == 404
        assert "não está cadastrada" in r.json()["detail"]


class TestLote:
    def test_grava_o_lote_inteiro(self, cliente):
        lote = [corpo(track=i) for i in range(20)]
        dados = cliente.post("/eventos/lote", json=lote).json()
        assert dados == {"recebidos": 20, "registrados": 20, "duplicados": 0}

    def test_reenvio_do_lote_e_todo_duplicado(self, cliente):
        lote = [corpo(track=i) for i in range(20)]
        cliente.post("/eventos/lote", json=lote)
        dados = cliente.post("/eventos/lote", json=lote).json()
        assert dados == {"recebidos": 20, "registrados": 0, "duplicados": 20}


class TestConsulta:
    @pytest.fixture
    def povoado(self, cliente):
        lote = [
            corpo(camera="entrada_a", h=8, track=1),
            corpo(camera="entrada_a", h=8, track=2),
            corpo(camera="entrada_a", h=18, direcao=Direcao.SAIDA, track=3),
            corpo(camera="entrada_b", h=19, direcao=Direcao.SAIDA, track=4),
        ]
        cliente.post("/eventos/lote", json=lote)
        return cliente

    def test_contagem_diaria(self, povoado):
        linhas = povoado.get("/contagem/diaria").json()
        totais = {(r["camera_id"], r["direcao"]): r["total"] for r in linhas}
        assert totais[("entrada_a", "ENTRADA")] == 2
        assert totais[("entrada_a", "SAIDA")] == 1
        assert totais[("entrada_b", "SAIDA")] == 1

    def test_contagem_horaria(self, povoado):
        linhas = povoado.get("/contagem/horaria?camera_id=entrada_a").json()
        assert {(r["hora"], r["direcao"], r["total"]) for r in linhas} == {
            (8, "ENTRADA", 2),
            (18, "SAIDA", 1),
        }

    def test_lista_cameras(self, povoado):
        ids = {c["id"] for c in povoado.get("/cameras").json()}
        assert {"entrada_a", "entrada_b"} <= ids
