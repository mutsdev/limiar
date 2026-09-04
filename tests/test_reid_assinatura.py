"""Vetor de aparência: normalização, cosseno e média — em Python puro."""

from math import isclose, sqrt

import pytest

from fluxo.reid import assinatura as asg


class TestNormalizar:
    def test_norma_vira_um(self):
        v = asg.normalizar([3.0, 4.0])
        assert isclose(sqrt(sum(x * x for x in v)), 1.0)

    def test_vetor_nulo_nao_divide_por_zero(self):
        assert asg.normalizar([0.0, 0.0]) == [0.0, 0.0]

    def test_aceita_iteravel_qualquer(self):
        assert asg.normalizar(x for x in (0, 2)) == [0.0, 1.0]


class TestSimilaridade:
    def test_iguais_dao_um(self):
        assert isclose(asg.similaridade([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 1.0)

    def test_ortogonais_dao_zero(self):
        assert isclose(asg.similaridade([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_opostos_dao_menos_um(self):
        assert isclose(asg.similaridade([1.0, 0.0], [-1.0, 0.0]), -1.0)

    def test_magnitude_nao_importa(self):
        """Recorte maior ou mais claro não é outra pessoa."""
        assert isclose(asg.similaridade([1.0, 1.0], [10.0, 10.0]), 1.0)

    def test_vetor_nulo_da_zero(self):
        assert asg.similaridade([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_dimensoes_diferentes_e_erro(self):
        with pytest.raises(ValueError):
            asg.similaridade([1.0], [1.0, 2.0])


class TestMedia:
    def test_media_de_um_e_ele_normalizado(self):
        assert asg.media([[0.0, 2.0]]) == [0.0, 1.0]

    def test_media_fica_entre_os_dois(self):
        m = asg.media([[1.0, 0.0], [0.0, 1.0]])
        assert isclose(m[0], m[1])
        assert isclose(sqrt(m[0] ** 2 + m[1] ** 2), 1.0)

    def test_vazia_da_vazia(self):
        assert asg.media([]) == []

    def test_dimensoes_diferentes_e_erro(self):
        with pytest.raises(ValueError):
            asg.media([[1.0], [1.0, 2.0]])
