"""As três tabelas da Etapa 2: upsert, expiração mecânica e apelido de teste."""

from datetime import date, datetime, time, timedelta

import pytest

from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento
from fluxo.dominio.identidade import Apelido, PessoaSessao, Vinculo
from fluxo.persistencia import repositorio
from fluxo.persistencia.repositorio import CameraDesconhecida, PessoaDesconhecida

# Hoje, e não uma data fixa: toda escrita chama `purgar_expirados`, que apaga o
# que passou de 48 h. Com data literal os testes passavam por dois dias e
# depois falhavam sozinhos, sem ninguém ter mexido em nada.
DIA = date.today()
MEIA_NOITE = datetime.combine(DIA, time(0, 0), tzinfo=FUSO_LOCAL)
T0 = MEIA_NOITE + timedelta(hours=9)


def pessoa(pseudonimo="P1", camera="entrada_a", minutos=0):
    return PessoaSessao(
        camera_id=camera, data_ref=DIA, pseudonimo=pseudonimo,
        primeiro_visto=T0 + timedelta(minutes=minutos),
        ultimo_visto=T0 + timedelta(minutes=minutos),
    )


def evento(track, direcao, minutos, camera="entrada_a"):
    return EventoCruzamento.criar(
        camera, T0 + timedelta(minutes=minutos), direcao, track_id_local=track, confianca=0.9
    )


def vinculo(e, pseudonimo, metodo="nova", sim=None):
    return Vinculo(
        id_evento=e.id_evento, camera_id=e.camera_id, data_ref=DIA,
        pseudonimo=pseudonimo, similaridade=sim, atribuido=pseudonimo is not None, metodo=metodo,
    )


