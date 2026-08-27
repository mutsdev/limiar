"""Gravar o que a visão enxergou, e recontar em cima disso.

A trilha só vale se recontá-la der exatamente o mesmo resultado que contar ao
vivo. Se divergir, todo número medido por replay — e é assim que a calibração
passa a ser feita — estaria descrevendo um sistema que não existe.
"""

from datetime import datetime, timedelta

import pytest

from fluxo.avaliacao import trilhas
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL, Direcao
from fluxo.dominio.rastro import Rastro

INICIO = datetime(2026, 8, 27, 9, 0, 0, tzinfo=FUSO_LOCAL)
FPS = 25


def nova_linha(**kwargs):
    padrao = dict(
        camera_id="entrada_a", a=(450.0, 30.0), b=(450.0, 240.0), lado_dentro=-1
    )
    padrao.update(kwargs)
    return LinhaDeContagem(**padrao)


def rastro_em(x, y=135.0, track=1, conf=0.9):
    return Rastro(id_local=track, caixa=(x - 20, y - 100, x + 20, y), confianca=conf)


TRAVESSIA = [300, 340, 380, 420, 480, 520, 560, 600]


def gravar_travessia(caminho, xs=TRAVESSIA, **cabecalho):
    with trilhas.Gravador(caminho, camera="entrada_a", **cabecalho) as g:
        for i, x in enumerate(xs):
            g.gravar(i, INICIO + timedelta(seconds=i / FPS), [rastro_em(x)])
    return caminho


class TestIdaEVolta:
    def test_recontar_a_trilha_da_o_mesmo_que_contar_ao_vivo(self, tmp_path):
        """A propriedade que sustenta o replay inteiro."""
        ao_vivo = nova_linha()
        for i, x in enumerate(TRAVESSIA):
            ao_vivo.processar(i, INICIO + timedelta(seconds=i / FPS), [rastro_em(x)])

        trilha = trilhas.carregar(gravar_travessia(tmp_path / "t.jsonl"))
        replay = nova_linha()
        eventos = trilhas.contar(trilha, replay)

        assert len(eventos) == 1
        assert eventos[0].direcao is Direcao.ENTRADA
        assert (replay.entradas, replay.saidas) == (ao_vivo.entradas, ao_vivo.saidas)

    def test_o_id_do_evento_tambem_e_o_mesmo(self, tmp_path):
        """O id é determinístico, e é o que impede contagem inflada no reenvio.

        Se o replay gerasse ids diferentes, reprocessar uma trilha e enviar o
        resultado duplicaria tudo no banco em vez de ser reconhecido.
        """
        ao_vivo = nova_linha()
        eventos_vivo = []
        for i, x in enumerate(TRAVESSIA):
            eventos_vivo += ao_vivo.processar(
                i, INICIO + timedelta(seconds=i / FPS), [rastro_em(x)]
            )

        trilha = trilhas.carregar(gravar_travessia(tmp_path / "t.jsonl"))
        eventos_replay = trilhas.contar(trilha, nova_linha())

        assert [e.id_evento for e in eventos_replay] == [e.id_evento for e in eventos_vivo]

    def test_preserva_quadros_vazios(self, tmp_path):
        """Sem eles o replay não sabe quanto tempo passou, e esquece cedo demais."""
        caminho = tmp_path / "t.jsonl"
        with trilhas.Gravador(caminho, camera="entrada_a") as g:
            g.gravar(0, INICIO, [rastro_em(300)])
            g.gravar(1, INICIO + timedelta(seconds=1 / FPS), [])
            g.gravar(2, INICIO + timedelta(seconds=2 / FPS), [])

        trilha = trilhas.carregar(caminho)
        assert trilha.total_quadros == 3
        assert [len(r) for _, _, r in trilha.quadros] == [1, 0, 0]

    def test_cabecalho_guarda_a_procedencia(self, tmp_path):
        caminho = gravar_travessia(
            tmp_path / "t.jsonl", modelo="yolo11n.pt", versao="abc1234"
        )
        trilha = trilhas.carregar(caminho)
        assert trilha.cabecalho["modelo"] == "yolo11n.pt"
        assert trilha.cabecalho["versao"] == "abc1234"
        assert trilha.cabecalho["formato"] == trilhas.FORMATO

    def test_conta_tracks_e_quadros(self, tmp_path):
        caminho = tmp_path / "t.jsonl"
        with trilhas.Gravador(caminho, camera="x") as g:
            g.gravar(0, INICIO, [rastro_em(100, track=1), rastro_em(200, track=2)])
            g.gravar(1, INICIO, [rastro_em(110, track=1)])
        trilha = trilhas.carregar(caminho)
        assert trilha.total_quadros == 2
        assert trilha.pessoas == 2


class TestArquivoRuim:
    def test_arquivo_inexistente_diz_como_gravar(self, tmp_path):
        with pytest.raises(trilhas.TrilhaInvalida, match="gravar-trilhas"):
            trilhas.carregar(tmp_path / "nao_existe.jsonl")

    def test_outro_jsonl_qualquer_nao_passa_por_trilha(self, tmp_path):
        """A fila local também é JSONL. Confundir as duas daria erro longe daqui."""
        caminho = tmp_path / "fila.jsonl"
        caminho.write_text('{"id_evento": "abc", "direcao": "entrada"}\n', encoding="utf-8")
        with pytest.raises(trilhas.TrilhaInvalida, match="não é uma trilha"):
            trilhas.carregar(caminho)

    def test_linha_corrompida_e_erro_localizado(self, tmp_path):
        caminho = tmp_path / "t.jsonl"
        caminho.write_text(
            f'{{"formato": "{trilhas.FORMATO}"}}\nnão é json\n', encoding="utf-8"
        )
        with pytest.raises(trilhas.TrilhaInvalida, match=":2"):
            trilhas.carregar(caminho)


class TestCruzamentosPorPessoa:
    """A métrica que funciona sem contagem manual: acima de 1,00 é contagem dupla."""

    def test_sem_eventos_e_zero(self):
        assert trilhas.cruzamentos_por_pessoa([]) == 0.0

    def test_uma_pessoa_um_cruzamento(self, tmp_path):
        trilha = trilhas.carregar(gravar_travessia(tmp_path / "t.jsonl"))
        eventos = trilhas.contar(trilha, nova_linha())
        assert trilhas.cruzamentos_por_pessoa(eventos) == 1.0

    def test_a_mesma_pessoa_contada_duas_vezes_passa_de_um(self, tmp_path):
        """Ida e volta com folga de sobra para o cooldown: dois eventos, um track."""
        ida_e_volta = TRAVESSIA + [600] * 60 + list(reversed(TRAVESSIA))
        trilha = trilhas.carregar(gravar_travessia(tmp_path / "t.jsonl", ida_e_volta))
        eventos = trilhas.contar(trilha, nova_linha(quadros_ate_esquecer=500))
        assert len(eventos) == 2
        assert trilhas.cruzamentos_por_pessoa(eventos) == 2.0
