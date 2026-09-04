"""O remetente da Etapa 2: rotas certas, fila própria, e nada derruba a contagem."""

from datetime import date, datetime

import httpx

from fluxo.agente.fila_local import FilaLocal
from fluxo.agente.remetente import Remetente
from fluxo.dominio.evento import FUSO_LOCAL
from fluxo.dominio.identidade import Apelido, PessoaSessao, Vinculo

T0 = datetime(2026, 9, 4, 9, 0, 0, tzinfo=FUSO_LOCAL)


class _Resposta:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erro", request=None, response=None)


def pessoa(pseudonimo="P1"):
    return PessoaSessao(
        camera_id="entrada_a", data_ref=date(2026, 9, 4), pseudonimo=pseudonimo,
        primeiro_visto=T0, ultimo_visto=T0,
    )


def vinculo(i, pseudonimo="P1"):
    return Vinculo(
        id_evento=f"e{i}", camera_id="entrada_a", data_ref=date(2026, 9, 4),
        pseudonimo=pseudonimo, similaridade=0.9, atribuido=True, metodo="saida",
    )


def remetente(tmp_path, **kw):
    return Remetente(
        "http://servico", FilaLocal(tmp_path / "fila.jsonl"), espera_inicial=0.0,
        fila_vinculos=FilaLocal(tmp_path / "vinculos.jsonl", modelo=Vinculo), **kw,
    )


class TestRotas:
    def test_pessoas_vao_para_a_rota_certa(self, tmp_path, monkeypatch):
        chamadas = []
        monkeypatch.setattr(
            httpx, "post", lambda url, **kw: (chamadas.append((url, kw["json"])), _Resposta())[1]
        )
        assert remetente(tmp_path).registrar_pessoas([pessoa()]) is True
        assert chamadas[0][0] == "http://servico/pessoas/lote"
        assert chamadas[0][1][0]["pseudonimo"] == "P1"

    def test_vinculos_vao_para_a_rota_certa(self, tmp_path, monkeypatch):
        chamadas = []
        monkeypatch.setattr(
            httpx, "post", lambda url, **kw: (chamadas.append(url), _Resposta())[1]
        )
        assert remetente(tmp_path).enviar_vinculos([vinculo(1)]) is True
        assert chamadas == ["http://servico/vinculos/lote"]

    def test_apelido_e_put(self, tmp_path, monkeypatch):
        chamadas = []
        monkeypatch.setattr(
            httpx, "put", lambda url, **kw: (chamadas.append((url, kw["json"])), _Resposta())[1]
        )
        a = Apelido(camera_id="entrada_a", data_ref=date(2026, 9, 4), pseudonimo="P1", apelido="m")
        assert remetente(tmp_path).aplicar_apelido(a) is True
        assert chamadas[0][0] == "http://servico/pessoas/apelido"
        assert chamadas[0][1]["apelido"] == "m"

    def test_listas_vazias_nao_fazem_requisicao(self, tmp_path, monkeypatch):
        def nao(*a, **k):
            raise AssertionError("não deveria postar")

        monkeypatch.setattr(httpx, "post", nao)
        r = remetente(tmp_path)
        assert r.registrar_pessoas([]) is True
        assert r.enviar_vinculos([]) is True


class TestFilaDeVinculos:
    def test_sem_rede_vai_para_a_fila_propria(self, tmp_path, monkeypatch):
        def cai(*a, **k):
            raise httpx.ConnectError("sem rede")

        monkeypatch.setattr(httpx, "post", cai)
        r = remetente(tmp_path)
        assert r.enviar_vinculos([vinculo(1), vinculo(2)]) is False
        assert r.fila_vinculos.tamanho == 2
        assert r.fila.tamanho == 0  # a fila de eventos não é tocada
        assert all(isinstance(v, Vinculo) for v in r.fila_vinculos.ler())

    def test_quando_a_rede_volta_a_fila_e_drenada(self, tmp_path, monkeypatch):
        r = remetente(tmp_path)
        r.fila_vinculos.enfileirar([vinculo(1)])
        enviados = []
        monkeypatch.setattr(
            httpx, "post", lambda url, **kw: (enviados.append(kw["json"]), _Resposta())[1]
        )
        assert r.enviar_vinculos([vinculo(2)]) is True
        assert r.fila_vinculos.tamanho == 0
        assert sorted(v["id_evento"] for lote in enviados for v in lote) == ["e1", "e2"]

    def test_sem_fila_configurada_perde_sem_quebrar(self, tmp_path, monkeypatch):
        def cai(*a, **k):
            raise httpx.ConnectError("sem rede")

        monkeypatch.setattr(httpx, "post", cai)
        r = Remetente("http://servico", FilaLocal(tmp_path / "f.jsonl"), espera_inicial=0.0)
        assert r.enviar_vinculos([vinculo(1)]) is False
        assert r.drenar_vinculos() == 0

    def test_pessoas_nao_tem_fila(self, tmp_path, monkeypatch):
        def cai(*a, **k):
            raise httpx.ConnectError("sem rede")

        monkeypatch.setattr(httpx, "post", cai)
        r = remetente(tmp_path)
        assert r.registrar_pessoas([pessoa()]) is False
        assert r.fila_vinculos.tamanho == 0

    def test_apelido_sem_rede_devolve_falso(self, tmp_path, monkeypatch):
        def cai(*a, **k):
            raise httpx.ConnectError("sem rede")

        monkeypatch.setattr(httpx, "put", cai)
        a = Apelido(camera_id="entrada_a", data_ref=date(2026, 9, 4), pseudonimo="P1", apelido="m")
        assert remetente(tmp_path).aplicar_apelido(a) is False


class TestFilaGenerica:
    def test_fila_de_eventos_continua_igual(self, tmp_path):
        from fluxo.dominio.evento import Direcao, EventoCruzamento

        fila = FilaLocal(tmp_path / "f.jsonl")
        e = EventoCruzamento.criar("entrada_a", T0, Direcao.ENTRADA, track_id_local=1)
        fila.enfileirar([e])
        assert fila.ler() == [e]

    def test_fila_de_vinculos_le_vinculos(self, tmp_path):
        fila = FilaLocal(tmp_path / "v.jsonl", modelo=Vinculo)
        fila.enfileirar([vinculo(1)])
        assert fila.ler() == [vinculo(1)]
