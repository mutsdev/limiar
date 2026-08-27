"""Geometria do cruzamento — funções puras sobre coordenadas.

Este é o componente mais crítico do sistema, e de propósito ele não importa
numpy, opencv nem nada pesado: assim a parte que decide se alguém passou pode
ser provada em milissegundos, sem GPU, sem modelo e sem vídeo.
"""

from __future__ import annotations

from math import hypot

from fluxo.dominio.rastro import Caixa, Ponto

# Tolerância para comparar float com zero. Coordenadas são em pixels, então
# qualquer coisa abaixo disso é ruído de arredondamento, não geometria.
EPS = 1e-9


def produto_vetorial(a: Ponto, b: Ponto, p: Ponto) -> float:
    """Componente z do produto vetorial (B-A) x (P-A).

    O sinal diz de que lado da reta AB o ponto P está.
    """
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def lado(a: Ponto, b: Ponto, p: Ponto) -> int:
    """+1, -1 ou 0 (sobre a reta)."""
    v = produto_vetorial(a, b, p)
    if v > EPS:
        return 1
    if v < -EPS:
        return -1
    return 0


def distancia_ponto_reta(p: Ponto, a: Ponto, b: Ponto) -> float:
    """Distância perpendicular de P à reta AB, em pixels.

    Usada pela zona morta: enquanto a pessoa está perto demais da linha, a
    decisão é adiada em vez de arriscada.
    """
    comprimento = hypot(b[0] - a[0], b[1] - a[1])
    if comprimento < EPS:
        return hypot(p[0] - a[0], p[1] - a[1])
    return abs(produto_vetorial(a, b, p)) / comprimento


def _no_retangulo(p: Ponto, q: Ponto, r: Ponto) -> bool:
    """Q está na caixa envolvente do segmento PR (usado no caso colinear)."""
    return (
        min(p[0], r[0]) - EPS <= q[0] <= max(p[0], r[0]) + EPS
        and min(p[1], r[1]) - EPS <= q[1] <= max(p[1], r[1]) + EPS
    )


def segmentos_se_cruzam(p1: Ponto, p2: Ponto, a: Ponto, b: Ponto) -> bool:
    """O deslocamento P1->P2 cruza o SEGMENTO AB?

    A distinção entre segmento e reta infinita é essencial: sem ela, alguém
    passando muito à esquerda da porta — fora da linha desenhada, mas ainda
    do outro lado da reta que a contém — seria contado.
    """
    o1 = lado(p1, p2, a)
    o2 = lado(p1, p2, b)
    o3 = lado(a, b, p1)
    o4 = lado(a, b, p2)

    if o1 != o2 and o3 != o4:
        return True

    # Casos colineares: o ponto toca o segmento sem atravessá-lo.
    if o1 == 0 and _no_retangulo(p1, a, p2):
        return True
    if o2 == 0 and _no_retangulo(p1, b, p2):
        return True
    if o3 == 0 and _no_retangulo(a, p1, b):
        return True
    if o4 == 0 and _no_retangulo(a, p2, b):
        return True

    return False


def ponto_base(caixa: Caixa) -> Ponto:
    """Centro da base da caixa. Ver Rastro.ponto_base para o porquê."""
    x1, _, x2, y2 = caixa
    return ((x1 + x2) / 2.0, y2)


def distancia(p: Ponto, q: Ponto) -> float:
    """Distância euclidiana entre dois pontos, em pixels.

    Usada pela costura de rastros: o quanto a pessoa pode ter andado enquanto
    esteve sem detecção.
    """
    return hypot(q[0] - p[0], q[1] - p[1])
