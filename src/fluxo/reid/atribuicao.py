"""Quem saiu é quem, entre os que estão dentro — resolvido em lote.

PROJETO.txt §12(a): a atribuição é em lote, com o algoritmo húngaro, nunca
gulosa uma saída por vez. Guloso erra quando duas pessoas parecidas saem
juntas: a primeira leva o melhor par das duas e a segunda fica com o resto.

§12(b): nunca forçar casamento. A opção "não sei" existe como colunas
fantasmas na própria matriz de custo, com custo igual a `1 - limiar`. O
húngaro escolhe "não atribuído" sozinho quando nenhum candidato real passa do
limiar — não é um filtro aplicado depois, é parte da otimização.

Implementação própria O(n³): o conjunto de candidatos é quem está dentro do
prédio agora (dezenas), não o mundo. Uma dependência a mais não se justifica.
"""

from __future__ import annotations

from fluxo.reid.assinatura import Assinatura, similaridade

INFINITO = float("inf")


def hungaro(custos: list[list[float]]) -> list[tuple[int, int]]:
    """Atribuição de custo mínimo. Devolve pares (linha, coluna).

    Aceita matriz retangular: com mais linhas que colunas, algumas linhas
    ficam sem par; com mais colunas, algumas colunas. Linhas e colunas vazias
    devolvem lista vazia.
    """
    n = len(custos)
    if n == 0:
        return []
    m = len(custos[0])
    if m == 0:
        return []
    if any(len(linha) != m for linha in custos):
        raise ValueError("Matriz de custos irregular")

    # O algoritmo abaixo exige n <= m. Se não for, transpõe e destranspõe.
    transposta = n > m
    if transposta:
        custos = [[custos[i][j] for i in range(n)] for j in range(m)]
        n, m = m, n

    # Kuhn-Munkres com potenciais (versão de e-maxx), índices a partir de 1.
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)  # p[j] = linha atribuída à coluna j (0 = nenhuma)
    caminho = [0] * (m + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minimo = [INFINITO] * (m + 1)
        usado = [False] * (m + 1)
        while True:
            usado[j0] = True
            i0 = p[j0]
            delta = INFINITO
            j1 = 0
            for j in range(1, m + 1):
                if usado[j]:
                    continue
                atual = custos[i0 - 1][j - 1] - u[i0] - v[j]
                if atual < minimo[j]:
                    minimo[j] = atual
                    caminho[j] = j0
                if minimo[j] < delta:
                    delta = minimo[j]
                    j1 = j
            for j in range(m + 1):
                if usado[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minimo[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = caminho[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    pares = [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j] != 0]
    if transposta:
        pares = [(j, i) for i, j in pares]
    return sorted(pares)


def atribuir(
    saidas: list[Assinatura],
    candidatos: list[Assinatura],
    limiar: float,
) -> tuple[list[tuple[int, int, float]], list[int]]:
    """Casa cada saída com no máximo um candidato, ou com "não sei".

    Devolve (pares, nao_atribuidas): pares como (índice da saída, índice do
    candidato, similaridade); nao_atribuidas como índices de saída.

    A matriz é `n × (m + n)`: as `m` primeiras colunas são os candidatos reais
    com custo `1 - similaridade`; as `n` últimas são fantasmas com custo
    `1 - limiar`. Uma saída só vai para um candidato real se ele for melhor
    que o fantasma — ou seja, se a similaridade passar do limiar.
    """
    n = len(saidas)
    if n == 0:
        return [], []
    m = len(candidatos)
    custo_fantasma = 1.0 - limiar

    sims = [[similaridade(s, c) for c in candidatos] for s in saidas]
    custos = [
        [1.0 - sims[i][j] for j in range(m)] + [custo_fantasma] * n
        for i in range(n)
    ]

    pares: list[tuple[int, int, float]] = []
    nao_atribuidas: list[int] = []
    for i, j in hungaro(custos):
        if j < m:
            pares.append((i, j, sims[i][j]))
        else:
            nao_atribuidas.append(i)
    return pares, sorted(nao_atribuidas)
