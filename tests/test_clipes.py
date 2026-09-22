"""Clipes de dúvida: gatilhos, anel, debounce, veredito e purga — sem OpenCV."""

from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timedelta

import pytest

from fluxo.contagem.linha import Duvida, LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL, Direcao
from fluxo.dominio.rastro import Rastro
from fluxo.reid.galeria import Decisao
from fluxo.visao import clipes

T0 = datetime(2026, 9, 21, 9, 0, 0, tzinfo=FUSO_LOCAL)
A, B = (450.0, 30.0), (450.0, 240.0)


def linha(**kw):
    return LinhaDeContagem(camera_id="entrada_a", a=A, b=B, zona_morta_px=15.0, **kw)


def rastro(track, x, conf=0.9):
    return Rastro(id_local=track, caixa=(x - 20, 35, x + 20, 135), confianca=conf)


def decisao(metodo, sim, track=3, pseudonimo="P1"):
    return Decisao("e", track, Direcao.SAIDA, T0, pseudonimo, sim, metodo)


class TestGatilhos:
    def test_deteccao_fraca_perto_da_linha(self):
        ds = clipes.duvidas_de_deteccao([rastro(7, 440, conf=0.4)], linha())
        assert [(d.gatilho, d.track) for d in ds] == [("deteccao", 7)]
        assert "0.40" in ds[0].motivo

    def test_deteccao_forte_perto_nao_e_duvida(self):
        assert clipes.duvidas_de_deteccao([rastro(7, 440, conf=0.9)], linha()) == []

    def test_deteccao_fraca_longe_nao_e_duvida(self):
        assert clipes.duvidas_de_deteccao([rastro(7, 300, conf=0.4)], linha()) == []

    def test_reid_sem_par_sempre(self):
        ds = clipes.duvidas_de_reid(
            [decisao("nao_atribuido", 0.66, pseudonimo=None)], {"saida": 0.70}
        )
        assert len(ds) == 1 and ds[0].gatilho == "reid"
        assert "0.66 < 0.70" in ds[0].motivo

    def test_reid_sem_par_sem_candidata(self):
        ds = clipes.duvidas_de_reid([decisao("nao_atribuido", None, pseudonimo=None)], {})
        assert "ninguém" in ds[0].motivo

    def test_reid_no_fio_do_limiar(self):
        limiares = {"saida": 0.70, "reentrada": 0.75}
        assert len(clipes.duvidas_de_reid([decisao("saida", 0.72)], limiares)) == 1
        assert len(clipes.duvidas_de_reid([decisao("reentrada", 0.71)], limiares)) == 1
        assert clipes.duvidas_de_reid([decisao("saida", 0.90)], limiares) == []
        assert clipes.duvidas_de_reid([decisao("nova", None)], limiares) == []

    def test_sem_limiares_so_o_sem_par_dispara(self):
        assert clipes.duvidas_de_reid([decisao("saida", 0.70)], {}) == []


def gravador(tmp_path, fps=10, antes_s=1.0, depois_s=0.5, **kw):
    gravados = []
    relogio = [0.0]
    g = clipes.GravadorDeDuvidas(
        tmp_path, "entrada_a", fps, 640, 480, params={"x": 1},
        antes_s=antes_s, depois_s=depois_s,
        codificar=lambda img: bytes([img]),
        gravar=lambda caminho, quadros, sidecar: gravados.append((caminho, quadros, sidecar)),
        relogio=lambda: relogio[0], **kw,
    )
    return g, gravados, relogio


