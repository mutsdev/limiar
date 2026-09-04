"""trilha/2: as assinaturas viajam na trilha, e a trilha/1 antiga continua lendo."""

from datetime import datetime, timedelta

from fluxo.avaliacao import trilhas
from fluxo.dominio.evento import FUSO_LOCAL
from fluxo.dominio.rastro import Rastro

INICIO = datetime(2026, 9, 4, 9, 0, 0, tzinfo=FUSO_LOCAL)


def rastro_em(x, track=1):
    return Rastro(id_local=track, caixa=(x - 20, 35.0, x + 20, 135.0), confianca=0.9)


class TestAssinaturasNaTrilha:
    def test_ida_e_volta(self, tmp_path):
        caminho = tmp_path / "t.jsonl"
        with trilhas.Gravador(caminho, camera="entrada_a", modelo_reid="resnet18") as g:
            g.gravar(0, INICIO, [rastro_em(300)])
            g.gravar(1, INICIO + timedelta(seconds=1), [rastro_em(340)])
            g.gravar_assinatura(1, 1, [0.6, 0.8, 0.0])
            g.gravar(2, INICIO + timedelta(seconds=2), [rastro_em(380)])

        trilha = trilhas.carregar(caminho)
        assert trilha.cabecalho["formato"] == "trilha/2"
        assert trilha.cabecalho["modelo_reid"] == "resnet18"
        # As linhas de assinatura não viram quadro.
        assert trilha.total_quadros == 3
        assert trilha.assinaturas == {1: [(1, [0.6, 0.8, 0.0])]}

    def test_assinatura_de_devolve_a_mais_recente_ate_o_quadro(self, tmp_path):
        caminho = tmp_path / "t.jsonl"
        with trilhas.Gravador(caminho, camera="x") as g:
            g.gravar(0, INICIO, [])
            g.gravar_assinatura(0, 7, [1.0, 0.0])
            g.gravar(5, INICIO, [])
            g.gravar_assinatura(5, 7, [0.0, 1.0])

        trilha = trilhas.carregar(caminho)
        assert trilha.assinatura_de(7, 0) == [1.0, 0.0]
        assert trilha.assinatura_de(7, 4) == [1.0, 0.0]
        assert trilha.assinatura_de(7, 5) == [0.0, 1.0]
        assert trilha.assinatura_de(7, 99) == [0.0, 1.0]
        assert trilha.assinatura_de(8, 99) is None

    def test_arredonda_para_o_arquivo_nao_explodir(self, tmp_path):
        caminho = tmp_path / "t.jsonl"
        with trilhas.Gravador(caminho, camera="x") as g:
            g.gravar_assinatura(0, 1, [0.123456789])
        assert '0.12346' in caminho.read_text(encoding="utf-8")


class TestLegado:
    def test_trilha_v1_continua_carregando(self, tmp_path):
        caminho = tmp_path / "v1.jsonl"
        caminho.write_text(
            '{"formato": "trilha/1", "camera": "entrada_a"}\n'
            '{"q": 0, "t": "2026-09-04T09:00:00-03:00", '
            '"r": [[1, 280.0, 35.0, 320.0, 135.0, 0.9]]}\n',
            encoding="utf-8",
        )
        trilha = trilhas.carregar(caminho)
        assert trilha.total_quadros == 1
        assert trilha.assinaturas == {}
        assert trilha.assinatura_de(1, 0) is None

    def test_formato_desconhecido_ainda_e_recusado(self, tmp_path):
        caminho = tmp_path / "v9.jsonl"
        caminho.write_text('{"formato": "trilha/9"}\n', encoding="utf-8")
        try:
            trilhas.carregar(caminho)
        except trilhas.TrilhaInvalida as erro:
            assert "trilha/2" in str(erro)
        else:
            raise AssertionError("trilha/9 deveria ser recusada")
