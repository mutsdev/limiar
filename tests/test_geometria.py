"""Prova do núcleo geométrico.

Nada aqui precisa de vídeo, modelo ou GPU — só coordenadas. É por isso que a
parte que decide se alguém passou pode ser verificada exaustivamente.
"""

import pytest

from fluxo.contagem import geometria

# Linha vertical, como uma porta vista de lado.
A = (450.0, 30.0)
B = (450.0, 240.0)


class TestLado:
    @pytest.mark.parametrize(
        "ponto,esperado",
        [
            ((200.0, 100.0), 1),    # bem à esquerda
            ((449.0, 100.0), 1),    # um pixel à esquerda
            ((450.0, 100.0), 0),    # exatamente sobre a reta
            ((451.0, 100.0), -1),   # um pixel à direita
            ((900.0, 100.0), -1),   # bem à direita
            ((450.0, 1000.0), 0),   # sobre o prolongamento da reta
        ],
    )
    def test_sinal(self, ponto, esperado):
        assert geometria.lado(A, B, ponto) == esperado

    def test_inverter_a_linha_inverte_o_sinal(self):
        p = (600.0, 100.0)
        assert geometria.lado(A, B, p) == -geometria.lado(B, A, p)


class TestDistancia:
    @pytest.mark.parametrize(
        "ponto,esperado",
        [
            ((450.0, 100.0), 0.0),
            ((470.0, 100.0), 20.0),
            ((430.0, 100.0), 20.0),
            ((450.0, 5000.0), 0.0),   # sobre a reta, mesmo fora do segmento
        ],
    )
    def test_perpendicular(self, ponto, esperado):
        assert geometria.distancia_ponto_reta(ponto, A, B) == pytest.approx(esperado)

    def test_linha_degenerada_vira_distancia_ao_ponto(self):
        # Linha de comprimento zero: não há reta, só um ponto.
        d = geometria.distancia_ponto_reta((3.0, 4.0), (0.0, 0.0), (0.0, 0.0))
        assert d == pytest.approx(5.0)


class TestCruzamento:
    @pytest.mark.parametrize(
        "p1,p2,esperado,motivo",
        [
            ((300.0, 100.0), (600.0, 100.0), True,  "perpendicular, da esquerda"),
            ((600.0, 100.0), (300.0, 100.0), True,  "perpendicular, da direita"),
            ((300.0, 50.0),  (600.0, 200.0), True,  "diagonal dentro do segmento"),
            ((300.0, 100.0), (440.0, 100.0), False, "para antes da linha"),
            ((460.0, 100.0), (600.0, 100.0), False, "começa depois da linha"),
            ((300.0, 100.0), (300.0, 200.0), False, "anda paralelo, mesmo lado"),
            # O caso que separa segmento de reta infinita:
            ((300.0, 500.0), (600.0, 500.0), False, "cruza a reta ABAIXO do segmento"),
            ((300.0, 10.0),  (600.0, 10.0),  False, "cruza a reta ACIMA do segmento"),
            ((300.0, 30.0),  (600.0, 30.0),  True,  "passa exatamente pelo ponto A"),
            ((300.0, 240.0), (600.0, 240.0), True,  "passa exatamente pelo ponto B"),
            ((300.0, 239.9), (600.0, 239.9), True,  "raspa dentro do segmento"),
            ((300.0, 240.1), (600.0, 240.1), False, "raspa fora do segmento"),
        ],
    )
    def test_segmento(self, p1, p2, esperado, motivo):
        assert geometria.segmentos_se_cruzam(p1, p2, A, B) is esperado, motivo

    def test_e_simetrico_no_sentido_do_movimento(self):
        p1, p2 = (300.0, 100.0), (600.0, 100.0)
        assert geometria.segmentos_se_cruzam(p1, p2, A, B) is True
        assert geometria.segmentos_se_cruzam(p2, p1, A, B) is True

    def test_deslocamento_nulo_sobre_a_linha_conta_como_toque(self):
        p = (450.0, 100.0)
        assert geometria.segmentos_se_cruzam(p, p, A, B) is True

    def test_deslocamento_nulo_longe_da_linha_nao_toca(self):
        p = (100.0, 100.0)
        assert geometria.segmentos_se_cruzam(p, p, A, B) is False

    def test_linha_diagonal(self):
        a, b = (0.0, 0.0), (100.0, 100.0)
        assert geometria.segmentos_se_cruzam((0.0, 100.0), (100.0, 0.0), a, b) is True
        assert geometria.segmentos_se_cruzam((200.0, 300.0), (300.0, 200.0), a, b) is False


class TestPontoBase:
    def test_e_o_centro_da_base(self):
        assert geometria.ponto_base((100.0, 50.0, 180.0, 300.0)) == (140.0, 300.0)

    def test_ignora_a_altura_da_caixa(self):
        """A caixa encolher por cima não move o ponto do pé.

        É exatamente por isso que o ponto de referência é a base, e não o
        centro: oclusão parcial no topo é comum e não deveria mover a pessoa.
        """
        alta = geometria.ponto_base((100.0, 10.0, 180.0, 300.0))
        baixa = geometria.ponto_base((100.0, 200.0, 180.0, 300.0))
        assert alta == baixa
