"""As rotas da Etapa 2, pelo TestClient, contra o banco temporário."""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento
from fluxo.servico.api import app

DIA = "2026-09-04"
T0 = datetime(2026, 9, 4, 9, 0, 0, tzinfo=FUSO_LOCAL)


@pytest.fixture
def cliente(banco):
    return TestClient(app)


def pessoa(pseudonimo="P1", camera="entrada_a"):
    return {
        "camera_id": camera, "data_ref": DIA, "pseudonimo": pseudonimo,
        "primeiro_visto": T0.isoformat(), "ultimo_visto": T0.isoformat(),
    }


def evento(track, direcao, minutos):
    return EventoCruzamento.criar(
        "entrada_a", T0 + timedelta(minutes=minutos), direcao, track_id_local=track, confianca=0.9
    )


def vinculo(e, pseudonimo, metodo="nova", sim=None):
    return {
        "id_evento": e.id_evento, "camera_id": e.camera_id, "data_ref": DIA,
        "pseudonimo": pseudonimo, "similaridade": sim,
        "atribuido": pseudonimo is not None, "metodo": metodo,
    }


class TestPessoas:
    def test_lote_grava_e_lista(self, cliente):
        r = cliente.post("/pessoas/lote", json=[pessoa("P1"), pessoa("P2")])
        assert r.status_code == 200
        assert r.json() == {"recebidos": 2, "gravados": 2}
        lista = cliente.get("/pessoas", params={"data_inicio": DIA, "data_fim": DIA}).json()
        assert [p["pseudonimo"] for p in lista] == ["P1", "P2"]

    def test_camera_desconhecida_e_404(self, cliente):
        assert cliente.post("/pessoas/lote", json=[pessoa(camera="x")]).status_code == 404

    def test_pseudonimo_longo_demais_e_422(self, cliente):
        assert cliente.post("/pessoas/lote", json=[pessoa("P" * 40)]).status_code == 422


class TestVinculos:
    def test_lote_e_reenvio(self, cliente):
        e1, e2 = evento(1, Direcao.ENTRADA, 0), evento(2, Direcao.SAIDA, 30)
        cliente.post("/eventos/lote", json=[e.model_dump(mode="json") for e in (e1, e2)])
        cliente.post("/pessoas/lote", json=[pessoa("P1")])
        corpo = [vinculo(e1, "P1"), vinculo(e2, "P1", "saida", 0.8)]
        r = cliente.post("/vinculos/lote", json=corpo)
        assert r.json() == {"recebidos": 2, "gravados": 2}
        assert cliente.post("/vinculos/lote", json=corpo).json()["gravados"] == 2
        vs = cliente.get("/vinculos", params={"camera_id": "entrada_a"}).json()
        assert len(vs) == 2
        assert vs[1]["direcao"] == "SAIDA"
        assert vs[1]["pseudonimo"] == "P1"

    def test_metodo_invalido_e_422(self, cliente):
        e = evento(1, Direcao.ENTRADA, 0)
        corpo = vinculo(e, "P1")
        corpo["metodo"] = "chute"
        assert cliente.post("/vinculos/lote", json=[corpo]).status_code == 422

    def test_nao_atribuido(self, cliente):
        e = evento(1, Direcao.SAIDA, 0)
        r = cliente.post("/vinculos/lote", json=[vinculo(e, None, "nao_atribuido")])
        assert r.status_code == 200
        v = cliente.get("/vinculos").json()[0]
        assert v["pseudonimo"] is None
        assert v["atribuido"] == 0


class TestApelido:
    def test_define_apelido(self, cliente):
        cliente.post("/pessoas/lote", json=[pessoa("P1")])
        r = cliente.put("/pessoas/apelido", json={
            "camera_id": "entrada_a", "data_ref": DIA, "pseudonimo": "P1", "apelido": "maria",
        })
        assert r.status_code == 200
        assert cliente.get("/pessoas").json()[0]["apelido"] == "maria"

    def test_pseudonimo_inexistente_e_404(self, cliente):
        r = cliente.put("/pessoas/apelido", json={
            "camera_id": "entrada_a", "data_ref": DIA, "pseudonimo": "P9", "apelido": "x",
        })
        assert r.status_code == 404


class TestChave:
    def test_escrita_exige_chave_quando_definida(self, cliente, monkeypatch):
        from fluxo import config

        monkeypatch.setattr(config, "CHAVE_API", "segredo")
        assert cliente.post("/pessoas/lote", json=[pessoa()]).status_code == 401
        assert cliente.post("/vinculos/lote", json=[]).status_code == 401
        assert cliente.put("/pessoas/apelido", json={
            "camera_id": "entrada_a", "data_ref": DIA, "pseudonimo": "P1", "apelido": "x",
        }).status_code == 401
        # Leitura continua aberta: só serve agregados.
        assert cliente.get("/pessoas").status_code == 200

    def test_com_chave_passa(self, cliente, monkeypatch):
        from fluxo import config

        monkeypatch.setattr(config, "CHAVE_API", "segredo")
        r = cliente.post("/pessoas/lote", json=[pessoa()], headers={"X-Chave-API": "segredo"})
        assert r.status_code == 200


class TestArranque:
    def test_lifespan_purga_o_vencido(self, banco, monkeypatch):
        """Pseudônimo vencido não sobrevive a um reinício do serviço."""
        from fluxo.dominio.identidade import PessoaSessao
        from fluxo.persistencia import repositorio

        velho = PessoaSessao(
            camera_id="entrada_a", data_ref=date(2020, 1, 1), pseudonimo="P1",
            primeiro_visto=datetime(2020, 1, 1, 8, tzinfo=FUSO_LOCAL),
            ultimo_visto=datetime(2020, 1, 1, 8, tzinfo=FUSO_LOCAL),
        )
        # Sem purgar na escrita, para o arranque ter o que apagar. Num contexto
        # próprio: `monkeypatch.undo()` desfaria também o CAMINHO_BANCO da
        # fixture, e o TestClient abriria o banco real.
        with pytest.MonkeyPatch.context() as sem_purga:
            sem_purga.setattr(repositorio, "purgar_expirados", lambda *a, **k: 0)
            repositorio.upsert_pessoas(banco, [velho])
        assert len(repositorio.listar_pessoas(banco)) == 1

        with TestClient(app) as c:
            assert c.get("/pessoas").json() == []
