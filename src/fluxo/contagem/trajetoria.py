"""Histórico de posições de cada pessoa rastreada."""

from __future__ import annotations

from collections import deque

from fluxo.dominio.rastro import Ponto


class Trajetoria:
    """As últimas posições de um track, com suavização.

    A caixa da detecção oscila alguns pixels entre quadros. Sem suavizar, uma
    pessoa parada em cima da linha alterna de lado várias vezes por segundo e
    o contador dispara em série.
    """

    __slots__ = ("_pontos", "_janela", "quadros", "ultimo_quadro")

    def __init__(self, janela: int = 3, capacidade: int = 30) -> None:
        self._janela = max(1, janela)
        self._pontos: deque[Ponto] = deque(maxlen=capacidade)
        self.quadros = 0
        self.ultimo_quadro = -1

    def adicionar(self, ponto: Ponto, quadro: int) -> None:
        self._pontos.append(ponto)
        self.quadros += 1
        self.ultimo_quadro = quadro

    @property
    def vazia(self) -> bool:
        return not self._pontos

    def suavizado(self) -> Ponto:
        """Média móvel das últimas posições."""
        recentes = list(self._pontos)[-self._janela :]
        n = len(recentes)
        return (
            sum(p[0] for p in recentes) / n,
            sum(p[1] for p in recentes) / n,
        )

    def bruto(self) -> Ponto:
        return self._pontos[-1]
