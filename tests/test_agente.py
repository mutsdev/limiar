"""Fila local e remetente — a defesa contra a rede da portaria cair."""

from datetime import datetime, timedelta

import httpx
import pytest

from fluxo.agente.fila_local import FilaLocal
from fluxo.agente.remetente import Remetente
from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento


def evento(track=1, segundos=0):
    return EventoCruzamento.criar(
        "entrada_a",
        datetime(2026, 8, 25, 8, 0, 0, tzinfo=FUSO_LOCAL) + timedelta(seconds=segundos),
        Direcao.ENTRADA,
        track_id_local=track,
        confianca=0.9,
    )


class TestFilaLocal:
    def test_enfileira_e_le_de_volta(self, tmp_path):
        fila = FilaLocal(tmp_path / "f.jsonl")
        assert fila.enfileirar([evento(1), evento(2, 5)]) == 2
        lidos = fila.ler()
        assert [e.track_id_local for e in lidos] == [1, 2]
        assert lidos[0].direcao is Direcao.ENTRADA

    def test_fila_inexistente_e_vazia(self, tmp_path):
        fila = FilaLocal(tmp_path / "nao-existe.jsonl")
        assert fila.ler() == []
        assert fila.tamanho == 0

    def test_append_preserva_o_que_ja_estava(self, tmp_path):
        fila = FilaLocal(tmp_path / "f.jsonl")
        fila.enfileirar([evento(1)])
        fila.enfileirar([evento(2, 5)])
        assert fila.tamanho == 2

    def test_linha_truncada_e_descartada_sem_derrubar_o_resto(self, tmp_path):
        """Queda no meio da escrita corrompe no maximo a ultima linha.

        Descartar uma linha e melhor que travar a fila inteira — o formato
        JSONL existe exatamente para ter essa propriedade.
        """
        caminho = tmp_path / "f.jsonl"
        fila = FilaLocal(caminho)
        fila.enfileirar([evento(1), evento(2, 5)])
        with caminho.open("a", encoding="utf-8") as f:
            f.write('{"camera_id": "entrada_a", "instan')
        assert len(fila.ler()) == 2

    def test_limpar_remove(self, tmp_path):
        fila = FilaLocal(tmp_path / "f.jsonl")
        fila.enfileirar([evento(1)])
        fila.limpar()
        assert fila.tamanho == 0


class _RespostaFalsa:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erro", request=None, response=None)


class TestRemetente:
    def test_envio_bem_sucedido_nao_enfileira(self, tmp_path, monkeypatch):
        enviados = []
        monkeypatch.setattr(
            httpx, "post", lambda url, **kw: (enviados.append(kw["json"]), _RespostaFalsa())[1]
        )
        fila = FilaLocal(tmp_path / "f.jsonl")
        r = Remetente("http://x", fila, espera_inicial=0)
        assert r.enviar([evento(1), evento(2, 5)]) is True
        assert r.enviados == 2
        assert fila.tamanho == 0
        assert len(enviados[0]) == 2

    def test_servico_fora_do_ar_manda_tudo_para_a_fila(self, tmp_path, monkeypatch):
        def cai(url, **kw):
            raise httpx.ConnectError("sem rede")

        monkeypatch.setattr(httpx, "post", cai)
        fila = FilaLocal(tmp_path / "f.jsonl")
        r = Remetente("http://x", fila, tentativas=2, espera_inicial=0)
        assert r.enviar([evento(1)]) is False
        assert r.enviados == 0
        assert fila.tamanho == 1

    def test_tenta_de_novo_antes_de_desistir(self, tmp_path, monkeypatch):
        chamadas = {"n": 0}

        def instavel(url, **kw):
            chamadas["n"] += 1
            if chamadas["n"] < 3:
                raise httpx.ConnectError("instavel")
            return _RespostaFalsa()

        monkeypatch.setattr(httpx, "post", instavel)
        fila = FilaLocal(tmp_path / "f.jsonl")
        r = Remetente("http://x", fila, tentativas=3, espera_inicial=0)
        assert r.enviar([evento(1)]) is True
        assert chamadas["n"] == 3
        assert fila.tamanho == 0

    def test_drenar_fila_esvazia_quando_a_rede_volta(self, tmp_path, monkeypatch):
        fila = FilaLocal(tmp_path / "f.jsonl")
        fila.enfileirar([evento(i, i) for i in range(1, 6)])

        monkeypatch.setattr(httpx, "post", lambda url, **kw: _RespostaFalsa())
        r = Remetente("http://x", fila, espera_inicial=0)
        assert r.drenar_fila() == 5
        assert fila.tamanho == 0

    def test_drenar_fila_mantem_tudo_se_a_rede_ainda_esta_fora(self, tmp_path, monkeypatch):
        fila = FilaLocal(tmp_path / "f.jsonl")
        fila.enfileirar([evento(1)])

        def cai(url, **kw):
            raise httpx.ConnectError("sem rede")

        monkeypatch.setattr(httpx, "post", cai)
        r = Remetente("http://x", fila, tentativas=1, espera_inicial=0)
        assert r.drenar_fila() == 0
        assert fila.tamanho == 1

    def test_lista_vazia_nao_faz_requisicao(self, tmp_path, monkeypatch):
        def nao_deveria(url, **kw):
            raise AssertionError("nao deveria ter chamado a rede")

        monkeypatch.setattr(httpx, "post", nao_deveria)
        r = Remetente("http://x", FilaLocal(tmp_path / "f.jsonl"))
        assert r.enviar([]) is True

    @pytest.mark.parametrize("status,esperado", [(200, True), (500, False)])
    def test_saude(self, tmp_path, monkeypatch, status, esperado):
        monkeypatch.setattr(httpx, "get", lambda url, **kw: _RespostaFalsa(status))
        r = Remetente("http://x", FilaLocal(tmp_path / "f.jsonl"))
        assert r.servico_no_ar() is esperado
