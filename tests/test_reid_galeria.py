"""A galeria de ocupação, com vetores inventados.

Três pessoas ortogonais (A, B, C) bastam para provar as regras: entrada cria
ou reencontra, saída espera o lote, ninguém é forçado, e o dia apaga tudo.
"""

from datetime import datetime, timedelta

from fluxo.dominio.evento import FUSO_LOCAL, Direcao
from fluxo.reid import galeria as g

T0 = datetime(2026, 9, 4, 9, 0, 0, tzinfo=FUSO_LOCAL)
A = [1.0, 0.0, 0.0]
B = [0.0, 1.0, 0.0]
C = [0.0, 0.0, 1.0]


def em(segundos):
    return T0 + timedelta(seconds=segundos)


def nova(**kw):
    padrao = dict(limiar_saida=0.7, limiar_reentrada=0.75, janela_lote_s=60, max_permanencia_h=12)
    padrao.update(kw)
    return g.Galeria(**padrao)


def ruidoso(v, eps=0.15):
    return [x + eps for x in v]


class TestEntrada:
    def test_primeira_entrada_cria_p1(self):
        gal = nova()
        d = gal.entrar("e1", 1, A, em(0))
        assert d.pseudonimo == "P1"
        assert d.metodo == g.METODO_NOVA
        assert d.pessoa_nova
        assert gal.criadas == 1
        assert [p.pseudonimo for p in gal.dentro] == ["P1"]

    def test_duas_pessoas_diferentes_sao_dois_p(self):
        gal = nova()
        gal.entrar("e1", 1, A, em(0))
        d = gal.entrar("e2", 2, B, em(5))
        assert d.pseudonimo == "P2"
        assert len(gal.dentro) == 2

    def test_parecida_com_quem_esta_dentro_ainda_e_nova(self):
        """Só quem está FORA é candidato a reentrada."""
        gal = nova()
        gal.entrar("e1", 1, A, em(0))
        d = gal.entrar("e2", 2, ruidoso(A), em(5))
        assert d.pseudonimo == "P2"
        assert d.metodo == g.METODO_NOVA

    def test_etiqueta_do_track(self):
        gal = nova()
        gal.entrar("e1", 7, A, em(0))
        assert gal.etiqueta(7) == "P1"


class TestSaidaEmLote:
    def test_saida_espera_a_janela(self):
        gal = nova(janela_lote_s=60)
        gal.entrar("e1", 1, A, em(0))
        gal.sair("s1", 2, A, em(100))
        assert gal.pendentes == 1
        assert gal.etiqueta(2) == "P1?"
        assert gal.resolver(em(130)) == []
        decisoes = gal.resolver(em(161))
        assert len(decisoes) == 1
        assert decisoes[0].pseudonimo == "P1"
        assert decisoes[0].metodo == g.METODO_SAIDA
        assert gal.etiqueta(2) == "P1"
        assert gal.dentro == []
        assert gal.atribuidas == 1

    def test_preparar_resolve_o_lote_vencido(self):
        gal = nova(janela_lote_s=10)
        gal.entrar("e1", 1, A, em(0))
        gal.sair("s1", 1, A, em(20))
        assert gal.preparar(em(25)) == []
        decisoes = gal.preparar(em(31))
        assert [d.id_evento for d in decisoes] == ["s1"]

    def test_saida_sem_ninguem_parecido_fica_sem_par(self):
        gal = nova()
        gal.entrar("e1", 1, A, em(0))
        gal.sair("s1", 2, C, em(10))
        assert gal.etiqueta(2) == g.SEM_PAR
        d = gal.resolver(em(100))[0]
        assert d.pseudonimo is None
        assert d.metodo == g.METODO_NAO_ATRIBUIDO
        assert not d.atribuido
        assert gal.nao_atribuidas == 1
        # P1 continua dentro: ninguém foi forçado a sair.
        assert [p.pseudonimo for p in gal.dentro] == ["P1"]

    def test_duas_saidas_parecidas_resolvem_juntas(self):
        """O caso do guloso: a primeira saída é 'meio A meio B', a segunda é A."""
        gal = nova(limiar_saida=0.5)
        gal.entrar("e1", 1, A, em(0))
        gal.entrar("e2", 2, B, em(1))
        gal.sair("s1", 3, [0.8, 0.6, 0.0], em(50))
        gal.sair("s2", 4, A, em(55))
        decisoes = {d.id_evento: d.pseudonimo for d in gal.resolver(em(200))}
        assert decisoes == {"s1": "P2", "s2": "P1"}

    def test_fechar_resolve_sem_esperar(self):
        gal = nova(janela_lote_s=3600)
        gal.entrar("e1", 1, A, em(0))
        gal.sair("s1", 1, A, em(5))
        assert [d.pseudonimo for d in gal.fechar(em(6))] == ["P1"]
        assert gal.pendentes == 0


