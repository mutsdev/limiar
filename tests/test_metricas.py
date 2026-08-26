"""Métricas de avaliação."""

import pytest

from fluxo.avaliacao import metricas


class TestErroDirecional:
    def test_contagem_perfeita(self):
        e = metricas.ErroDirecional("ENTRADA", 100, 100)
        assert e.erro_absoluto == 0
        assert e.erro_percentual == 0.0
        assert e.vies == 0

    def test_contou_demais(self):
        e = metricas.ErroDirecional("ENTRADA", 110, 100)
        assert e.erro_absoluto == 10
        assert e.erro_percentual == pytest.approx(10.0)
        assert e.vies == 10

    def test_perdeu_passagem(self):
        e = metricas.ErroDirecional("SAIDA", 85, 100)
        assert e.erro_percentual == pytest.approx(15.0)
        assert e.vies == -15

    def test_referencia_zero_com_contagem_zero_e_acerto(self):
        assert metricas.ErroDirecional("ENTRADA", 0, 0).erro_percentual == 0.0

    def test_referencia_zero_com_falso_positivo_e_infinito(self):
        """Não há denominador. Reportar 0% aqui esconderia falso positivo."""
        assert metricas.ErroDirecional("ENTRADA", 3, 0).erro_percentual == float("inf")


class TestAvaliacao:
    def test_aprova_dentro_da_meta(self):
        a = metricas.avaliar(105, 96, 100, 100)
        assert a.aprovado is True

    def test_reprova_se_uma_direcao_estoura(self):
        """Média não vale: 2% numa direção não compensa 20% na outra."""
        a = metricas.avaliar(102, 80, 100, 100)
        assert a.entrada.erro_percentual == pytest.approx(2.0)
        assert a.saida.erro_percentual == pytest.approx(20.0)
        assert a.aprovado is False

    def test_limite_exato_aprova(self):
        assert metricas.avaliar(110, 90, 100, 100).aprovado is True

    def test_relatorio_mostra_as_duas_direcoes(self):
        texto = metricas.avaliar(105, 96, 100, 100, mae_janela=0.4).relatorio()
        assert "ENTRADA" in texto and "SAIDA" in texto
        assert "APROVADO" in texto
        assert "MAE por janela" in texto

    def test_relatorio_diz_reprovado(self):
        assert "REPROVADO" in metricas.avaliar(150, 100, 100, 100).relatorio()


class TestMaePorJanela:
    def test_series_iguais_dao_zero(self):
        assert metricas.mae_por_janela({0: 5, 1: 3}, {0: 5, 1: 3}) == 0.0

    def test_erros_que_se_compensam_no_total_aparecem_aqui(self):
        """Total idêntico (8 e 8), mas dois erros de 1 em janelas diferentes.

        É a razão de existir desta métrica: o total sozinho diria 0% de erro.
        """
        auto = {0: 6, 1: 2}
        manual = {0: 5, 1: 3}
        assert sum(auto.values()) == sum(manual.values())
        assert metricas.mae_por_janela(auto, manual) == pytest.approx(1.0)

    def test_janela_presente_so_de_um_lado_conta(self):
        assert metricas.mae_por_janela({0: 4}, {0: 4, 5: 2}) == pytest.approx(1.0)

    def test_vazio_nao_divide_por_zero(self):
        assert metricas.mae_por_janela({}, {}) == 0.0
