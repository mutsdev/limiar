"""O húngaro contra a força bruta, e o "não sei" como parte da otimização."""

import random
from itertools import permutations

import pytest

from fluxo.reid.atribuicao import atribuir, hungaro


def custo_total(custos, pares):
    return sum(custos[i][j] for i, j in pares)


def melhor_por_forca_bruta(custos):
    n, m = len(custos), len(custos[0])
    # n <= m: escolhe m-permutações de tamanho n; n > m: o simétrico.
    if n <= m:
        return min(
            sum(custos[i][perm[i]] for i in range(n))
            for perm in permutations(range(m), n)
        )
    return min(
        sum(custos[perm[j]][j] for j in range(m))
        for perm in permutations(range(n), m)
    )


class TestHungaro:
    def test_vazio(self):
        assert hungaro([]) == []
        assert hungaro([[]]) == []

    def test_um_por_um(self):
        assert hungaro([[3.0]]) == [(0, 0)]

    def test_diagonal_obvia(self):
        custos = [[1.0, 9.0], [9.0, 1.0]]
        assert hungaro(custos) == [(0, 0), (1, 1)]

    def test_o_caso_que_o_guloso_erra(self):
        """A linha 0 prefere a coluna 0, mas dá-la à linha 1 sai mais barato."""
        custos = [[1.0, 2.0], [1.0, 10.0]]
        pares = hungaro(custos)
        assert pares == [(0, 1), (1, 0)]
        assert custo_total(custos, pares) == 3.0

    @pytest.mark.parametrize("semente", range(30))
    def test_bate_com_forca_bruta_em_quadradas(self, semente):
        rng = random.Random(semente)
        n = rng.randint(1, 6)
        custos = [[rng.random() for _ in range(n)] for _ in range(n)]
        pares = hungaro(custos)
        assert len(pares) == n
        assert len({i for i, _ in pares}) == n
        assert len({j for _, j in pares}) == n
        assert custo_total(custos, pares) == pytest.approx(melhor_por_forca_bruta(custos))

    @pytest.mark.parametrize("semente", range(30))
    def test_bate_com_forca_bruta_em_retangulares(self, semente):
        rng = random.Random(semente)
        n, m = rng.randint(1, 5), rng.randint(1, 5)
        custos = [[rng.random() for _ in range(m)] for _ in range(n)]
        pares = hungaro(custos)
        assert len(pares) == min(n, m)
        assert custo_total(custos, pares) == pytest.approx(melhor_por_forca_bruta(custos))

    def test_matriz_irregular_e_erro(self):
        with pytest.raises(ValueError):
            hungaro([[1.0, 2.0], [1.0]])


A = [1.0, 0.0, 0.0]
B = [0.0, 1.0, 0.0]
C = [0.0, 0.0, 1.0]


def perto_de(v, ruido=0.1):
    return [x + ruido if i == 0 else x for i, x in enumerate(v)]


class TestAtribuir:
    def test_sem_saidas(self):
        assert atribuir([], [A], 0.7) == ([], [])

    def test_sem_candidatos_tudo_fica_sem_par(self):
        pares, sem = atribuir([A, B], [], 0.7)
        assert pares == []
        assert sem == [0, 1]

    def test_pareia_o_parecido(self):
        pares, sem = atribuir([perto_de(B)], [A, B, C], 0.7)
        assert sem == []
        assert len(pares) == 1
        i, j, sim = pares[0]
        assert (i, j) == (0, 1)
        assert sim > 0.9

    def test_abaixo_do_limiar_nao_forca(self):
        """Regra §12(b): o candidato existe, mas não é bom — fica sem par."""
        meio = [0.7, 0.7, 0.0]  # cos com A e com B ~ 0,71
        pares, sem = atribuir([meio], [A, B], limiar=0.9)
        assert pares == []
        assert sem == [0]

    def test_no_limiar_exato_passa(self):
        meio = [1.0, 1.0, 0.0]  # cos com A = 0,7071...
        pares, _ = atribuir([meio], [A], limiar=0.7)
        assert len(pares) == 1

    def test_duas_saidas_um_candidato(self):
        """Só um pode levar; o outro fica honesto, sem par."""
        pares, sem = atribuir([A, perto_de(A, 0.2)], [A], 0.7)
        assert len(pares) == 1
        assert len(sem) == 1
        assert pares[0][1] == 0

    def test_lote_resolve_o_que_o_guloso_erraria(self):
        """Saída 0 é 'meio A meio B'; saída 1 é A puro.

        Guloso daria A para a saída 0 (primeira a chegar) e deixaria a saída
        1 — que É o A — sem par. O lote dá A para 1 e B para 0.
        """
        meio = [0.8, 0.6, 0.0]
        pares, sem = atribuir([meio, A], [A, B], 0.5)
        assert sem == []
        atribuicao = {i: j for i, j, _ in pares}
        assert atribuicao == {0: 1, 1: 0}
