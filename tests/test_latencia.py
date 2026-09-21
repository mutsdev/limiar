"""MedidorDeLatencia — a mediana e o texto do placar.

O relógio é injetado: nada aqui dorme, e cada amostra vale exatamente o que o
teste mandou valer.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fluxo.dominio.evento import FUSO_LOCAL
from fluxo.visao.latencia import MedidorDeLatencia, formatar

INSTANTE = datetime(2026, 9, 4, 20, 0, 0, tzinfo=FUSO_LOCAL)


class RelogioFalso:
    """Devolve INSTANTE + o deslocamento que o teste pedir."""

    def __init__(self) -> None:
        self.agora = INSTANTE

    def __call__(self) -> datetime:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += timedelta(seconds=segundos)


def medidor_com(atrasos: list[float], janela: int = 15) -> MedidorDeLatencia:
    """Um medidor que já observou quadros com exatamente estes atrasos."""
    relogio = RelogioFalso()
    m = MedidorDeLatencia(janela=janela, agora=relogio)
    for atraso in atrasos:
        # O quadro chegou `atraso` segundos atrás, na régua do relógio falso.
        m.observar(relogio.agora - timedelta(seconds=atraso))
    return m


def test_sem_amostra_o_texto_e_vazio():
    m = MedidorDeLatencia(agora=RelogioFalso())
    assert m.texto == ""
    assert m.mediana_s is None


def test_observar_devolve_o_atraso_cru():
    relogio = RelogioFalso()
    m = MedidorDeLatencia(agora=relogio)
    assert m.observar(relogio.agora - timedelta(milliseconds=150)) == 0.15


def test_mediana_ignora_o_solavanco():
    # Catorze quadros a 100 ms e um a 3 s: a mediana continua em 100 ms, que é
    # o comportamento normal, em vez de acusar degradação por um tropeço.
    m = medidor_com([0.1] * 14 + [3.0])
    assert m.mediana_s == 0.1
    assert m.texto == "latencia 100 ms"


def test_a_janela_esquece_o_que_saiu():
    # O 5 s sai da janela de três: sobram os 100 ms, e a mediana os acompanha.
    m = medidor_com([5.0, 0.1, 0.1, 0.1], janela=3)
    assert m.mediana_s == 0.1


def test_quadro_do_futuro_vira_zero():
    # Fonte de arquivo datada pelo FPS pode produzir instante à frente do
    # relógio. Zero é ruim, mas negativo seria mentira.
    relogio = RelogioFalso()
    m = MedidorDeLatencia(agora=relogio)
    assert m.observar(relogio.agora + timedelta(seconds=30)) == 0.0
    assert m.mediana_s == 0.0


def test_formatar_troca_para_segundos_no_limite():
    assert formatar(0.0) == "0 ms"
    assert formatar(0.1435) == "144 ms"
    assert formatar(9.99) == "9990 ms"
    assert formatar(10.0) == "10.0 s"
    assert formatar(75.5) == "75.5 s"


def test_texto_e_ascii_puro():
    # cv2.putText não desenha acento: o placar sairia com caixas no lugar.
    assert medidor_com([0.12]).texto.isascii()
