"""MedidorDeTaxa — o intervalo entre quadros lido como quadros por segundo.

O relógio é injetado: nada aqui dorme, e cada intervalo vale exatamente o que
o teste mandou valer.
"""

from __future__ import annotations

import pytest

from fluxo.visao.taxa import MedidorDeTaxa, formatar


class RelogioFalso:
    """Um monotonic de mentira, em segundos, que só anda quando mandam."""

    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


def medidor_com(intervalos: list[float], janela: int = 15) -> MedidorDeTaxa:
    """Um medidor que já viu quadros separados por exatamente estes intervalos."""
    relogio = RelogioFalso()
    m = MedidorDeTaxa(janela=janela, agora=relogio)
    m.marcar()
    for intervalo in intervalos:
        relogio.avancar(intervalo)
        m.marcar()
    return m


def test_sem_quadro_o_texto_e_vazio():
    m = MedidorDeTaxa(agora=RelogioFalso())
    assert m.texto == ""
    assert m.quadros_por_s is None


def test_primeiro_quadro_nao_define_intervalo():
    # Um quadro sozinho não tem antecessor: ainda não há taxa alguma a exibir.
    m = medidor_com([])
    assert m.quadros_por_s is None
    assert m.texto == ""


def test_intervalo_constante_vira_a_taxa_esperada():
    m = medidor_com([0.08] * 5)
    assert m.quadros_por_s == pytest.approx(12.5)
    assert m.texto == "12 q/s"


def test_marcar_devolve_o_intervalo():
    relogio = RelogioFalso()
    m = MedidorDeTaxa(agora=relogio)
    assert m.marcar() is None
    relogio.avancar(0.25)
    assert m.marcar() == 0.25


def test_mediana_ignora_o_solavanco():
    # Quatorze quadros a 100 ms e uma pausa de 3 s: a taxa continua em 10 q/s,
    # que é o comportamento normal, em vez de despencar por um tropeço.
    m = medidor_com([0.1] * 14 + [3.0])
    assert m.quadros_por_s == pytest.approx(10.0)


def test_a_janela_esquece_o_que_saiu():
    m = medidor_com([5.0, 0.1, 0.1, 0.1], janela=3)
    assert m.quadros_por_s == pytest.approx(10.0)


def test_quadros_no_mesmo_tique_do_relogio_nao_dividem_por_zero():
    # Resolução do monotonic no Windows é ~15 ms: vídeo pequeno sem espera
    # fecha mais de um quadro dentro do mesmo tique.
    m = medidor_com([0.0, 0.0, 0.0])
    assert m.quadros_por_s is None
    assert m.texto == ""


def test_formatar_troca_de_casa_decimal_no_limite():
    assert formatar(0.0) == "0.0 q/s"
    assert formatar(9.94) == "9.9 q/s"
    assert formatar(10.0) == "10 q/s"
    assert formatar(38.6) == "39 q/s"


def test_texto_e_ascii_puro():
    # cv2.putText não desenha acento: o placar sairia com caixas no lugar.
    assert medidor_com([0.1]).texto.isascii()
