"""A camada de identidade do agente, com extrator de mentira.

O "recorte" é a própria caixa, e o "vetor" sai da posição dela: quem anda à
esquerda é A, quem anda à direita é B. Sem torch, sem imagem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fluxo.agente.identidade import PASTA_SEM_PAR, Identidade
from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento
from fluxo.dominio.identidade import PessoaSessao, Vinculo
from fluxo.dominio.rastro import Rastro
from fluxo.reid.galeria import METODO_NAO_ATRIBUIDO, METODO_NOVA, METODO_SAIDA, Galeria

T0 = datetime(2026, 9, 4, 9, 0, 0, tzinfo=FUSO_LOCAL)
A = [1.0, 0.0, 0.0]
B = [0.0, 1.0, 0.0]


@dataclass(frozen=True, slots=True)
class QuadroFalso:
    indice: int
    instante: datetime
    imagem: object = None
    apos_lacuna: bool = False


class ExtratorFalso:
    def __init__(self):
        self.lotes = []

    def recortar(self, imagem, caixa):
        if caixa[2] - caixa[0] < 2:
            return None
        return caixa

    def extrair(self, recortes):
        self.lotes.append(list(recortes))
        return [A if c[0] < 300 else B for c in recortes]


class TrilhaFalsa:
    def __init__(self):
        self.assinaturas = []

    def gravar_assinatura(self, quadro, id_local, assinatura):
        self.assinaturas.append((quadro, id_local, assinatura))


class RemetenteFalso:
    def __init__(self):
        self.pessoas = []
        self.vinculos = []

    def registrar_pessoas(self, pessoas):
        self.pessoas.extend(pessoas)
        return True

    def enviar_vinculos(self, vinculos):
        self.vinculos.extend(vinculos)
        return True


def quadro(i, segundos=None):
    return QuadroFalso(i, T0 + timedelta(seconds=i if segundos is None else segundos))


def rastro(track, x, largura=40.0):
    return Rastro(id_local=track, caixa=(x, 100.0, x + largura, 300.0), confianca=0.9)


def evento(track, direcao, segundos):
    return EventoCruzamento.criar(
        "entrada_a", T0 + timedelta(seconds=segundos), direcao, track_id_local=track, confianca=0.9
    )


def nova(**kw):
    padrao = dict(
        camera_id="entrada_a",
        extrator=ExtratorFalso(),
        galeria=Galeria(limiar_saida=0.7, limiar_reentrada=0.75, janela_lote_s=60),
        intervalo_recorte_quadros=1,
    )
    padrao.update(kw)
    return Identidade(**padrao)


class TestEntrada:
    def test_entrada_cria_p1_e_etiqueta_o_track(self):
        ident = nova()
        decisoes = ident.observar(quadro(0), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 0)])
        assert [d.pseudonimo for d in decisoes] == ["P1"]
        assert decisoes[0].metodo == METODO_NOVA
        assert ident.etiquetas() == {1: "P1"}
        assert ident.decisoes == decisoes

    def test_a_rede_so_roda_no_cruzamento(self):
        ident = nova()
        for i in range(5):
            ident.observar(quadro(i), [rastro(1, 100)], [])
        assert ident.extrator.lotes == []
        ident.observar(quadro(5), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 5)])
        assert len(ident.extrator.lotes) == 1

    def test_o_lote_junta_o_buffer_e_o_quadro_do_cruzamento(self):
        ident = nova(recortes_por_track=2)
        for i in range(5):
            ident.observar(quadro(i), [rastro(1, 100)], [])
        ident.observar(quadro(5), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 5)])
        # 2 do buffer + 1 do quadro atual
        assert len(ident.extrator.lotes[0]) == 3

    def test_track_nunca_recortado_nao_gera_identidade(self):
        ident = nova()
        decisoes = ident.observar(quadro(0), [], [evento(9, Direcao.ENTRADA, 0)])
        assert decisoes == []
        assert ident.sem_recorte == 1

    def test_caixa_sem_area_e_ignorada(self):
        ident = nova()
        decisoes = ident.observar(
            quadro(0), [rastro(1, 100, largura=0.5)], [evento(1, Direcao.ENTRADA, 0)]
        )
        assert decisoes == []
        assert ident.sem_recorte == 1


class TestSaida:
    def test_saida_espera_o_lote_e_resolve(self):
        ident = nova()
        ident.observar(quadro(0), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 0)])
        ident.observar(quadro(1, 30), [rastro(2, 100)], [evento(2, Direcao.SAIDA, 30)])
        assert ident.etiquetas()[2] == "P1?"
        assert ident.galeria.pendentes == 1

        decisoes = ident.observar(quadro(2, 100), [rastro(2, 100)], [])
        assert [d.metodo for d in decisoes] == [METODO_SAIDA]
        assert decisoes[0].pseudonimo == "P1"
        assert ident.etiquetas()[2] == "P1"

    def test_fechar_resolve_o_que_ficou_na_fila(self):
        ident = nova()
        ident.observar(quadro(0), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 0)])
        ident.observar(quadro(1, 30), [rastro(2, 100)], [evento(2, Direcao.SAIDA, 30)])
        decisoes = ident.fechar()
        assert [d.pseudonimo for d in decisoes] == ["P1"]
        assert ident.galeria.pendentes == 0

    def test_saida_de_desconhecido_fica_sem_par(self):
        ident = nova()
        ident.observar(quadro(0), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 0)])
        ident.observar(quadro(1, 30), [rastro(2, 500)], [evento(2, Direcao.SAIDA, 30)])
        decisoes = ident.fechar()
        assert decisoes[0].metodo == METODO_NAO_ATRIBUIDO
        assert decisoes[0].pseudonimo is None


class TestRecortesETrilha:
    def test_miniatura_vai_para_a_pasta_do_pseudonimo(self, tmp_path):
        gravados = []
        ident = nova(pasta_recortes=tmp_path, gravar_imagem=lambda c, img: gravados.append(c))
        ident.observar(quadro(0), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 0)])
        assert len(gravados) == 1
        caminho = gravados[0]
        assert caminho == tmp_path / "2026-09-04" / "entrada_a" / "P1" / "090000_ENTRADA_t1.jpg"

    def test_o_indice_liga_a_miniatura_ao_id_evento(self, tmp_path):
        ident = nova(pasta_recortes=tmp_path, gravar_imagem=lambda c, img: None)
        e = evento(1, Direcao.ENTRADA, 0)
        ident.observar(quadro(0), [rastro(1, 100)], [e])
        indice = (tmp_path / "2026-09-04" / "entrada_a" / "indice.csv").read_text(encoding="utf-8")
        linhas = indice.splitlines()
        assert linhas[0] == "id_evento,instante,direcao,pseudonimo,metodo,arquivo"
        assert linhas[1].startswith(e.id_evento + ",")
        assert linhas[1].endswith(",P1,nova,P1/090000_ENTRADA_t1.jpg")

    def test_sem_par_vai_para_a_pasta_propria(self, tmp_path):
        gravados = []
        ident = nova(pasta_recortes=tmp_path, gravar_imagem=lambda c, img: gravados.append(c))
        ident.observar(quadro(0), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 0)])
        ident.observar(quadro(1, 30), [rastro(2, 500)], [evento(2, Direcao.SAIDA, 30)])
        ident.fechar()
        assert gravados[1].parent.name == PASTA_SEM_PAR

    def test_o_melhor_recorte_e_o_de_maior_caixa(self, tmp_path):
        gravados = []
        ident = nova(pasta_recortes=tmp_path, gravar_imagem=lambda c, img: gravados.append(img))
        ident.observar(quadro(0), [rastro(1, 100, largura=20)], [])
        ident.observar(quadro(1), [rastro(1, 100, largura=80)], [])
        ident.observar(quadro(2), [rastro(1, 100, largura=30)], [evento(1, Direcao.ENTRADA, 2)])
        assert gravados[0][2] - gravados[0][0] == 80

    def test_sem_pasta_nada_e_gravado(self):
        gravados = []
        ident = nova(gravar_imagem=lambda c, img: gravados.append(c))
        ident.observar(quadro(0), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 0)])
        assert gravados == []

    def test_assinatura_vai_para_a_trilha(self):
        trilha = TrilhaFalsa()
        ident = nova(trilha=trilha)
        ident.observar(quadro(7), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 7)])
        assert len(trilha.assinaturas) == 1
        q, id_local, vetor = trilha.assinaturas[0]
        assert (q, id_local) == (7, 1)
        assert vetor == A


class TestEsquecer:
    def test_track_sumido_perde_etiqueta_e_buffer(self):
        ident = nova(esquecer_apos_quadros=2)
        ident.observar(quadro(0), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 0)])
        assert ident.etiquetas() == {1: "P1"}
        ident.observar(quadro(1), [], [])
        ident.observar(quadro(2), [], [])
        assert ident.etiquetas() == {1: "P1"}
        ident.observar(quadro(3), [], [])
        assert ident.etiquetas() == {}
        assert 1 not in ident._buffers


class TestPublicar:
    def test_remetente_recebe_pessoa_nova_e_vinculos(self):
        rem = RemetenteFalso()
        ident = nova(remetente=rem)
        ident.observar(quadro(0), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 0)])
        ident.observar(quadro(1, 30), [rastro(2, 100)], [evento(2, Direcao.SAIDA, 30)])
        ident.fechar()

        assert len(rem.pessoas) == 1
        assert isinstance(rem.pessoas[0], PessoaSessao)
        assert rem.pessoas[0].pseudonimo == "P1"
        assert rem.pessoas[0].data_ref.isoformat() == "2026-09-04"

        assert len(rem.vinculos) == 2
        assert all(isinstance(v, Vinculo) for v in rem.vinculos)
        assert [v.metodo for v in rem.vinculos] == [METODO_NOVA, METODO_SAIDA]
        assert rem.vinculos[1].atribuido
        assert ident.pessoas_enviadas == 1
        assert ident.vinculos_enviados == 2

    def test_avisar_recebe_uma_linha_por_decisao(self):
        linhas = []
        ident = nova()
        ident.observar(quadro(0), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 0)],
                       avisar=linhas.append)
        assert len(linhas) == 1
        assert "P1" in linhas[0] and "nova" in linhas[0]

    def test_placar_resume_a_galeria(self):
        ident = nova()
        ident.observar(quadro(0), [rastro(1, 100)], [evento(1, Direcao.ENTRADA, 0)])
        assert ident.placar().startswith("pessoas 1  dentro 1")