class TestPessoas:
    def test_grava_e_lista(self, banco):
        assert repositorio.upsert_pessoas(banco, [pessoa("P1"), pessoa("P2")]) == 2
        linhas = repositorio.listar_pessoas(banco, DIA, DIA)
        assert [linha["pseudonimo"] for linha in linhas] == ["P1", "P2"]
        assert linhas[0]["apelido"] is None

    def test_reenvio_alarga_as_datas_sem_duplicar(self, banco):
        repositorio.upsert_pessoas(banco, [pessoa("P1", minutos=10)])
        repositorio.upsert_pessoas(banco, [pessoa("P1", minutos=0)])
        repositorio.upsert_pessoas(banco, [pessoa("P1", minutos=50)])
        linhas = repositorio.listar_pessoas(banco)
        assert len(linhas) == 1
        assert linhas[0]["primeiro_visto"] == T0.isoformat()
        assert linhas[0]["ultimo_visto"] == (T0 + timedelta(minutes=50)).isoformat()

    def test_camera_desconhecida(self, banco):
        with pytest.raises(CameraDesconhecida):
            repositorio.upsert_pessoas(banco, [pessoa(camera="porta_dos_fundos")])

    def test_ordena_p10_depois_de_p2(self, banco):
        repositorio.upsert_pessoas(banco, [pessoa("P10"), pessoa("P2")])
        assert [linha["pseudonimo"] for linha in repositorio.listar_pessoas(banco)] == ["P2", "P10"]

    def test_reenvio_atualiza_dentro(self, banco):
        repositorio.upsert_pessoas(banco, [pessoa("P1")])
        assert repositorio.listar_pessoas(banco)[0]["dentro"] == 1
        fora = pessoa("P1", minutos=30).model_copy(update={"dentro": False})
        repositorio.upsert_pessoas(banco, [fora])
        assert repositorio.listar_pessoas(banco)[0]["dentro"] == 0

    def test_migracao_acrescenta_dentro_a_banco_antigo(self):
        # Um banco criado antes da coluna: só o CREATE de então, sem `dentro`.
        conn = repositorio.conectar(":memory:")
        conn.execute("CREATE TABLE camera (id TEXT PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE pessoa_sessao (
                id INTEGER PRIMARY KEY AUTOINCREMENT, camera_id TEXT NOT NULL,
                data_ref TEXT NOT NULL, pseudonimo TEXT NOT NULL,
                primeiro_visto TEXT NOT NULL, ultimo_visto TEXT NOT NULL,
                expira_em TEXT NOT NULL, UNIQUE (camera_id, data_ref, pseudonimo))
            """
        )
        conn.execute(
            "INSERT INTO pessoa_sessao VALUES (1, 'c', '2026-09-04', 'P1', 't', 't', 't')"
        )
        repositorio.criar_banco(conn)
        colunas = {r[1] for r in conn.execute("PRAGMA table_info(pessoa_sessao)")}
        assert "dentro" in colunas
        # O que já existia continua lá, e nasce "dentro" — o padrão da coluna.
        assert conn.execute("SELECT dentro FROM pessoa_sessao").fetchone()[0] == 1
        repositorio.criar_banco(conn)  # segunda vez não quebra


class TestVinculos:
    def test_liga_evento_a_pessoa_e_conta_direcoes(self, banco):
        e1, e2 = evento(1, Direcao.ENTRADA, 0), evento(2, Direcao.SAIDA, 60)
        repositorio.inserir_eventos(banco, [e1, e2])
        repositorio.upsert_pessoas(banco, [pessoa("P1")])
        repositorio.upsert_vinculos(banco, [vinculo(e1, "P1"), vinculo(e2, "P1", "saida", 0.9)])

        pessoas = repositorio.listar_pessoas(banco)
        assert (pessoas[0]["entradas"], pessoas[0]["saidas"]) == (1, 1)

        vs = repositorio.listar_vinculos(banco, DIA, DIA)
        assert [v["direcao"] for v in vs] == ["ENTRADA", "SAIDA"]
        assert vs[1]["similaridade"] == 0.9
        assert vs[1]["pseudonimo"] == "P1"

    def test_vinculo_grava_o_dentro(self, banco):
        e1, e2, e3 = (
            evento(1, Direcao.ENTRADA, 0), evento(2, Direcao.SAIDA, 60),
            evento(3, Direcao.ENTRADA, 120),
        )
        repositorio.upsert_vinculos(banco, [vinculo(e1, "P1")])
        assert repositorio.listar_pessoas(banco)[0]["dentro"] == 1
        repositorio.upsert_vinculos(banco, [vinculo(e2, "P1", "saida", 0.9)])
        assert repositorio.listar_pessoas(banco)[0]["dentro"] == 0
        repositorio.upsert_vinculos(banco, [vinculo(e3, "P1", "reentrada", 0.9)])
        assert repositorio.listar_pessoas(banco)[0]["dentro"] == 1

    def test_nao_atribuido_e_gravado_com_pessoa_nula(self, banco):
        e = evento(1, Direcao.SAIDA, 0)
        repositorio.inserir_evento(banco, e)
        repositorio.upsert_vinculos(banco, [vinculo(e, None, "nao_atribuido")])
        v = repositorio.listar_vinculos(banco)[0]
        assert v["pseudonimo"] is None
        assert v["atribuido"] == 0

    def test_vinculo_antes_da_pessoa_cria_a_pessoa(self, banco):
        e = evento(1, Direcao.ENTRADA, 0)
        repositorio.upsert_vinculos(banco, [vinculo(e, "P7")])
        assert [linha["pseudonimo"] for linha in repositorio.listar_pessoas(banco)] == ["P7"]
        # A pessoa provisória é carimbada com "agora"; o upsert dela, chegando
        # depois, alarga as datas para as reais.
        repositorio.upsert_pessoas(banco, [pessoa("P7", minutos=50)])
        linha = repositorio.listar_pessoas(banco)[0]
        # "Alarga", não "substitui": primeiro_visto é o menor dos dois carimbos
        # e ultimo_visto o maior. Como um deles é sempre `real`, a dupla
        # desigualdade vale a qualquer hora do dia — inclusive antes das 9h.
        real = (T0 + timedelta(minutes=50)).isoformat()
        assert linha["primeiro_visto"] <= real
        assert linha["ultimo_visto"] >= real

    def test_reenvio_substitui(self, banco):
        e = evento(1, Direcao.SAIDA, 0)
        repositorio.upsert_pessoas(banco, [pessoa("P1"), pessoa("P2")])
        repositorio.upsert_vinculos(banco, [vinculo(e, "P1", "saida", 0.7)])
        repositorio.upsert_vinculos(banco, [vinculo(e, "P2", "saida", 0.8)])
        vs = repositorio.listar_vinculos(banco)
        assert len(vs) == 1
        assert vs[0]["pseudonimo"] == "P2"

    def test_vinculo_sem_evento_ainda_aparece(self, banco):
        """O evento pode chegar depois (lote de 25). Não é FK, é junção."""
        e = evento(1, Direcao.ENTRADA, 0)
        repositorio.upsert_vinculos(banco, [vinculo(e, "P1")])
        v = repositorio.listar_vinculos(banco)[0]
        assert v["instante"] is None

    def test_camera_desconhecida(self, banco):
        e = evento(1, Direcao.ENTRADA, 0, camera="porta_dos_fundos")
        with pytest.raises(CameraDesconhecida):
            repositorio.upsert_vinculos(banco, [vinculo(e, "P1")])


class TestApelido:
    def test_define_e_aparece_na_lista(self, banco):
        repositorio.upsert_pessoas(banco, [pessoa("P1")])
        repositorio.definir_apelido(
            banco, Apelido(camera_id="entrada_a", data_ref=DIA, pseudonimo="P1", apelido="maria")
        )
        assert repositorio.listar_pessoas(banco)[0]["apelido"] == "maria"

    def test_redefinir_substitui(self, banco):
        repositorio.upsert_pessoas(banco, [pessoa("P1")])
        for nome in ("maria", "joao"):
            repositorio.definir_apelido(
                banco, Apelido(camera_id="entrada_a", data_ref=DIA, pseudonimo="P1", apelido=nome)
            )
        assert repositorio.listar_pessoas(banco)[0]["apelido"] == "joao"

    def test_pseudonimo_inexistente(self, banco):
        with pytest.raises(PessoaDesconhecida):
            repositorio.definir_apelido(
                banco, Apelido(camera_id="entrada_a", data_ref=DIA, pseudonimo="P9", apelido="x")
            )


class TestExpiracao:
    """PROJETO §16.5: identidade efêmera por construção, não por política."""

    def test_pessoa_some_depois_de_expira_h(self, banco):
        e = evento(1, Direcao.ENTRADA, 0)
        repositorio.upsert_pessoas(banco, [pessoa("P1")], expira_h=48)
        repositorio.upsert_vinculos(banco, [vinculo(e, "P1")])
        repositorio.definir_apelido(
            banco, Apelido(camera_id="entrada_a", data_ref=DIA, pseudonimo="P1", apelido="maria")
        )

        # O prazo conta da MEIA-NOITE do dia de referência, não do primeiro
        # avistamento: por isso os dois instantes saem de MEIA_NOITE.
        antes = MEIA_NOITE + timedelta(hours=47, minutes=59)  # ainda no prazo
        assert repositorio.purgar_expirados(banco, antes) == 0
        assert len(repositorio.listar_pessoas(banco)) == 1

        depois = MEIA_NOITE + timedelta(hours=48, seconds=1)  # 48h após o início do dia
        assert repositorio.purgar_expirados(banco, depois) == 1
        assert repositorio.listar_pessoas(banco) == []
        assert repositorio.listar_vinculos(banco) == []
        assert banco.execute("SELECT COUNT(*) FROM apelido_teste").fetchone()[0] == 0

    def test_toda_escrita_purga(self, banco):
        antiga = PessoaSessao(
            camera_id="entrada_a", data_ref=date(2026, 8, 1), pseudonimo="P1",
            primeiro_visto=datetime(2026, 8, 1, 8, tzinfo=FUSO_LOCAL),
            ultimo_visto=datetime(2026, 8, 1, 8, tzinfo=FUSO_LOCAL),
        )
        repositorio.upsert_pessoas(banco, [antiga], expira_h=0)
        # Vencida na hora: a escrita seguinte (qualquer uma) a apaga.
        repositorio.upsert_pessoas(
            banco, [PessoaSessao(
                camera_id="entrada_a", data_ref=date.today(), pseudonimo="P1",
                primeiro_visto=datetime.now(FUSO_LOCAL), ultimo_visto=datetime.now(FUSO_LOCAL),
            )],
            expira_h=48,
        )
        linhas = repositorio.listar_pessoas(banco)
        assert [linha["data_ref"] for linha in linhas] == [date.today().isoformat()]

    def test_saida_sem_par_antiga_tambem_some(self, banco):
        e = evento(1, Direcao.SAIDA, 0)
        repositorio.upsert_vinculos(banco, [vinculo(e, None, "nao_atribuido")])
        repositorio.purgar_expirados(banco, T0 + timedelta(days=5))
        assert repositorio.listar_vinculos(banco) == []
