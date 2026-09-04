"""Assinatura de aparência: o vetor que representa como alguém está vestido hoje.

Só listas de float e aritmética de escola. É de propósito: a camada que decide
"é a mesma pessoa" precisa ser testável sem instalar 2,5 GB de visão.
"""

from __future__ import annotations

from collections.abc import Iterable
from math import sqrt

Assinatura = list[float]

# Norma abaixo disso é vetor nulo — não há aparência para comparar.
EPS = 1e-12


def normalizar(v: Iterable[float]) -> Assinatura:
    """Escala para norma 1. Vetor nulo volta nulo, em vez de dividir por zero."""
    valores = [float(x) for x in v]
    norma = sqrt(sum(x * x for x in valores))
    if norma < EPS:
        return valores
    return [x / norma for x in valores]


def similaridade(a: Assinatura, b: Assinatura) -> float:
    """Cosseno entre dois vetores, em [-1, 1]. Vetor nulo dá 0.

    Cosseno e não distância euclidiana porque a magnitude do vetor varia com
    o tamanho do recorte e a iluminação — coisas que não são a pessoa.
    """
    if len(a) != len(b):
        raise ValueError(f"Dimensões diferentes: {len(a)} e {len(b)}")
    na = sqrt(sum(x * x for x in a))
    nb = sqrt(sum(x * x for x in b))
    if na < EPS or nb < EPS:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def media(vetores: Iterable[Assinatura]) -> Assinatura:
    """Média elemento a elemento, normalizada.

    Um recorte só é um instante ruim ou bom por sorte; a média de vários
    recortes da mesma passagem é o que faz a assinatura representar a pessoa
    e não o quadro.
    """
    lista = [list(v) for v in vetores]
    if not lista:
        return []
    dim = len(lista[0])
    if any(len(v) != dim for v in lista):
        raise ValueError("Vetores de dimensões diferentes na média")
    soma = [0.0] * dim
    for v in lista:
        for i, x in enumerate(v):
            soma[i] += x
    n = len(lista)
    return normalizar(x / n for x in soma)
