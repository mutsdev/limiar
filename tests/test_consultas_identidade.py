"""As consultas da aba Pessoas, em cima do banco temporário."""

from datetime import date, datetime, timedelta

from fluxo.analise import consultas
from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento
from fluxo.dominio.identidade import Apelido, PessoaSessao, Vinculo
from fluxo.persistencia import repositorio

DIA = date(2026, 9, 4)
T0 = datetime(2026, 9, 4, 9, 0, 0, tzinfo=FUSO_LOCAL)


def _povoar(banco):
    e1 = EventoCruzamento.criar("entrada_a", T0, Direcao.ENTRADA, track_id_local=1)
    e2 = EventoCruzamento.criar(
        "entrada_a", T0 + timedelta(minutes=90), Direcao.SAIDA, track_id_local=2
    )
    e3 = EventoCruzamento.criar(
        "entrada_a", T0 + timedelta(minutes=95), Direcao.SAIDA, track_id_local=3
    )
    repositorio.inserir_eventos(banco, [e1, e2, e3])
    repositorio.upsert_pessoas(banco, [PessoaSessao(
        camera_id="entrada_a", data_ref=DIA, pseudonimo="P1",
        primeiro_visto=T0, ultimo_visto=T0 + timedelta(minutes=90),
    )])
    repositorio.upsert_vinculos(banco, [
        Vinculo(id_evento=e1.id_evento, camera_id="entrada_a", data_ref=DIA,
                pseudonimo="P1", similaridade=None, atribuido=True, metodo="nova"),
        Vinculo(id_evento=e2.id_evento, camera_id="entrada_a", data_ref=DIA,
                pseudonimo="P1", similaridade=0.9, atribuido=True, metodo="saida"),
        Vinculo(id_evento=e3.id_evento, camera_id="entrada_a", data_ref=DIA,
                pseudonimo=None, similaridade=None, atribuido=False, metodo="nao_atribuido"),
    ])
    repositorio.definir_apelido(
        banco, Apelido(camera_id="entrada_a", data_ref=DIA, pseudonimo="P1", apelido="maria")
    )


class TestCarregar:
    def test_vazio_tem_as_colunas(self, banco):
        pessoas = consultas.carregar_pessoas(banco)
        vinculos = consultas.carregar_vinculos(banco)
        assert list(pessoas.columns) == consultas.COLUNAS_PESSOAS
        assert list(vinculos.columns) == consultas.COLUNAS_VINCULOS
        assert consultas.permanencias(vinculos).empty

    def test_povoado(self, banco):
        _povoar(banco)
        pessoas = consultas.carregar_pessoas(banco, DIA, DIA, "entrada_a")
        assert list(pessoas["pseudonimo"]) == ["P1"]
        assert pessoas.iloc[0]["apelido"] == "maria"
        assert (int(pessoas.iloc[0]["entradas"]), int(pessoas.iloc[0]["saidas"])) == (1, 1)

        vinculos = consultas.carregar_vinculos(banco, DIA, DIA)
        assert len(vinculos) == 3
        assert vinculos["instante"].notna().all()


class TestResumo:
    def test_numeros_da_aba(self, banco):
        _povoar(banco)
        pessoas = consultas.carregar_pessoas(banco)
        vinculos = consultas.carregar_vinculos(banco)
        r = consultas.resumo_identidade(pessoas, vinculos)
        assert r["unicos"] == 1
        assert r["saidas"] == 2
        assert r["sem_par"] == 1
        assert r["taxa_sem_par"] == 0.5
        assert r["permanencias"] == 1
        assert r["permanencia_media_min"] == 90.0

    def test_permanencias_levam_o_apelido(self, banco):
        _povoar(banco)
        perms = consultas.permanencias(consultas.carregar_vinculos(banco))
        assert list(perms["pseudonimo"]) == ["P1"]
        assert perms.iloc[0]["apelido"] == "maria"
        assert perms.iloc[0]["minutos"] == 90.0

    def test_vazio_nao_quebra(self, banco):
        r = consultas.resumo_identidade(
            consultas.carregar_pessoas(banco), consultas.carregar_vinculos(banco)
        )
        assert r["unicos"] == 0
        assert r["taxa_sem_par"] == 0.0