class TestGravador:
    def test_grava_depois_s_apos_o_gatilho_com_o_anel_inteiro(self, tmp_path):
        g, gravados, _ = gravador(tmp_path)  # anel de 15 quadros, 5 depois
        li = linha()
        for i in range(20):
            g.observar(i, T0 + timedelta(seconds=i / 10), [], li, [])
        li.duvidas.append(Duvida("contagem", 7, "sumiu"))
        d = g.observar(20, T0 + timedelta(seconds=2), [], li, [])
        assert d is not None and d.track == 7
        assert gravados == []
        for i in range(21, 26):
            g.observar(i, T0 + timedelta(seconds=i / 10), [], li, [])
        assert len(gravados) == 1
        caminho, quadros, sidecar = gravados[0]
        # 15 quadros: os 9 antes do gatilho, o do gatilho, e os 5 depois.
        assert quadros == [bytes([i]) for i in range(11, 26)]
        assert caminho.parent == tmp_path
        assert caminho.name == "20260921_090002_contagem_t7.mp4"
        assert sidecar["motivo"] == "sumiu" and sidecar["params"] == {"x": 1}
        assert sidecar["quadros"] == 15 and sidecar["fps"] == 10
        assert g.gravados == 1
        assert list(li.duvidas) == []

    def test_mesma_chave_nao_grava_duas_vezes(self, tmp_path):
        g, gravados, relogio = gravador(tmp_path)
        li = linha()
        assert g.observar(0, T0, [rastro(7, 440, conf=0.4)], li, []) is not None
        for i in range(1, 10):
            relogio[0] = 100.0 * i
            assert g.observar(i, T0, [rastro(7, 440, conf=0.4)], li, []) is None
        assert g.ignoradas == 0  # vista, não ignorada: nem chegou a competir

    def test_intervalo_minimo_entre_clipes(self, tmp_path):
        g, _, relogio = gravador(tmp_path, intervalo_min_s=10.0)
        li = linha()
        assert g.observar(0, T0, [rastro(1, 440, conf=0.4)], li, []) is not None
        for i in range(1, 6):
            g.observar(i, T0, [], li, [])  # fecha o clipe em curso
        relogio[0] = 5.0
        assert g.observar(6, T0, [rastro(2, 440, conf=0.4)], li, []) is None
        assert g.ignoradas == 1
        relogio[0] = 11.0
        assert g.observar(7, T0, [rastro(3, 440, conf=0.4)], li, []) is not None

    def test_duvida_durante_gravacao_e_ignorada(self, tmp_path):
        g, _, _ = gravador(tmp_path)
        li = linha()
        g.observar(0, T0, [rastro(1, 440, conf=0.4)], li, [])
        assert g.observar(1, T0, [rastro(2, 440, conf=0.4)], li, []) is None
        assert g.ignoradas == 1

    def test_fechar_grava_o_que_estava_em_curso(self, tmp_path):
        g, gravados, _ = gravador(tmp_path)
        g.observar(0, T0, [rastro(1, 440, conf=0.4)], linha(), [])
        g.fechar()
        assert len(gravados) == 1
        g.fechar()
        assert len(gravados) == 1

    def test_fechar_espera_as_threads_de_gravacao(self, tmp_path):
        esperas = []

        class ThreadFalsa:
            def join(self, timeout=None):
                esperas.append(timeout)

        g = clipes.GravadorDeDuvidas(
            tmp_path, "entrada_a", 10, 640, 480,
            codificar=lambda img: b"q",
            gravar=lambda *a: [ThreadFalsa()],
        )
        g.observar(object(), T0, [rastro(1, 440, conf=0.4)], linha(), [])
        g.fechar(espera_s=5.0)
        # Sem o join, o processo termina no meio da escrita e o mp4 fica vazio.
        assert esperas == [5.0]

    def test_teto_de_clipes_por_execucao(self, tmp_path):
        g, _, relogio = gravador(tmp_path, maximo=2)
        li = linha()
        for i in range(5):
            relogio[0] = i * 100.0
            g.observar(i, T0, [rastro(i, 440, conf=0.4)], li, [])
            for j in range(6):  # fecha o clipe em curso
                g.observar(i * 10 + j, T0, [], li, [])
        assert g.gravados == 2
        assert g.ignoradas == 3

    def test_decisoes_de_reid_tambem_disparam(self, tmp_path):
        g, _, _ = gravador(tmp_path, limiares={"saida": 0.70})
        d = g.observar(0, T0, [], linha(), [decisao("nao_atribuido", 0.6, pseudonimo=None)])
        assert d is not None and d.gatilho == "reid"


def clipe_no_disco(pasta, id_clipe, instante="2026-09-21T09:00:00-03:00"):
    (pasta / f"{id_clipe}.mp4").write_bytes(b"v")
    (pasta / f"{id_clipe}.json").write_text(
        f'{{"id": "{id_clipe}", "instante": "{instante}", "camera": "entrada_a", '
        f'"gatilho": "contagem"}}', encoding="utf-8",
    )


class TestDisco:
    def test_listar_mais_novo_primeiro_e_so_com_mp4(self, tmp_path):
        clipe_no_disco(tmp_path, "a", "2026-09-21T09:00:00-03:00")
        clipe_no_disco(tmp_path, "b", "2026-09-21T10:00:00-03:00")
        (tmp_path / "c.json").write_text('{"id": "c", "instante": "2026-09-21T11:00:00-03:00"}')
        lista = clipes.listar_clipes(tmp_path)
        assert [c["id"] for c in lista] == ["b", "a"]
        assert lista[0]["mp4"].endswith("b.mp4")

    def test_listar_pasta_inexistente(self, tmp_path):
        assert clipes.listar_clipes(tmp_path / "nada") == []

    def test_veredito_escreve_csv_e_apaga_o_clipe(self, tmp_path):
        clipe_no_disco(tmp_path, "a")
        clipe = clipes.listar_clipes(tmp_path)[0]
        clipes.registrar_veredito(tmp_path, clipe, "errou", "duas juntas")
        assert not (tmp_path / "a.mp4").exists() and not (tmp_path / "a.json").exists()
        with (tmp_path / clipes.ARQUIVO_VEREDITOS).open(encoding="utf-8") as f:
            linhas = list(csv.DictReader(f))
        assert len(linhas) == 1
        assert (linhas[0]["id_clipe"], linhas[0]["veredito"], linhas[0]["nota"]) == (
            "a", "errou", "duas juntas"
        )
        assert linhas[0]["gatilho"] == "contagem"
        assert clipes.listar_clipes(tmp_path) == []

    def test_veredito_invalido(self, tmp_path):
        with pytest.raises(ValueError):
            clipes.registrar_veredito(tmp_path, {}, "talvez")

    def test_purga_apaga_so_os_velhos(self, tmp_path):
        clipe_no_disco(tmp_path, "velho")
        clipe_no_disco(tmp_path, "novo")
        antigo = time.time() - 49 * 3600
        for nome in ("velho.mp4", "velho.json"):
            os.utime(tmp_path / nome, (antigo, antigo))
        assert clipes.purgar_clipes(tmp_path, max_idade_h=48) == 2
        assert [c["id"] for c in clipes.listar_clipes(tmp_path)] == ["novo"]
        assert clipes.purgar_clipes(tmp_path / "nada") == 0