class TestReentrada:
    def test_quem_saiu_e_voltou_e_o_mesmo_p(self):
        gal = nova()
        gal.entrar("e1", 1, A, em(0))
        gal.sair("s1", 1, A, em(10))
        gal.resolver(em(100))
        d = gal.entrar("e2", 5, ruidoso(A, 0.1), em(200))
        assert d.pseudonimo == "P1"
        assert d.metodo == g.METODO_REENTRADA
        assert gal.reentradas == 1
        assert gal.pessoas["P1"].entradas == 2
        assert len(gal.pessoas) == 1

    def test_abaixo_do_limiar_de_reentrada_e_pessoa_nova(self):
        gal = nova(limiar_reentrada=0.99)
        gal.entrar("e1", 1, A, em(0))
        gal.sair("s1", 1, A, em(10))
        gal.resolver(em(100))
        d = gal.entrar("e2", 5, ruidoso(A, 0.3), em(200))
        assert d.pseudonimo == "P2"


class TestDiaEFantasmas:
    def test_virar_o_dia_apaga_a_galeria(self):
        gal = nova()
        gal.entrar("e1", 1, A, em(0))
        gal.preparar(em(0))
        amanha = T0 + timedelta(days=1)
        gal.preparar(amanha)
        assert gal.pessoas == {}
        assert gal.etiquetas() == {}
        d = gal.entrar("e2", 1, A, amanha)
        assert d.pseudonimo == "P1"  # numeração recomeça
        assert d.metodo == g.METODO_NOVA

    def test_saida_pendente_na_virada_resolve_contra_ontem(self):
        gal = nova(janela_lote_s=3600)
        gal.entrar("e1", 1, A, em(0))
        gal.sair("s1", 1, A, em(10))
        decisoes = gal.preparar(T0 + timedelta(days=1))
        assert [d.pseudonimo for d in decisoes] == ["P1"]
        assert gal.pessoas == {}

    def test_fantasma_sai_dos_candidatos(self):
        gal = nova(max_permanencia_h=1)
        gal.entrar("e1", 1, A, em(0))
        assert gal.purgar_fantasmas(em(3601)) == 1
        assert gal.fantasmas == 1
        assert gal.dentro == []
        # E não rouba o par de uma saída real: C não tem com quem casar.
        gal.sair("s1", 2, A, em(3700))
        d = gal.resolver(em(4000))[0]
        assert d.metodo == g.METODO_NAO_ATRIBUIDO

    def test_esquecer_solta_etiqueta_de_track_sumido(self):
        gal = nova()
        gal.entrar("e1", 1, A, em(0))
        gal.entrar("e2", 2, B, em(0))
        gal.esquecer({2})
        assert gal.etiquetas() == {2: "P2"}


class TestDePipeline:
    def test_le_a_secao_reid(self):
        gal = g.Galeria.de_pipeline({"reid": {"limiar_saida": 0.55, "janela_lote_s": 5}})
        assert gal.limiar_saida == 0.55
        assert gal.janela_lote_s == 5.0
        assert gal.limiar_reentrada == 0.75  # default

    def test_sem_secao_usa_defaults(self):
        gal = g.Galeria.de_pipeline({})
        assert gal.limiar_saida == 0.70


class TestDecisao:
    def test_direcao_e_instante_viajam_na_decisao(self):
        gal = nova()
        d = gal.entrar("e1", 1, A, em(0))
        assert d.direcao is Direcao.ENTRADA
        assert d.instante == em(0)
