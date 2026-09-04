"""Pureza, fragmentação, não atribuído e permanência — em cima de registros inventados."""

from datetime import datetime, timedelta

from fluxo.dominio.evento import FUSO_LOCAL, Direcao
from fluxo.reid import metricas as m

T0 = datetime(2026, 9, 4, 9, 0, 0, tzinfo=FUSO_LOCAL)


def reg(i, direcao, minutos, pseudonimo):
    return m.Registro(f"e{i}", T0 + timedelta(minutes=minutos), direcao, pseudonimo)


E, S = Direcao.ENTRADA, Direcao.SAIDA


class TestPureza:
    def test_tudo_certo_da_um(self):
        regs = [reg(1, E, 0, "P1"), reg(2, S, 60, "P1"), reg(3, E, 5, "P2")]
        gab = {"e1": "maria", "e2": "maria", "e3": "joao"}
        p = m.pureza(regs, gab)
        assert p.taxa == 1.0
        assert p.confusoes == 0
        assert p.por_pseudonimo["P1"] == ("maria", 2, 2)

    def test_confusao_derruba(self):
        regs = [reg(1, E, 0, "P1"), reg(2, S, 60, "P1"), reg(3, E, 90, "P1")]
        gab = {"e1": "maria", "e2": "maria", "e3": "joao"}
        p = m.pureza(regs, gab)
        assert p.total == 3
        assert p.certos == 2
        assert p.confusoes == 1

    def test_sem_rotulo_e_sem_par_ficam_de_fora(self):
        regs = [reg(1, E, 0, "P1"), reg(2, S, 60, None), reg(3, E, 5, "P2")]
        gab = {"e1": "maria", "e2": "maria"}  # e3 sem rótulo, e2 sem par
        p = m.pureza(regs, gab)
        assert p.total == 1

    def test_vazio(self):
        p = m.pureza([], {})
        assert p.taxa == 0.0


class TestFragmentacao:
    def test_uma_pessoa_um_p(self):
        regs = [reg(1, E, 0, "P1"), reg(2, S, 60, "P1")]
        f = m.fragmentacao(regs, {"e1": "maria", "e2": "maria"})
        assert f.media == 1.0
        assert f.divididas == 0

    def test_pessoa_dividida_em_dois(self):
        regs = [reg(1, E, 0, "P1"), reg(2, S, 60, "P1"), reg(3, E, 90, "P2")]
        f = m.fragmentacao(regs, {"e1": "maria", "e2": "maria", "e3": "maria"})
        assert f.por_apelido == {"maria": {"P1", "P2"}}
        assert f.media == 2.0
        assert f.divididas == 1
        assert f.pessoas == 1


class TestNaoAtribuido:
    def test_conta_so_saidas(self):
        regs = [reg(1, E, 0, "P1"), reg(2, S, 60, None), reg(3, S, 70, "P1")]
        assert m.taxa_nao_atribuido(regs) == (2, 1, 0.5)

    def test_sem_saidas(self):
        assert m.taxa_nao_atribuido([reg(1, E, 0, "P1")]) == (0, 0, 0.0)


class TestPermanencia:
    def test_entrada_e_saida_viram_par(self):
        regs = [reg(1, E, 0, "P1"), reg(2, S, 90, "P1")]
        perms = m.permanencias(regs)
        assert len(perms) == 1
        assert perms[0].segundos == 90 * 60

    def test_reentrada_gera_dois_pares(self):
        regs = [reg(1, E, 0, "P1"), reg(2, S, 60, "P1"), reg(3, E, 120, "P1"), reg(4, S, 150, "P1")]
        perms = m.permanencias(regs)
        assert [p.segundos / 60 for p in perms] == [60, 30]

    def test_entrada_sem_saida_nao_vira_par(self):
        assert m.permanencias([reg(1, E, 0, "P1")]) == []

    def test_saida_sem_entrada_e_ignorada(self):
        assert m.permanencias([reg(1, S, 0, "P1")]) == []

    def test_duas_entradas_seguidas_mantem_a_ultima(self):
        regs = [reg(1, E, 0, "P1"), reg(2, E, 30, "P1"), reg(3, S, 60, "P1")]
        perms = m.permanencias(regs)
        assert [p.segundos / 60 for p in perms] == [30]

    def test_nao_atribuido_nao_entra(self):
        regs = [reg(1, E, 0, None), reg(2, S, 30, None)]
        assert m.permanencias(regs) == []


class TestResumo:
    def test_sem_gabarito(self):
        regs = [reg(1, E, 0, "P1"), reg(2, S, 60, "P1"), reg(3, S, 70, None)]
        r = m.resumo(regs)
        assert r["pessoas"] == 1
        assert r["saidas"] == 2
        assert r["sem_par"] == 1
        assert r["permanencias"] == 1
        assert r["permanencia_media_min"] == 60.0
        assert "pureza" not in r

    def test_com_gabarito(self):
        regs = [reg(1, E, 0, "P1"), reg(2, S, 60, "P1")]
        r = m.resumo(regs, {"e1": "maria", "e2": "maria"})
        assert r["pureza"] == 1.0
        assert r["fragmentacao"] == 1.0
        assert r["pessoas_reais"] == 1
