"""FonteViva — reconexão, watchdog e a marca de lacuna.

Nada aqui abre vídeo: a fábrica injetada entrega fontes falsas, e o relógio e
a espera injetados fazem o tempo andar sem dormir de verdade.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime

from fluxo.dominio.evento import FUSO_LOCAL
from fluxo.visao.fonte_viva import ConfigFonteViva, FonteViva

INSTANTE = datetime(2026, 8, 31, 8, 0, 0, tzinfo=FUSO_LOCAL)


@dataclass(frozen=True, slots=True)
class QuadroFalso:
    indice: int
    instante: datetime
    imagem: object
    apos_lacuna: bool = False


class FonteFalsa:
    """Entrega N quadros e morre — o read() que falhou.

    Com `depois_congela=True` ela fica presa em vez de morrer: é a última
    fonte de cada roteiro, para o leitor não reconectar mais uma vez no fim
    do teste e tornar `reconexoes` dependente de corrida.
    """

    def __init__(self, n: int, depois_congela: bool = False):
        self.n = n
        self.depois_congela = depois_congela
        self.fechada = False
        self._solta = threading.Event()
        self.fps, self.largura, self.altura = 10.0, 768, 432

    def __iter__(self):
        for i in range(self.n):
            if self.fechada:
                return
            yield QuadroFalso(i, INSTANTE, object())
        if self.depois_congela:
            self._solta.wait(timeout=5.0)

    def fechar(self):
        self.fechada = True
        self._solta.set()


class FonteCongelada:
    """Conecta mas nunca entrega quadro — o stream travado."""

    def __init__(self):
        self._solta = threading.Event()
        self.fechada = False
        self.fps, self.largura, self.altura = 10.0, 768, 432

    def __iter__(self):
        # O timeout é rede de segurança do teste, não parte do contrato.
        self._solta.wait(timeout=5.0)
        return
        yield  # noqa — torna a função um gerador

    def fechar(self):
        self.fechada = True
        self._solta.set()


class Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def avancar(self, s: float) -> None:
        self.t += s


def fabrica_roteirizada(roteiro: list, esperas: list | None = None, relogio: Relogio | None = None):
    """Cada chamada consome um item: exceção é falha de abertura, objeto é a
    fonte. Esgotado o roteiro, entrega fontes congeladas — o leitor estaciona
    em vez de girar em laço quente."""
    fila = list(roteiro)

    def fabrica():
        if fila:
            item = fila.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return FonteCongelada()

    return fabrica


def montar(roteiro, config, relogio=None, pulso=None):
    relogio = relogio or Relogio()
    esperas: list[float] = []

    def espera(s: float) -> None:
        esperas.append(s)
        relogio.avancar(s)

    fv = FonteViva(
        "http://camera-fake/stream",
        config=config,
        fabrica=fabrica_roteirizada(roteiro),
        espera=espera,
        relogio=relogio,
        pulso=pulso,
    )
    return fv, esperas


def coletar_ate(fv: FonteViva, indice_final: int) -> list:
    coletados = []
    for quadro in fv:
        coletados.append(quadro)
        if quadro.indice >= indice_final:
            break
    return coletados


class TestReconexao:
    def test_indice_continua_atraves_da_queda(self):
        cfg = ConfigFonteViva(timeout_quadro_s=2.0, lacuna_para_zerar_s=100.0)
        fv, _ = montar(
            [FonteFalsa(3), OSError("sem rota"), FonteFalsa(2, depois_congela=True)], cfg
        )
        try:
            coletados = coletar_ate(fv, 4)
        finally:
            fv.fechar()

        indices = [q.indice for q in coletados]
        assert indices == sorted(indices)
        assert indices[-1] == 4  # o último quadro global das duas fontes
        assert fv.reconexoes == 1
        # Lacuna curta não marca nada: o rastreio deve sobreviver intacto.
        assert not any(q.apos_lacuna for q in coletados)

    def test_lacuna_longa_marca_o_primeiro_quadro(self):
        cfg = ConfigFonteViva(
            timeout_quadro_s=2.0, espera_inicial_s=1.0,
            espera_maxima_s=30.0, lacuna_para_zerar_s=2.0,
        )
        # Duas falhas de abertura: as esperas somam 1+2+4 = 7 s > 2 s.
        fv, _ = montar(
            [FonteFalsa(2), OSError("fora"), OSError("fora"),
             FonteFalsa(2, depois_congela=True)],
            cfg,
        )
        try:
            coletados = coletar_ate(fv, 3)
        finally:
            fv.fechar()

        depois_da_queda = [q for q in coletados if q.indice >= 2]
        assert depois_da_queda, "nenhum quadro chegou depois da reconexão"
        # A marca pode ter migrado num descarte de fila, mas nunca se perde.
        assert depois_da_queda[0].apos_lacuna is True

    def test_recuo_exponencial_ate_o_teto(self):
        cfg = ConfigFonteViva(
            timeout_quadro_s=2.0, espera_inicial_s=1.0,
            espera_maxima_s=4.0, lacuna_para_zerar_s=100.0,
        )
        falhas = [OSError("fora") for _ in range(6)]
        fv, esperas = montar([*falhas, FonteFalsa(1, depois_congela=True)], cfg)
        try:
            coletados = coletar_ate(fv, 0)
        finally:
            fv.fechar()

        assert [q.indice for q in coletados] == [0]
        assert esperas[:6] == [1.0, 2.0, 4.0, 4.0, 4.0, 4.0]
        # Falha de abertura antes do primeiro quadro não é reconexão.
        assert fv.reconexoes == 0


class TestWatchdog:
    def test_stream_congelado_e_derrubado_e_substituido(self):
        congelada = FonteCongelada()
        cfg = ConfigFonteViva(timeout_quadro_s=0.2, lacuna_para_zerar_s=100.0)
        fv, _ = montar([congelada, FonteFalsa(1, depois_congela=True)], cfg)
        try:
            coletados = coletar_ate(fv, 0)
        finally:
            fv.fechar()

        assert congelada.fechada, "o watchdog deveria ter fechado a fonte presa"
        assert [q.indice for q in coletados] == [0]


class TestPulso:
    def test_bate_com_quadro_e_sem_quadro(self):
        batidas = []
        cfg = ConfigFonteViva(timeout_quadro_s=0.2, lacuna_para_zerar_s=100.0)
        # Uma fonte congelada primeiro: o consumidor acorda no timeout, sem
        # quadro, e ainda assim tem de bater.
        fv, _ = montar(
            [FonteCongelada(), FonteFalsa(1, depois_congela=True)], cfg,
            pulso=lambda: batidas.append(1),
        )
        try:
            coletados = coletar_ate(fv, 0)
        finally:
            fv.fechar()
        assert [q.indice for q in coletados] == [0]
        assert len(batidas) >= 2


class TestDesistir:
    def test_sem_quadro_por_muito_tempo_termina_a_iteracao(self):
        cfg = ConfigFonteViva(
            timeout_quadro_s=0.2, espera_inicial_s=1.0, espera_maxima_s=4.0,
            lacuna_para_zerar_s=100.0, desistir_apos_s=10.0,
        )
        falhas = [OSError("sem rota") for _ in range(20)]
        fv, esperas = montar(falhas, cfg)
        try:
            coletados = list(fv)  # termina sozinha, sem fechar()
        finally:
            fv.fechar()
        assert coletados == []
        assert fv.desistiu
        # 1+2+4+4 = 11 s ≥ 10: desiste na quinta falha, não na vigésima.
        assert len(esperas) == 4

    def test_sem_limite_nao_desiste(self):
        cfg = ConfigFonteViva(timeout_quadro_s=0.2, espera_maxima_s=1.0, lacuna_para_zerar_s=100.0)
        fv, _ = montar([OSError("x") for _ in range(5)] + [FonteFalsa(1, depois_congela=True)], cfg)
        try:
            coletados = coletar_ate(fv, 0)
        finally:
            fv.fechar()
        assert [q.indice for q in coletados] == [0]
        assert not fv.desistiu

    def test_quadro_recente_adia_a_desistencia(self):
        cfg = ConfigFonteViva(
            timeout_quadro_s=0.2, espera_inicial_s=1.0, espera_maxima_s=1.0,
            lacuna_para_zerar_s=100.0, desistir_apos_s=3.0,
        )
        fv, esperas = montar(
            [FonteFalsa(1), OSError("x"), OSError("x"), FonteFalsa(1, depois_congela=True)], cfg
        )
        try:
            coletados = coletar_ate(fv, 1)
        finally:
            fv.fechar()
        # A fonte caiu logo depois do quadro 0: duas esperas de 1 s somam 2 s
        # < 3 s desde o último quadro, então a terceira tentativa acontece e
        # o quadro 1 chega. (O 0 pode ter sido descartado pela fila de um.)
        assert coletados[-1].indice == 1
        assert not fv.desistiu


class TestFechar:
    def test_fechar_encerra_a_iteracao_e_a_thread(self):
        cfg = ConfigFonteViva(timeout_quadro_s=0.2)
        fv, _ = montar([FonteFalsa(1)], cfg)
        primeiro = next(iter(fv))
        assert primeiro.indice == 0
        fv.fechar()
        assert not fv._thread.is_alive()
